"""Build the dashboard timeout indexes without blocking ingestion writes.

Run once with DATABASE_URL_SYNC configured, before recording the matching
Supabase migration. Stops on the first connection, lock or query failure;
there are no automatic retries. A later explicit run repairs an invalid
index left by an interrupted CREATE INDEX CONCURRENTLY.
"""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

INDEXES = (
    ("ix_soa_created_desc_nulls_last", "shopify_order_attribution", "created_at DESC NULLS LAST"),
    ("ix_raw_dump_meta_extracted_at", "raw_dump_meta", "extracted_at"),
)


def build_indexes(conn) -> None:
    # CONCURRENTLY cannot run inside a transaction. These limits bound only
    # this maintenance connection; dashboard timeouts remain unchanged.
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '240s'")
        cur.execute("SET lock_timeout = '5s'")
        for name, table, columns in INDEXES:
            cur.execute(
                "SELECT i.indisvalid, t.relname "
                "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
                "WHERE i.indexrelid = to_regclass(%s)",
                (f"public.{name}",),
            )
            existing = cur.fetchone()
            if existing:
                if existing[1] != table:
                    raise RuntimeError(f"Index {name} belongs to an unexpected table; stopping")
                if existing[0]:
                    print(f"{name}: already valid", flush=True)
                    continue
                # IF NOT EXISTS alone would silently keep an INVALID index.
                cur.execute(sql.SQL("DROP INDEX CONCURRENTLY {}").format(
                    sql.Identifier("public", name)
                ))
            started = monotonic()
            print(f"Building {name}", flush=True)
            cur.execute(sql.SQL("CREATE INDEX CONCURRENTLY {} ON {} ({})").format(
                sql.Identifier(name), sql.Identifier("public", table), sql.SQL(columns)
            ))
            cur.execute("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(%s)",
                        (f"public.{name}",))
            if cur.fetchone() != (True,):
                raise RuntimeError(f"Index {name} was not validated; stopping")
            print(f"{name}: valid ({monotonic() - started:.1f}s)", flush=True)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    dsn = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(dsn, connect_timeout=12)
    try:
        build_indexes(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
