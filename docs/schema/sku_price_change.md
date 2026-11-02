# `sku_price_change`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~93 rows (planner estimate) · 32 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `old_price` | `numeric` | yes |  |
| 3 | `new_price` | `numeric` | yes |  |
| 4 | `price_change` | `numeric` | yes |  |
| 5 | `direction` | `text` | yes |  |
| 6 | `effective_date` | `date` | no |  |
| 7 | `hidden` | `boolean` | no | `false` |
| 8 | `loaded_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `sku_price_change_pkey`
  - `CREATE UNIQUE INDEX sku_price_change_pkey ON public.sku_price_change USING btree (master_sku)`

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
