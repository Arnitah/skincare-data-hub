"""Native Extracts (Australia): Shopify feed + structured product pages.

Pages carry far more than a generic store: phyto-compounds, application categories/concerns,
compliance IDs (CAS, EC, INCI, FSANZ), plant part, origin, solubility, shelf life.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from .. import inci, net
from .shopify import _feed, _prices

FAQ_SOLVENT = "Water/Glycerin (preserved with Potassium Sorbate + Sodium Benzoate; Citric Acid for pH) per site FAQ"


def _lines(el):
    if el is None:
        return []
    for br in el.find_all("br"):
        br.replace_with("\n")
    return [re.sub(r"\s+", " ", x).strip() for x in el.get_text("\n").split("\n") if x.strip()]


def _parse(html):
    s = BeautifulSoup(html, "html.parser")
    facts = {}
    for t in s.select(".ProductDetail__Title"):
        c = t.find_next_sibling(class_="ProductDetail__Content")
        if c:
            facts.setdefault(t.get_text(" ", strip=True), " ".join(_lines(c)))
    compounds = []
    for btn in s.select(".Collapsible__Button"):
        if "Phyto-Compounds" in btn.get_text():
            inner = btn.find_next_sibling(class_="Collapsible__Inner")
            compounds = _lines(inner.select_one(".Rte")) if inner else []
            break
    tabs = {}
    for d in s.select(".DetailTab"):
        h, c = d.find("h2"), d.select_one(".DetailTab__Content")
        if h and c:
            tabs.setdefault(h.get_text(" ", strip=True), _lines(c))
    apps = {}
    for t in s.select(".ProductIcon__Title"):
        title = t.get_text(" ", strip=True)
        coll = t.find_parent(class_="Collapsible")
        items = [i for i in _lines(coll.select_one(".ProductIcon__Content") if coll else None)
                 if not i.upper().startswith(("MORE FROM", "MORE FORM"))]
        if title and title not in apps:
            apps[title] = list(dict.fromkeys("Conditioning" if i == "Condition" else i for i in items))
    bot = ""
    h1 = s.find("h1")
    if h1 and h1.find_next("h2"):
        bot = h1.find_next("h2").get_text(" ", strip=True)
    return facts, compounds, tabs, apps, bot


def _compliance(lines):
    d = {}
    for l in lines:
        m = re.match(r"^(CAS|EC|EINECS|INCI|INC|NCI|Food ID|PFK ID)\s*:\s*(.*)$", l, re.I)
        if m:
            k = {"INC": "INCI", "NCI": "INCI"}.get(m.group(1).upper(), m.group(1).upper())
            d.setdefault(k, m.group(2).strip())
    return d


def _shelf(lines):
    m = re.search(r"(\d+)\s*-?\s*(\d+)?\s*months", " ".join(lines), re.I)
    return int(m.group(1)) if m else None


def run(src, ctx):
    s, base = ctx["session"], src["base_url"].rstrip("/")
    products = _feed(s, base)

    def fetch(p):
        try:
            return p, net.get(s, f"{base}/products/{p['handle']}", delay=0.7).text
        except Exception as e:  # noqa: BLE001
            return p, e

    records, failed = [], 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for p, html in ex.map(fetch, products):
            rid = f"{src['id']}:{p['handle']}"
            if isinstance(html, Exception):
                failed += 1
                if rid in ctx["previous"]:
                    records.append(ctx["previous"][rid])
                continue
            facts, compounds, tabs, apps, bot = _parse(html)
            comp = _compliance(tabs.get("Compliance", []))
            inci_name = comp.get("INCI", "")
            lo, hi, sizes, avail = _prices(p)
            ptype = p.get("product_type") or ""
            concerns = list(dict.fromkeys(c for items in apps.values() for c in items))
            composition = " | ".join(tabs.get("Composition", []))
            if ptype == "Carrier Oil":
                solv = "Oil (cold pressed)"
            elif "Water/Glycerin" in composition:
                solv = "Water/Glycerin"
            else:
                solv = FAQ_SOLVENT
            records.append({
                "id": rid, "source_id": src["id"], "country": src["country"], "currency": src["currency"],
                "name": p["title"].strip(), "category": ptype,
                "tags": "; ".join(t for t in p.get("tags", []) if t in ("Australian Native", "Traditional Botanical", "Native India", "Mushroom")),
                "url": f"{base}/products/{p['handle']}",
                "image_url": (p.get("images") or [{}])[0].get("src", "") if p.get("images") else "",
                "price_min": lo, "price_max": hi, "sizes": sizes, "in_stock": avail,
                "inci": inci_name,
                "inci_components": re.split(r"\s+/\s+|;\s*", inci_name)[0].strip() if inci_name else "",
                "ingredient_keys": inci.key(re.split(r"\s+/\s+|;\s*", inci_name)[0]) if inci_name else "",
                "cas": comp.get("CAS", ""),
                "botanical_name": bot,
                "plant_part": facts.get("Plant part", ""),
                "use_level_min_pct": None, "use_level_max_pct": None, "use_level_text": "",  # not published; request TDS
                "ph_min": None, "ph_max": None,
                "solubility": "Oil soluble" if ptype == "Carrier Oil" else ("Water soluble" if facts.get("Water-soluble") == "Yes" else ""),
                "shelf_life_months": _shelf(tabs.get("Shelf Life", [])),
                "description": "",
                "extra": {
                    "ec": comp.get("EC", ""), "fsanz_food_id": comp.get("FOOD ID", ""), "fsanz_pfk_id": comp.get("PFK ID", ""),
                    "botanical_origin": facts.get("Botanical Origin", ""), "grade_source": facts.get("Source", ""),
                    "topical": facts.get("Topical", ""), "ingestible": facts.get("Ingestible", "") or None,
                    "solvent": solv, "phyto_compounds": compounds,
                    "application_categories": list(apps.keys()), "concerns": concerns,
                    "product_formats": tabs.get("Delivery", []),
                    "certified_palm_oil_free": "CERTIFIED PALM OIL FREE" in tabs,
                },
            })
    warnings = [f"{failed} product page(s) failed to load; kept previous data for those"] if failed else []
    return {"records": records, "warnings": warnings, "pages_failed": failed}
