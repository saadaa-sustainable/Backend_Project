# `cpis_by_sku_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~9,863 rows (planner estimate) · 1880 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `attributed_orders` | `integer` | yes |  |
| 4 | `attributed_units` | `integer` | yes |  |
| 5 | `attributed_revenue` | `numeric` | yes |  |
| 6 | `matched_ad_count` | `integer` | yes |  |
| 7 | `ad_spend` | `numeric` | yes |  |
| 8 | `ad_spend_vw` | `numeric` | yes |  |
| 9 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |
| 10 | `halo_orders` | `integer` | yes | `0` |
| 11 | `halo_units` | `integer` | yes | `0` |
| 12 | `halo_revenue` | `numeric` | yes | `0` |
| 13 | `order_revenue` | `numeric` | yes |  |
| 14 | `order_units` | `integer` | yes |  |
| 15 | `google_spend` | `numeric` | yes | `0` |
| 16 | `google_spend_vw` | `numeric` | yes | `0` |

## Keys and indexes

- **Primary key** — `cpis_by_sku_daily_pkey`
  - `CREATE UNIQUE INDEX cpis_by_sku_daily_pkey ON public.cpis_by_sku_daily USING btree (master_sku, day)`
- Index — `ix_cbsd_day`: `CREATE INDEX ix_cbsd_day ON public.cpis_by_sku_daily USING btree (day)`
- Index — `ix_cbsd_sku`: `CREATE INDEX ix_cbsd_sku ON public.cpis_by_sku_daily USING btree (master_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
