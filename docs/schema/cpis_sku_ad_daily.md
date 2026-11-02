# `cpis_sku_ad_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~71,939 rows (planner estimate) · 11 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `master_sku` | `text` | no |  |
| 3 | `ad_id` | `text` | no |  |
| 4 | `refreshed_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `cpis_sku_ad_daily_pkey`
  - `CREATE UNIQUE INDEX cpis_sku_ad_daily_pkey ON public.cpis_sku_ad_daily USING btree (day, master_sku, ad_id)`
- Index — `ix_csad_ad_day`: `CREATE INDEX ix_csad_ad_day ON public.cpis_sku_ad_daily USING btree (ad_id, day)`
- Index — `ix_csad_sku_day`: `CREATE INDEX ix_csad_sku_day ON public.cpis_sku_ad_daily USING btree (master_sku, day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
