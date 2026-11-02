# `shopify_sessions`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~2,188,822 rows (planner estimate) · 822 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `session_key` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `referrer_source` | `text` | yes |  |
| 4 | `utm_source` | `text` | yes |  |
| 5 | `utm_campaign` | `text` | yes |  |
| 6 | `utm_medium` | `text` | yes |  |
| 7 | `sessions` | `numeric` | yes |  |
| 8 | `pageviews` | `numeric` | yes |  |
| 9 | `conversion_rate` | `numeric` | yes |  |
| 10 | `bounce_rate` | `numeric` | yes |  |
| 11 | `extracted_at` | `timestamp with time zone` | yes |  |
| 12 | `flattened_at` | `timestamp with time zone` | yes |  |
| 13 | `bounces` | `numeric` | yes |  |
| 14 | `average_session_duration` | `numeric` | yes |  |
| 15 | `pageviews_per_session` | `numeric` | yes |  |
| 16 | `online_store_visitors` | `numeric` | yes |  |
| 17 | `added_to_cart_rate` | `numeric` | yes |  |
| 18 | `sessions_with_cart_additions` | `numeric` | yes |  |
| 19 | `reached_checkout_rate` | `numeric` | yes |  |
| 20 | `sessions_that_reached_checkout` | `numeric` | yes |  |
| 21 | `checkout_conversion_rate` | `numeric` | yes |  |
| 22 | `completed_checkout_rate` | `numeric` | yes |  |
| 23 | `sessions_that_completed_checkout` | `numeric` | yes |  |
| 24 | `sessions_that_reached_and_completed_checkout` | `numeric` | yes |  |
| 25 | `landing_page_path` | `text` | yes |  |
| 26 | `landing_page_type` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_sessions_pkey`
  - `CREATE UNIQUE INDEX shopify_sessions_pkey ON public.shopify_sessions USING btree (session_key)`
- Index — `ix_shopify_sessions_day_sessions`: `CREATE INDEX ix_shopify_sessions_day_sessions ON public.shopify_sessions USING btree (day) INCLUDE (sessions)`
- Index — `ix_shopify_sessions_landing_page_path`: `CREATE INDEX ix_shopify_sessions_landing_page_path ON public.shopify_sessions USING btree (landing_page_path)`
- Index — `ix_shopify_sessions_utm_campaign`: `CREATE INDEX ix_shopify_sessions_utm_campaign ON public.shopify_sessions USING btree (utm_campaign)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
