# `shopify_attribution_coverage`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_day` | `date` | yes |  |
| 2 | `orders` | `bigint` | yes |  |
| 3 | `revenue` | `numeric` | yes |  |
| 4 | `attributed_orders` | `bigint` | yes |  |
| 5 | `attributed_revenue` | `numeric` | yes |  |
| 6 | `unattr_not_in_ga4` | `bigint` | yes |  |
| 7 | `unattr_no_first_click` | `bigint` | yes |  |
| 8 | `unattr_no_last_click` | `bigint` | yes |  |

## Keys and indexes

- **No primary key.**
- No indexes. Any filter on this table is a sequential scan.

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
