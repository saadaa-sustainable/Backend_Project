# `webhook_events`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~14,724 rows (planner estimate) · 30 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `bigint` | no | `nextval('webhook_events_id_seq'::regclass)` |
| 2 | `source` | `text` | no |  |
| 3 | `event` | `text` | no |  |
| 4 | `payload` | `jsonb` | no |  |
| 5 | `headers` | `jsonb` | yes |  |
| 6 | `received_at` | `timestamp with time zone` | no | `now()` |
| 7 | `processed_at` | `timestamp with time zone` | yes |  |
| 8 | `process_error` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `webhook_events_pkey`
  - `CREATE UNIQUE INDEX webhook_events_pkey ON public.webhook_events USING btree (id)`
- Index — `ix_webhook_events_src_event`: `CREATE INDEX ix_webhook_events_src_event ON public.webhook_events USING btree (source, event, received_at DESC)`
- Index — `ix_webhook_events_unprocessed`: `CREATE INDEX ix_webhook_events_unprocessed ON public.webhook_events USING btree (received_at) WHERE (processed_at IS NULL)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
