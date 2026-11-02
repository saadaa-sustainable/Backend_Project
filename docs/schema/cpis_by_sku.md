# `cpis_by_sku`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~318 rows (planner estimate) · 120 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `window_key` | `text` | no |  |
| 3 | `window_from` | `date` | yes |  |
| 4 | `window_to` | `date` | yes |  |
| 5 | `units_sold` | `numeric` | yes |  |
| 6 | `ending_inventory_units` | `numeric` | yes |  |
| 7 | `avg_sell_through_rate` | `numeric` | yes |  |
| 8 | `matched_ad_count` | `integer` | yes |  |
| 9 | `ad_spend` | `numeric` | yes |  |
| 10 | `ncp_count` | `numeric` | yes |  |
| 11 | `cost_per_ncp` | `numeric` | yes |  |
| 12 | `cost_per_unit_sold` | `numeric` | yes |  |
| 13 | `computed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `cpis_by_sku_pkey`
  - `CREATE UNIQUE INDEX cpis_by_sku_pkey ON public.cpis_by_sku USING btree (master_sku, window_key)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more
- `window_key` → `cpis_by_sku_utm`, `master_sku_returns`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
