# `sku_price_impact_pages`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | yes |  |
| 2 | `direction` | `text` | yes |  |
| 3 | `old_price` | `numeric` | yes |  |
| 4 | `new_price` | `numeric` | yes |  |
| 5 | `page_type` | `text` | yes |  |
| 6 | `page_path` | `text` | yes |  |
| 7 | `page_title` | `text` | yes |  |
| 8 | `skus_on_page` | `integer` | yes |  |
| 9 | `product_status` | `text` | yes |  |
| 10 | `sessions_7d` | `numeric` | yes |  |
| 11 | `atc_rate_7d` | `numeric` | yes |  |

## Keys and indexes

- **No primary key.**
- No indexes. Any filter on this table is a sequential scan.

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
