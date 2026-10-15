---
description: Exercise every filter on the analytics API and report dead filters, scope violations and database cost
---

Run the filter sweep and act on what it finds.

```
.venv/bin/python scripts/filter_sweep.py $ARGUMENTS
```

The API must be up on 127.0.0.1:8002. If it is not, start it first:
`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002`

Useful forms:

| | |
|---|---|
| `/sweep` | every endpoint (slow — one cold query per probe) |
| `/sweep --only landing-pages` | one endpoint |
| `/sweep --save` | record this run as the baseline |
| `/sweep --check` | compare against the baseline, exit 1 on regression |

## Reading the result

- **DEAD** — the filter changed nothing. Either it is not wired up, or a
  second control is shadowing it. Fix the wiring; do not delete the test.
- **WIDENS** — adding a filter returned MORE rows. Almost always a
  predicate applied to the wrong side of a join.
- **SCOPE** — the filter moved a field it must not. The frozen fields per
  filter live in `.claude/filter_sweep.json`; a violation means the
  filter is narrowing a population some other column is still reporting
  whole.
- **⚠ no cheaper than unfiltered** — the filter cut the rows but not the
  blocks. The database is applying the predicate *after* doing the work.
  Push it down into the CTE.

Judge cost by **blocks, not milliseconds**. This instance has 256MB of
shared_buffers against ~32GB, so wall-clock moves 10-25x with load while
block counts hold steady.

A second run inside the response-cache TTL measures the cache, not the
database. Restart uvicorn between runs when the numbers look too good.
