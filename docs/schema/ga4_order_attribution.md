# `ga4_order_attribution`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~329,392 rows (planner estimate) · 365 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `transaction_id` | `text` | no |  |
| 2 | `order_at` | `timestamp with time zone` | yes |  |
| 3 | `user_pseudo_id` | `text` | yes |  |
| 4 | `revenue` | `numeric` | yes |  |
| 5 | `first_seen_at` | `timestamp with time zone` | yes |  |
| 6 | `first_source` | `text` | yes |  |
| 7 | `first_medium` | `text` | yes |  |
| 8 | `first_campaign` | `text` | yes |  |
| 9 | `first_campaign_id` | `text` | yes |  |
| 10 | `first_ad_id` | `text` | yes |  |
| 11 | `first_adset_id` | `text` | yes |  |
| 12 | `first_landing` | `text` | yes |  |
| 13 | `last_landing` | `text` | yes |  |
| 14 | `total_sessions` | `integer` | yes |  |
| 15 | `sourced_sessions` | `integer` | yes |  |
| 16 | `days_to_convert` | `integer` | yes |  |
| 17 | `fetched_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `ga4_order_attribution_pkey`
  - `CREATE UNIQUE INDEX ga4_order_attribution_pkey ON public.ga4_order_attribution USING btree (transaction_id)`
- Index — `ix_ga4_oa_first_ad`: `CREATE INDEX ix_ga4_oa_first_ad ON public.ga4_order_attribution USING btree (first_ad_id)`
- Index — `ix_ga4_oa_order_at`: `CREATE INDEX ix_ga4_oa_order_at ON public.ga4_order_attribution USING btree (order_at)`
- Index — `ix_ga4_oa_user`: `CREATE INDEX ix_ga4_oa_user ON public.ga4_order_attribution USING btree (user_pseudo_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `first_ad_id` → `shopify_order_clicks`
- `first_adset_id` → `shopify_order_clicks`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
