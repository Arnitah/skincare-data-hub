"""Open Beauty Facts: daily full CSV export, filtered to products that list ingredients.

Licence: Open Database Licence (ODbL). Attribution + share-alike apply to this table.
"""
import csv
import gzip
import io
import sys

from .. import inci, net

EXPORT = "https://static.openbeautyfacts.org/data/en.openbeautyfacts.org.products.csv.gz"
csv.field_size_limit(sys.maxsize)


def _clean_tags(v):
    return "; ".join(t.split(":", 1)[-1].replace("-", " ") for t in (v or "").split(",") if t)


def run(src, ctx):
    r = net.get(ctx["session"], EXPORT, delay=0, timeout=300)
    raw = gzip.decompress(r.content).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    records = []
    for row in reader:
        text = (row.get("ingredients_text") or "").strip()
        code = (row.get("code") or "").strip()
        if not text or not code:
            continue
        raw_items = inci.split_list(text)
        items = [i for i in raw_items if inci.looks_valid(i)]
        if len(items) < 2 or len(items) < 0.6 * len(raw_items):   # mostly unreadable label text -> skip
            continue
        records.append({
            "id": f"{src['id']}:{code}", "source_id": src["id"],
            "country": "GLOBAL", "currency": "",
            "name": (row.get("product_name") or "").strip() or "(unnamed)",
            "brand": (row.get("brands") or "").split(",")[0].strip(),
            "category": (row.get("main_category_en") or "").strip() or _clean_tags(row.get("categories_tags")).split("; ")[0],
            "tags": _clean_tags(row.get("categories_tags"))[:400],
            "barcode": code,
            "size": (row.get("quantity") or "").strip(),
            "countries_sold": _clean_tags(row.get("countries_tags")),
            "url": f"https://world.openbeautyfacts.org/product/{code}",
            "image_url": row.get("image_url") or "",
            "price_min": None, "price_max": None, "sizes": "", "in_stock": None,
            "ingredients_text": text[:4000],
            "ingredients": items,
            "ingredient_count": len(items),
        })
    return {"records": records, "warnings": [], "pages_failed": 0}
