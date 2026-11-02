# `ad_reach_cumulative`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~998,110 rows (planner estimate) · 330 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `level` | `text` | no |  |
| 2 | `entity_id` | `text` | no |  |
| 3 | `as_of_date` | `date` | no |  |
| 4 | `epoch_date` | `date` | no |  |
| 5 | `entity_name` | `text` | yes |  |
| 6 | `account_id` | `text` | yes |  |
| 7 | `cumulative_reach` | `bigint` | no |  |
| 8 | `cumulative_impressions` | `bigint` | yes |  |
| 9 | `cumulative_spend` | `numeric(18,4)` | yes |  |
| 10 | `fetched_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_reach_cumulative_pkey`
  - `CREATE UNIQUE INDEX ad_reach_cumulative_pkey ON public.ad_reach_cumulative USING btree (level, entity_id, epoch_date, as_of_date)`
- Index — `ix_arc_entity`: `CREATE INDEX ix_arc_entity ON public.ad_reach_cumulative USING btree (entity_id, as_of_date DESC)`
- Index — `ix_arc_epoch_date`: `CREATE INDEX ix_arc_epoch_date ON public.ad_reach_cumulative USING btree (epoch_date)`
- Index — `ix_arc_level_asof`: `CREATE INDEX ix_arc_level_asof ON public.ad_reach_cumulative USING btree (level, as_of_date DESC)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `as_of_date` → `inventory_variant_current`, `master_sku_inventory_current`
- `entity_id` → `cpis_value_weighted_daily`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
