# `sku_price_impact_summary`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `direction` | `text` | yes |  |
| 2 | `hidden` | `boolean` | yes |  |
| 3 | `anchor_day` | `date` | yes |  |
| 4 | `skus` | `bigint` | yes |  |
| 5 | `sessions_today` | `numeric` | yes |  |
| 6 | `sessions_prev_day` | `numeric` | yes |  |
| 7 | `sessions_prev_week` | `numeric` | yes |  |
| 8 | `sessions_prev_month` | `numeric` | yes |  |
| 9 | `atc_rate_today` | `numeric` | yes |  |
| 10 | `atc_rate_prev_day` | `numeric` | yes |  |
| 11 | `atc_rate_prev_week` | `numeric` | yes |  |
| 12 | `atc_rate_prev_month` | `numeric` | yes |  |
| 13 | `units_today` | `bigint` | yes |  |
| 14 | `units_prev_day` | `bigint` | yes |  |
| 15 | `units_prev_week` | `bigint` | yes |  |
| 16 | `units_prev_month` | `bigint` | yes |  |
| 17 | `revenue_today` | `numeric` | yes |  |
| 18 | `revenue_prev_day` | `numeric` | yes |  |
| 19 | `revenue_prev_week` | `numeric` | yes |  |
| 20 | `revenue_prev_month` | `numeric` | yes |  |

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
