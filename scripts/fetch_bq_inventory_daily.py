"""Fetch saadaa-wh.MAPLEMONK.saadaa_inventory_planning from BigQuery and
mirror it into public.bq_inventory_daily in media_data_saadaa.

Schema-aware: introspects the BQ table live at run time, generates a
matching Postgres DDL + INSERT column list from that. Resilient to
upstream schema changes -- if MapleMonk adds/renames/removes a column,
the next run picks it up automatically. No manual DDL updates needed.

Auth path:
  1. GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service-account
     JSON key file (recommended for scheduled runs).
  2. gcloud application-default credentials -- the file created by
     `gcloud auth application-default login`.

Required IAM on the identity that runs this:
  * roles/bigquery.jobUser        on project saadaa-wh
  * roles/bigquery.dataViewer     on dataset MAPLEMONK  (or the table)

Load strategy:
  Full refresh -- TRUNCATE + bulk INSERT via psycopg2 execute_values in
  batches of BATCH_SIZE. Idempotent, safe to re-run.

Usage:
    ./.venv/Scripts/python.exe scripts/fetch_bq_inventory_daily.py

Optional env overrides:
    BQ_INVENTORY_TABLE       full FQN, default saadaa-wh.MAPLEMONK.saadaa_inventory_planning
    BQ_INVENTORY_BATCH_SIZE  rows per INSERT batch (default 5000)
    BQ_INVENTORY_DATE_FROM   only fetch rows on/after this date (YYYY-MM-DD)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from google.cloud import bigquery  # noqa: E402


BQ_TABLE = os.environ.get(
    "BQ_INVENTORY_TABLE",
    "saadaa-wh.MAPLEMONK.saadaa_inventory_planning",
)
PG_TABLE = "public.bq_inventory_daily"
BATCH_SIZE = int(os.environ.get("BQ_INVENTORY_BATCH_SIZE", "5000"))
DATE_FROM = os.environ.get("BQ_INVENTORY_DATE_FROM")  # optional YYYY-MM-DD


# BQ -> Postgres type mapping. Wide types on purpose (numeric for every
# real, bigint for every int) -- MapleMonk sometimes ships INT64 values
# into a FLOAT64 column mid-sync, and numeric handles both without
# overflowing on the Postgres side.
BQ_TO_PG = {
    "STRING":     "text",
    "BYTES":      "text",
    "INTEGER":    "bigint",
    "INT64":      "bigint",
    "FLOAT":      "numeric",
    "FLOAT64":    "numeric",
    "NUMERIC":    "numeric",
    "BIGNUMERIC": "numeric",
    "BOOLEAN":    "boolean",
    "BOOL":       "boolean",
    "DATE":       "date",
    "DATETIME":   "timestamp",
    "TIMESTAMP":  "timestamptz",
    "TIME":       "time",
    "GEOGRAPHY":  "text",
    "JSON":       "jsonb",
}


def _pg_dsn() -> str:
    dsn = os.environ["DATABASE_URL_SYNC"]
    return dsn.replace("postgresql+psycopg2://", "postgresql://")


def _quote_pg_ident(name: str) -> str:
    # Column names from BQ can contain uppercase / spaces / mixed case.
    # Always double-quote so Postgres preserves the exact identifier.
    return '"' + name.replace('"', '""') + '"'


def build_ddl(schema: list[bigquery.SchemaField]) -> str:
    cols_sql: list[str] = []
    for field in schema:
        pg_type = BQ_TO_PG.get(field.field_type.upper())
        if pg_type is None:
            # Nested RECORD / ARRAY / STRUCT columns can't be mirrored 1:1;
            # dump them as jsonb so we don't lose the payload.
            pg_type = "jsonb"
        cols_sql.append(f"    {_quote_pg_ident(field.name)} {pg_type}")
    # `synced_at` is our own -- populated on INSERT via the DEFAULT.
    cols_sql.append('    "synced_at" timestamptz DEFAULT NOW()')
    return (
        f"CREATE TABLE IF NOT EXISTS {PG_TABLE} (\n"
        + ",\n".join(cols_sql)
        + "\n);\n"
        f"CREATE INDEX IF NOT EXISTS ix_bqinv_sku      ON {PG_TABLE}(sku);\n"
        f"CREATE INDEX IF NOT EXISTS ix_bqinv_date_day ON {PG_TABLE}(date_day);\n"
    )


def build_recreate_sql(schema: list[bigquery.SchemaField]) -> str:
    """DROP + CREATE the target table so old columns that no longer exist
    in BQ get removed and new ones get added. Non-transactional cost is
    fine -- refresh runs in a single txn and we TRUNCATE anyway."""
    return f"DROP TABLE IF EXISTS {PG_TABLE};\n" + build_ddl(schema)


def build_select_sql(schema: list[bigquery.SchemaField]) -> str:
    cols = ", ".join(f"`{f.name}`" for f in schema)
    where = f"WHERE date_day >= DATE('{DATE_FROM}')" if DATE_FROM else ""
    return f"SELECT {cols} FROM `{BQ_TABLE}` {where}"


def main() -> None:
    t0 = time.time()
    print(f"[bq] project     : saadaa-wh")
    print(f"[bq] table       : {BQ_TABLE}")
    print(f"[bq] date_from   : {DATE_FROM or '(unset -- fetching full table)'}")
    print(f"[pg] target      : {PG_TABLE}")
    print(f"[pg] batch_size  : {BATCH_SIZE}")

    bq_client = bigquery.Client(project="saadaa-wh")

    print("\n[bq] introspecting schema ...")
    table = bq_client.get_table(BQ_TABLE)
    schema = list(table.schema)
    print(f"[bq]   {len(schema)} columns, {table.num_rows:,} rows in source")
    unknown_types = [
        f.name for f in schema
        if f.field_type.upper() not in BQ_TO_PG and f.field_type.upper() != "RECORD"
    ]
    if unknown_types:
        print(f"[bq]   warning: unknown BQ types will be stored as jsonb: {unknown_types}")

    ddl = build_recreate_sql(schema)
    select_sql = build_select_sql(schema)

    print("\n[bq] running SELECT ...")
    job = bq_client.query(select_sql)
    it = job.result(page_size=BATCH_SIZE)
    print(f"[bq] job {job.job_id} started; streaming rows ...")

    columns = [f.name for f in schema]
    col_list = ", ".join(_quote_pg_ident(c) for c in columns)

    # Commit-per-N-rows so a crash mid-fetch leaves partially loaded data
    # behind (better than losing all 1M+ rows). The initial DDL + TRUNCATE
    # is its own quick transaction; subsequent inserts commit every
    # COMMIT_EVERY rows.
    COMMIT_EVERY = 50_000

    conn = psycopg2.connect(_pg_dsn())
    conn.autocommit = False
    inserted = 0
    try:
        # Step 1: DDL + TRUNCATE in its own txn.
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
            cur.execute(ddl)
        conn.commit()

        sql = f"INSERT INTO {PG_TABLE} ({col_list}) VALUES %s"

        # Step 2: stream + commit periodically.
        batch: list[tuple] = []
        last_commit = 0
        with conn.cursor() as cur:
            for row in it:
                batch.append(tuple(row.get(c) for c in columns))
                if len(batch) >= BATCH_SIZE:
                    psycopg2.extras.execute_values(cur, sql, batch, page_size=BATCH_SIZE)
                    inserted += len(batch)
                    batch.clear()
                    if inserted - last_commit >= COMMIT_EVERY:
                        conn.commit()
                        last_commit = inserted
                        print(f"[pg]   inserted {inserted:,} rows (committed)")
            if batch:
                psycopg2.extras.execute_values(cur, sql, batch, page_size=len(batch))
                inserted += len(batch)
            conn.commit()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] bq_inventory_daily refreshed in {dt:.1f}s")
    print(f"    columns       : {len(columns)}")
    print(f"    rows inserted : {inserted:,}")
    if inserted:
        rate = inserted / max(dt, 0.001)
        print(f"    throughput    : {rate:,.0f} rows/sec")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        msg = str(exc)
        if "bigquery.jobs.create" in msg:
            print("\n[FAIL] Permission denied: bigquery.jobs.create", file=sys.stderr)
            print(
                "    Fix: grant roles/bigquery.jobUser on the saadaa-wh project\n"
                "    to the identity that ran this script.",
                file=sys.stderr,
            )
            sys.exit(2)
        if "bigquery.tables.get" in msg or "Access Denied" in msg:
            print("\n[FAIL] Permission denied: table read", file=sys.stderr)
            print(
                f"    Fix: grant roles/bigquery.dataViewer on the MAPLEMONK\n"
                f"    dataset (or {BQ_TABLE}) to the identity that ran this script.",
                file=sys.stderr,
            )
            sys.exit(2)
        raise
