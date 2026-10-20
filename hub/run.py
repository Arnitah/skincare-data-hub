"""Daily runner: fetch every active source, diff against yesterday, write tables + status.

Usage:
    python -m hub.run                 # all active sources
    python -m hub.run --only cosrx    # one or more source ids (comma separated)
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time
import traceback
from collections import Counter, defaultdict

import re

import yaml

from . import inci, net
from .adapters import ADAPTERS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(ROOT, "state")
DOCS = os.path.join(ROOT, "docs")

TABLE_FOR_KIND = {"raw_material": "raw_materials", "product": "products", "regulatory": "regulatory"}
META = ("first_seen", "last_seen", "last_changed", "record_status", "removed_on")
NOISE = ("image_url",)  # changes often (CDN version params), never meaningful

COLUMNS = {
    "raw_materials": ["id", "source_id", "record_status", "country", "currency", "name", "category", "inci",
                      "inci_components", "ingredient_keys", "cas", "botanical_name", "plant_part",
                      "use_level_min_pct", "use_level_max_pct", "use_level_text", "ph_min", "ph_max", "solubility",
                      "shelf_life_months", "price_min", "price_max", "price_min_usd", "sizes", "in_stock",
                      "regulatory_flags", "url", "image_url", "tags", "description",
                      "first_seen", "last_seen", "last_changed", "removed_on"],
    "products": ["id", "source_id", "record_status", "brand", "name", "category", "country", "countries_sold",
                 "barcode", "size", "price_min", "price_max", "currency", "price_min_usd", "ingredient_count",
                 "regulated_ingredient_count", "ingredients_text", "url", "image_url", "tags",
                 "first_seen", "last_seen", "last_changed", "removed_on"],
    "regulatory": ["id", "source_id", "record_status", "jurisdiction", "country", "regulator", "substance",
                   "inci", "ingredient_key", "also_known_as", "cas", "ec", "status", "reference", "product_type",
                   "max_concentration", "conditions", "warnings", "legal_role", "source_version",
                   "source_updated", "source_url", "official_source_url", "data_via",
                   "first_seen", "last_seen", "last_changed", "removed_on"],
}
SOURCE_COLS = ["source_id", "name", "kind", "country", "currency", "language", "adapter", "base_url", "active",
               "last_run_status", "last_run_at", "last_success_at", "consecutive_failures",
               "records_active", "records_added", "records_changed", "records_removed",
               "duration_seconds", "message"]
RUN_COLS = ["run_id", "source_id", "started_at", "finished_at", "status", "records_active",
            "records_added", "records_changed", "records_removed", "pages_failed", "message"]
STATUS_LABEL = {"positive_list": "permitted with conditions", "allowed_colorant": "permitted colorant",
                "allowed_preservative": "permitted preservative (limits apply)",
                "allowed_uv_filter": "permitted UV filter (limits apply)"}
CHANGE_COLS = ["date", "run_id", "source_id", "table", "record_id", "name", "change", "fields", "details"]


# ---------------------------------------------------------------- io helpers
def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, obj, pretty=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), default=str)


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).replace("\r", " ").replace("\n", " ")


def _write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in cols])


def _read_csv(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def _hash(rec):
    body = {k: v for k, v in rec.items() if k not in META and k not in NOISE and not k.startswith("_")
            and k not in ("regulatory_flags", "regulated_ingredient_count", "price_min_usd")}
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _cas_list(v):
    """'1317-70-0[2] / 13463-67-7' -> ['1317-70-0', '13463-67-7']"""
    return list(dict.fromkeys(re.findall(r"\b\d{2,7}-\d{2}-\d\b", str(v or ""))))


def _brief(v):
    s = _cell(v)
    return s if len(s) <= 80 else s[:77] + "..."


# ---------------------------------------------------------------- fx
def _fx(s):
    try:
        r = net.get(s, "https://api.frankfurter.dev/v1/latest?base=USD", delay=0)
        rates = r.json()["rates"]
        rates["USD"] = 1.0
        return rates
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    cfg = yaml.safe_load(open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8"))
    defaults = cfg.get("defaults", {})
    sources = [dict(defaults, **s) for s in cfg["sources"]]

    now = dt.datetime.now(dt.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    today = now.strftime("%Y-%m-%d")

    tables = {t: {r["id"]: r for r in _read_json(os.path.join(DATA, f"{t}.json"), [])} for t in COLUMNS}
    src_state = _read_json(os.path.join(STATE, "sources_state.json"), {})
    s = net.session(defaults.get("user_agent"))
    fx = _fx(s)

    changes, runs = [], []
    for src in sources:
        sid = src["id"]
        st = src_state.setdefault(sid, {})
        if not src.get("active") or (only and sid not in only):
            continue
        table = TABLE_FOR_KIND[src["kind"]]
        prev = {k: v for k, v in tables[table].items() if v.get("source_id") == sid}
        prev_active = sum(1 for v in prev.values() if v.get("record_status") != "removed")
        cache_path = os.path.join(STATE, "cache", f"{sid}.json")
        cache = _read_json(cache_path, {})
        started = time.time()
        status, message, res = "passed", "", None
        print(f"[{sid}] running ...", flush=True)
        try:
            res = ADAPTERS[src["adapter"]].run(src, {"session": s, "previous": prev, "cache": cache, "fx": fx})
            n = len(res["records"])
            if n == 0:
                status, message = "failed", "Source returned 0 records (site down, blocked, or layout changed)"
            elif prev_active >= 20 and n < src.get("min_expected", 0.5) * prev_active:
                status = "failed"
                message = (f"Only {n} records vs {prev_active} last run - looks like a layout change or block; "
                           f"kept previous data")
            elif res.get("pages_failed") or res.get("warnings"):
                status, message = "partial", "; ".join(res.get("warnings", []))
        except Exception as e:  # noqa: BLE001
            status, message = "failed", f"{type(e).__name__}: {e}"[:400]
            traceback.print_exc()

        added = changed = removed = 0
        if status in ("passed", "partial"):
            seen = set()
            initial = not prev
            for rec in res["records"]:
                rid = rec["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                old = prev.get(rid)
                rec["record_status"] = "active"
                rec["last_seen"] = today
                rec["removed_on"] = ""
                if old is None:
                    rec["first_seen"] = rec["last_changed"] = today
                    added += 1
                    if not initial:
                        changes.append({"date": today, "run_id": run_id, "source_id": sid, "table": table,
                                        "record_id": rid, "name": rec.get("name") or rec.get("substance"),
                                        "change": "added", "fields": "", "details": ""})
                else:
                    rec["first_seen"] = old.get("first_seen") or today
                    if _hash(rec) != _hash(old) or old.get("record_status") == "removed":
                        rec["last_changed"] = today
                        changed += 1
                        diff = [k for k in set(rec) | set(old)
                                if k not in META and k not in NOISE and not k.startswith("_")
                                and k not in ("regulatory_flags", "regulated_ingredient_count", "price_min_usd")
                                and _cell(rec.get(k)) != _cell(old.get(k))]
                        if old.get("record_status") == "removed":
                            diff.append("record_status")
                        details = "; ".join(f"{k}: {_brief(old.get(k))} -> {_brief(rec.get(k))}"
                                            for k in sorted(diff)[:4] if not isinstance(rec.get(k), (list, dict)))
                        changes.append({"date": today, "run_id": run_id, "source_id": sid, "table": table,
                                        "record_id": rid, "name": rec.get("name") or rec.get("substance"),
                                        "change": "changed", "fields": ", ".join(sorted(diff)), "details": details})
                    else:
                        rec["last_changed"] = old.get("last_changed") or today
                tables[table][rid] = rec
            if status == "passed":                       # only trust removals from a clean run
                for rid, old in prev.items():
                    if rid not in seen and old.get("record_status") != "removed":
                        old["record_status"] = "removed"
                        old["removed_on"] = today
                        removed += 1
                        changes.append({"date": today, "run_id": run_id, "source_id": sid, "table": table,
                                        "record_id": rid, "name": old.get("name") or old.get("substance"),
                                        "change": "removed", "fields": "", "details": ""})
            if initial:
                changes.append({"date": today, "run_id": run_id, "source_id": sid, "table": table,
                                "record_id": "", "name": src["name"], "change": "initial_import",
                                "fields": "", "details": f"{added} records imported"})
            _write_json(cache_path, cache)

        active_now = sum(1 for v in tables[table].values() if v.get("source_id") == sid and v.get("record_status") != "removed")
        dur = round(time.time() - started, 1)
        st["last_run_status"] = status
        st["last_run_at"] = now.isoformat(timespec="seconds")
        if status != "failed":
            st["last_success_at"] = st["last_run_at"]
            st["consecutive_failures"] = 0
        else:
            st["consecutive_failures"] = st.get("consecutive_failures", 0) + 1
        st.update({"records_active": active_now, "records_added": added, "records_changed": changed,
                   "records_removed": removed, "duration_seconds": dur, "message": message})
        runs.append({"run_id": run_id, "source_id": sid, "started_at": dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat(timespec="seconds"),
                     "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     "status": status, "records_active": active_now, "records_added": added,
                     "records_changed": changed, "records_removed": removed,
                     "pages_failed": (res or {}).get("pages_failed", 0), "message": message})
        print(f"[{sid}] {status.upper()} active={active_now} +{added} ~{changed} -{removed} {dur}s {message}", flush=True)

    _derive_and_write(tables, fx, sources, src_state, runs, changes, run_id, now)
    _write_json(os.path.join(STATE, "sources_state.json"), src_state, pretty=True)
    ran = [r for r in runs]
    if ran and all(r["status"] == "failed" for r in ran):
        sys.exit(1)


# ---------------------------------------------------------------- derived tables + outputs
def _derive_and_write(tables, fx, sources, src_state, runs, changes, run_id, now):
    today = now.strftime("%Y-%m-%d")
    # USD prices
    for t in ("raw_materials", "products"):
        for r in tables[t].values():
            rate = fx.get((r.get("currency") or "").upper())
            r["price_min_usd"] = round(r["price_min"] / rate, 2) if rate and r.get("price_min") is not None else None

    # Regulatory index by ingredient key and CAS
    reg_by_key, reg_by_cas = defaultdict(list), defaultdict(list)
    restrictive = defaultdict(bool)          # key -> prohibited/restricted somewhere
    for r in tables["regulatory"].values():
        if r.get("record_status") == "removed":
            continue
        mx = re.split(r"[\n;]", str(r.get("max_concentration") or ""))[0].strip()[:40]
        label = f"{r['jurisdiction']}: {STATUS_LABEL.get(r['status'], r['status'])}" + (f" (max {mx})" if mx else "")
        keys = {r.get("ingredient_key")}
        if "(and)" not in (r.get("substance") or "").lower():     # don't map a blend's rule onto each part
            keys |= {inci.key(a) for a in (r.get("also_known_as") or "").split("; ")}
        for k in keys:
            if k:
                reg_by_key[k].append(label)
                if r.get("status") in ("prohibited", "restricted"):
                    restrictive[k] = True
        for c in _cas_list(r.get("cas")):
            reg_by_cas[c].append(label)

    def flags_for(keys, cas=""):
        out = []
        for k in keys:
            out += reg_by_key.get(k, [])
        for c in _cas_list(cas):
            out += reg_by_cas.get(c, [])
        return "; ".join(dict.fromkeys(out))

    # Ingredient registry
    reg = {}

    def touch(k, name, field):
        if not k:
            return None
        e = reg.setdefault(k, {"ingredient_key": k, "names": Counter(), "cas": set(), "raw_material_count": 0,
                               "product_count": 0, "sources": set()})
        e["names"][name] += 1
        e[field] += 1
        return e

    for r in tables["raw_materials"].values():
        if r.get("record_status") == "removed":
            continue
        comps = [c for c in (r.get("inci_components") or "").split("; ") if c]
        keys = []
        for name in comps:
            k = inci.key(name)
            e = touch(k, name, "raw_material_count")
            if not e:
                continue
            keys.append(k)
            e["sources"].add(r["source_id"])
            if r.get("cas") and len(comps) == 1:
                e["cas"].add(r["cas"])
        r["regulatory_flags"] = flags_for(keys, r.get("cas"))

    pi_rows = []
    for r in tables["products"].values():
        if r.get("record_status") == "removed":
            continue
        flagged = 0
        for pos, name in enumerate(r.get("ingredients") or [], 1):
            k = inci.key(name)
            e = touch(k, name, "product_count")
            if e:
                e["sources"].add(r["source_id"])
            if restrictive.get(k):
                flagged += 1
            pi_rows.append({"product_id": r["id"], "position": pos, "inci_name": name, "ingredient_key": k})
        r["regulated_ingredient_count"] = flagged

    for r in tables["regulatory"].values():
        k = r.get("ingredient_key")
        if k and k in reg:
            reg[k]["cas"].update(_cas_list(r.get("cas")))

    ingredients = []
    for k, e in sorted(reg.items()):
        # keep the registry clean: product-only names seen once that don't look like an ingredient are noise
        if e["raw_material_count"] == 0 and e["product_count"] < 2 and k not in reg_by_key:
            continue
        ingredients.append({"ingredient_key": k, "inci_name": e["names"].most_common(1)[0][0],
                            "cas": "; ".join(sorted(e["cas"]))[:200],
                            "raw_material_count": e["raw_material_count"], "product_count": e["product_count"],
                            "regulatory_flags": flags_for([k]), "sources": "; ".join(sorted(e["sources"]))})

    # ---- write tables
    for t, cols in COLUMNS.items():
        rows = sorted(tables[t].values(), key=lambda r: r["id"])
        _write_json(os.path.join(DATA, f"{t}.json"), rows)
        _write_csv(os.path.join(DATA, f"{t}.csv"), cols, rows)
    _write_csv(os.path.join(DATA, "product_ingredients.csv"), ["product_id", "position", "inci_name", "ingredient_key"], pi_rows)
    icols = ["ingredient_key", "inci_name", "cas", "raw_material_count", "product_count", "regulatory_flags", "sources"]
    _write_csv(os.path.join(DATA, "ingredients.csv"), icols, ingredients)
    _write_json(os.path.join(DATA, "ingredients.json"), ingredients)

    # ---- history
    hist = _read_csv(os.path.join(DATA, "sync_runs.csv")) + runs
    cutoff = (now - dt.timedelta(days=365)).strftime("%Y%m%d")
    hist = [h for h in hist if h["run_id"][:8] >= cutoff]
    _write_csv(os.path.join(DATA, "sync_runs.csv"), RUN_COLS, hist)

    log = _read_csv(os.path.join(DATA, "change_log.csv")) + changes
    cutoff_d = (now - dt.timedelta(days=180)).strftime("%Y-%m-%d")
    log = [c for c in log if c["date"] >= cutoff_d]
    _write_csv(os.path.join(DATA, "change_log.csv"), CHANGE_COLS, log)

    # ---- sources table with status columns
    src_rows = []
    for src in sources:
        st = src_state.get(src["id"], {})
        row = {"source_id": src["id"], "name": src["name"], "kind": src["kind"], "country": src["country"],
               "currency": src.get("currency", ""), "language": src.get("language", ""), "adapter": src["adapter"],
               "base_url": src.get("base_url") or src.get("jurisdiction", ""), "active": src.get("active", False)}
        row.update({k: st.get(k, "") for k in SOURCE_COLS if k not in row})
        if not src.get("active"):
            row["last_run_status"] = "paused"
        src_rows.append(row)
    _write_csv(os.path.join(DATA, "sources.csv"), SOURCE_COLS, src_rows)

    # ---- small sheet-friendly copies (Google Sheets IMPORTDATA has size limits)
    sheets = os.path.join(DATA, "sheets")
    _write_csv(os.path.join(sheets, "products_index.csv"),
               [c for c in COLUMNS["products"] if c not in ("ingredients_text", "tags", "image_url")],
               [r for r in sorted(tables["products"].values(), key=lambda r: r["id"]) if r.get("record_status") != "removed"])
    _write_csv(os.path.join(sheets, "change_log_recent.csv"), CHANGE_COLS, log[-2000:][::-1])
    _write_csv(os.path.join(sheets, "raw_materials.csv"),
               [c for c in COLUMNS["raw_materials"] if c not in ("description", "image_url", "tags")],
               sorted(tables["raw_materials"].values(), key=lambda r: r["id"]))
    _write_csv(os.path.join(sheets, "regulatory.csv"),
               [c for c in COLUMNS["regulatory"] if c not in ("conditions", "warnings", "data_via")],
               sorted(tables["regulatory"].values(), key=lambda r: r["id"]))

    # ---- dashboard feed
    counts = {t: sum(1 for r in tables[t].values() if r.get("record_status") != "removed") for t in COLUMNS}
    counts["ingredients"] = len(ingredients)
    counts["products_with_regulated_ingredients"] = sum(1 for r in tables["products"].values()
                                                      if r.get("record_status") != "removed" and r.get("regulated_ingredient_count"))
    history = defaultdict(list)
    for h in hist:
        history[h["source_id"]].append({"run_id": h["run_id"], "status": h["status"]})
    status = {"generated_at": now.isoformat(timespec="seconds"), "run_id": run_id, "date": today,
              "totals": counts, "sources": src_rows,
              "history": {k: v[-30:] for k, v in history.items()},
              "recent_changes": [c for c in log if c["change"] != "initial_import"][-150:][::-1],
              "imports": [c for c in log if c["change"] == "initial_import"][-30:][::-1]}
    _write_json(os.path.join(DATA, "status.json"), status, pretty=True)
    _write_json(os.path.join(DOCS, "status.json"), status)


if __name__ == "__main__":
    main()
