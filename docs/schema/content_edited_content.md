# `content_edited_content`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~650 rows (planner estimate) · 232 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `requisition_id` | `text` | no |  |
| 2 | `nomenclature` | `text` | no | `''::text` |
| 3 | `submitted_at` | `text` | yes |  |
| 4 | `edited_link` | `text` | yes |  |
| 5 | `edited_by` | `text` | yes |  |
| 6 | `video_format` | `text` | yes |  |
| 7 | `remarks` | `text` | yes |  |
| 8 | `approval_status` | `text` | yes |  |
| 9 | `date_of_completion` | `text` | yes |  |
| 10 | `testing_status` | `text` | yes |  |
| 11 | `source_ad_id` | `text` | yes |  |
| 12 | `testing_date` | `text` | yes |  |
| 13 | `mirrored_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `content_edited_content_pkey`
  - `CREATE UNIQUE INDEX content_edited_content_pkey ON public.content_edited_content USING btree (requisition_id, nomenclature)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `requisition_id` → `content_graphic_register`, `content_iterated_register`
- `source_ad_id` → `content_asset_register`, `content_graphic_register`, `content_iterated_register`
- `testing_date` → `content_iterated_register`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
