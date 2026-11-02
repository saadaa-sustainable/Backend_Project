# `ad_name_override`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~98 rows (planner estimate) · 120 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `utm_content_lower` | `text` | no |  |
| 2 | `adset_id` | `text` | no | `'*'::text` |
| 3 | `ad_id` | `text` | no |  |
| 4 | `ad_name` | `text` | yes |  |
| 5 | `note` | `text` | yes |  |
| 6 | `added_at` | `timestamp with time zone` | no | `now()` |
| 7 | `weight` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `ad_name_override_pkey`
  - `CREATE UNIQUE INDEX ad_name_override_pkey ON public.ad_name_override USING btree (utm_content_lower, adset_id, ad_id)`
- Index — `ix_ad_name_override_ad_id`: `CREATE INDEX ix_ad_name_override_ad_id ON public.ad_name_override USING btree (ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
