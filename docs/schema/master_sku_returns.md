# `master_sku_returns`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~265 rows (planner estimate) · 96 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `window_key` | `text` | no |  |
| 3 | `window_from` | `date` | yes |  |
| 4 | `window_to` | `date` | yes |  |
| 5 | `orders_count` | `integer` | yes |  |
| 6 | `units_ordered` | `numeric` | yes |  |
| 7 | `units_returned` | `numeric` | yes |  |
| 8 | `return_rate_pct` | `numeric` | yes |  |
| 9 | `refund_value` | `numeric` | yes |  |
| 10 | `exchange_count` | `integer` | yes |  |
| 11 | `updated_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `master_sku_returns_pkey`
  - `CREATE UNIQUE INDEX master_sku_returns_pkey ON public.master_sku_returns USING btree (master_sku, window_key)`
- Index — `ix_msr_window`: `CREATE INDEX ix_msr_window ON public.master_sku_returns USING btree (window_key)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more
- `window_key` → `cpis_by_sku`, `cpis_by_sku_utm`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
