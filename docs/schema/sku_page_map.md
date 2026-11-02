# `sku_page_map`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~4,942 rows (planner estimate) · 1288 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `page_path` | `text` | no |  |
| 3 | `page_type` | `text` | no |  |
| 4 | `page_title` | `text` | yes |  |
| 5 | `skus_on_page` | `integer` | yes |  |
| 6 | `product_handle` | `text` | yes |  |
| 7 | `product_status` | `text` | yes |  |
| 8 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `sku_page_map_pkey`
  - `CREATE UNIQUE INDEX sku_page_map_pkey ON public.sku_page_map USING btree (master_sku, page_path)`
- Index — `ix_spm_path`: `CREATE INDEX ix_spm_path ON public.sku_page_map USING btree (page_path)`
- Index — `ix_spm_type`: `CREATE INDEX ix_spm_type ON public.sku_page_map USING btree (page_type)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
