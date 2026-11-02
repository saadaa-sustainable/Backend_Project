# `shopify_landing_page_analysis`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~878,077 rows (planner estimate) · 163 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | yes |  |
| 2 | `landing_page_path` | `text` | yes |  |
| 3 | `landing_page_type` | `text` | yes |  |
| 4 | `referrer_source` | `text` | yes |  |
| 5 | `matched_campaign_id` | `text` | yes |  |
| 6 | `matched_campaign_name` | `text` | yes |  |
| 7 | `sessions` | `numeric` | yes |  |
| 8 | `pageviews` | `numeric` | yes |  |
| 9 | `sessions_with_cart_additions` | `numeric` | yes |  |
| 10 | `sessions_that_reached_checkout` | `numeric` | yes |  |
| 11 | `sessions_that_completed_checkout` | `numeric` | yes |  |
| 12 | `added_to_cart_rate` | `numeric` | yes |  |
| 13 | `conversion_rate` | `numeric` | yes |  |
| 14 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **No primary key.**
- Index — `ix_shopify_landing_page_analysis_campaign`: `CREATE INDEX ix_shopify_landing_page_analysis_campaign ON public.shopify_landing_page_analysis USING btree (matched_campaign_id)`
- Index — `ix_shopify_landing_page_analysis_day`: `CREATE INDEX ix_shopify_landing_page_analysis_day ON public.shopify_landing_page_analysis USING btree (day)`
- Index — `ix_shopify_landing_page_analysis_path`: `CREATE INDEX ix_shopify_landing_page_analysis_path ON public.shopify_landing_page_analysis USING btree (landing_page_path)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `matched_campaign_id` → `shopify_order_attribution`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
