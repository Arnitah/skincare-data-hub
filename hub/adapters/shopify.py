"""Generic Shopify store adapter (products.json feed + optional product-page fetch).

Works for raw-material suppliers (-> raw_materials table) and brand stores (-> products table).
Product pages are only re-fetched when the product's updated_at changed since the last run.
"""
from concurrent.futures import ThreadPoolExecutor

from .. import extract, inci, net


def _feed(s, base):
    out, page = [], 1
    while page <= 40:
        r = net.get(s, f"{base}/products.json?limit=250&page={page}", delay=1.0)
        batch = r.json().get("products", [])
        if not batch:
            break
        out += batch
        page += 1
    return out


def _keep(p, src):
    title = (p.get("title") or "").lower()
    ptype = p.get("product_type") or ""
    if "include_types" in src and ptype not in src["include_types"]:
        return False
    if ptype in src.get("exclude_types", []):
        return False
    if set(p.get("tags") or []) & set(src.get("exclude_tags", [])):
        return False
    if any(w.lower() in title for w in src.get("exclude_title_words", [])):
        return False
    return True


def _prices(p):
    ps = [float(v["price"]) for v in p.get("variants", []) if v.get("price")]
    sizes = [v.get("title") for v in p.get("variants", []) if v.get("title") and v["title"] != "Default Title"]
    return (min(ps) if ps else None, max(ps) if ps else None, "; ".join(sizes[:12]),
            any(v.get("available") for v in p.get("variants", [])))


def run(src, ctx):
    s, base, kind = ctx["session"], src["base_url"].rstrip("/"), src["kind"]
    prev = ctx["previous"]
    cache = ctx["cache"]          # handle -> {"u": updated_at, "has": bool}; persisted between runs
    products = [p for p in _feed(s, base) if _keep(p, src)]
    warnings, failed = [], 0

    # Decide which product pages need fetching
    page_text = {}
    if src.get("fetch_pages"):
        todo = []
        for p in products:
            rid = f"{src['id']}:{p['handle']}"
            c = cache.get(p["handle"])
            unchanged = c and c.get("u") == p.get("updated_at")
            if unchanged and (prev.get(rid) or not c.get("has")):
                page_text[p["handle"]] = None          # unchanged since last run: reuse / skip
            else:
                todo.append(p["handle"])

        def fetch(h):
            try:
                return h, extract.text(net.get(s, f"{base}/products/{h}", delay=src.get("page_delay", 1.5)).text)
            except Exception as e:  # noqa: BLE001
                return h, e

        upd = {p["handle"]: p.get("updated_at") for p in products}
        with ThreadPoolExecutor(max_workers=2) as ex:
            for h, res in ex.map(fetch, todo):
                if getattr(getattr(res, "response", None), "status_code", None) == 404:
                    # unpublished/hidden listing (draft copies, regional duplicates): not an error, skip it
                    cache[h] = {"u": upd.get(h), "has": False}
                    page_text[h] = None
                    continue
                if isinstance(res, Exception):
                    failed += 1
                    page_text[h] = False
                else:
                    page_text[h] = res

    records = []
    for p in products:
        rid = f"{src['id']}:{p['handle']}"
        old = prev.get(rid)
        body = extract.text(p.get("body_html"))
        pt = page_text.get(p["handle"])
        if pt is False or (pt is None and src.get("fetch_pages")):
            if old:                                   # page failed or unchanged -> keep last good extraction
                rec = dict(old)
                rec.update(_live_fields(p, src))
                records.append(rec)
            continue
        full = body + "\n" + (pt or "")

        lo, hi, sizes, avail = _prices(p)
        common = {
            "id": rid, "source_id": src["id"], "country": src["country"], "currency": src.get("currency", ""),
            "name": p["title"].strip(), "category": p.get("product_type") or "",
            "tags": "; ".join(p.get("tags") or [])[:500],
            "url": f"{base}/products/{p['handle']}",
            "image_url": (p.get("images") or [{}])[0].get("src", "") if p.get("images") else "",
            "price_min": lo, "price_max": hi, "sizes": sizes, "in_stock": avail,
        }
        if kind == "raw_material":
            inci_name = extract.inci(full)
            if src.get("fetch_pages"):
                cache[p["handle"]] = {"u": p.get("updated_at"), "has": bool(inci_name)}
            if src.get("require_inci") and not inci_name:
                continue
            ulo, uhi = extract.percent_range(full)
            plo, phi = extract.ph_range(full)
            comps = inci.split_blend(inci_name)
            common.update({
                "inci": inci_name,
                "inci_components": "; ".join(comps),
                "ingredient_keys": "; ".join(dict.fromkeys(k for k in (inci.key(c) for c in comps) if k)),
                "cas": "", "botanical_name": "", "plant_part": "",
                "use_level_min_pct": ulo, "use_level_max_pct": uhi,
                "use_level_text": extract.use_level_text(full),
                "ph_min": plo, "ph_max": phi,
                "solubility": extract.solubility(full),
                "shelf_life_months": extract.shelf_life_months(full),
                "description": body[:600],
            })
        else:
            ing = extract.ingredient_list(full)
            if src.get("fetch_pages"):
                cache[p["handle"]] = {"u": p.get("updated_at"), "has": bool(ing)}
            if src.get("require_inci") and not ing:
                continue
            items = [i for i in inci.split_list(ing) if inci.looks_valid(i)]
            common.update({
                "brand": src.get("brand", ""), "barcode": "",
                "size": extract.size_from_title(p["title"]) or sizes,
                "countries_sold": src["country"],
                "ingredients_text": ing,
                "ingredients": items,
                "ingredient_count": len(items),
            })
        records.append(common)

    if failed:
        warnings.append(f"{failed} product page(s) failed to load; kept previous data for those")
    return {"records": records, "warnings": warnings, "pages_failed": failed}


def _live_fields(p, src):
    lo, hi, sizes, avail = _prices(p)
    return {"price_min": lo, "price_max": hi, "sizes": sizes, "in_stock": avail, "name": p["title"].strip()}
