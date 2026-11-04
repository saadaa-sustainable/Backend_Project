"""First-click and last-click attribution per order, from the GA4 export.

WHY THIS EXISTS
---------------
The dashboard credits every order to its LAST click, because that is all
`customAttributes` records. Measured on real journeys, that is often not
the ad that did the work:

  * One customer clicked four Meta ads over 17 days. The 29 September
    session -- 21 minutes, 9 products -- did the persuading and is
    credited by neither first- nor last-click. Last click gave the whole
    Rs 1,478 to a Stories ad clicked the following day.
  * Another bought six times through organic search while Meta retention
    campaigns reached her the whole time and sold her nothing.

Neither fact is visible without knowing the sessions BEFORE the
converting one, which is what this table stores.

WHY NOT SHOPIFY
---------------
Shopify's own `customerJourneySummary` is empty for 96 percent of orders
on this store: GoKwik owns the checkout, so Shopify never sees the
session. Confirmed on live orders with `ready = true` and
`momentsCount = 0` -- the attribution finished and found nothing. GA4
sees 76 percent of orders, which is the only workable source.

WHY NOT QUERY BIGQUERY LIVE
---------------------------
The GA4 export is sharded by day and not clustered by user, so a
per-customer lookup scans the whole date range. Measured:

    one session, one day          0.60 GiB   $0.004
    one customer, 30 days        26.49 GiB   $0.16
    one customer, 173 days      226.67 GiB   $1.38   <- per page view

A nightly bulk extract of the same data costs $0.0014 a day. So the
aggregation runs in BigQuery and only the result lands in Postgres.

GRAIN AND JOIN
--------------
One row per GA4 `transaction_id`, which IS `shopify_orders.name`
(verified: 95.8 percent of GA4 purchases join to a real order, 75.9
percent of orders are seen by GA4).

ATTRIBUTION WINDOW
------------------
Sessions are looked back LOOKBACK_DAYS before the order. GA4's own
acquisition window is 30 days; this defaults to 90 because the journeys
that matter here run longer -- one spanned 173 days across six channels.
A longer window costs more scan and finds more first touches; it does
not change last click.

NOTE ON utm_content AND utm_term
--------------------------------
On this store `utm_content` carries the AD id and `utm_term` the AD SET
id -- the reverse of what the names suggest. Confirmed against
meta_ads/meta_adsets. 61 percent of utm_content values are numeric ad
ids, 12 percent are ad NAMES, and the rest are third-party tokens, so
the resolver downstream has to try both forms.

Usage:
    ./.venv/bin/python scripts/fetch_ga4_order_attribution.py --days 7
    ./.venv/bin/python scripts/fetch_ga4_order_attribution.py --from 2026-01-01
    ./.venv/bin/python scripts/fetch_ga4_order_attribution.py --days 7 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

PROPERTY = os.getenv("GA4_PROPERTY_ID", "383126449")
BQ_PROJECT = os.getenv("GA4_BQ_PROJECT", "saadaa-wh")
BQ_DATASET = os.getenv("GA4_BQ_DATASET", f"analytics_{PROPERTY}")

#: How far back to look for sessions preceding an order. See the module
#: docstring -- 90, not GA4's own 30, because the journeys worth seeing
#: are longer than GA4's acquisition window.
LOOKBACK_DAYS = int(os.getenv("GA4_ATTRIBUTION_LOOKBACK_DAYS", "90"))

#: The A/B testing tool fires on every interaction and is 47 percent of
#: all events. It carries no traffic source and never changes a session's
#: attribution, so excluding it halves the scan.
NOISE_EVENTS = ("Convert_Test_Tracking", "experience_impression")

DDL = """
CREATE TABLE IF NOT EXISTS public.ga4_order_attribution (
    transaction_id    text PRIMARY KEY,
    order_at          timestamptz,
    user_pseudo_id    text,
    revenue           numeric,

    first_seen_at     timestamptz,
    first_source      text,
    first_medium      text,
    first_campaign    text,
    first_campaign_id text,
    first_ad_id       text,
    first_adset_id    text,
    first_landing     text,

    last_landing      text,

    total_sessions    integer,
    sourced_sessions  integer,
    days_to_convert   integer,
    fetched_at        timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ga4_oa_order_at  ON public.ga4_order_attribution(order_at);
CREATE INDEX IF NOT EXISTS ix_ga4_oa_first_ad  ON public.ga4_order_attribution(first_ad_id);
CREATE INDEX IF NOT EXISTS ix_ga4_oa_user      ON public.ga4_order_attribution(user_pseudo_id);

-- GA4 supplies the FIRST click and nothing else. The last click is
-- ours: shopify_order_attribution.matched_ad_id, mapped from the UTM
-- the order itself carries. GA4's last click was a second, conflicting
-- answer to a question already settled. last_landing stays: it is a
-- PAGE, not an attribution, and the landing-page section keys on it.
ALTER TABLE public.ga4_order_attribution
  DROP COLUMN IF EXISTS last_source,
  DROP COLUMN IF EXISTS last_medium,
  DROP COLUMN IF EXISTS last_campaign,
  DROP COLUMN IF EXISTS last_campaign_id,
  DROP COLUMN IF EXISTS last_ad_id,
  DROP COLUMN IF EXISTS last_adset_id;
DROP INDEX IF EXISTS public.ix_ga4_oa_last_ad;
"""

COLUMNS = [
    "transaction_id", "order_at", "user_pseudo_id", "revenue",
    "first_seen_at", "first_source", "first_medium", "first_campaign",
    "first_campaign_id", "first_ad_id", "first_adset_id", "first_landing",
    "last_landing",
    "total_sessions", "sourced_sessions", "days_to_convert",
]

UPSERT = f"""
INSERT INTO public.ga4_order_attribution ({', '.join(COLUMNS)}, fetched_at)
VALUES %s
ON CONFLICT (transaction_id) DO UPDATE SET
  {', '.join(f'{c} = EXCLUDED.{c}' for c in COLUMNS if c != 'transaction_id')},
  fetched_at = EXCLUDED.fetched_at
"""

# A session's traffic source is the one its EARLIEST sourced event
# carries, taken whole.
#
# This used to be six separate MIN()s, on the reasoning that MIN skips
# NULLs and so collapses to "the one non-null value". There is rarely
# one value. MIN on a string is ALPHABETICAL, and GA4 writes
# `(organic)`, `(referral)` and `(direct)` as campaign names whenever it
# classifies traffic itself -- all of which begin with `(`, which sorts
# before every letter and digit. So any session that also recorded a
# referral hop (returning from the GoKwik checkout domain, from
# l.instagram.com, anywhere cross-domain) had its real campaign
# overwritten by a placeholder, while manual_content survived because
# the second event left that NULL.
#
# Measured when this was fixed: of orders carrying an ad id, the share
# whose landing URL still held its UTMs went from 58.1% to 97.2%, and
# ad ids sitting under a placeholder campaign fell from 1,504 to 126.
#
# ARRAY_AGG ... ORDER BY event_timestamp LIMIT 1 takes the fields
# TOGETHER from one event, so a session can no longer report one
# event's source beside another event's campaign.
SQL = """
WITH sess AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id') AS sid,
    MIN(TIMESTAMP_MICROS(event_timestamp))                      AS started_at,
    COALESCE(
      ARRAY_AGG(
        IF(collected_traffic_source.manual_source IS NOT NULL,
           STRUCT(collected_traffic_source.manual_source        AS src,
                  collected_traffic_source.manual_medium        AS med,
                  collected_traffic_source.manual_campaign_name AS camp,
                  collected_traffic_source.manual_campaign_id   AS camp_id,
                  collected_traffic_source.manual_content       AS ad_id,
                  collected_traffic_source.manual_term          AS adset_id),
           NULL)
        IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)],
      ARRAY_AGG(
        IF(collected_traffic_source.manual_campaign_name IS NOT NULL
           OR collected_traffic_source.manual_medium IS NOT NULL
           OR collected_traffic_source.manual_content IS NOT NULL,
           STRUCT(collected_traffic_source.manual_source        AS src,
                  collected_traffic_source.manual_medium        AS med,
                  collected_traffic_source.manual_campaign_name AS camp,
                  collected_traffic_source.manual_campaign_id   AS camp_id,
                  collected_traffic_source.manual_content       AS ad_id,
                  collected_traffic_source.manual_term          AS adset_id),
           NULL)
        IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)]
    )                                                           AS ts,
    -- Same bug, same fix: MIN(page_location) picked the page whose URL
    -- sorted first, and `/` (0x2F) sorts before `?` (0x3F), so the bare
    -- homepage beat the UTM-carrying landing URL.
    ARRAY_AGG((SELECT value.string_value FROM UNNEST(event_params)
                WHERE key='page_location')
              IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)]
                                                                AS landing,
    COUNTIF(event_name = 'purchase')                            AS buys,
    MIN(ecommerce.transaction_id)                               AS txn,
    MAX(ecommerce.purchase_revenue)                             AS revenue
  FROM `{project}.{dataset}.events_intraday_*`
  WHERE _TABLE_SUFFIX BETWEEN @lookback AND @until
    AND event_name NOT IN UNNEST(@noise)
  GROUP BY user_pseudo_id, sid
),
sess_flat AS (
  SELECT user_pseudo_id, sid, started_at,
         ts.src, ts.med, ts.camp, ts.camp_id, ts.ad_id, ts.adset_id,
         landing, buys, txn, revenue
  FROM sess
),
orders AS (
  SELECT * FROM sess_flat
   WHERE buys > 0 AND txn IS NOT NULL
     AND DATE(started_at) BETWEEN PARSE_DATE('%Y%m%d', @since)
                              AND PARSE_DATE('%Y%m%d', @until)
),
-- Every session by the same person in the lookback window up to and
-- including the order's own session.
pairs AS (
  SELECT
    o.txn, o.user_pseudo_id, o.started_at AS order_at, o.revenue,
    s.started_at, s.src, s.med, s.camp, s.camp_id, s.ad_id, s.adset_id, s.landing,
    ROW_NUMBER() OVER (PARTITION BY o.txn ORDER BY s.started_at ASC,  s.sid ASC)  AS rn_first,
    ROW_NUMBER() OVER (PARTITION BY o.txn ORDER BY s.started_at DESC, s.sid DESC) AS rn_last,
    COUNT(*)    OVER (PARTITION BY o.txn)                                         AS total_sessions,
    SUM(CASE WHEN s.src IS NOT NULL THEN 1 ELSE 0 END)
                OVER (PARTITION BY o.txn)                                         AS sourced_sessions
  FROM orders o
  JOIN sess_flat s
    ON  s.user_pseudo_id = o.user_pseudo_id
    AND s.started_at    <= o.started_at
    AND s.started_at    >= TIMESTAMP_SUB(o.started_at, INTERVAL @lookback_days DAY)
)
SELECT
  txn AS transaction_id,
  ANY_VALUE(order_at)        AS order_at,
  ANY_VALUE(user_pseudo_id)  AS user_pseudo_id,
  ANY_VALUE(revenue)         AS revenue,
  MAX(IF(rn_first = 1, started_at, NULL)) AS first_seen_at,
  MAX(IF(rn_first = 1, src,        NULL)) AS first_source,
  MAX(IF(rn_first = 1, med,        NULL)) AS first_medium,
  MAX(IF(rn_first = 1, camp,       NULL)) AS first_campaign,
  MAX(IF(rn_first = 1, camp_id,    NULL)) AS first_campaign_id,
  MAX(IF(rn_first = 1, ad_id,      NULL)) AS first_ad_id,
  MAX(IF(rn_first = 1, adset_id,   NULL)) AS first_adset_id,
  MAX(IF(rn_first = 1, landing,    NULL)) AS first_landing,
  MAX(IF(rn_last  = 1, landing,    NULL)) AS last_landing,
  ANY_VALUE(total_sessions)   AS total_sessions,
  ANY_VALUE(sourced_sessions) AS sourced_sessions,
  TIMESTAMP_DIFF(ANY_VALUE(order_at),
                 MAX(IF(rn_first = 1, started_at, NULL)), DAY) AS days_to_convert
FROM pairs
GROUP BY txn
"""


def _dsn() -> str:
    return os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")


def _credentials():
    """Service account, else ADC. NOT the GA4 OAuth token.

    secrets/ga4_token.json is deliberately skipped here even though it
    sits right next to this script. It was granted `analytics.readonly`
    and nothing else, so asking it for `cloud-platform` fails at refresh
    with `invalid_scope: Bad Request` -- the token cannot widen its own
    grant. That token is for the Data API; BigQuery is a different
    service and needs its own credential.

    A scheduled run should use the service account: ADC is a developer's
    personal login and is not present on a CI runner.
    """
    import google.auth
    sa = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if sa and Path(sa).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            sa, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds, _ = google.auth.default()
    return creds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, help="Trailing window of ORDER days, ending today.")
    ap.add_argument("--from", dest="from_date", help="First order day (YYYY-MM-DD).")
    ap.add_argument("--to", dest="to_date", help="Last order day (YYYY-MM-DD).")
    ap.add_argument("--lookback", type=int, default=LOOKBACK_DAYS,
                    help=f"Days of sessions to look back before an order (default {LOOKBACK_DAYS}).")
    ap.add_argument("--dry-run", action="store_true", help="Estimate the scan and exit.")
    args = ap.parse_args()

    today = date.today()
    if args.days:
        until, since = today, today - timedelta(days=args.days - 1)
    else:
        since = date.fromisoformat(args.from_date) if args.from_date else date(2026, 1, 1)
        until = date.fromisoformat(args.to_date) if args.to_date else today
    if since > until:
        print(f"Empty range: {since} .. {until}", file=sys.stderr)
        return 2
    lookback = since - timedelta(days=args.lookback)

    from google.cloud import bigquery
    client = bigquery.Client(project=BQ_PROJECT, credentials=_credentials())
    sql = SQL.format(project=BQ_PROJECT, dataset=BQ_DATASET)
    params = [
        bigquery.ScalarQueryParameter("since", "STRING", since.strftime("%Y%m%d")),
        bigquery.ScalarQueryParameter("until", "STRING", until.strftime("%Y%m%d")),
        bigquery.ScalarQueryParameter("lookback", "STRING", lookback.strftime("%Y%m%d")),
        bigquery.ScalarQueryParameter("lookback_days", "INT64", args.lookback),
        bigquery.ArrayQueryParameter("noise", "STRING", list(NOISE_EVENTS)),
    ]
    print(f"Orders:    {since} .. {until}")
    print(f"Sessions:  from {lookback} ({args.lookback}-day lookback)")

    est = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, dry_run=True, use_query_cache=False))
    gib = est.total_bytes_processed / 2 ** 30
    print(f"Scan:      {gib:,.1f} GiB  (~${gib / 1024 * 6.25:,.2f})")
    if args.dry_run:
        print("\n--dry-run: nothing fetched.")
        return 0

    t0 = time.time()
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params)).result())
    print(f"Fetched:   {len(rows):,} orders in {time.time() - t0:.1f}s")
    if not rows:
        return 0

    payload = [tuple(r[c] for c in COLUMNS) + (datetime.now(timezone.utc),) for r in rows]
    conn = psycopg2.connect(_dsn(), connect_timeout=20)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
            cur.execute(DDL)
        conn.commit()
        # Chunked: the Supabase pooler drops a single oversized statement,
        # and a full-year backfill is ~415k rows.
        written = 0
        for i in range(0, len(payload), 1000):
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, UPSERT, payload[i:i + 1000], page_size=1000)
            conn.commit()
            written += len(payload[i:i + 1000])
        print(f"Written:   {written:,} rows into public.ga4_order_attribution")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE first_ad_id IS NOT NULL),
                       -- Reachable from a Shopify order, which is the
                       -- only way a first click is of any use: the
                       -- order number IS the transaction_id.
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM public.shopify_orders s
                            WHERE s.name = ga4_order_attribution.transaction_id)),
                       ROUND(AVG(total_sessions), 1),
                       ROUND(AVG(days_to_convert), 1)
                  FROM public.ga4_order_attribution
                 WHERE order_at::date BETWEEN %s AND %s
            """, (since, until))
            n, with_ad, joined, avg_s, avg_d = cur.fetchone()
            print(f"\n[OK] {n:,} orders in range")
            print(f"     first-click ad id present   {with_ad:,}  ({100 * with_ad / n:.1f}%)")
            print(f"     matched to a Shopify order  {joined:,}  ({100 * joined / n:.1f}%)")
            print(f"     avg sessions before order   {avg_s}")
            print(f"     avg days to convert         {avg_d}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
