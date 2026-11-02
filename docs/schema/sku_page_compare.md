# `sku_page_compare`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~3,271 rows (planner estimate) · 1352 kB

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
| 8 | `page_type` | `text` | yes |  |
| 9 | `page_path` | `text` | yes |  |
| 10 | `page_title` | `text` | yes |  |
| 11 | `skus_on_page` | `integer` | yes |  |
| 12 | `product_status` | `text` | yes |  |
| 13 | `sessions_today` | `numeric` | yes |  |
| 14 | `sessions_prev_day` | `numeric` | yes |  |
| 15 | `sessions_prev_week` | `numeric` | yes |  |
| 16 | `sessions_prev_month` | `numeric` | yes |  |
| 17 | `atc_rate_today` | `numeric` | yes |  |
| 18 | `atc_rate_prev_day` | `numeric` | yes |  |
| 19 | `atc_rate_prev_week` | `numeric` | yes |  |
| 20 | `atc_rate_prev_month` | `numeric` | yes |  |
| 21 | `revenue_today` | `numeric` | yes |  |
| 22 | `revenue_prev_day` | `numeric` | yes |  |
| 23 | `revenue_prev_week` | `numeric` | yes |  |
| 24 | `revenue_prev_month` | `numeric` | yes |  |
| 25 | `orders_today` | `numeric` | yes |  |
| 26 | `orders_prev_day` | `numeric` | yes |  |
| 27 | `orders_prev_week` | `numeric` | yes |  |
| 28 | `orders_prev_month` | `numeric` | yes |  |
| 29 | `revenue_per_1k_today` | `numeric` | yes |  |
| 30 | `revenue_per_1k_prev_week` | `numeric` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ix_spc_key`: `CREATE UNIQUE INDEX ix_spc_key ON public.sku_page_compare USING btree (master_sku, page_type, page_path)`
- Index — `ix_spc_tab`: `CREATE INDEX ix_spc_tab ON public.sku_page_compare USING btree (page_type, master_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
