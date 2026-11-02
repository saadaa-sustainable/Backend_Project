# `ga4_daily_landing`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~783,996 rows (planner estimate) · 325 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `property_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `landing_page` | `text` | no |  |
| 4 | `channel_group` | `text` | no |  |
| 5 | `sessions` | `bigint` | yes |  |
| 6 | `total_users` | `bigint` | yes |  |
| 7 | `pdp_views` | `bigint` | yes |  |
| 8 | `add_to_carts` | `bigint` | yes |  |
| 9 | `checkouts` | `bigint` | yes |  |
| 10 | `purchases` | `bigint` | yes |  |
| 11 | `revenue` | `numeric` | yes |  |
| 12 | `bounce_rate` | `numeric` | yes |  |
| 13 | `key_event_rate` | `numeric` | yes |  |
| 14 | `engaged_sessions` | `bigint` | yes |  |
| 15 | `property_timezone` | `text` | yes |  |
| 16 | `sampled` | `boolean` | yes | `false` |
| 17 | `thresholded` | `boolean` | yes | `false` |
| 18 | `fetched_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `ga4_daily_landing_pkey`
  - `CREATE UNIQUE INDEX ga4_daily_landing_pkey ON public.ga4_daily_landing USING btree (property_id, day, landing_page, channel_group)`
- Index — `ix_ga4_landing_channel`: `CREATE INDEX ix_ga4_landing_channel ON public.ga4_daily_landing USING btree (channel_group)`
- Index — `ix_ga4_landing_day`: `CREATE INDEX ix_ga4_landing_day ON public.ga4_daily_landing USING btree (day)`
- Index — `ix_ga4_landing_page`: `CREATE INDEX ix_ga4_landing_page ON public.ga4_daily_landing USING btree (landing_page)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
