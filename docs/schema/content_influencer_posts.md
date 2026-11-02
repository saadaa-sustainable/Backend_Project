# `content_influencer_posts`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~14,794 rows (planner estimate) · 10 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `bigint` | yes |  |
| 2 | `post_id` | `text` | no |  |
| 3 | `post_id_short` | `text` | yes |  |
| 4 | `username` | `text` | yes |  |
| 5 | `nomenclature` | `text` | yes |  |
| 6 | `content_type` | `text` | yes |  |
| 7 | `deliverable_type` | `text` | yes |  |
| 8 | `deliverable_role` | `text` | yes |  |
| 9 | `collab_type` | `text` | yes |  |
| 10 | `campaign_id` | `text` | yes |  |
| 11 | `post_date` | `date` | yes |  |
| 12 | `created_at` | `timestamp with time zone` | yes |  |
| 13 | `updated_at` | `timestamp with time zone` | yes |  |
| 14 | `workflow_status` | `text` | yes |  |
| 15 | `partnership_status` | `text` | yes |  |
| 16 | `ads_status` | `text` | yes |  |
| 17 | `ads_results` | `text` | yes |  |
| 18 | `ads_usage_rights` | `text` | yes |  |
| 19 | `post_link` | `text` | yes |  |
| 20 | `download_link` | `text` | yes |  |
| 21 | `post_thumbnail` | `text` | yes |  |
| 22 | `computed_is_tested` | `boolean` | yes |  |
| 23 | `matched_ad_id` | `text` | yes |  |
| 24 | `matched_ad_name` | `text` | yes |  |
| 25 | `mirrored_at` | `timestamp with time zone` | yes |  |
| 26 | `ingested_from_ctd_at` | `timestamp with time zone` | no | `now()` |
| 27 | `source_testing_status` | `text` | yes |  |
| 28 | `source_ad_result` | `text` | yes |  |
| 29 | `source_table` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `content_influencer_posts_pkey`
  - `CREATE UNIQUE INDEX content_influencer_posts_pkey ON public.content_influencer_posts USING btree (post_id)`
- Index — `idx_cip_computed_is_tested`: `CREATE INDEX idx_cip_computed_is_tested ON public.content_influencer_posts USING btree (computed_is_tested)`
- Index — `idx_cip_matched_ad_id`: `CREATE INDEX idx_cip_matched_ad_id ON public.content_influencer_posts USING btree (matched_ad_id) WHERE (matched_ad_id IS NOT NULL)`
- Index — `idx_cip_username`: `CREATE INDEX idx_cip_username ON public.content_influencer_posts USING btree (username)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more
- `matched_ad_id` → `content_asset_register`, `content_graphic_register`, `shopify_order_attribution`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
