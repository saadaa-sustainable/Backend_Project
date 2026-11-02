# `flatten_settings`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · unknown rows (planner estimate) · 32 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `job_key` | `text` | no |  |
| 2 | `auto_enabled` | `boolean` | no | `false` |
| 3 | `updated_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `flatten_settings_pkey`
  - `CREATE UNIQUE INDEX flatten_settings_pkey ON public.flatten_settings USING btree (job_key)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `job_key` → `flatten_runs`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
