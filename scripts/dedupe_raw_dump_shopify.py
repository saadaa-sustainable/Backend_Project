"""dedupe_raw_dump_shopify.py -- find and remove duplicate bronze rows.

raw_dump_shopify is append-with-upsert: ingest_shopify.py writes with
`ON CONFLICT (object_type, source_id) WHERE source_id IS NOT NULL DO
UPDATE`, so a re-fetch normally overwrites in place. Duplicates can still
appear, and this script is the repair for when they do:

  * a NULL/empty source_id matches no conflict target (the backing unique
    index is partial on the same predicate), so such a row was INSERTED
    FRESH on every run. Fixed at source 2026-09-04 -- _build_rows now
    falls back to a payload hash -- but rows written before that fix are
    still here, and this cleans them up.
  * the unique index being dropped, rebuilt, or absent on a fresh
    database lets ordinary rows double up until it is restored.
  * a bulk import or restore that bypassed the ingest path entirely.

Which row survives
------------------
The newest per key, ordered by (extracted_at DESC, id DESC) -- byte for
byte the ordering app/services/silver/shopify_flatten.py uses in its
DISTINCT ON. That equivalence is the point: the row this script keeps is
exactly the row the silver layer would have selected, so deduplicating
bronze can never change what silver produces.

Keys, by row shape:
    source_id present -> (object_type, source_id)
    source_id NULL    -> (object_type, payload_hash)   [content identity]

Safety
------
Reports only, unless you pass --apply. Deletes run one object_type at a
time so no single transaction sits on the whole ~4.8M-row table -- long
transactions on shared bronze are a known cause of statement_timeout
kills on the CPIS refreshes.

Usage:
    python scripts/dedupe_raw_dump_shopify.py                     # report all
    python scripts/dedupe_raw_dump_shopify.py --object-type orders
    python scripts/dedupe_raw_dump_shopify.py --apply             # delete
    python scripts/dedupe_raw_dump_shopify.py --apply --object-type products
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


TABLE = "raw_dump_shopify"

#: Same ordering as shopify_flatten.py's DISTINCT ON. Keep them in step:
#: if this diverges, dedupe starts keeping a different row than silver
#: would have picked, and bronze and silver quietly disagree.
KEEP_ORDER = "extracted_at DESC, id DESC"

#: Duplicates keyed on the natural id. Counted per object_type so the
#: report says WHERE the problem is rather than just that there is one.
COUNT_SQL = f"""
SELECT object_type,
       COUNT(*)                              AS rows,
       COUNT(*) - COUNT(DISTINCT source_id)  AS duplicate_rows
FROM {TABLE}
WHERE source_id IS NOT NULL
  AND (%(object_type)s IS NULL OR object_type = %(object_type)s)
GROUP BY object_type
HAVING COUNT(*) - COUNT(DISTINCT source_id) > 0
ORDER BY 3 DESC
"""

#: Rows with no natural id at all. Identity falls back to payload_hash,
#: so genuinely identical payloads collapse and genuinely different ones
#: are left alone.
COUNT_NULL_SQL = f"""
SELECT object_type,
       COUNT(*)                                AS rows,
       COUNT(*) - COUNT(DISTINCT payload_hash) AS duplicate_rows
FROM {TABLE}
WHERE source_id IS NULL
  AND (%(object_type)s IS NULL OR object_type = %(object_type)s)
GROUP BY object_type
HAVING COUNT(*) - COUNT(DISTINCT payload_hash) > 0
ORDER BY 3 DESC
"""

DELETE_SQL = f"""
DELETE FROM {TABLE} a
USING (
    SELECT id FROM (
        SELECT id,
               row_number() OVER (
                   PARTITION BY object_type, {{key_expr}}
                   ORDER BY {KEEP_ORDER}
               ) AS rn
        FROM {TABLE}
        WHERE {{null_pred}}
          AND object_type = %(object_type)s
    ) ranked
    WHERE rn > 1
) dupes
WHERE a.id = dupes.id
"""


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or ""
    return (url.replace("postgresql+psycopg2://", "postgresql://")
               .replace("postgresql+asyncpg://", "postgresql://")
               .split("?")[0])


def report(cur, object_type: str | None) -> list[tuple[str, str, int, int]]:
    """Return [(scope, object_type, rows, duplicate_rows)] for both shapes."""
    findings: list[tuple[str, str, int, int]] = []
    for scope, sql in (("source_id", COUNT_SQL), ("payload_hash", COUNT_NULL_SQL)):
        cur.execute(sql, {"object_type": object_type})
        for ot, rows, dupes in cur.fetchall():
            findings.append((scope, ot, rows, dupes))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--object-type", default=None,
                    help="Limit to one object_type (e.g. products, orders, inventory)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete. Without this the script only reports.")
    args = ap.parse_args()

    dsn = _dsn()
    if not dsn:
        print("Set DATABASE_URL_SYNC (or DATABASE_URL) first.", file=sys.stderr)
        return 2

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            findings = report(cur, args.object_type)

        if not findings:
            scope = args.object_type or "any object_type"
            print(f"No duplicate rows in {TABLE} for {scope}. Nothing to do.")
            return 0

        print(f"Duplicate rows in {TABLE}:\n")
        print(f"  {'key':<13} {'object_type':<28} {'rows':>10} {'duplicates':>11}")
        for scope, ot, rows, dupes in findings:
            print(f"  {scope:<13} {ot:<28} {rows:>10,} {dupes:>11,}")
        total = sum(d for _, _, _, d in findings)
        print(f"\n  {total:,} row(s) would be deleted, keeping the newest per key "
              f"({KEEP_ORDER}).")

        if not args.apply:
            print("\nReport only. Re-run with --apply to delete.")
            return 0

        # One transaction per object_type: keeps each lock window short on
        # a table the CPIS refreshes also read.
        deleted_total = 0
        for scope, ot, _, _ in findings:
            key_expr = "source_id" if scope == "source_id" else "payload_hash"
            null_pred = ("source_id IS NOT NULL" if scope == "source_id"
                         else "source_id IS NULL")
            sql = DELETE_SQL.format(key_expr=key_expr, null_pred=null_pred)
            with conn.cursor() as cur:
                cur.execute(sql, {"object_type": ot})
                deleted = cur.rowcount
            conn.commit()
            deleted_total += deleted
            print(f"  deleted {deleted:,} duplicate {ot} row(s) [{scope}]")

        with conn.cursor() as cur:
            remaining = report(cur, args.object_type)
        if remaining:
            print("\nWARNING: duplicates remain -- new rows may have been written "
                  "mid-run. Re-run to converge.")
            for scope, ot, rows, dupes in remaining:
                print(f"  {scope:<13} {ot:<28} {dupes:>11,}")
            return 1
        print(f"\nDeleted {deleted_total:,} row(s). No duplicates remain.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
