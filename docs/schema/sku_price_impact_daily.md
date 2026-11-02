# `sku_price_impact_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~11,253 rows (planner estimate) · 2560 kB

> dc78bae13862f0f7

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | yes |  |
| 2 | `day` | `date` | yes |  |
| 3 | `old_price` | `numeric` | yes |  |
| 4 | `new_price` | `numeric` | yes |  |
| 5 | `price_change` | `numeric` | yes |  |
| 6 | `direction` | `text` | yes |  |
| 7 | `hidden` | `boolean` | yes |  |
| 8 | `at_new_price` | `boolean` | yes |  |
| 9 | `product_sessions` | `numeric` | yes |  |
| 10 | `product_atc` | `numeric` | yes |  |
| 11 | `product_atc_rate` | `numeric` | yes |  |
| 12 | `product_checkout_rate` | `numeric` | yes |  |
| 13 | `collection_sessions` | `numeric` | yes |  |
| 14 | `collection_atc_rate` | `numeric` | yes |  |
| 15 | `units_sold` | `integer` | yes |  |
| 16 | `revenue` | `numeric` | yes |  |
| 17 | `units_per_1k_sessions` | `numeric` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ix_spid_sku_day`: `CREATE UNIQUE INDEX ix_spid_sku_day ON public.sku_price_impact_daily USING btree (master_sku, day)`
- Index — `ix_spid_day`: `CREATE INDEX ix_spid_day ON public.sku_price_impact_daily USING btree (day)`

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
