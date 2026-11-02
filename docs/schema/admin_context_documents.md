# `admin_context_documents`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · unknown rows (planner estimate) · 96 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `filename` | `character varying(255)` | no |  |
| 3 | `content_type` | `character varying(128)` | no |  |
| 4 | `extracted_text` | `text` | no |  |
| 5 | `uploaded_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `admin_context_documents_pkey`
  - `CREATE UNIQUE INDEX admin_context_documents_pkey ON public.admin_context_documents USING btree (id)`
- Index — `ix_admin_context_documents_filename`: `CREATE INDEX ix_admin_context_documents_filename ON public.admin_context_documents USING btree (filename)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
