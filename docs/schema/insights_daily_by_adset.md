# `insights_daily_by_adset`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~67,868 rows (planner estimate) · 21 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `adset_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `spend` | `numeric` | yes |  |
| 4 | `impressions` | `numeric` | yes |  |
| 5 | `reach` | `numeric` | yes |  |
| 6 | `clicks` | `numeric` | yes |  |
| 7 | `all_clicks` | `numeric` | yes |  |
| 8 | `conv_value` | `numeric` | yes |  |
| 9 | `purchases` | `numeric` | yes |  |
| 10 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |
| 11 | `ftewv_count` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `insights_daily_by_adset_pkey`
  - `CREATE UNIQUE INDEX insights_daily_by_adset_pkey ON public.insights_daily_by_adset USING btree (adset_id, day)`
- Index — `ix_insights_daily_by_adset_day`: `CREATE INDEX ix_insights_daily_by_adset_day ON public.insights_daily_by_adset USING btree (day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
