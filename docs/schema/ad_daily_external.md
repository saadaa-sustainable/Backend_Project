# `ad_daily_external`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~654,790 rows (planner estimate) · 205 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `spend` | `numeric` | yes |  |
| 4 | `impressions` | `numeric` | yes |  |
| 5 | `reach` | `numeric` | yes |  |
| 6 | `conv_value` | `numeric` | yes |  |
| 7 | `ncp_count` | `numeric` | yes |  |
| 8 | `ftewv_count` | `numeric` | yes |  |
| 9 | `synced_at` | `timestamp with time zone` | yes |  |
| 10 | `purchases` | `numeric` | yes |  |
| 11 | `link_clicks` | `numeric` | yes |  |
| 12 | `shopify_orders` | `numeric` | yes |  |
| 13 | `shopify_sales` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `ad_daily_external_pkey`
  - `CREATE UNIQUE INDEX ad_daily_external_pkey ON public.ad_daily_external USING btree (ad_id, day)`
- Index — `ix_ade_ad_day`: `CREATE INDEX ix_ade_ad_day ON public.ad_daily_external USING btree (ad_id, day)`
- Index — `ix_ade_day`: `CREATE INDEX ix_ade_day ON public.ad_daily_external USING btree (day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
