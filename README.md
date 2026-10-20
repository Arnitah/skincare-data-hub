# Skincare Data Hub

One shared, self-updating database that **Safe Batch** (DIY recipe safety) and **Clay** (finished-product
skincare app) both read from. Every day a GitHub Action visits each source, records what is new, changed
or removed, and publishes the result as plain CSV/JSON files plus a status page.

- **Status dashboard:** https://arnitah.github.io/skincare-data-hub/
- **Data files:** [`data/`](data/) (raw URLs below)
- **Schedule:** daily 09:17 UTC (05:17 Toronto) — see [`.github/workflows/daily.yml`](.github/workflows/daily.yml).
  Run on demand from the **Actions** tab → *Daily data refresh* → *Run workflow*.

## Tables

| File | One row per | Used by |
|---|---|---|
| `data/raw_materials.csv` / `.json` | supplier listing of a DIY ingredient (INCI, CAS, use level %, pH, solubility, shelf life, price) | Safe Batch |
| `data/products.csv` / `.json` | finished product (brand, barcode, full ingredient list, countries sold, price) | Clay |
| `data/product_ingredients.csv` | product × ingredient, in label order | Clay |
| `data/ingredients.csv` / `.json` | unique ingredient (normalised INCI key) with counts and per-country regulatory flags | both |
| `data/regulatory.csv` / `.json` | per-country rule (prohibited / restricted, max concentration, warnings, official source) | both |
| `data/sources.csv` | source, **with status columns**: `last_run_status` (passed / partial / failed / paused), `last_run_at`, `last_success_at`, `consecutive_failures`, records added/changed/removed, `message` | monitoring |
| `data/sync_runs.csv` | source × run (12-month history) | monitoring |
| `data/change_log.csv` | field-level change (added / changed / removed), 180 days | both |
| `data/sheets/*.csv` | slimmer copies sized for Google Sheets | Google Sheet |

Every row carries `record_status` (`active` / `removed`), `first_seen`, `last_seen` and `last_changed`.
Apps should normally filter to `record_status = active`.

**JSON is the richer format.** `raw_materials.json` keeps source-specific detail in `extra`
(e.g. Native Extracts phyto-compounds, concerns, FSANZ IDs); `products.json` has `ingredients` as an ordered list.

### Reading from an app

```
https://raw.githubusercontent.com/Arnitah/skincare-data-hub/main/data/products.json
https://raw.githubusercontent.com/Arnitah/skincare-data-hub/main/data/raw_materials.json
https://raw.githubusercontent.com/Arnitah/skincare-data-hub/main/data/ingredients.json
https://raw.githubusercontent.com/Arnitah/skincare-data-hub/main/data/regulatory.json
https://raw.githubusercontent.com/Arnitah/skincare-data-hub/main/data/status.json
```

Cache these (they change at most once a day) rather than fetching per request.

## How different countries are handled

- **INCI name is the join key.** It is the one ingredient identifier used worldwide. Names are normalised
  (`hub/inci.py`) so `Aqua/Water/Eau` → `water`, `(Mango)`-style common names are dropped, etc. CAS numbers
  are used as a second match for regulatory rules.
- **Values are stored as published plus normalised:** original price + `currency`, and `price_min_usd`
  (daily ECB rates via frankfurter.dev). `country` = where the source is based; `countries_sold` = where a
  product is sold.
- **Rules are per jurisdiction.** `regulatory_flags` on each ingredient/raw material lists every
  jurisdiction's status (e.g. `EU: restricted (max 2%); CA: prohibited`). `flagged_ingredient_count` on
  products counts ingredients that are prohibited or restricted somewhere.
- **One failing source never affects the others**, and a source that suddenly returns far fewer records than
  yesterday is marked *failed* and its previous data is kept (guards against site redesigns wiping data).

## Sources

Configured in [`sources.yaml`](sources.yaml). Set `active: true/false` to switch one on or off.

| Kind | Source | Country |
|---|---|---|
| DIY raw materials | Native Extracts, Lotioncrafter, Formulator Sample Shop, Windy Point Soap Making Supplies, Aromantic | AU, US, US, CA, GB |
| Finished products | Open Beauty Facts, Round Lab, COSRX | Global, KR, KR |
| Regulatory | EU annexes, Health Canada Hotlist, US FDA (on) · GB, KR, AU, JP, CN, ASEAN, BR, IN, NZ, SA (off) | |

### Adding a source

- **A Shopify store** (most indie suppliers and brands): add an entry with `adapter: shopify`, its
  `base_url`, `kind`, `country`, `currency`, and include/exclude filters. Add `fetch_pages: true` if the
  ingredient list is only on the product page.
- **Anything else:** add a module in `hub/adapters/` exposing `run(src, ctx)` and register it in
  `hub/adapters/__init__.py`.

Run locally: `pip install -r requirements.txt && python -m hub.run --only <source_id>`

## Caveats

- Supplier "concern"/"benefit" tags are marketing positioning, not efficacy or safety evidence.
- Use levels, pH and solubility are parsed from supplier text; blanks mean the supplier didn't publish them.
- Regulatory data comes from cosingchecker.com, a third-party structured copy of official sources; each rule
  keeps `official_source_url` and `source_url`. Verify against the official source before relying on a rule.
- Open Beauty Facts data is © Open Beauty Facts contributors under the
  [Open Database Licence](https://opendatacommons.org/licenses/odbl/1-0/); derived product tables must keep
  attribution and the same licence.
- Native Extracts samples are trade-only (not for personal use) per their site.
- Requests identify themselves with a `skincare-data-hub` user agent and are rate-limited per host.
