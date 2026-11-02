# `content_graphic_register`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~2,586 rows (planner estimate) · 2024 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `requisition_id` | `text` | no |  |
| 2 | `asset_date` | `date` | yes |  |
| 3 | `priority` | `text` | yes |  |
| 4 | `creative` | `text` | yes |  |
| 5 | `nomenclature` | `text` | yes |  |
| 6 | `reference_links` | `text` | yes |  |
| 7 | `product` | `text` | yes |  |
| 8 | `audience_type` | `text` | yes |  |
| 9 | `graphic_type` | `text` | yes |  |
| 10 | `key_message` | `text` | yes |  |
| 11 | `things_to_note` | `text` | yes |  |
| 12 | `objective` | `text` | yes |  |
| 13 | `demographic` | `text` | yes |  |
| 14 | `who_is_this_for` | `text` | yes |  |
| 15 | `visuals` | `text` | yes |  |
| 16 | `count_9_16` | `integer` | yes |  |
| 17 | `count_4_5` | `integer` | yes |  |
| 18 | `count_16_9` | `integer` | yes |  |
| 19 | `count_1_1` | `integer` | yes |  |
| 20 | `total_count` | `integer` | yes |  |
| 21 | `platform` | `text` | yes |  |
| 22 | `assignee` | `text` | yes |  |
| 23 | `catchphrase_main` | `text` | yes |  |
| 24 | `catchphrase_sub` | `text` | yes |  |
| 25 | `due_date` | `date` | yes |  |
| 26 | `status_of_completion` | `text` | yes |  |
| 27 | `date_of_completion` | `date` | yes |  |
| 28 | `status_of_testing` | `text` | yes |  |
| 29 | `test_results` | `text` | yes |  |
| 30 | `test_status` | `text` | yes |  |
| 31 | `status` | `text` | yes |  |
| 32 | `ad_id` | `text` | yes |  |
| 33 | `ad_launch_date` | `date` | yes |  |
| 34 | `impressions` | `bigint` | yes |  |
| 35 | `cac` | `numeric` | yes |  |
| 36 | `link_1` | `text` | yes |  |
| 37 | `link_2` | `text` | yes |  |
| 38 | `link_3` | `text` | yes |  |
| 39 | `summary_status` | `text` | yes |  |
| 40 | `summary_result` | `text` | yes |  |
| 41 | `mirrored_at` | `timestamp with time zone` | yes |  |
| 42 | `computed_is_tested` | `boolean` | yes |  |
| 43 | `matched_ad_id` | `text` | yes |  |
| 44 | `matched_ad_name` | `text` | yes |  |
| 45 | `ingested_from_ctd_at` | `timestamp with time zone` | no | `now()` |
| 46 | `source_ad_id` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `content_graphic_register_pkey`
  - `CREATE UNIQUE INDEX content_graphic_register_pkey ON public.content_graphic_register USING btree (requisition_id)`
- Index — `idx_cgr_ad_id`: `CREATE INDEX idx_cgr_ad_id ON public.content_graphic_register USING btree (ad_id) WHERE (ad_id IS NOT NULL)`
- Index — `idx_cgr_computed_is_tested`: `CREATE INDEX idx_cgr_computed_is_tested ON public.content_graphic_register USING btree (computed_is_tested)`
- Index — `idx_cgr_matched_ad_id`: `CREATE INDEX idx_cgr_matched_ad_id ON public.content_graphic_register USING btree (matched_ad_id) WHERE (matched_ad_id IS NOT NULL)`
- Index — `idx_cgr_product`: `CREATE INDEX idx_cgr_product ON public.content_graphic_register USING btree (product)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `matched_ad_id` → `content_asset_register`, `content_influencer_posts`, `shopify_order_attribution`
- `requisition_id` → `content_edited_content`, `content_iterated_register`
- `source_ad_id` → `content_asset_register`, `content_edited_content`, `content_iterated_register`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
