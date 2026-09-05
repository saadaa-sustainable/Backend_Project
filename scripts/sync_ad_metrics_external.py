"""Mirror the authoritative per-ad metrics table into
public.ad_metrics_external, then let ad_lifecycle overlay from it.

WHAT THIS IS FOR
----------------
Backend_Project computes its own per-ad metrics from raw_dump_meta, and
that pipeline is incomplete for anything older than a few months: the
daily Meta ingest only ever walks forward, so ads that stopped running
before the rolling window reached them were never fetched. Measured
2026-09-05, ads with spend per month, this project against the reference
system that has the full series:

    2026-01   548 / 1,765      2026-05    506 / 1,666
    2026-02   406 / 1,326      2026-06    685 / 1,462
    2026-03   474 / 1,442      2026-07  1,074 / 1,475
    2026-04   336 / 1,248      2026-08  1,863 / 1,712

The reference system keeps a daily series going back to 2022 and is the
number the business already reconciles against, so its figures are taken
as correct where the two disagree.

HOW IT PLUGS IN
---------------
This script only WRITES THE MIRROR. Nothing reads it here. The overlay
happens in app/services/silver/ad_lifecycle.py, which applies these
values on top of its own computed rows at the end of every refresh --
so ad_performance_summary, /admin/analytics/ads-analyse and the
dashboard all pick them up with no change to the endpoint or the
frontend. ad_lifecycle is the single leverage point because
ad_performance_summary is built from it.

Ads present here but absent from ad_lifecycle (19,565 against 14,866 --
the ones this project never ingested) are inserted too, so the row count
matches rather than merely the values.

WHAT IT DOES NOT COVER
----------------------
The source has no per-SKU line items and no add_to_cart /
checkout_initiate at the daily grain, so CPIS master-SKU attribution,
the asset/creative joins, the media thumbnails and the day-14 replay all
stay on this project's own data. Daily Shopify orders/sales exist only
inside the 90-day rollup's coverage, so a windowed Shopify figure is
available for recent windows and absent for older ones.

Only the columns listed in _COLUMN_MAP are overlaid; everything else
falls through untouched. That is deliberate -- a column is either fully
overlaid or fully local, never half.

CONFIGURATION
-------------
AD_METRICS_SOURCE_URL must point at the source database. Without it the
script exits 0 and does nothing, so the daily pipeline stays green on an
install that has not configured a source -- the overlay simply does not
happen and ad_lifecycle keeps its own values.

Usage:
    python scripts/sync_ad_metrics_external.py
    python scripts/sync_ad_metrics_external.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402


def _dsn(raw: str | None) -> str:
    return (raw or "").replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    ).split("?")[0]


SOURCE_DSN = _dsn(os.environ.get("AD_METRICS_SOURCE_URL"))
TARGET_DSN = _dsn(os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL"))

#: source column -> ad_metrics_external column. The mirror deliberately
#: uses THIS project's names, so the overlay in ad_lifecycle.py is a
#: plain column-for-column assignment with no translation layer to drift.
_COLUMN_MAP: dict[str, str] = {
    "ad_id": "ad_id",
    "ad_name": "ad_name",
    "ad_status": "ad_status",
    "ad_created": "ad_created_time",
    "account_name": "account_name",
    "campaign_name": "campaign_name",
    "adset_id": "adset_id",
    "adset_name": "adset_name",
    "amount_spent": "spend",
    "impressions": "impressions",
    "reach": "reach",
    "frequency": "frequency",
    "conv_value": "conv_value",
    "purchases": "purchases",
    "ncp_count": "ncp_count",
    "ftewv_count": "ftewv_count",
    "cost_per_ncp": "cost_per_ncp",
    "cost_per_ftewv": "cost_per_ftewv",
    "cpc_link": "cpc_link",
    "ctr_pct": "ctr_pct",
    "cost_per_1000": "cpr_1000",
    "checkout_compl_pct": "checkout_compl_pct",
    "cr_link_clicks_pct": "cr_lc_pct",
    "atc_lc_pct": "atc_lc_pct",
    "ci_atc_pct": "ci_atc_pct",
    "contrib_margin_pct": "contrib_margin_pct",
    "profit_efficiency": "profit_efficiency",
    "engagement_count": "engagement_count",
    "link_clicks_raw": "inline_link_clicks",
    "atc_count": "add_to_cart",
    "ci_count": "checkout_initiate",
    "ltv_reach": "ltv_reach",
    "ltv_frequency": "ltv_frequency",
    "pct_reach_ftewv": "pct_reach_ftewv",
    "f1_pass": "f1_pass",
    "f2_pass": "f2_pass",
    "f3_pass": "f3_pass",
    "f4_pass": "f4_pass",
    "category": "category",
    "shopify_orders": "shopify_orders",
    "shopify_sales": "shopify_revenue",
    "shopify_aov": "shopify_aov",
    "shopify_roas": "shopify_roas",
    "date_target_imp_achieved": "impressions_50k_date",
    "days_to_target_f1": "days_to_50k",
}

_TEXT = {"ad_id", "ad_name", "ad_status", "account_name", "campaign_name",
         "adset_id", "adset_name", "category"}
_BOOL = {"f1_pass", "f2_pass", "f3_pass", "f4_pass"}
_DATE = {"impressions_50k_date"}
_TS = {"ad_created_time"}
_INT = {"days_to_50k"}


def _sql_type(col: str) -> str:
    if col in _TEXT:
        return "text"
    if col in _BOOL:
        return "boolean"
    if col in _DATE:
        return "date"
    if col in _TS:
        return "timestamptz"
    if col in _INT:
        return "integer"
    return "numeric"


TARGET_COLUMNS = list(_COLUMN_MAP.values())

DDL = (
    "CREATE TABLE IF NOT EXISTS public.ad_metrics_external (\n"
    + ",\n".join(
        f"    {c} {_sql_type(c)}" + (" PRIMARY KEY" if c == "ad_id" else "")
        for c in TARGET_COLUMNS
    )
    + ",\n    synced_at timestamptz\n)"
)

SELECT_SQL = (
    "SELECT " + ", ".join(_COLUMN_MAP) + " FROM ae_table_view WHERE ad_id IS NOT NULL"
)

INSERT_SQL = (
    f"INSERT INTO public.ad_metrics_external ({', '.join(TARGET_COLUMNS)}, synced_at) VALUES %s"
)


# ----------------------------------------------------------------------
# Daily grain -- what the dashboard's "delivery date" filter reads
# ----------------------------------------------------------------------
#
# date_field='delivery' in /admin/analytics/ads-analyse keeps every ad but
# replaces spend/impressions/reach with the window's sums. It used to
# compute those from this project's own raw_dump_meta, which meant the
# one filter mode that re-aggregates was also the one mode that bypassed
# the per-ad overlay entirely -- a user switching to 'delivery' silently
# dropped back to the incomplete figures, and the row went internally
# inconsistent (windowed local spend beside overlaid lifetime conv_value,
# so cost_per_ncp on that row mixed two sources).
#
# It also double-counted: the old query UNION ALLed raw_dump_meta_daily
# and raw_dump_meta and summed, so any (ad, day) present in both was
# added twice.
#
# Mirroring the source's own daily series fixes all three at once: same
# provenance as the per-ad overlay, one row per (ad, day), full history.
# The source keeps THREE daily tables and its own window function picks
# between them by DATE, so mirroring any single one of them reproduces a
# number the reference dashboard does not actually show. Measured
# 2026-09-05 over 2026-08-01..08-31:
#
#     source                       ads    spend        impressions
#     90-day rollup              1,300   11,285,263    105,162,390
#     detail + backfill, deduped 1,726   12,187,489    111,611,347
#
# 8% apart on spend and 426 ads apart on coverage -- not rounding. The
# reference reads the rollup whenever the window falls inside its
# coverage (every default view: it holds the last 90 days) and falls
# back to the deduped detail tables only for older windows.
#
# So the mirror splits on the same boundary the source does: the rollup
# supplies every day it covers, the deduped detail tables supply the
# days before it starts. Verified 2026-09-05 -- over 2026-08-01..08-31
# this query and the source's own window function agree to the rupee on
# all eight aggregates (ads 1,300; spend 11,285,263; impressions
# 105,162,390; conv 33,479,670; purchases 27,433; clicks 1,734,690; ncp
# 11,106; ftewv 333,482).
#
# NOT a precedence dedup across all three. Trying that first -- rollup
# wins per (ad, day), the detail tables fill the gaps -- came out 8%
# high, because the detail tables hold (ad, day) pairs the rollup does
# not, and every one of them leaked in as an extra row. The rollup is
# not a superset of the tables it summarises; it is a different
# selection, and the boundary between them is a date.
#
# For windows the rollup does not cover there is nothing to match: the
# source's own fallback branch is broken. Any window starting before the
# rollup's first day raises
#
#     42702: column reference "ad_id" is ambiguous
#     DETAIL: It could refer to either a PL/pgSQL variable or a table
#     column.
#
# from its window function (reproduced 2026-09-05 for 2026-03 and
# 2026-05), and its dashboard swallows the error and leaves whatever
# numbers were on screen. So the deduped-detail leg here has no
# reference figure to agree with; it is this project's own answer for a
# range the source cannot render at all. A window that STRADDLES the
# boundary would take that same broken branch there, while the mirror
# answers it from the rollup plus deduped detail.
#
# Only the rollup carries daily shopify_orders / shopify_sales, hence
# the NULLs in the other two legs: a windowed Shopify figure exists for
# the days the rollup covers and is honestly absent before that, rather
# than being quietly backfilled from a lifetime total.
_DAILY_COLUMN_MAP: dict[str, str] = {
    "ad_id": "ad_id",
    "date": "day",
    "spend": "spend",
    "impressions": "impressions",
    "reach": "reach",
    "conv_value": "conv_value",
    "purchases": "purchases",
    "link_clicks": "link_clicks",
    "ncp_count": "ncp_count",
    "ftewv_count": "ftewv_count",
    "shopify_orders": "shopify_orders",
    "shopify_sales": "shopify_sales",
}

DAILY_TARGET_COLUMNS = list(_DAILY_COLUMN_MAP.values())

DAILY_DDL = """
CREATE TABLE IF NOT EXISTS public.ad_daily_external (
    ad_id       text NOT NULL,
    day         date NOT NULL,
    spend       numeric,
    impressions numeric,
    reach       numeric,
    conv_value  numeric,
    ncp_count   numeric,
    ftewv_count numeric,
    synced_at   timestamptz,
    PRIMARY KEY (ad_id, day)
)
"""

# The table shipped before purchases / link_clicks / the Shopify pair
# existed, so an install that already has it needs them added rather
# than the CREATE being enough.
DAILY_ALTERS = [
    "ALTER TABLE public.ad_daily_external "
    f"ADD COLUMN IF NOT EXISTS {c} numeric"
    for c in ("purchases", "link_clicks", "shopify_orders", "shopify_sales")
]

DAILY_INDEXES = [
    # The delivery filter selects by day range for a page of ad_ids, so
    # both orders get used.
    "CREATE INDEX IF NOT EXISTS ix_ade_day ON public.ad_daily_external (day)",
    "CREATE INDEX IF NOT EXISTS ix_ade_ad_day ON public.ad_daily_external (ad_id, day)",
]

DAILY_SELECT_SQL = """
WITH bound AS (SELECT MIN(date) AS d0 FROM public.ae_daily_90d),
u AS (
    SELECT ad_id::text                            AS ad_id,
           date,
           amount_spent::numeric                  AS spend,
           impressions::numeric                   AS impressions,
           reach::numeric                         AS reach,
           conversion_value::numeric              AS conv_value,
           purchases::numeric                     AS purchases,
           link_clicks_raw::numeric               AS link_clicks,
           ncp_count::numeric                     AS ncp_count,
           ftewv_count::numeric                   AS ftewv_count,
           shopify_orders::numeric                AS shopify_orders,
           shopify_sales::numeric                 AS shopify_sales,
           0                                      AS pri
      FROM public.ae_daily_90d
     WHERE ad_id IS NOT NULL AND date IS NOT NULL AND date >= %(since)s
    UNION ALL
    SELECT ad_id::text, date,
           amount_spent_inr::numeric,
           impressions::numeric,
           reach::numeric,
           conversion_value::numeric,
           purchases::numeric,
           COALESCE(inline_link_clicks, outbound_clicks)::numeric,
           ncp_count::numeric,
           ftewv_count::numeric,
           NULL::numeric,
           NULL::numeric,
           1
      FROM public.primary_table, bound
     WHERE ad_id IS NOT NULL AND date IS NOT NULL AND date >= %(since)s
       AND date < bound.d0
       AND impressions IS NOT NULL AND impressions > 0
    UNION ALL
    SELECT ad_id::text, date,
           amount_spent_inr::numeric,
           impressions::numeric,
           reach::numeric,
           conversion_value::numeric,
           NULL::numeric,
           outbound_clicks::numeric,
           ncp_count::numeric,
           ftewv_count::numeric,
           NULL::numeric,
           NULL::numeric,
           2
      FROM public.backfill_table, bound
     WHERE ad_id IS NOT NULL AND date IS NOT NULL AND date >= %(since)s
       AND date < bound.d0
       AND impressions IS NOT NULL AND impressions > 0
)
SELECT DISTINCT ON (ad_id, date)
       ad_id, date, spend, impressions, reach, conv_value, purchases,
       link_clicks, ncp_count, ftewv_count, shopify_orders, shopify_sales
  FROM u
 ORDER BY ad_id, date, pri
"""


DAILY_INSERT_SQL = (
    f"INSERT INTO public.ad_daily_external ({', '.join(DAILY_TARGET_COLUMNS)}, synced_at) "
    "VALUES %s "
    # The source can carry more than one row per (ad, day) across
    # accounts; collapse rather than fail the whole batch.
    "ON CONFLICT (ad_id, day) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in DAILY_TARGET_COLUMNS if c not in ("ad_id", "day"))
    + ", synced_at = EXCLUDED.synced_at"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Read the source and report the row count without writing.")
    ap.add_argument("--since", default="2025-01-01",
                    help="Earliest day to mirror for the daily grain (default 2025-01-01). "
                         "The per-ad table is always mirrored in full -- it is only ~19.6k rows.")
    ap.add_argument("--since-days", type=int, default=None,
                    help="Mirror the trailing N days instead of --since. The daily "
                         "pipeline uses this: only the recent window changes between "
                         "runs, and re-upserting 456k rows every night to rewrite a "
                         "few thousand is time the run does not have. Use --since for "
                         "a one-off deep backfill.")
    ap.add_argument("--skip-daily", action="store_true",
                    help="Mirror only the per-ad table, not the daily grain.")
    args = ap.parse_args()
    if args.since_days is not None:
        args.since = (date.today() - timedelta(days=args.since_days)).isoformat()

    if not SOURCE_DSN:
        # Not an error. An install without a configured source just keeps
        # ad_lifecycle's own numbers; the pipeline must not go red for it.
        print("AD_METRICS_SOURCE_URL not set -- nothing to mirror, skipping.")
        return 0
    if not TARGET_DSN:
        print("Set DATABASE_URL_SYNC (or DATABASE_URL) first.", file=sys.stderr)
        return 2

    t0 = time.time()
    src = psycopg2.connect(SOURCE_DSN)
    try:
        with src.cursor() as cur:
            cur.execute(SELECT_SQL)
            rows = cur.fetchall()
    finally:
        src.close()
    print(f"read {len(rows):,} rows from source in {time.time() - t0:.1f}s")

    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0
    if not rows:
        # Refuse to blank the mirror on an empty read. An overlay that
        # silently became a no-op would look exactly like the numbers
        # regressing, with nothing to point at.
        print("source returned 0 rows -- leaving the existing mirror alone.",
              file=sys.stderr)
        return 1

    now = time.strftime("%Y-%m-%d %H:%M:%S%z")
    payload = [tuple(r) + (now,) for r in rows]

    tgt = psycopg2.connect(TARGET_DSN)
    try:
        with tgt, tgt.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '600s'")
            cur.execute(DDL)
            # TRUNCATE + INSERT inside ONE transaction: a failure rolls
            # back to the previous mirror rather than leaving the overlay
            # with nothing to apply.
            cur.execute("TRUNCATE public.ad_metrics_external")
            execute_values(cur, INSERT_SQL, payload, page_size=1000)
            cur.execute("SELECT COUNT(*) FROM public.ad_metrics_external")
            written = cur.fetchone()[0]
    finally:
        tgt.close()

    print(f"ad_metrics_external: {written:,} rows in {time.time() - t0:.1f}s")

    if args.skip_daily:
        print("--skip-daily: daily grain not mirrored.")
        return 0

    t1 = time.time()
    src = psycopg2.connect(SOURCE_DSN)
    try:
        with src.cursor() as cur:
            cur.execute(DAILY_SELECT_SQL, {"since": args.since})
            daily = cur.fetchall()
    finally:
        src.close()
    print(f"read {len(daily):,} daily rows (from {args.since}) in {time.time() - t1:.1f}s")

    if not daily:
        print("source returned 0 daily rows -- leaving the existing daily mirror alone.",
              file=sys.stderr)
        return 1

    daily_payload = [tuple(r) + (now,) for r in daily]
    tgt = psycopg2.connect(TARGET_DSN)
    try:
        with tgt, tgt.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '1800s'")
            cur.execute(DAILY_DDL)
            for statement in DAILY_ALTERS:
                cur.execute(statement)
            for statement in DAILY_INDEXES:
                cur.execute(statement)
            # Upsert rather than TRUNCATE: this table is big enough that
            # a truncate leaves a visible window where the delivery
            # filter would read an empty mirror and report zero spend
            # for every ad.
            execute_values(cur, DAILY_INSERT_SQL, daily_payload, page_size=2000)
            cur.execute("SELECT COUNT(*) FROM public.ad_daily_external")
            daily_written = cur.fetchone()[0]
    finally:
        tgt.close()

    print(f"ad_daily_external: {daily_written:,} rows total in {time.time() - t1:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
