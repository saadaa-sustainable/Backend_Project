#!/usr/bin/env python
"""One-line database queries, so nothing has to re-derive the DSN.

WHY THIS EXISTS
---------------
831 of 8,097 Bash calls across this project's Claude Code transcripts
(10.3%) opened with the same six lines:

    import os, psycopg2
    from dotenv import load_dotenv
    load_dotenv('/Users/anmolsaadaa/Backend_Project/.env')
    dsn = os.environ['DATABASE_URL_SYNC'].replace(
        'postgresql+psycopg2://', 'postgresql://')
    c = psycopg2.connect(dsn); c.autocommit = True

720 of them re-derived the sync DSN by hand. Every one of those is a
chance to print a live connection string into a PUBLIC repository's
transcript. This module is the one place that knows how to connect, and
it refuses to put the DSN anywhere a human or a log can see it.

USE
---
    scripts/dbq.py "SELECT count(*) FROM public.shopify_orders"
    scripts/dbq.py -f query.sql --json
    scripts/dbq.py --explain "SELECT ... WHERE day > '2026-01-01'"

From a script that needs more than one statement:

    from scripts.dbq import connect
    with connect() as conn, conn.cursor() as cur:
        cur.execute(...)

SAFETY
------
Read-only by default. A statement that is not a SELECT/WITH/EXPLAIN/SHOW
needs --write, which exists so a rebuild can use the same helper rather
than going back to hand-rolled boilerplate.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

#: Anything that looks like credentials in a URI. Applied to every error
#: and every traceback this module can emit -- psycopg2 puts the whole
#: DSN in some connection errors, and this repo is public.
_SECRET = re.compile(r"(?i)\b([a-z+]+://)[^@\s/]+@")


def scrub(text: object) -> str:
    """Replace `scheme://user:pass@` with `scheme://[redacted]@`."""
    return _SECRET.sub(r"\1[redacted]@", str(text))


def dsn() -> str:
    """The sync DSN, in the one shape psycopg2 accepts.

    SQLAlchemy's `postgresql+psycopg2://` prefix is not a libpq scheme,
    so it has to come off. That rewrite is what 720 Bash calls each did
    from memory; it lives here now.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None:
        # Absolute path, not a bare load_dotenv(): the CWD is often a
        # scratchpad, and a silent miss there reads as "no credentials".
        load_dotenv(ENV)
    raw = os.environ.get("DATABASE_URL_SYNC")
    if not raw:
        sys.exit(
            f"DATABASE_URL_SYNC is not set and {ENV} did not supply it. "
            "This is the sync (psycopg2) DSN, not DATABASE_URL."
        )
    return raw.replace("postgresql+psycopg2://", "postgresql://")


@contextmanager
def connect(*, autocommit: bool = True, statement_timeout: str | None = "120s"):
    """A psycopg2 connection to the project database.

    autocommit defaults True because the overwhelming majority of uses
    are a single read; pass False when a rebuild needs a transaction.
    """
    import psycopg2
    try:
        conn = psycopg2.connect(dsn())
    except Exception as exc:  # noqa: BLE001 -- re-raised scrubbed
        raise SystemExit(f"could not connect: {scrub(exc)[:400]}") from None
    conn.autocommit = autocommit
    try:
        if statement_timeout:
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = '{statement_timeout}'")
        yield conn
    finally:
        conn.close()


_READ_ONLY = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/|\s)*(select|with|explain|show|table|values)\b",
                        re.I | re.S)


def render(columns: list[str], rows: list[tuple], limit: int) -> str:
    if not rows:
        return "(0 rows)"
    shown = rows[:limit]
    def cell(v: object) -> str:
        if v is None:
            return "—"
        if isinstance(v, bool):
            return "t" if v else "f"
        if isinstance(v, int):
            return f"{v:,}"
        if isinstance(v, float):
            return f"{v:,.2f}"
        return str(v)
    table = [list(columns)] + [[cell(v) for v in r] for r in shown]
    widths = [max(len(r[i]) for r in table) for i in range(len(columns))]
    numeric = [
        all(isinstance(r[i], (int, float)) or r[i] is None for r in shown)
        for i in range(len(columns))
    ]
    out = []
    for n, row in enumerate(table):
        cells = [
            c.rjust(widths[i]) if numeric[i] else c.ljust(widths[i])
            for i, c in enumerate(row)
        ]
        out.append("  ".join(cells).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    if len(rows) > limit:
        out.append(f"... {len(rows) - limit:,} more of {len(rows):,} rows (raise --limit)")
    else:
        out.append(f"({len(rows):,} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dbq", description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?", help="the statement to run")
    ap.add_argument("-f", "--file", help="read the statement from a file instead")
    ap.add_argument("--json", action="store_true", help="emit JSON records")
    ap.add_argument("--csv", action="store_true", help="emit CSV")
    ap.add_argument("--explain", action="store_true",
                    help="wrap in EXPLAIN (ANALYZE, BUFFERS) -- judge buffers, not seconds")
    ap.add_argument("--write", action="store_true",
                    help="permit a statement that is not a read")
    ap.add_argument("--timeout", default="120s", help="statement_timeout (default 120s)")
    ap.add_argument("--limit", type=int, default=50, help="rows to print (default 50)")
    args = ap.parse_args(argv)

    sql = args.sql
    if args.file:
        sql = Path(args.file).read_text()
    if not sql or not sql.strip():
        ap.error("give a statement, or -f FILE")

    if not _READ_ONLY.match(sql) and not args.write:
        return _fail(
            "this does not look like a read. Re-run with --write if that is "
            "intended.\n  dbq defaults to read-only so a stray UPDATE cannot "
            "reach production from a one-liner."
        )
    if args.explain:
        sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}"

    import psycopg2
    with connect(autocommit=not args.write, statement_timeout=args.timeout) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description is None:
                    if args.write:
                        conn.commit()
                    print(f"OK, {cur.rowcount:,} row(s) affected")
                    return 0
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
        except psycopg2.Error as exc:
            return _fail(scrub(exc)[:600])
        if args.write:
            conn.commit()

    if args.json:
        import json
        print(json.dumps([dict(zip(cols, r)) for r in rows], default=str, indent=2))
    elif args.csv:
        import csv
        w = csv.writer(sys.stdout)
        w.writerow(cols)
        w.writerows(rows)
    elif args.explain:
        for r in rows:
            print(r[0])
    else:
        print(render(cols, rows, args.limit))
    return 0


def _fail(message: str) -> int:
    print(scrub(message), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
