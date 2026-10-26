"""Google Ads spend, per campaign per day, for blended MER.

WHY THIS EXISTS
---------------
Every spend figure in this warehouse is Meta's. There are exactly two ad
accounts in it -- Raho Saadaa and Fourth Ad Account - SD -- and both are
Meta. Google Ads has never been ingested in any form.

That was tolerable while every efficiency number was attributed, because
an unresolved Google click simply showed a dash. It stops being
tolerable the moment anything divides TOTAL revenue by spend. Measured
over the 30 days to 2026-10-19:

    store revenue            Rs 4,60,89,741
    Meta spend               Rs 1,16,20,374      -> 3.97x
    Google spend             Rs    11,56,599
    both                     Rs 1,27,76,973      -> 3.61x

A "blended" MER built on Meta spend alone reads 3.97x against a true
3.61x: a 10% overstatement, always in the flattering direction, on a
number people move budget with. Hence this.

WHERE THE DATA COMES FROM, AND WHY NOT THE GOOGLE ADS API
---------------------------------------------------------
`saadaa-wh.MAPLEMONK.Google_ads_SAADAA_GADS_Campaign_Data` -- campaign x
day, already landed in BigQuery by MapleMonk's Airbyte connector and
refreshed daily (observed 2026-10-19 05:35, same morning). It carries
`metrics_cost_micros` and covers 2025-08-18 onward across 38 campaigns
and five channel types.

The Google Ads API would remove the MapleMonk dependency, but it needs a
developer token, an OAuth client and a refresh token that this project
does not have, and it would deliver the same numbers. If MapleMonk is
ever switched off this script is what breaks, and swapping it for the
API means rewriting the SQL below and nothing else: the Postgres table
it fills is the contract.

NOTE ON THE EARLIER MAPLEMONK REMOVAL
-------------------------------------
BigQuery inventory was deliberately dropped from the nightly on
2026-10-16: 14.1M rows scanned into a 245 MB table every night to feed
one rendered column. This is not that. The source table is 1.8 MB, the
query below reads four columns of it, and the result is ~40 rows a day.

COST AND CURRENCY
-----------------
Costs are `metrics_cost_micros` / 1e6 in the account's own currency,
which is INR on customer 6770669478 -- the only Google Ads account here.
Stored as rupees, so it adds directly to Meta spend with no conversion.

Usage:
    ./.venv/bin/python scripts/fetch_google_ads_spend.py
    ./.venv/bin/python scripts/fetch_google_ads_spend.py --days 400
    ./.venv/bin/python scripts/fetch_google_ads_spend.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# dbq owns the DSN: it loads .env from an absolute path, rewrites the
# SQLAlchemy prefix psycopg2 cannot parse, and scrubs credentials out of
# every error -- which matters because this repository is public.
from scripts.dbq import connect  # noqa: E402

BQ_PROJECT = "saadaa-wh"
BQ_TABLE = "saadaa-wh.MAPLEMONK.Google_ads_SAADAA_GADS_Campaign_Data"

DDL = """
CREATE TABLE IF NOT EXISTS public.google_ads_spend_daily (
    day              date   NOT NULL,
    campaign_id      text   NOT NULL,
    campaign_name    text,
    campaign_status  text,
    channel_type     text,
    -- Rupees, already divided out of micros. Named `spend` to match
    -- insights_daily_by_ad, so the two sum without a translation layer.
    spend            numeric NOT NULL DEFAULT 0,
    clicks           bigint  NOT NULL DEFAULT 0,
    impressions      bigint  NOT NULL DEFAULT 0,
    -- Google's OWN attributed conversions. Kept for context, never for
    -- blended MER: blended divides store revenue by spend and takes no
    -- platform's word for what it caused.
    conversions      numeric NOT NULL DEFAULT 0,
    conv_value       numeric NOT NULL DEFAULT 0,
    fetched_at       timestamptz NOT NULL,
    PRIMARY KEY (day, campaign_id)
);
CREATE INDEX IF NOT EXISTS ix_google_ads_spend_daily_day
    ON public.google_ads_spend_daily(day);
"""

UPSERT = """
INSERT INTO public.google_ads_spend_daily
  (day, campaign_id, campaign_name, campaign_status, channel_type,
   spend, clicks, impressions, conversions, conv_value, fetched_at)
VALUES %s
ON CONFLICT (day, campaign_id) DO UPDATE SET
  campaign_name = EXCLUDED.campaign_name,
  campaign_status = EXCLUDED.campaign_status,
  channel_type = EXCLUDED.channel_type,
  spend = EXCLUDED.spend,
  clicks = EXCLUDED.clicks,
  impressions = EXCLUDED.impressions,
  conversions = EXCLUDED.conversions,
  conv_value = EXCLUDED.conv_value,
  fetched_at = EXCLUDED.fetched_at
-- Do not overwrite a FRESH row the Google Ads API wrote. Both feeds
-- land in this table and the API is the authority: MapleMonk's copy of
-- CONVERSIONS is a snapshot of whatever had attributed when it synced,
-- and measured 2026-10-21 it was short by Rs 39,332 over 30 days, all
-- of it in the last eight. Spend agrees to the rupee, so the guard
-- costs nothing there and protects the column that matters.
--
-- The staleness clause is the important half. A bare
-- `source <> 'google_ads_api'` would mean that if the API feed ever
-- stopped -- an expired refresh token, a revoked developer token --
-- MapleMonk's rows would be refused forever and Google data would
-- silently FREEZE at the last API run, while both jobs reported
-- success. Letting MapleMonk take an API row back once it is three
-- days stale makes the API preferred rather than absolute, so a dead
-- feed degrades to the slightly laggier source instead of to nothing.
WHERE public.google_ads_spend_daily.source <> 'google_ads_api'
   OR public.google_ads_spend_daily.fetched_at < now() - interval '3 days'
"""

#: The DDL above is CREATE TABLE IF NOT EXISTS, so it will not add a
#: column to a table that already exists. `source` has to arrive by
#: ALTER, and it must exist before the UPSERT's WHERE clause references
#: it -- scripts/fetch_google_ads_api.py runs the same statement.
MIGRATIONS = [
    "ALTER TABLE public.google_ads_spend_daily "
    "  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'maplemonk'",
]

#: GROUP BY because the source is an Airbyte landing table and can hold
#: more than one row per campaign-day across sync generations. Summing
#: is right for the metrics and MAX picks one label for the rest; a bare
#: SELECT would silently double a day's spend after a re-sync.
SQL = """
SELECT
  segments_date                                    AS day,
  CAST(campaign_id AS STRING)                      AS campaign_id,
  MAX(campaign_name)                               AS campaign_name,
  MAX(campaign_status)                             AS campaign_status,
  MAX(campaign_advertising_channel_type)           AS channel_type,
  SUM(metrics_cost_micros) / 1e6                   AS spend,
  SUM(metrics_clicks)                              AS clicks,
  SUM(metrics_impressions)                         AS impressions,
  SUM(metrics_conversions)                         AS conversions,
  SUM(metrics_conversions_value)                   AS conv_value
FROM `{table}`
WHERE segments_date BETWEEN @since AND @until
GROUP BY segments_date, campaign_id
"""


def _credentials():
    """Service account, else ADC -- the same chain the GA4 BigQuery
    fetchers use. A scheduled run needs the service account: ADC is a
    developer's personal login and is not present on a CI runner."""
    import google.auth
    sa = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if sa and Path(sa).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            sa, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds, _ = google.auth.default()
    return creds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=35,
                    help="Trailing days to refresh, ending today (default 35). "
                         "Google restates recent days as conversions land, so "
                         "the window is re-pulled rather than appended to.")
    ap.add_argument("--from", dest="from_date", default=None, help="First day (YYYY-MM-DD).")
    ap.add_argument("--to", dest="to_date", default=None, help="Last day (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true", help="Estimate the scan and exit.")
    args = ap.parse_args()

    from google.cloud import bigquery

    until = date.fromisoformat(args.to_date) if args.to_date else date.today()
    since = (date.fromisoformat(args.from_date) if args.from_date
             else until - timedelta(days=args.days - 1))

    client = bigquery.Client(project=BQ_PROJECT, credentials=_credentials())
    sql = SQL.format(table=BQ_TABLE)
    params = [
        bigquery.ScalarQueryParameter("since", "DATE", since),
        bigquery.ScalarQueryParameter("until", "DATE", until),
    ]

    dry = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, dry_run=True, use_query_cache=False))
    gib = dry.total_bytes_processed / 1024 ** 3
    print(f"Source:    {BQ_TABLE}")
    print(f"Range:     {since} .. {until}")
    print(f"Scan:      {gib:.3f} GiB  (~${gib * 6.25 / 1024:.4f})")
    if args.dry_run:
        print("\n--dry-run: nothing fetched.")
        return 0

    t0 = time.time()
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params)).result())
    payload = [(r["day"], r["campaign_id"], r["campaign_name"], r["campaign_status"],
                r["channel_type"], float(r["spend"] or 0), int(r["clicks"] or 0),
                int(r["impressions"] or 0), float(r["conversions"] or 0),
                float(r["conv_value"] or 0)) for r in rows]
    print(f"Fetched:   {len(payload):,} campaign-days in {time.time() - t0:.1f}s")

    with connect(autocommit=False, statement_timeout="300s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            for _stmt in MIGRATIONS:
                cur.execute(_stmt)
            if payload:
                # fetched_at comes from the server clock, not this
                # machine's -- the nightly and a laptop run must stamp
                # rows the same way for freshness checks to mean anything.
                psycopg2.extras.execute_values(
                    cur, UPSERT, payload,
                    template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                    page_size=1000)
        conn.commit()

    total = sum(p[5] for p in payload)
    print(f"Written:   {len(payload):,} rows into public.google_ads_spend_daily")
    print(f"\n[OK] Rs {total:,.0f} of Google Ads spend across "
          f"{len({p[1] for p in payload})} campaigns, {since} .. {until}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
