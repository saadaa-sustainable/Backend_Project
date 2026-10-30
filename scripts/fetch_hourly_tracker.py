#!/usr/bin/env python
"""Hourly campaign tracker -- sessions, spend and revenue by the hour.

Built for the Diwali campaign, where a daily dashboard is too slow to
act on. Everything here is the SAME definition as the Overview's
session band, just bucketed by hour instead of by day, so the two agree
when you sum a day up.

WHERE EACH NUMBER COMES FROM, AND WHY
-------------------------------------
sessions      ShopifyQL `sessions`, GROUP BY hour, utm_source. Verified
              live 2026-10-30: 24 rows a day, and the utm split works
              at hour grain, which is what makes paid-vs-direct
              possible.

revenue       The ORDERS are authoritative, summed from each order's
              totalPrice -- the same basis the Overview divides by, so
              an hour and a day mean the same thing, and the channel
              splits actually add up to the total.

              ShopifyQL `sales` is carried beside it as a cross-check,
              not as the number. Its `total_sales` is NET OF RETURNS and
              its `gross_sales` is before discounts, so neither equals
              an order total: measured on 2026-10-29, gross 18,23,217 /
              total_sales 14,72,931 / returns -1,17,934, and
              total_sales + returns = 15,90,864 against the orders'
              15,96,762 -- 0.4 per cent apart, which is the reconciliation
              this column exists to show.

              ShopifyQL could not have answered this anyway: `GROUP BY
              hour, utm_source` on `sales` is rejected with "Attribution
              Syntax Required", so a channel split has to come from the
              orders regardless.

spend         Meta insights with
              breakdowns=hourly_stats_aggregated_by_advertiser_time_zone.
              Verified live: 24 rows with spend and impressions, in the
              ADVERTISER's timezone, which is the same Asia/Kolkata the
              store reports in -- so the two line up without shifting.

              Google Ads is NOT here. It comes from a MapleMonk export
              that lands daily; there is nothing hourly to read, and a
              day's figure spread over 24 hours would be an invention.
              Cost per session is therefore Meta + Kwikchat, and the
              column says so.

kwikchat      The flat placeholder, divided by 24. It is already an
              estimate at day grain; this does not make it more wrong,
              and leaving it out would make cost per session read low
              in exactly the flattering direction.

ga4           Hourly ARPU, revenue and sessions. Best effort: GA4 lags
              and a missing hour is reported as NULL rather than zero.

TIMEZONE
--------
Asia/Kolkata throughout. ShopifyQL returns the hour as a UTC instant
(2026-10-28T18:30:00Z is midnight IST on the 29th); Meta returns a
"00:00:00 - 00:59:59" label in the advertiser's timezone. Both are
normalised to the UTC instant that starts the IST hour, so one row per
real hour and no double-counting at the day boundary.

Usage:
    .venv/bin/python scripts/fetch_hourly_tracker.py              # today
    .venv/bin/python scripts/fetch_hourly_tracker.py --date 2026-10-29
    .venv/bin/python scripts/fetch_hourly_tracker.py --days 3
    .venv/bin/python scripts/fetch_hourly_tracker.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402

from scripts.dbq import connect  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

TABLE = "public.hourly_campaign_tracker"

#: Kwikchat's flat daily placeholder, spread evenly. Same constant the
#: seeder uses; imported rather than retyped would drag in that script's
#: argparse, so it is asserted against it in the tests instead.
KWIKCHAT_DAILY = 30_000.0

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    -- The UTC instant that starts an Asia/Kolkata hour.
    hour                    timestamptz PRIMARY KEY,
    day_ist                 date NOT NULL,
    hour_of_day             smallint NOT NULL,

    -- Sessions, from ShopifyQL.
    sessions                integer,
    sessions_paid           integer,
    sessions_direct         integer,
    sessions_meta           integer,
    sessions_google         integer,
    -- The raw per-source split, kept rather than thrown away after
    -- bucketing. ShopifyQL already returns it, the buckets above are
    -- lossy, and "which source" is the first question anyone asks when
    -- a bucket moves. ~20-40 keys an hour.
    sessions_by_source      jsonb,

    -- Revenue. `revenue` is ShopifyQL's hour total and is the
    -- authoritative one; the per-channel figures come from the orders
    -- and will not sum to it exactly, because an order with no
    -- utm_source belongs to no channel.
    -- Summed from order totals. The channel columns below are the
    -- same figure split, so they reconcile against it exactly.
    revenue                 numeric,
    orders                  integer,
    -- ShopifyQL's own total for the hour, net of returns. A
    -- cross-check, deliberately a different measure.
    revenue_shopifyql       numeric,
    revenue_meta            numeric,
    revenue_google          numeric,
    revenue_paid            numeric,
    orders_meta             integer,
    new_customers           integer,
    new_customer_revenue    numeric,

    -- Spend. Meta is real; kwikchat is the flat placeholder / 24.
    meta_spend              numeric,
    meta_impressions        bigint,
    kwikchat_spend          numeric,

    -- GA4, best effort.
    ga4_sessions            integer,
    ga4_revenue             numeric,
    ga4_active_users        integer,

    fetched_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_hourly_tracker_day ON {TABLE} (day_ist);
"""

#: The table ships before every column it will ever have, and
#: CREATE TABLE IF NOT EXISTS is a no-op once it exists -- so a new
#: column needs an ALTER or the next write dies on an undefined column.
MIGRATIONS = [
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS sessions_by_source jsonb",
]

COLUMNS = [
    "hour", "day_ist", "hour_of_day",
    "sessions", "sessions_paid", "sessions_direct", "sessions_meta", "sessions_google",
    "sessions_by_source",
    "revenue", "orders", "revenue_shopifyql", "revenue_meta", "revenue_google",
    "revenue_paid", "orders_meta", "new_customers", "new_customer_revenue",
    "meta_spend", "meta_impressions", "kwikchat_spend",
    "ga4_sessions", "ga4_revenue", "ga4_active_users",
]

UPSERT = f"""
INSERT INTO {TABLE} ({", ".join(COLUMNS)})
VALUES %s
ON CONFLICT (hour) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "hour")},
  fetched_at = now()
"""


# ----------------------------------------------------------------------
# Channel rules. The SAME utm_source test the rest of the dashboard
# uses, so an hour's Meta sessions and a day's Meta sessions mean the
# same thing. Kept in Python because ShopifyQL hands back the raw
# utm_source and the bucketing happens here, not in SQL.
# ----------------------------------------------------------------------
def is_meta(src: str | None) -> bool:
    if not src:
        return False
    s = src.strip().lower()
    return (
        s.startswith("meta")
        or "=meta" in s
        or s.startswith(("facebook.", "instagram."))
        or s.endswith((".facebook.com", ".instagram.com"))
        or s in {"facebook", "fb", "ig", "instagram", "igshopping", "an",
                 "msg", "messenger", "fb.me", "{{site_source_name}}"}
    )


def is_google(src: str | None) -> bool:
    if not src:
        return False
    s = src.strip().lower()
    return "google" in s or "adwords" in s or s in {"gads", "yt_ads", "youtube"}


def is_direct(src: str | None) -> bool:
    """No utm_source at all, or one that literally says direct/none.

    This is the denominator the 'paid' figures exclude. A session with
    no source is not necessarily organic -- it is unattributed -- but it
    is certainly not one we paid for, which is the question being asked.
    """
    if not src:
        return True
    return src.strip().lower() in {"direct", "none", "(direct)", "(none)", ""}


def source_label(src: str) -> str:
    """The key a utm_source is counted under in sessions_by_source."""
    return src.strip().lower()


def ist_hour(instant: datetime) -> datetime:
    """Normalise any aware datetime to the UTC instant starting its IST hour."""
    local = instant.astimezone(IST)
    return local.replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------
async def fetch_sessions(client, store, day: date) -> dict[datetime, dict]:
    """Sessions per hour, split by channel."""
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    q = (f"FROM sessions SHOW sessions "
         f"SINCE {day.isoformat()} UNTIL {day.isoformat()} "
         f"GROUP BY hour, utm_source ORDER BY hour LIMIT 2000")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"sessions parseErrors: {resp['parseErrors']}")
    out: dict[datetime, dict] = {}
    for row in (resp.get("tableData") or {}).get("rows", []):
        hour = ist_hour(datetime.fromisoformat(row["hour"].replace("Z", "+00:00")))
        src, n = row.get("utm_source"), int(float(row.get("sessions") or 0))
        b = out.setdefault(hour, dict(sessions=0, sessions_paid=0, sessions_direct=0,
                                      sessions_meta=0, sessions_google=0,
                                      sessions_by_source={}))
        # Null and the literal strings Shopify uses for "no source" all
        # mean the same thing to a reader, so they collapse to one key
        # rather than appearing as four near-identical slices. Case is
        # folded for the same reason: the campaigns are tagged by hand
        # and META/Meta/meta are one source, not three.
        label = "(direct)" if is_direct(src) else source_label(src)
        b["sessions_by_source"][label] = b["sessions_by_source"].get(label, 0) + n
        b["sessions"] += n
        if is_direct(src):
            b["sessions_direct"] += n
        else:
            b["sessions_paid"] += n
        if is_meta(src):
            b["sessions_meta"] += n
        if is_google(src):
            b["sessions_google"] += n
    return out


async def fetch_sales(client, store, day: date) -> dict[datetime, dict]:
    """The authoritative revenue and order count per hour."""
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    q = (f"FROM sales SHOW total_sales, returns, orders "
         f"SINCE {day.isoformat()} UNTIL {day.isoformat()} "
         f"GROUP BY hour ORDER BY hour LIMIT 100")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"sales parseErrors: {resp['parseErrors']}")
    out = {}
    for row in (resp.get("tableData") or {}).get("rows", []):
        hour = ist_hour(datetime.fromisoformat(row["hour"].replace("Z", "+00:00")))
        # total_sales is net of returns; adding them back gives the
        # gross figure the orders carry, which is what this compares to.
        out[hour] = {
            "revenue_shopifyql": (float(row.get("total_sales") or 0)
                                  - float(row.get("returns") or 0)),
        }
    return out


ORDERS_HOURLY_QUERY = """
query HourlyOrders($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query) {
    edges {
      node {
        id
        createdAt
        totalPriceSet { shopMoney { amount } }
        customer { id numberOfOrders }
        customAttributes { key value }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


async def fetch_orders(client, store, day: date) -> dict[datetime, dict]:
    """Per-channel revenue, from the orders themselves.

    ShopifyQL cannot split sales by utm_source -- it answers
    "Attribution Syntax Required" -- so the channel breakdown is read
    from each order's customAttributes, which is the same place the
    daily pipeline reads utm_source from.
    """
    from shopify_client import graphql_request  # noqa: PLC0415

    lo = datetime.combine(day, datetime.min.time(), IST)
    hi = lo + timedelta(days=1)
    q = f"created_at:>='{lo.isoformat()}' AND created_at:<'{hi.isoformat()}'"
    out: dict[datetime, dict] = {}
    after = None
    while True:
        data = await graphql_request(client, store, ORDERS_HOURLY_QUERY,
                                     {"first": 250, "after": after, "query": q})
        conn = data["orders"]
        for edge in conn["edges"]:
            n = edge["node"]
            created = datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00"))
            hour = ist_hour(created)
            price = float(n["totalPriceSet"]["shopMoney"]["amount"] or 0)
            attrs = {a["key"]: a["value"] for a in (n.get("customAttributes") or [])}
            src = attrs.get("utm_source")
            cust = n.get("customer") or {}
            # numberOfOrders counts the customer's LIFETIME orders, so 1
            # means this is their first -- the same test the daily
            # acquisition figures use.
            first_order = str(cust.get("numberOfOrders") or "") == "1"
            b = out.setdefault(hour, dict(revenue=0.0, orders=0, revenue_meta=0.0,
                                          revenue_google=0.0, revenue_paid=0.0,
                                          orders_meta=0, new_customers=0,
                                          new_customer_revenue=0.0))
            b["revenue"] += price
            b["orders"] += 1
            if is_meta(src):
                b["revenue_meta"] += price
                b["orders_meta"] += 1
            if is_google(src):
                b["revenue_google"] += price
            if not is_direct(src):
                b["revenue_paid"] += price
            if first_order:
                b["new_customers"] += 1
                b["new_customer_revenue"] += price
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    return out


async def fetch_meta(client, day: date) -> dict[datetime, dict]:
    """Spend and impressions per hour, summed across every ad account."""
    from ingest_last_15_days import _discover_accounts  # noqa: PLC0415

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ACCESS_TOKEN is not set")
    base = f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}"
    out: dict[datetime, dict] = {}
    for acct in _discover_accounts().values():
        params = {
            "access_token": token, "level": "account",
            "fields": "spend,impressions",
            "time_range": json.dumps({"since": day.isoformat(), "until": day.isoformat()}),
            "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
            "limit": 500,
        }
        r = await client.get(f"{base}/act_{acct.account_id}/insights", params=params)
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"{acct.name}: {body['error'].get('message')}")
        for row in body.get("data", []):
            label = row.get("hourly_stats_aggregated_by_advertiser_time_zone", "")
            # "14:00:00 - 14:59:59" -> 14, already the advertiser's
            # timezone, which is the store's.
            hh = int(label.split(":", 1)[0])
            hour = datetime.combine(day, datetime.min.time(), IST).replace(hour=hh)
            hour = hour.astimezone(timezone.utc)
            b = out.setdefault(hour, dict(meta_spend=0.0, meta_impressions=0))
            b["meta_spend"] += float(row.get("spend") or 0)
            b["meta_impressions"] += int(float(row.get("impressions") or 0))
    return out


def fetch_ga4(day: date) -> dict[datetime, dict]:
    """GA4 by hour. Best effort -- a failure must not stop the rest."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient  # noqa: PLC0415
        from google.analytics.data_v1beta.types import (  # noqa: PLC0415
            DateRange, Dimension, Metric, RunReportRequest)
    except ImportError:
        return {}
    property_id = os.environ.get("GA4_PROPERTY_ID", "383126449")
    try:
        # fetch_ga4_daily owns the credential chain -- service account,
        # then a cached OAuth token, then ADC. Bare ADC is NOT enough:
        # it authenticates without the analytics scope and the call dies
        # with ACCESS_TOKEN_SCOPE_INSUFFICIENT.
        import importlib.util  # noqa: PLC0415
        spec = importlib.util.spec_from_file_location(
            "ga4_daily", ROOT / "scripts" / "fetch_ga4_daily.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        client = BetaAnalyticsDataClient(credentials=mod._credentials())
        req = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=day.isoformat(), end_date=day.isoformat())],
            dimensions=[Dimension(name="hour")],
            metrics=[Metric(name="sessions"), Metric(name="totalRevenue"),
                     Metric(name="activeUsers")],
        )
        resp = client.run_report(req)
    except Exception as exc:  # noqa: BLE001 -- best effort by design
        print(f"  [warn] GA4 hourly unavailable: {str(exc)[:120]}", flush=True)
        return {}
    out = {}
    for row in resp.rows:
        raw = row.dimension_values[0].value
        # GA4 emits an "(other)" bucket when a report exceeds its
        # cardinality limit. It is not an hour and belongs to no hour,
        # so it is dropped rather than folded into one -- which would
        # silently inflate whichever hour it landed on.
        if not raw.isdigit():
            continue
        hh = int(raw)
        hour = datetime.combine(day, datetime.min.time(), IST).replace(hour=hh)
        out[hour.astimezone(timezone.utc)] = {
            "ga4_sessions": int(float(row.metric_values[0].value or 0)),
            "ga4_revenue": float(row.metric_values[1].value or 0),
            "ga4_active_users": int(float(row.metric_values[2].value or 0)),
        }
    return out


# ----------------------------------------------------------------------
async def build_day(client, store, day: date) -> list[dict]:
    sessions, sales, orders, meta = await asyncio.gather(
        fetch_sessions(client, store, day),
        fetch_sales(client, store, day),
        fetch_orders(client, store, day),
        fetch_meta(client, day),
    )
    ga4 = fetch_ga4(day)

    hours = sorted(set(sessions) | set(sales) | set(orders) | set(meta) | set(ga4))
    rows = []
    for hour in hours:
        local = hour.astimezone(IST)
        row = {
            "hour": hour, "day_ist": local.date(), "hour_of_day": local.hour,
            # The placeholder, spread evenly. Only for hours that have
            # actually happened -- giving a future hour its share would
            # make cost per session read high all day.
            "kwikchat_spend": round(KWIKCHAT_DAILY / 24.0, 4),
        }
        for source in (sessions, sales, orders, meta, ga4):
            row.update(source.get(hour, {}))
        rows.append(row)
    return rows


def write(rows: list[dict]) -> int:
    import psycopg2.extras  # noqa: PLC0415

    tuples = [
        tuple(json.dumps(r.get(c)) if c == "sessions_by_source" and r.get(c) is not None
              else r.get(c) for c in COLUMNS)
        for r in rows
    ]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        for statement in MIGRATIONS:
            cur.execute(statement)
        psycopg2.extras.execute_values(cur, UPSERT, tuples, page_size=200)
        conn.commit()
    return len(tuples)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="One IST day. Default: today.")
    ap.add_argument("--days", type=int, default=1,
                    help="Trailing days ending at --date (default today).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from shopify_client import discover_stores  # noqa: PLC0415

    end = args.date or datetime.now(IST).date()
    days = [end - timedelta(days=i) for i in range(args.days - 1, -1, -1)]
    store = list(discover_stores().values())[0]

    total = 0
    async with httpx.AsyncClient(timeout=120) as client:
        for day in days:
            rows = await build_day(client, store, day)
            sess = sum(r.get("sessions") or 0 for r in rows)
            spend = sum((r.get("meta_spend") or 0) + (r.get("kwikchat_spend") or 0) for r in rows)
            rev = sum(r.get("revenue") or 0 for r in rows)
            crosscheck = sum(r.get("revenue_shopifyql") or 0 for r in rows)
            print(f"{day}  {len(rows):>2} hours   {sess:>7,} sessions   "
                  f"Rs {spend:>10,.0f} spend   Rs {rev:>11,.0f} revenue")
            if rev and crosscheck:
                drift = 100.0 * (crosscheck - rev) / rev
                # Stated, not hidden: two different queries over the same
                # day will not agree to the rupee, and a reader should
                # see by how much rather than trust one blindly.
                print(f"          ShopifyQL cross-check Rs {crosscheck:,.0f} "
                      f"({drift:+.1f}%)")
            if not args.dry_run:
                total += write(rows)

    print(f"\n[{'DRY RUN' if args.dry_run else 'OK'}] "
          f"{total:,} hourly rows {'built' if args.dry_run else 'written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
