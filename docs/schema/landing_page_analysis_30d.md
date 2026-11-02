# `landing_page_analysis_30d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~3,016 rows (planner estimate) · 976 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `landing_page_path` | `text` | no |  |
| 2 | `window_from` | `date` | yes |  |
| 3 | `window_to` | `date` | yes |  |
| 4 | `sessions` | `bigint` | yes |  |
| 5 | `visitors` | `bigint` | yes |  |
| 6 | `cart_addition_sessions` | `bigint` | yes |  |
| 7 | `checkout_sessions` | `bigint` | yes |  |
| 8 | `bounces` | `bigint` | yes |  |
| 9 | `ad_spend` | `numeric(14,2)` | yes |  |
| 10 | `ad_impressions` | `bigint` | yes |  |
| 11 | `ad_conv_value` | `numeric(14,2)` | yes |  |
| 12 | `distinct_ads` | `integer` | yes |  |
| 13 | `atc_rate` | `numeric` | yes |  |
| 14 | `checkout_rate` | `numeric` | yes |  |
| 15 | `bounce_rate` | `numeric` | yes |  |
| 16 | `cost_per_session` | `numeric` | yes |  |
| 17 | `computed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `landing_page_analysis_30d_pkey`
  - `CREATE UNIQUE INDEX landing_page_analysis_30d_pkey ON public.landing_page_analysis_30d USING btree (landing_page_path)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
