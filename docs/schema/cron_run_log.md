# `cron_run_log`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~92 rows (planner estimate) · 728 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `bigint` | no | `nextval('cron_run_log_id_seq'::regclass)` |
| 2 | `project` | `text` | no |  |
| 3 | `run_started` | `timestamp with time zone` | no | `now()` |
| 4 | `run_finished` | `timestamp with time zone` | yes |  |
| 5 | `duration_s` | `numeric` | yes |  |
| 6 | `status` | `text` | no | `'running'::text` |
| 7 | `workflow_run` | `text` | yes |  |
| 8 | `git_sha` | `text` | yes |  |
| 9 | `steps` | `jsonb` | yes |  |
| 10 | `n_steps_ok` | `integer` | yes |  |
| 11 | `n_steps_fail` | `integer` | yes |  |
| 12 | `error` | `text` | yes |  |
| 13 | `host` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `cron_run_log_pkey`
  - `CREATE UNIQUE INDEX cron_run_log_pkey ON public.cron_run_log USING btree (id)`
- Index — `ix_cron_run_log_project_started`: `CREATE INDEX ix_cron_run_log_project_started ON public.cron_run_log USING btree (project, run_started DESC)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
