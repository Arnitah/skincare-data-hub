"""Milk Ingredient Atlas + research registers, linked to live hub data.

Reference files (curated by hand, in reference/):
  milk_atlas.json              35 atlas entries (Beauty Intelligence Stage 8.52B)
  milk_atlas_matchers.yaml     how each entry is recognised in ingredient lists
  milk_research_registers.json traditions / commercial products / scientific evidence registers

Every run re-matches the atlas against all active products and raw materials, so new products that
contain e.g. donkey milk or colostrum appear automatically. Matches are always record_status=candidate:
an ingredient list showing a material is a lead, not a verified claim.
"""
import json
import os
import re
from collections import Counter, defaultdict

import yaml

from . import inci

REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference")

MATCH_COLS = ["atlas_id", "atlas_name", "match_type", "table", "record_id", "source_id", "brand", "name",
              "category_group", "matched_ingredient", "ingredient_position", "ingredient_count", "country",
              "countries_sold", "url", "record_status", "first_seen"]
SUMMARY_COLS = ["atlas_id", "name", "group", "products_exact", "products_related", "raw_materials_exact",
                "raw_materials_related", "new_matches_today", "example_products", "atlas_commercial_examples",
                "atlas_verification_status", "evidence_ids", "tradition_ids"]

# Which register rows speak to which atlas entries (by the material each row is about)
EVIDENCE_LINKS = {
    "EV-01": ["MILK-027", "MILK-028", "MILK-029", "MILK-030"], "EV-02": ["MILK-027", "MILK-032"],
    "EV-03": ["MILK-006"], "EV-04": ["MILK-010"], "EV-07": ["MILK-027", "MILK-028"],
    "EV-08": ["MILK-011", "MILK-025"], "EV-09": ["MILK-009", "MILK-010", "MILK-011", "MILK-012", "MILK-013"],
}
TRADITION_LINKS = {"TR-01": ["MILK-006"], "TR-02": ["MILK-001", "MILK-027"], "TR-03": ["MILK-002"],
                   "TR-04": ["MILK-003"], "TR-05": ["MILK-005"], "TR-06": ["MILK-011", "MILK-025"],
                   "TR-07": ["MILK-009"], "TR-08": ["MILK-012"], "TR-09": ["MILK-022"], "TR-10": ["MILK-032"]}
COMMERCIAL_LINKS = {"PR-01": ["MILK-002"], "PR-02": ["MILK-005"], "PR-03": ["MILK-006"], "PR-04": ["MILK-006"],
                    "PR-05": ["MILK-009", "MILK-028"], "PR-06": ["MILK-010"], "PR-07": ["MILK-025"],
                    "PR-08": ["MILK-011", "MILK-025"], "PR-09": ["MILK-022"]}

# Evidence applies to a specific ingredient FORM, not a whole atlas family: colloidal-oatmeal evidence must never
# attach to oat milk. These patterns (on the normalised ingredient key) decide which ingredients an evidence row covers.
EVIDENCE_KEYS = {
    "EV-01": r"\b(milk protein|lactis proteinum|hydroly[sz]ed milk protein|whey|lactis serum|casein|caseinate)",
    "EV-02": r"\b(milk protein|lactis proteinum|colostrum|lactoferrin)",
    "EV-03": r"\b(donkey( s)? milk|lac asinae|asinae lac|equus asinus milk|lait d anesse)",
    "EV-04": r"\bcolloidal oatmeal\b",
    "EV-07": r"\b(milk protein|lactis proteinum|hydroly[sz]ed milk protein|milk protein hydrolysate)",
}

# Register-strength text is kept verbatim; letter grades (A-D) are assigned by a reviewer in
# reviews/record_reviews.csv, never inferred here.
SAFETY_OR_EFFICACY = {"EV-01": "safety", "EV-02": "efficacy", "EV-03": "efficacy", "EV-04": "efficacy",
                      "EV-05": "data_rule", "EV-06": "data_rule", "EV-07": "safety", "EV-08": "data_rule",
                      "EV-09": "data_rule", "EV-10": "data_rule"}

EVIDENCE_COLS = ["evidence_id", "atlas_ids", "claim_text", "ingredient_formulation_or_derivative", "study_type",
                 "result_summary", "limitations", "strength_as_registered", "evidence_grade",
                 "evidence_grade_rationale", "safety_or_efficacy", "source_url", "link_notes", "record_status",
                 "review_date", "reviewer_notes", "imported_from"]
TRADITION_COLS = ["tradition_id", "atlas_ids", "material_or_ingredient", "region_or_community", "practice_description",
                  "evidence_status", "documentation_quality", "next_step", "source_url", "link_notes",
                  "record_status", "review_date", "reviewer_notes", "imported_from"]
COMMERCIAL_COLS = ["commercial_product_id", "atlas_ids", "brand", "product_name", "material_claim", "market",
                   "product_type", "availability_status", "ingredient_interpretation", "product_url",
                   "hub_product_matches", "record_status", "review_date", "reviewer_notes", "imported_from"]


def _load():
    atlas = json.load(open(os.path.join(REF, "milk_atlas.json"), encoding="utf-8"))
    matchers = yaml.safe_load(open(os.path.join(REF, "milk_atlas_matchers.yaml"), encoding="utf-8"))
    regs = json.load(open(os.path.join(REF, "milk_research_registers.json"), encoding="utf-8"))
    compiled = {}
    for aid, m in matchers.items():
        compiled[aid] = {k: [re.compile(p if p.startswith(("^", "\\b")) else r"\b" + p) for p in (m or {}).get(k, [])]
                         for k in ("exact", "related", "exclude")}   # word boundary: 'oat milk' must not match 'goat milk'
    return atlas, compiled, regs


def _classify(key, m):
    if not key or any(p.search(key) for p in m["exclude"]):
        return None
    if any(p.search(key) for p in m["exact"]):
        return "exact"
    if any(p.search(key) for p in m["related"]):
        return "related"
    return None


def build(products, raw_materials, today):
    """Return dict of output tables. products / raw_materials: active records only."""
    atlas, matchers, regs = _load()
    names = {r["atlas_id"]: r["name"] for r in atlas["records"]}
    matches = []
    cache = {}                                 # ingredient_key -> [(atlas_id, match_type)]

    def classify_all(k):
        if k not in cache:
            cache[k] = [(aid, mt) for aid, m in matchers.items() for mt in [_classify(k, m)] if mt]
        return cache[k]

    def row(aid, mt, table, rec, ingredient, pos):
        return {"atlas_id": aid, "atlas_name": names.get(aid, ""), "match_type": mt, "table": table,
                "record_id": rec["id"], "source_id": rec["source_id"], "brand": rec.get("brand", ""),
                "name": rec.get("name", ""),
                "category_group": rec.get("category_group", "") if table == "products" else "raw_material",
                "matched_ingredient": ingredient, "ingredient_position": pos,
                "ingredient_count": rec.get("ingredient_count", "") if table == "products" else "",
                "country": rec.get("country", ""), "countries_sold": rec.get("countries_sold", ""),
                "url": rec.get("url", ""), "record_status": "candidate", "first_seen": rec.get("first_seen", "")}

    def best_hits(named_items):
        """named_items: [(position, ingredient_name)] -> {atlas_id: (match_type, position, name)}; exact beats related."""
        best = {}
        for pos, name in named_items:
            for aid, mt in classify_all(inci.key(name)):
                cur = best.get(aid)
                if cur is None or (mt == "exact" and cur[0] == "related"):
                    best[aid] = (mt, pos, name)
        return best

    for p in products:
        for aid, (mt, pos, name) in best_hits(list(enumerate(p.get("ingredients") or [], 1))).items():
            matches.append(row(aid, mt, "products", p, name, pos))
    for r in raw_materials:
        comps = [c for c in (r.get("inci_components") or "").split("; ") if c] or [r.get("inci", "")]
        for aid, (mt, _pos, name) in best_hits([("", c) for c in comps]).items():
            matches.append(row(aid, mt, "raw_materials", r, name, ""))

    key_to_atlas = {k: v for k, v in cache.items() if v}

    by_atlas = defaultdict(list)
    for m in matches:
        by_atlas[m["atlas_id"]].append(m)

    def links(table, aid):
        return [k for k, v in table.items() if aid in v]

    def example_rank(m):
        brand_site = 0 if m["source_id"] != "open_beauty_facts" else 1
        return (brand_site, not m["brand"], m["ingredient_position"] or 99)

    atlas_out, summary = [], []
    for rec in atlas["records"]:
        aid = rec["atlas_id"]
        ms = by_atlas.get(aid, [])
        pe = [m for m in ms if m["table"] == "products" and m["match_type"] == "exact"]
        pr = [m for m in ms if m["table"] == "products" and m["match_type"] == "related"]
        re_ = [m for m in ms if m["table"] == "raw_materials" and m["match_type"] == "exact"]
        rr = [m for m in ms if m["table"] == "raw_materials" and m["match_type"] == "related"]
        new_today = sum(1 for m in ms if m["first_seen"] == today)
        ex = sorted(pe, key=example_rank)[:12]
        hub = {
            "products_exact": len(pe), "products_related": len(pr),
            "raw_materials_exact": len(re_), "raw_materials_related": len(rr), "new_matches_today": new_today,
            "by_source": dict(Counter(m["source_id"] for m in pe + pr).most_common()),
            "by_category_group": dict(Counter(m["category_group"] for m in pe).most_common()),
            "top_countries_sold": dict(Counter(c.strip() for m in pe for c in (m["countries_sold"] or "").split(";")
                                               if c.strip()).most_common(8)),
            "example_products": [{k: m[k] for k in ("brand", "name", "source_id", "matched_ingredient",
                                                     "ingredient_position", "ingredient_count", "url")} for m in ex],
            "example_raw_materials": [{k: m[k] for k in ("name", "source_id", "country", "matched_ingredient", "url")}
                                      for m in (re_ + rr)[:8]],
            "evidence_ids": links(EVIDENCE_LINKS, aid), "tradition_ids": links(TRADITION_LINKS, aid),
            "commercial_register_ids": links(COMMERCIAL_LINKS, aid),
            "record_status": "candidate",
            "note": "Hub matches are ingredient-list leads (record_status=candidate), not verified product claims.",
        }
        atlas_out.append(dict(rec, hub_matches=hub))
        summary.append({"atlas_id": aid, "name": rec["name"], "group": rec.get("group", ""),
                        "products_exact": len(pe), "products_related": len(pr), "raw_materials_exact": len(re_),
                        "raw_materials_related": len(rr), "new_matches_today": new_today,
                        "example_products": " | ".join(f"{m['brand']} {m['name']}".strip()[:60] for m in ex[:3]),
                        "atlas_commercial_examples": (rec.get("commercial_examples") or "")[:200],
                        "atlas_verification_status": rec.get("verification_status", ""),
                        "evidence_ids": "; ".join(hub["evidence_ids"]), "tradition_ids": "; ".join(hub["tradition_ids"])})

    # ---- registers in the starter-pack shape
    imported = regs.get("imported_from", "")
    evidence = []
    for r in regs.get("scientific_evidence_register", []):
        evidence.append({
            "evidence_id": r["id"], "atlas_ids": "; ".join(EVIDENCE_LINKS.get(r["id"], [])),
            "claim_text": r.get("question", ""), "ingredient_formulation_or_derivative": r.get("material", ""),
            "study_type": r.get("evidence_type", ""), "result_summary": r.get("finding", ""),
            "limitations": r.get("limits", ""), "strength_as_registered": r.get("strength", ""),
            "evidence_grade": "U", "evidence_grade_rationale": "Not graded yet - assign A-D in reviews/record_reviews.csv",
            "safety_or_efficacy": SAFETY_OR_EFFICACY.get(r["id"], ""),
            "source_url": " | ".join(r.get("source_urls", [])), "link_notes": r.get("link_corrections", ""),
            "record_status": "candidate", "review_date": regs.get("reviewDate", ""), "reviewer_notes": "",
            "imported_from": imported})
    traditions = []
    for r in regs.get("traditions_register", []):
        traditions.append({
            "tradition_id": r["id"], "atlas_ids": "; ".join(TRADITION_LINKS.get(r["id"], [])),
            "material_or_ingredient": r.get("material", ""), "region_or_community": r.get("region_context", ""),
            "practice_description": r.get("reported_use", ""), "evidence_status": r.get("verification_status", ""),
            "documentation_quality": r.get("confidence", ""), "next_step": r.get("next_step", ""),
            "source_url": " | ".join(r.get("source_urls", [])), "link_notes": r.get("link_corrections", ""),
            "record_status": "candidate", "review_date": regs.get("reviewDate", ""), "reviewer_notes": "",
            "imported_from": imported})
    commercial = []
    for r in regs.get("commercial_product_register", []):
        aids = COMMERCIAL_LINKS.get(r["id"], [])
        brand = (r.get("brand") or "").lower()
        hub_hits = [m for m in matches if m["table"] == "products" and m["atlas_id"] in aids
                    and brand and brand in (m["brand"] or "").lower()]
        commercial.append({
            "commercial_product_id": r["id"], "atlas_ids": "; ".join(aids), "brand": r.get("brand", ""),
            "product_name": r.get("product", ""), "material_claim": r.get("material_claim", ""),
            "market": r.get("market", ""), "product_type": r.get("format", ""),
            "availability_status": r.get("verification_status", ""),
            "ingredient_interpretation": r.get("ingredient_interpretation", ""),
            "product_url": " | ".join(r.get("source_urls", [])),
            "hub_product_matches": " | ".join(f"{m['name'][:50]} ({m['url']})" for m in hub_hits[:5]),
            "record_status": "candidate" if r["id"] != "PR-10" else "not_applicable",
            "review_date": regs.get("reviewDate", ""), "reviewer_notes": "", "imported_from": imported})

    return {"atlas": {"title": atlas.get("title"), "imported_from": atlas.get("imported_from"),
                      "generated": today, "records": atlas_out},
            "matches": matches, "summary": summary, "key_to_atlas": key_to_atlas,
            "evidence": evidence, "traditions": traditions, "commercial": commercial}
