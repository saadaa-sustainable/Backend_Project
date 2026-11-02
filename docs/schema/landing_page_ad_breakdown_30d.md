# `landing_page_ad_breakdown_30d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~13,066 rows (planner estimate) · 8184 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `landing_page_path` | `text` | no |  |
| 2 | `ad_id` | `text` | no |  |
| 3 | `ad_name` | `text` | yes |  |
| 4 | `ad_status` | `text` | yes |  |
| 5 | `campaign_name` | `text` | yes |  |
| 6 | `adset_name` | `text` | yes |  |
| 7 | `account_name` | `text` | yes |  |
| 8 | `preview_link` | `text` | yes |  |
| 9 | `ad_link` | `text` | yes |  |
| 10 | `impressions` | `bigint` | yes |  |
| 11 | `spend` | `numeric(14,2)` | yes |  |
| 12 | `conv_value` | `numeric(14,2)` | yes |  |
| 13 | `purchases` | `integer` | yes |  |
| 14 | `meta_roas` | `numeric` | yes |  |
| 15 | `shopify_orders` | `integer` | yes |  |
| 16 | `shopify_sales` | `numeric(14,2)` | yes |  |
| 17 | `shopify_roas` | `numeric` | yes |  |
| 18 | `roas_gap_pct` | `numeric` | yes |  |
| 19 | `page_sessions` | `bigint` | yes |  |
| 20 | `page_atc_rate` | `numeric` | yes |  |
| 21 | `page_bounce_rate` | `numeric` | yes |  |
| 22 | `page_cost_per_sess` | `numeric` | yes |  |
| 23 | `window_from` | `date` | yes |  |
| 24 | `window_to` | `date` | yes |  |
| 25 | `computed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `landing_page_ad_breakdown_30d_pkey`
  - `CREATE UNIQUE INDEX landing_page_ad_breakdown_30d_pkey ON public.landing_page_ad_breakdown_30d USING btree (landing_page_path, ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
