# `meta_hypothesis_tests`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~103 rows (planner estimate) · 264 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `row_index` | `integer` | yes |  |
| 2 | `test_date` | `text` | yes |  |
| 3 | `test_date_parsed` | `date` | yes |  |
| 4 | `month_of_testing` | `text` | yes |  |
| 5 | `test_category` | `text` | yes |  |
| 6 | `hypothesis_code` | `text` | yes |  |
| 7 | `hypothesis` | `text` | yes |  |
| 8 | `test_status` | `text` | yes |  |
| 9 | `primary_kpi` | `text` | yes |  |
| 10 | `success_criteria` | `text` | yes |  |
| 11 | `test_threshold` | `text` | yes |  |
| 12 | `confidence_interval` | `text` | yes |  |
| 13 | `supporting_metrics` | `text` | yes |  |
| 14 | `budget_per_day` | `text` | yes |  |
| 15 | `launch_date` | `text` | yes |  |
| 16 | `launch_date_parsed` | `date` | yes |  |
| 17 | `ad_account` | `text` | yes |  |
| 18 | `entity_raw` | `text` | yes |  |
| 19 | `entity_names` | `text[]` | yes |  |
| 20 | `matched_level` | `text` | yes |  |
| 21 | `matched_id` | `text` | yes |  |
| 22 | `matched_name` | `text` | yes |  |
| 23 | `completion_date` | `text` | yes |  |
| 24 | `completion_date_parsed` | `date` | yes |  |
| 25 | `total_ad_spend` | `text` | yes |  |
| 26 | `performance_summary` | `text` | yes |  |
| 27 | `insight_audience` | `text` | yes |  |
| 28 | `insight_creative` | `text` | yes |  |
| 29 | `insight_extra` | `text` | yes |  |
| 30 | `kpi_change` | `text` | yes |  |
| 31 | `outcome_next_steps` | `text` | yes |  |
| 32 | `detail_link` | `text` | yes |  |
| 33 | `test_result` | `text` | yes |  |
| 34 | `ingested_at` | `timestamp with time zone` | no | `now()` |
| 35 | `id` | `bigint` | no | `nextval('meta_hypothesis_tests_id_seq'::regclass)` |
| 36 | `source` | `text` | no | `'sheet'::text` |
| 37 | `created_at` | `timestamp with time zone` | no | `now()` |
| 38 | `updated_at` | `timestamp with time zone` | no | `now()` |
| 39 | `created_by` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `meta_hypothesis_tests_id_pkey`
  - `CREATE UNIQUE INDEX meta_hypothesis_tests_id_pkey ON public.meta_hypothesis_tests USING btree (id)`
- Unique — `meta_hypothesis_sheet_row`: `CREATE UNIQUE INDEX meta_hypothesis_sheet_row ON public.meta_hypothesis_tests USING btree (row_index) WHERE (source = 'sheet'::text)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
