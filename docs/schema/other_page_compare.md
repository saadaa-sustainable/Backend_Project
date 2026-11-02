# `other_page_compare`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~71 rows (planner estimate) · 120 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `page_type` | `text` | yes |  |
| 2 | `page_path` | `text` | yes |  |
| 3 | `anchor_day` | `date` | yes |  |
| 4 | `sku_note` | `text` | yes |  |
| 5 | `sessions_today` | `numeric` | yes |  |
| 6 | `sessions_prev_day` | `numeric` | yes |  |
| 7 | `sessions_prev_week` | `numeric` | yes |  |
| 8 | `sessions_prev_month` | `numeric` | yes |  |
| 9 | `atc_rate_today` | `numeric` | yes |  |
| 10 | `atc_rate_prev_day` | `numeric` | yes |  |
| 11 | `atc_rate_prev_week` | `numeric` | yes |  |
| 12 | `atc_rate_prev_month` | `numeric` | yes |  |
| 13 | `revenue_today` | `numeric` | yes |  |
| 14 | `revenue_prev_day` | `numeric` | yes |  |
| 15 | `revenue_prev_week` | `numeric` | yes |  |
| 16 | `revenue_prev_month` | `numeric` | yes |  |
| 17 | `orders_today` | `numeric` | yes |  |
| 18 | `orders_prev_day` | `numeric` | yes |  |
| 19 | `orders_prev_week` | `numeric` | yes |  |
| 20 | `orders_prev_month` | `numeric` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ix_opc_key`: `CREATE UNIQUE INDEX ix_opc_key ON public.other_page_compare USING btree (page_type, page_path)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
