"""Silver: per-master-SKU return metrics pulled from MapleMonk's
consolidated returns table in BigQuery.

Source
    saadaa-wh.MAPLEMONK.SAADAA_returns_consolidated   (9.4M rows, 95 cols)

Aggregation grain
    (master_sku, window_key)  where window_key is one of 7d / 30d / 90d.
    master_sku is BQ's `product_category` (already extracted -- no need
    to derive from variant SKU on the Supabase side).

Silver target
    public.master_sku_returns
        master_sku, window_key, window_from, window_to,
        orders_count, units_ordered, units_returned, return_rate_pct,
        refund_value, exchange_count, updated_at

Downstream: /cpis-utm LEFT JOINs this per row so the CPIS table can
render Return %, Refund Value, and Net-ROAS columns without any
per-request BQ traffic.

Auth
    Uses gcloud application-default credentials -- run
    `gcloud auth application-default login` once. Requires:
        roles/bigquery.jobUser        on project saadaa-wh
        roles/bigquery.dataViewer     on MAPLEMONK dataset

Usage
    ./.venv/Scripts/python.exe scripts/refresh_master_sku_returns.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
from google.cloud import bigquery  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://"
).split("?")[0]

# Session-mode port (avoids pgbouncer's default statement timeout so
# batched upserts don't get cut off mid-flight -- same trick used by
# _copy_ad_thumbnails.py).
DSN = DSN.replace(":6543/", ":5432/")

BQ_TABLE = "saadaa-wh.MAPLEMONK.SAADAA_returns_consolidated"


DDL = """
CREATE TABLE IF NOT EXISTS public.master_sku_returns (
    master_sku          text        NOT NULL,
    window_key          text        NOT NULL,
    window_from         date,
    window_to           date,
    orders_count        integer,
    units_ordered       numeric,
    units_returned      numeric,
    return_rate_pct     numeric,
    refund_value        numeric,
    exchange_count      integer,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (master_sku, window_key)
);
CREATE INDEX IF NOT EXISTS ix_msr_window ON public.master_sku_returns (window_key);
"""


BQ_QUERY_TEMPLATE = """
SELECT
  product_category AS master_sku,
  COUNT(DISTINCT order_id) AS orders_count,
  SUM(order_quantity)                              AS units_ordered,
  SUM(COALESCE(TOTAL_RETURNED_QUANTITY, 0))        AS units_returned,
  SAFE_DIVIDE(
    SUM(COALESCE(TOTAL_RETURNED_QUANTITY, 0)),
    SUM(order_quantity)
  ) * 100 AS return_rate_pct,
  SUM(COALESCE(total_refund_amount, 0))            AS refund_value,
  COUNTIF(LOWER(COALESCE(request_type, '')) LIKE '%exchange%')
                                                   AS exchange_count
FROM `{table}`
WHERE Order_Date >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL {days} DAY)
  AND product_category IS NOT NULL
  AND product_category != ''
GROUP BY 1
HAVING units_ordered > 0
"""


# Windows to pre-compute. Match CPIS's fixed windows so /cpis-utm can
# join on (master_sku, window_key) directly.
WINDOWS = [("7d", 7), ("30d", 30), ("90d", 90)]


def main() -> None:
    t0 = time.time()
    print(f"[bq] project     : saadaa-wh", flush=True)
    print(f"[bq] source table: {BQ_TABLE}", flush=True)

    bq = bigquery.Client(project="saadaa-wh")

    # Fetch all three windows in parallel-ish (sequential is fine -- BQ
    # is fast at scan-heavy aggregates and Supabase writes dominate).
    aggregates: dict[str, list[tuple]] = {}
    for window_key, days in WINDOWS:
        print(f"[bq] querying {window_key} window ({days}d)...", flush=True)
        sql = BQ_QUERY_TEMPLATE.format(table=BQ_TABLE, days=days)
        rows = list(bq.query(sql).result())
        aggregates[window_key] = rows
        print(f"      -> {len(rows):,} SKU rows", flush=True)

    # Write silver
    print("[pg] upserting into master_sku_returns...", flush=True)
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '300s'")
            cur.execute(DDL)
            conn.commit()

            # Truncate + insert is simpler than upsert for pre-computed
            # windows -- guarantees the row set matches BQ exactly.
            cur.execute("TRUNCATE public.master_sku_returns")
            for window_key, days in WINDOWS:
                rows = aggregates[window_key]
                # Batched insert. Each row is small (~7 numbers) so 500
                # per batch is comfortable through session-mode Postgres.
                batch = []
                for r in rows:
                    d = dict(r)
                    batch.append((
                        d["master_sku"],
                        window_key,
                        None, None,  # window_from/to -- BQ side handles range
                        int(d["orders_count"] or 0),
                        float(d["units_ordered"] or 0),
                        float(d["units_returned"] or 0),
                        float(d["return_rate_pct"] or 0),
                        float(d["refund_value"] or 0),
                        int(d["exchange_count"] or 0),
                    ))
                if not batch:
                    continue
                cur.executemany(
                    """
                    INSERT INTO public.master_sku_returns (
                        master_sku, window_key, window_from, window_to,
                        orders_count, units_ordered, units_returned,
                        return_rate_pct, refund_value, exchange_count
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    batch,
                )
                conn.commit()
                print(f"      {window_key}: {len(batch):,} rows written", flush=True)

            cur.execute(
                "SELECT window_key, COUNT(*), "
                "SUM(units_returned), SUM(refund_value) "
                "FROM public.master_sku_returns GROUP BY 1 ORDER BY 1"
            )
            print()
            print("Summary:")
            for w, n, ur, rv in cur.fetchall():
                print(
                    f"  {w:<5} {n:>4} SKUs   "
                    f"{int(ur or 0):>7,} units returned   "
                    f"Rs {float(rv or 0)/1e5:>7.1f}L refunded"
                )
    finally:
        conn.close()

    print(f"\n[OK] refreshed in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
