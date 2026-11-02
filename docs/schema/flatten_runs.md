# `flatten_runs`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · unknown rows (planner estimate) · 48 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `job_key` | `text` | no |  |
| 3 | `status` | `text` | no |  |
| 4 | `triggered_by` | `text` | no |  |
| 5 | `source_covered_at` | `timestamp with time zone` | yes |  |
| 6 | `rows_written` | `jsonb` | yes |  |
| 7 | `error_message` | `text` | yes |  |
| 8 | `started_at` | `timestamp with time zone` | no |  |
| 9 | `finished_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `flatten_runs_pkey`
  - `CREATE UNIQUE INDEX flatten_runs_pkey ON public.flatten_runs USING btree (id)`
- Index — `ix_flatten_runs_job_key_finished_at`: `CREATE INDEX ix_flatten_runs_job_key_finished_at ON public.flatten_runs USING btree (job_key, finished_at DESC)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `job_key` → `flatten_settings`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
