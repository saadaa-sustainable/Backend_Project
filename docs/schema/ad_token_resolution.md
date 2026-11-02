# `ad_token_resolution`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `token` | `text` | yes |  |
| 2 | `resolved_ad_id` | `text` | yes |  |
| 3 | `method` | `text` | yes |  |
| 4 | `label` | `text` | yes |  |
| 5 | `ads_sharing_this_name` | `bigint` | yes |  |

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
