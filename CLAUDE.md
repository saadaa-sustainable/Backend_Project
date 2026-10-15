
## Database access

Never re-derive the DSN inline. `scripts/dbq.py` owns the
`postgresql+psycopg2://` → `postgresql://` rewrite and scrubs
credentials out of every error, which matters because this repo is
public. A `PreToolUse` hook denies commands that do it by hand.

    .venv/bin/python scripts/dbq.py "SELECT ..."       # one query
    .venv/bin/python scripts/dbq.py --json  "SELECT ..."
    .venv/bin/python scripts/dbq.py --explain "SELECT ..."   # ANALYZE, BUFFERS
    from scripts.dbq import connect                     # inside a script

Read-only by default; a write needs `--write`.

## Filters

`scripts/filter_sweep.py` exercises every query parameter on the
analytics API one at a time and reports dead filters, filters that move
fields they should not, and filters the database answers no more cheaply
than the unfiltered query. `/sweep` runs it; `.claude/filter_sweep.json`
holds the per-endpoint knowledge the OpenAPI schema cannot carry.

Judge query cost by **blocks, not milliseconds** — 256MB of
shared_buffers against ~32GB of data means wall-clock swings 10-25x with
load while block counts hold steady.

## The nightly runs master

Anything the cron executes (`scripts/`, `app/`, `utils/`,
`.github/workflows/`) only takes effect once it is on `origin/master`.
A `SessionStart` hook and the status line warn when local pipeline work
has drifted, with the time remaining before 01:30 UTC.
