# `sku_price_impact_compare`

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
| 5 | `price_change` | `numeric` | yes |  |
| 6 | `hidden` | `boolean` | yes |  |
| 7 | `anchor_day` | `date` | yes |  |
| 8 | `anchor_at_new_price` | `boolean` | yes |  |
| 9 | `sessions_today` | `numeric` | yes |  |
| 10 | `sessions_prev_day` | `numeric` | yes |  |
| 11 | `sessions_prev_week` | `numeric` | yes |  |
| 12 | `sessions_prev_month` | `numeric` | yes |  |
| 13 | `atc_rate_today` | `numeric` | yes |  |
| 14 | `atc_rate_prev_day` | `numeric` | yes |  |
| 15 | `atc_rate_prev_week` | `numeric` | yes |  |
| 16 | `atc_rate_prev_month` | `numeric` | yes |  |
| 17 | `units_today` | `integer` | yes |  |
| 18 | `units_prev_day` | `integer` | yes |  |
| 19 | `units_prev_week` | `integer` | yes |  |
| 20 | `units_prev_month` | `integer` | yes |  |
| 21 | `revenue_today` | `numeric` | yes |  |
| 22 | `revenue_prev_day` | `numeric` | yes |  |
| 23 | `revenue_prev_week` | `numeric` | yes |  |
| 24 | `revenue_prev_month` | `numeric` | yes |  |
| 25 | `collection_sessions_today` | `numeric` | yes |  |
| 26 | `units_per_1k_today` | `numeric` | yes |  |
| 27 | `units_per_1k_prev_week` | `numeric` | yes |  |

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
