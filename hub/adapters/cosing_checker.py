"""Per-country cosmetic ingredient rules via CosIng Checker (cosingchecker.com).

Third-party structured copy of official regulator sources; every rule keeps its official URL.
EU rules come back as annex entries (II prohibited, III restricted, IV colorants, V preservatives,
VI UV filters); other jurisdictions come back with an explicit status.
"""
from .. import inci, net

API = "https://cosingchecker.com/api/v1"
EU_ANNEX_STATUS = {"II": "prohibited", "III": "restricted", "IV": "allowed_colorant",
                   "V": "allowed_preservative", "VI": "allowed_uv_filter"}


def run(src, ctx):
    s, j = ctx["session"], src["jurisdiction"]
    url = f"{API}/jurisdictions/{j}/rules/?per_page=100&page=1"
    meta = {}
    try:
        for x in net.get(s, f"{API}/jurisdictions/", delay=0.6).json()["results"]:
            if x["code"] == j:
                meta = x
    except Exception:  # noqa: BLE001
        pass
    records = []
    while url:
        d = net.get(s, url, delay=0.6).json()
        for r in d["results"]:
            records.append(_eu(r, src, meta) if r.get("evidence_type") == "eu_annex_entry" else _std(r, src, meta))
        url = d.get("next")
    # de-duplicate ids (rare duplicates in source)
    seen, out = set(), []
    for r in records:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return {"records": out, "warnings": [], "pages_failed": 0}


def _base(src, meta):
    return {"source_id": src["id"], "jurisdiction": src["jurisdiction"].upper(), "country": src["country"],
            "regulator": meta.get("regulator", ""), "official_source_url": meta.get("official_source_url", ""),
            "data_via": "cosingchecker.com (third-party structured copy)"}


def _eu(r, src, meta):
    names = r.get("identified_ingredients") or []
    inci_name = r.get("inci_glossary_name") or (names[0] if names else "")
    rec = _base(src, meta)
    rec.update({
        "id": f"{src['id']}:annex-{r.get('annex')}-{r.get('entry_number')}-{r.get('id')}",
        "substance": r.get("display_name") or r.get("chemical_name") or "",
        "inci": inci_name, "ingredient_key": inci.key(inci_name),
        "also_known_as": "; ".join(names[:8]),
        "cas": r.get("cas_number") or "", "ec": r.get("ec_number") or "",
        "status": EU_ANNEX_STATUS.get(r.get("annex"), "listed"),
        "reference": f"Annex {r.get('annex')} / {r.get('entry_number')}",
        "product_type": r.get("product_type") or "",
        "max_concentration": r.get("max_concentration") or "",
        "conditions": (r.get("other_restrictions") or "")[:1500],
        "warnings": (r.get("warnings") or "")[:1500],
        "legal_role": "binding",
        "source_version": r.get("regulation") or "",
        "source_updated": r.get("update_date") or "",
        "source_url": "https://cosingchecker.com" + (r.get("url") or ""),
    })
    return rec


def _std(r, src, meta):
    sub = r.get("substance") or {}
    name = sub.get("name") or ""
    rec = _base(src, meta)
    rec.update({
        "id": f"{src['id']}:{r.get('source_record_id') or name}",
        "substance": name,
        "inci": name, "ingredient_key": inci.key(name),
        "also_known_as": "",
        "cas": sub.get("cas_number") or "", "ec": sub.get("ec_number") or "",
        "status": r.get("status") or "",
        "reference": r.get("source_reference") or "",
        "product_type": "",
        "max_concentration": "",
        "conditions": (r.get("conditions") or "")[:1500],
        "warnings": (r.get("summary") or "")[:1500],
        "legal_role": r.get("legal_role") or "",
        "source_version": r.get("source_version") or "",
        "source_updated": r.get("source_updated_date") or "",
        "source_url": r.get("source_url") or "",
    })
    return rec
