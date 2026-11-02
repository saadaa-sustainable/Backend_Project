# `cpis_value_weighted_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~103,045 rows (planner estimate) · 38 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `entity_id` | `text` | no |  |
| 3 | `master_sku` | `text` | no |  |
| 4 | `attributed_orders` | `integer` | no |  |
| 5 | `attributed_units` | `integer` | no |  |
| 6 | `attributed_revenue` | `numeric` | no |  |
| 7 | `order_revenue` | `numeric` | no |  |
| 8 | `order_units` | `integer` | no |  |
| 9 | `entity_orders` | `integer` | no |  |
| 10 | `entity_spend` | `numeric` | no |  |
| 11 | `ad_spend` | `numeric` | no |  |
| 12 | `halo_orders` | `integer` | no |  |
| 13 | `halo_units` | `integer` | no |  |
| 14 | `halo_revenue` | `numeric` | no |  |
| 15 | `refreshed_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `cpis_value_weighted_daily_pkey`
  - `CREATE UNIQUE INDEX cpis_value_weighted_daily_pkey ON public.cpis_value_weighted_daily USING btree (day, entity_id, master_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `entity_id` → `ad_reach_cumulative`
- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
