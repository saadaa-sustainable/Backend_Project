# `alembic_version`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · unknown rows (planner estimate) · 24 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `version_num` | `character varying(32)` | no |  |

## Keys and indexes

- **Primary key** — `alembic_version_pkc`
  - `CREATE UNIQUE INDEX alembic_version_pkc ON public.alembic_version USING btree (version_num)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
