# `shopify_order_clicks`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_no` | `text` | yes |  |
| 2 | `order_at` | `timestamp with time zone` | yes |  |
| 3 | `order_day` | `date` | yes |  |
| 4 | `revenue` | `numeric` | yes |  |
| 5 | `financial_status` | `text` | yes |  |
| 6 | `first_seen_at` | `timestamp with time zone` | yes |  |
| 7 | `first_ad_id` | `text` | yes |  |
| 8 | `first_adset_id` | `text` | yes |  |
| 9 | `first_source` | `text` | yes |  |
| 10 | `first_medium` | `text` | yes |  |
| 11 | `first_campaign` | `text` | yes |  |
| 12 | `last_ad_id` | `text` | yes |  |
| 13 | `last_adset_id` | `text` | yes |  |
| 14 | `last_source` | `text` | yes |  |
| 15 | `last_medium` | `text` | yes |  |
| 16 | `last_campaign` | `text` | yes |  |
| 17 | `last_click_tier` | `text` | yes |  |
| 18 | `days_to_convert` | `integer` | yes |  |
| 19 | `total_sessions` | `integer` | yes |  |
| 20 | `seen_by_ga4` | `boolean` | yes |  |
| 21 | `attributed` | `boolean` | yes |  |

## Keys and indexes

- **No primary key.**
- No indexes. Any filter on this table is a sequential scan.

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `first_ad_id` → `ga4_order_attribution`
- `first_adset_id` → `ga4_order_attribution`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
