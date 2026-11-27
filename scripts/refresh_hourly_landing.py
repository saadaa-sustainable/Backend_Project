#!/usr/bin/env python
"""Hourly landing-page tracker -- traffic, orders and ad cost per page, per hour.

The hourly_campaign_tracker answers "how is the store doing this hour".
This answers "which PAGE is doing it", at the same grain, from the same
kind of live sources, so the two can be read side by side.

THREE WRITERS, ONE ROW
----------------------
Each fills its own columns of (hour, landing_page_path) and must not
clear the others': a page with sessions but no orders, or spend but no
sessions, is a normal and common state.

1. SESSIONS  ShopifyQL, `FROM sessions ... GROUP BY hour,
   landing_page_path`. Gives sessions, visitors, bounces, cart additions
   and reached-checkout per page per hour, live. Verified live
   2026-11-27.

2. ORDERS  Shopify GraphQL, the same hourly order query the campaign
   tracker uses. The landing page comes from the ORDER ITSELF --
   custom_attributes.full_url, written by the storefront -- not from
   GA4. 80.5% of orders over the last 7 days carry it, against GA4's
   70.8%, and it needs no join and no export.

   This replaces the previous GA4 route, which looked fine and was not:
   shopify_orders, order_customer_type and ga4_order_attribution are all
   rebuilt once a day by the 01:30 UTC nightly, so from 07:00 IST
   onwards they are frozen at that morning's snapshot. Measured
   2026-11-27 at 13:47 IST, all three stopped at 07:07 holding 285
   orders while the store had taken several times that. An hourly
   tracker reading a daily table is not an hourly tracker.

   New vs repeat is customer.numberOfOrders == 1, the same test the
   campaign tracker makes, rather than a warehouse flag that lags.

3. META  Ad-level Insights with
   breakdowns=hourly_stats_aggregated_by_advertiser_time_zone, each ad
   mapped to a page by its creative's landing URL.

   Spend lands on the page the AD POINTS AT, which is not always the
   page the buyer converted on. meta_roas is therefore "what Meta
   reports for the ads aimed here" and shopify_roas is "what the store
   booked from people who landed here". They answer different questions
   and will not match; both are on the row for that reason.

ONE PAGE KEY
------------
All three go through page_path() from app/services/gold/cpis.py, which
is the only reason an ad's URL, an order's full_url and ShopifyQL's
landing_page_path land on the same row. It collapses
/collections/x/products/y to /products/y, so normalising only two of the
three would split a page in half silently.

TIMEZONE
--------
Asia/Kolkata throughout. `hour` is a UTC instant at the start of the IST
hour, matching hourly_campaign_tracker.hour.

Usage:
    .venv/bin/python scripts/refresh_hourly_landing.py              # today
    .venv/bin/python scripts/refresh_hourly_landing.py --days 7
    .venv/bin/python scripts/refresh_hourly_landing.py --from 2026-11-01 --to 2026-11-20
    .venv/bin/python scripts/refresh_hourly_landing.py --only sessions,orders
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import os
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import httpx  # noqa: E402

from app.services.gold.cpis import page_path  # noqa: E402
from scripts.dbq import connect  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

DDL = """
CREATE TABLE IF NOT EXISTS hourly_landing_tracker (
    hour                    timestamptz NOT NULL,
    landing_page_path       text        NOT NULL,
    -- Where the visit came from: the session's or order's utm_source,
    -- folded onto one spelling (see norm_source). 'direct' when there
    -- is none. Part of the key, so one page can show Meta and Google
    -- traffic side by side instead of one blended row.
    source                  text        NOT NULL DEFAULT 'direct',
    -- traffic (ShopifyQL)
    sessions                integer     NOT NULL DEFAULT 0,
    visitors                integer     NOT NULL DEFAULT 0,
    bounces                 integer     NOT NULL DEFAULT 0,
    cart_additions          integer     NOT NULL DEFAULT 0,
    reached_checkout        integer     NOT NULL DEFAULT 0,
    -- orders (Shopify GraphQL, live)
    orders                  integer     NOT NULL DEFAULT 0,
    revenue                 numeric     NOT NULL DEFAULT 0,
    new_customer_orders     integer     NOT NULL DEFAULT 0,
    new_customer_sales      numeric     NOT NULL DEFAULT 0,
    repeat_customer_orders  integer     NOT NULL DEFAULT 0,
    repeat_customer_sales   numeric     NOT NULL DEFAULT 0,
    -- cost (Meta), two ways, never added together
    --
    -- meta_spend is spend on ads whose CREATIVE points at this page.
    -- order_spend is spend on ads that actually EARNED an order on this
    -- page: the order carries both its URL and the ad id, so the ad's
    -- spend follows its own orders, split by order share. The second
    -- covers far more spend, because an ad created today has no row in
    -- ad_media yet but still takes orders within the hour.
    meta_spend              numeric     NOT NULL DEFAULT 0,
    order_spend             numeric     NOT NULL DEFAULT 0,
    meta_impressions        bigint      NOT NULL DEFAULT 0,
    meta_conv_value         numeric     NOT NULL DEFAULT 0,
    meta_purchases          numeric     NOT NULL DEFAULT 0,
    ncp                     numeric     NOT NULL DEFAULT 0,
    sessions_refreshed_at   timestamptz,
    orders_refreshed_at     timestamptz,
    meta_refreshed_at       timestamptz,
    PRIMARY KEY (hour, landing_page_path, source)
);
CREATE INDEX IF NOT EXISTS hourly_landing_tracker_hour_idx
    ON hourly_landing_tracker (hour DESC);

-- What the STORE took, beside what this table could attribute to a
-- page. Shopify's own figures, so the dashboard's headline reconciles
-- with Shopify admin instead of with our own order fetch.
--
-- Not written into shopify_sales_daily: that is a silver table the
-- 01:30 nightly owns and rebuilds from the raw dump, which is also why
-- it reads a fraction of what the day had taken by mid-afternoon. An
-- hourly job writing into it would be fighting the nightly.
-- Which pages an ad's own orders landed on, per day. Written by the
-- ORDERS pass and read by the META pass, so `--only meta` still has the
-- mix to allocate by and the two passes stay independent.
CREATE TABLE IF NOT EXISTS landing_ad_order_mix (
    day               date    NOT NULL,
    ad_id             text    NOT NULL,
    landing_page_path text    NOT NULL,
    orders            integer NOT NULL DEFAULT 0,
    refreshed_at      timestamptz,
    PRIMARY KEY (day, ad_id, landing_page_path)
);

-- ad -> landing URL straight from Ads Manager exports
-- (scripts/import_landing_urls_csv.py). Declared here too so the
-- lookup below never meets a missing table on a fresh database.
CREATE TABLE IF NOT EXISTS ad_landing_map (
    ad_id            text PRIMARY KEY,
    landing_page_url text NOT NULL,
    source           text NOT NULL,
    imported_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS landing_store_totals (
    day           date NOT NULL PRIMARY KEY,
    gross_sales   numeric NOT NULL DEFAULT 0,
    net_sales     numeric NOT NULL DEFAULT 0,
    total_sales   numeric NOT NULL DEFAULT 0,
    orders        integer NOT NULL DEFAULT 0,
    refreshed_at  timestamptz
);
"""

# Columns added after the first version shipped; CREATE IF NOT EXISTS
# alone would leave an existing table without them.
#: Adding `source` to an existing table means rebuilding the primary
#: key, not just adding a column -- the old key would keep collapsing
#: every source onto one row.
MIGRATE_KEY = """
ALTER TABLE hourly_landing_tracker
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'direct';
ALTER TABLE hourly_landing_tracker DROP CONSTRAINT IF EXISTS hourly_landing_tracker_pkey;
ALTER TABLE hourly_landing_tracker
    ADD PRIMARY KEY (hour, landing_page_path, source);
CREATE INDEX IF NOT EXISTS hourly_landing_tracker_source_idx
    ON hourly_landing_tracker (source);
"""

MIGRATE = """
ALTER TABLE hourly_landing_tracker
    ADD COLUMN IF NOT EXISTS sessions              integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS visitors              integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bounces               integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cart_additions        integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reached_checkout      integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sessions_refreshed_at timestamptz,
    ADD COLUMN IF NOT EXISTS orders_refreshed_at   timestamptz,
    ADD COLUMN IF NOT EXISTS order_spend           numeric     NOT NULL DEFAULT 0
"""

#: Each writer clears only its own columns for the window before
#: reinserting, so a page that stopped selling (or stopped taking
#: traffic) drops to zero instead of keeping the previous run's figure.
CLEAR = {
    "sessions": "sessions = 0, visitors = 0, bounces = 0, cart_additions = 0, "
                "reached_checkout = 0",
    "orders":   "orders = 0, revenue = 0, new_customer_orders = 0, "
                "new_customer_sales = 0, repeat_customer_orders = 0, "
                "repeat_customer_sales = 0",
    "meta":     "meta_spend = 0, order_spend = 0, meta_impressions = 0, "
                "meta_conv_value = 0, meta_purchases = 0, ncp = 0",
}

UPSERT = {
    "sessions": """
        INSERT INTO hourly_landing_tracker AS t
            (hour, landing_page_path, source, sessions, visitors, bounces,
             cart_additions, reached_checkout, sessions_refreshed_at)
        VALUES (%(hour)s, %(path)s, %(source)s, %(sessions)s, %(visitors)s, %(bounces)s,
                %(cart_additions)s, %(reached_checkout)s, now())
        ON CONFLICT (hour, landing_page_path, source) DO UPDATE SET
            sessions = EXCLUDED.sessions, visitors = EXCLUDED.visitors,
            bounces = EXCLUDED.bounces, cart_additions = EXCLUDED.cart_additions,
            reached_checkout = EXCLUDED.reached_checkout,
            sessions_refreshed_at = EXCLUDED.sessions_refreshed_at
    """,
    "orders": """
        INSERT INTO hourly_landing_tracker AS t
            (hour, landing_page_path, source, orders, revenue,
             new_customer_orders, new_customer_sales,
             repeat_customer_orders, repeat_customer_sales, orders_refreshed_at)
        VALUES (%(hour)s, %(path)s, %(source)s, %(orders)s, %(revenue)s,
                %(new_orders)s, %(new_sales)s, %(rep_orders)s, %(rep_sales)s, now())
        ON CONFLICT (hour, landing_page_path, source) DO UPDATE SET
            orders = EXCLUDED.orders, revenue = EXCLUDED.revenue,
            new_customer_orders = EXCLUDED.new_customer_orders,
            new_customer_sales = EXCLUDED.new_customer_sales,
            repeat_customer_orders = EXCLUDED.repeat_customer_orders,
            repeat_customer_sales = EXCLUDED.repeat_customer_sales,
            orders_refreshed_at = EXCLUDED.orders_refreshed_at
    """,
    "meta": """
        INSERT INTO hourly_landing_tracker AS t
            (hour, landing_page_path, source, meta_spend, order_spend,
             meta_impressions, meta_conv_value, meta_purchases, ncp,
             meta_refreshed_at)
        VALUES (%(hour)s, %(path)s, 'meta', %(spend)s, %(order_spend)s,
                %(impressions)s, %(conv_value)s, %(purchases)s, %(ncp)s, now())
        ON CONFLICT (hour, landing_page_path, source) DO UPDATE SET
            meta_spend = EXCLUDED.meta_spend,
            order_spend = EXCLUDED.order_spend,
            meta_impressions = EXCLUDED.meta_impressions,
            meta_conv_value = EXCLUDED.meta_conv_value,
            meta_purchases = EXCLUDED.meta_purchases,
            ncp = EXCLUDED.ncp,
            meta_refreshed_at = EXCLUDED.meta_refreshed_at
    """,
}

DELETE_EMPTY = """
DELETE FROM hourly_landing_tracker
 WHERE hour >= %(from_ts)s AND hour < %(to_ts)s
   AND sessions = 0 AND orders = 0 AND meta_spend = 0 AND meta_impressions = 0
   AND order_spend = 0
"""

STORE_UPSERT = """
INSERT INTO landing_store_totals AS t
    (day, gross_sales, net_sales, total_sales, orders, refreshed_at)
VALUES (%(day)s, %(gross)s, %(net)s, %(total)s, %(orders)s, now())
ON CONFLICT (day) DO UPDATE SET
    gross_sales = EXCLUDED.gross_sales, net_sales = EXCLUDED.net_sales,
    total_sales = EXCLUDED.total_sales, orders = EXCLUDED.orders,
    refreshed_at = EXCLUDED.refreshed_at
"""

NCP_IDS_SQL = """
SELECT DISTINCT raw_payload ->> 'id' AS id
  FROM raw_dump_meta
 WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'NCP'
"""


#: Meta spends under half a dozen spellings and Google under three.
#: Folding them is what lets "meta" on the dashboard mean the whole of
#: Meta rather than whichever tag the campaign happened to carry.
_SOURCE_ALIASES = {
    "facebook": "meta", "fb": "meta", "ig": "meta", "instagram": "meta",
    "igshopping": "meta", "facebook.com": "meta", "m.facebook.com": "meta",
    "instagram.com": "meta", "fb_ig": "meta",
    "google.com": "google", "googleads": "google", "adwords": "google",
    "google_ads": "google", "gads": "google",
}


def norm_source(value: str | None) -> str:
    """One spelling per source. Unknown sources keep their own name
    rather than being swept into 'other': kwikchat and unloq are real
    channels here and vanish if they are bucketed."""
    v = (value or "").strip().lower()
    if not v or v in {"(direct)", "(none)", "none", "null"}:
        return "direct"
    return _SOURCE_ALIASES.get(v, v)


def ist_hour_utc(day: date, hh: int) -> datetime:
    """Start of an IST hour, as the UTC instant the table stores."""
    return datetime.combine(day, datetime.min.time(), IST).replace(
        hour=hh).astimezone(timezone.utc)


def to_ist_hour(instant: datetime) -> datetime:
    """Any instant, floored to the start of its IST hour, in UTC."""
    local = instant.astimezone(IST)
    return local.replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def write(kind: str, rows: list[dict], lo: date, hi: date) -> int:
    """Clear this writer's columns for the window, then insert its rows.

    execute_batch, not a cur.execute per row: a day of sessions is ~4,500
    (hour, page) pairs, and 4,500 round trips on one pooled connection is
    long enough that Supabase's pooler drops it mid-insert ("SSL SYSCALL
    error: Can't assign requested address"), which is how the 2026-11-26
    backfill died. Batching sends them a page at a time and keeps the
    whole write inside one transaction, so a failure leaves the previous
    run's figures rather than a half-cleared window.
    """
    from psycopg2.extras import execute_batch  # noqa: PLC0415

    with connect(autocommit=False, statement_timeout="600s") as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE hourly_landing_tracker SET {CLEAR[kind]} "
            "WHERE hour >= %(from_ts)s AND hour < %(to_ts)s",
            {"from_ts": ist_hour_utc(lo, 0),
             "to_ts": ist_hour_utc(hi + timedelta(days=1), 0)})
        execute_batch(cur, UPSERT[kind], rows, page_size=500)
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------- sessions
async def fetch_sessions(client, store, day: date) -> list[dict]:
    """Traffic per landing page per hour, straight from ShopifyQL.

    ShopifyQL has no cursor here, so the limit is set far above a day's
    distinct (hour, page) pairs and the row count is checked against it:
    silently returning the first 1,000 of 5,000 pages would understate
    every total on the dashboard with nothing to show for it.
    """
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    LIMIT = 100_000
    q = ("FROM sessions SHOW sessions, online_store_visitors, "
         "sessions_with_cart_additions, sessions_that_reached_checkout, bounces "
         f"SINCE {day.isoformat()} UNTIL {day.isoformat()} "
         f"GROUP BY hour, landing_page_path, utm_source ORDER BY hour LIMIT {LIMIT}")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"sessions parseErrors: {resp['parseErrors']}")
    raw = (resp.get("tableData") or {}).get("rows", [])
    if len(raw) >= LIMIT:
        raise RuntimeError(f"{day}: ShopifyQL returned {len(raw)} session rows, at the "
                           f"limit of {LIMIT} -- the day is being truncated")

    # Several raw paths collapse onto one key (/collections/x/products/y
    # and /products/y are the same page), so sum rather than assign.
    acc: dict[tuple[datetime, str, str], dict] = defaultdict(
        lambda: dict(sessions=0, visitors=0, bounces=0, cart_additions=0,
                     reached_checkout=0))
    for row in raw:
        path = page_path(row.get("landing_page_path") or "")
        if not path:
            continue
        hour = to_ist_hour(datetime.fromisoformat(row["hour"].replace("Z", "+00:00")))
        b = acc[(hour, path, norm_source(row.get("utm_source")))]
        b["sessions"] += int(float(row.get("sessions") or 0))
        b["visitors"] += int(float(row.get("online_store_visitors") or 0))
        b["bounces"] += int(float(row.get("bounces") or 0))
        b["cart_additions"] += int(float(row.get("sessions_with_cart_additions") or 0))
        b["reached_checkout"] += int(float(row.get("sessions_that_reached_checkout") or 0))
    return [{"hour": h, "path": p, "source": src, **v}
            for (h, p, src), v in acc.items()]


async def fetch_store_totals(client, store, lo: date, hi: date) -> list[dict]:
    """The store's own daily sales, from Shopify's `sales` dataset.

    gross_sales is before discounts and returns; total_sales is what
    Shopify admin shows as the headline. Both are kept because they
    differ by a third on a discount-heavy day and people quote each as
    "total sales".
    """
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    q = ("FROM sales SHOW gross_sales, net_sales, total_sales, orders "
         f"SINCE {lo.isoformat()} UNTIL {hi.isoformat()} GROUP BY day ORDER BY day")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"sales parseErrors: {resp['parseErrors']}")
    out = []
    for row in (resp.get("tableData") or {}).get("rows", []):
        out.append({"day": date.fromisoformat(row["day"][:10]),
                    "gross": float(row.get("gross_sales") or 0),
                    "net": float(row.get("net_sales") or 0),
                    "total": float(row.get("total_sales") or 0),
                    "orders": int(float(row.get("orders") or 0))})
    return out


# ------------------------------------------------------------------ orders
#: utm_content carries the Meta ad id -- but only sometimes. It is frozen
#: at click time, so for some ads it holds the ad NAME instead. Only a
#: plain 10-20 digit string is an id; anything else is left alone rather
#: than guessed at (scripts/refresh_ad_token_resolution.py is the
#: resolver for the named ones).
AD_ID_RE = re.compile(r"^[0-9]{10,20}$")


async def fetch_orders(client, store, day: date
                       ) -> tuple[list[dict], dict, dict[tuple[str, str], int]]:
    """Orders per landing page per hour, live, keyed on the order's own URL.

    Also returns the (ad_id, page) -> order count mix, which the META
    pass uses to put each ad's spend on the pages its own orders landed
    on. 76% of live orders carry both a numeric utm_content and a
    full_url, measured 2026-11-27.
    """
    from fetch_hourly_tracker import ORDERS_HOURLY_QUERY, is_excluded_order  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    lo = datetime.combine(day, datetime.min.time(), IST)
    hi = lo + timedelta(days=1)
    q = f"created_at:>='{lo.isoformat()}' created_at:<'{hi.isoformat()}'"

    acc: dict[tuple[datetime, str, str], dict] = defaultdict(
        lambda: dict(orders=0, revenue=0.0, new_orders=0, new_sales=0.0,
                     rep_orders=0, rep_sales=0.0))
    stats = dict(seen=0, excluded=0, no_url=0, placed=0, lost_revenue=0.0,
                 with_ad_id=0)
    mix: dict[tuple[str, str], int] = defaultdict(int)
    after = None
    while True:
        data = await graphql_request(client, store, ORDERS_HOURLY_QUERY,
                                     {"first": 250, "after": after, "query": q})
        orders = data["orders"]
        for edge in orders["edges"]:
            n = edge["node"]
            stats["seen"] += 1
            if is_excluded_order(n.get("cancelledAt"), n.get("tags")):
                stats["excluded"] += 1
                continue
            amount = float(((n.get("totalPriceSet") or {}).get("shopMoney") or {})
                           .get("amount") or 0)
            attrs = {a["key"]: a["value"] for a in (n.get("customAttributes") or [])}
            path = page_path(attrs.get("full_url") or "")
            if not path:
                # The storefront recorded no landing URL -- a direct
                # checkout, an app order, an older theme. Counted and
                # reported rather than dropped quietly: it is exactly the
                # gap between this table and the store's own total.
                stats["no_url"] += 1
                stats["lost_revenue"] += amount
                continue
            created = datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00"))
            # numberOfOrders counts the customer's orders INCLUDING this
            # one, so 1 means it is their first -- the same test the
            # campaign tracker makes. A guest checkout has no customer
            # and cannot be shown to be repeat, so it counts as new.
            nord = (n.get("customer") or {}).get("numberOfOrders")
            is_new = (int(nord) <= 1) if str(nord or "").isdigit() else True
            b = acc[(to_ist_hour(created), path, norm_source(attrs.get("utm_source")))]
            b["orders"] += 1
            b["revenue"] += amount
            if is_new:
                b["new_orders"] += 1
                b["new_sales"] += amount
            else:
                b["rep_orders"] += 1
                b["rep_sales"] += amount
            stats["placed"] += 1

            ad_id = (attrs.get("utm_content") or "").strip()
            if AD_ID_RE.match(ad_id):
                mix[(ad_id, path)] += 1
                stats["with_ad_id"] += 1
        if not orders["pageInfo"]["hasNextPage"]:
            break
        after = orders["pageInfo"]["endCursor"]

    rows = [{"hour": h, "path": p, "source": src,
             **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in b.items()}}
            for (h, p, src), b in acc.items()]
    return rows, stats, dict(mix)


MIX_UPSERT = """
INSERT INTO landing_ad_order_mix AS t (day, ad_id, landing_page_path, orders,
                                       refreshed_at)
VALUES (%(day)s, %(ad_id)s, %(path)s, %(orders)s, now())
ON CONFLICT (day, ad_id, landing_page_path) DO UPDATE SET
    orders = EXCLUDED.orders, refreshed_at = EXCLUDED.refreshed_at
"""


def write_mix(day: date, mix: dict[tuple[str, str], int]) -> int:
    """Replace the day's ad -> page order mix."""
    from psycopg2.extras import execute_batch  # noqa: PLC0415

    rows = [{"day": day, "ad_id": a, "path": p, "orders": n}
            for (a, p), n in mix.items()]
    with connect(autocommit=False, statement_timeout="600s") as conn, \
            conn.cursor() as cur:
        cur.execute("DELETE FROM landing_ad_order_mix WHERE day = %s", (day,))
        execute_batch(cur, MIX_UPSERT, rows, page_size=500)
        conn.commit()
    return len(rows)


def _shares(counts: dict[str, int]) -> dict[str, float]:
    """Order counts -> fractions of that ad's orders, summing to 1.

    Kept separate because this is the arithmetic that decides whether an
    ad's spend is conserved when it is split over several pages.
    """
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {path: n / total for path, n in counts.items()}


def load_ad_mix(day: date) -> dict[str, dict[str, float]]:
    """ad_id -> {page: share of that ad's orders}, for one day.

    Shares, not counts, so an ad's spend is split across the pages its
    orders landed on and the total still equals the ad's spend. The mix
    is the whole day's, applied to every hour: an ad rarely takes enough
    orders in a single hour for an hourly mix to mean anything.
    """
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT ad_id, landing_page_path, orders "
                    "  FROM landing_ad_order_mix WHERE day = %s AND orders > 0",
                    (day,))
        for ad_id, path, n in cur.fetchall():
            counts[ad_id][path] = int(n)
    return {ad_id: _shares(c) for ad_id, c in counts.items()}


# -------------------------------------------------------------------- meta
def load_ad_paths() -> dict[str, str]:
    """ad_id -> landing page path, from the tables that already hold it.

    ad_media first (scripts/backfill_ad_landing_urls.py and
    scripts/import_landing_urls_csv.py keep it current), then
    ad_landing_map for ads the nightly has not ingested yet, then
    landing_page_ad_breakdown_30d for anything it missed.

    Not resolved from the creatives here: that means scanning every
    adcreative row in raw_dump_meta, which the Supabase pooler kills
    mid-query, and both tables are built from those same creatives.

    An ad with no readable URL is reported as unattributed spend rather
    than spread over the pages that did resolve. The Ads Manager export
    is the fix for those -- see scripts/import_landing_urls_csv.py.
    """
    out: dict[str, str] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT ad_id, landing_page_url FROM ad_media "
                    " WHERE landing_page_url IS NOT NULL")
        for ad_id, url in cur.fetchall():
            p = page_path(url)
            if ad_id and p:
                out[ad_id] = p
        # Ads the nightly has not ingested yet are in neither table
        # above or below, only in the export.
        cur.execute("SELECT ad_id, landing_page_url FROM ad_landing_map")
        for ad_id, url in cur.fetchall():
            p = page_path(url)
            if ad_id and p:
                out.setdefault(ad_id, p)
        cur.execute("SELECT ad_id, landing_page_path FROM landing_page_ad_breakdown_30d "
                    " WHERE landing_page_path IS NOT NULL")
        for ad_id, raw in cur.fetchall():
            p = page_path(raw)
            if ad_id and p:
                out.setdefault(ad_id, p)
    return out


def ncp_action_types() -> set[str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(NCP_IDS_SQL)
        return {f"offsite_conversion.custom.{r[0]}" for r in cur.fetchall() if r[0]}


def _first(actions, order: tuple[str, ...]) -> float:
    """First matching action type wins -- omni_purchase already contains
    web + app + offline, so adding `purchase` to it double-counts."""
    for want in order:
        for a in actions or []:
            if a.get("action_type") == want:
                return float(a.get("value") or 0)
    return 0.0


async def meta_get(client, url, params, attempt: int = 0):
    """Graph GET that survives Meta's "service temporarily unavailable".

    Code 2 / subcode 1504044 is Meta shedding load on a heavy query. It
    arrives as a 400 with is_transient FALSE, so the shared
    _get_with_retry treats it as fatal and the whole run dies -- which on
    an hourly job means an hour with no spend at all. It is in fact
    transient: the identical request succeeds seconds later.
    """
    from ingest_last_15_days import _get_with_retry  # noqa: PLC0415

    try:
        return await _get_with_retry(client, url, params)
    except RuntimeError as exc:
        if "1504044" not in str(exc) or attempt >= 4:
            raise
        await asyncio.sleep(2 ** attempt * 3)
        return await meta_get(client, url, params, attempt + 1)


async def fetch_meta_day(client, day: date, ad_paths: dict[str, str],
                         ncp_types: set[str],
                         ad_mix: dict[str, dict[str, float]],
                         ) -> tuple[list[dict], float, float]:
    from ingest_last_15_days import _discover_accounts  # noqa: PLC0415

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ACCESS_TOKEN is not set")
    base = f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}"
    acc: dict[tuple[datetime, str], dict] = defaultdict(
        lambda: dict(spend=0.0, order_spend=0.0, impressions=0, conv_value=0.0,
                     purchases=0.0, ncp=0.0))
    unmapped = unplaced = 0.0

    for account in _discover_accounts().values():
        url = f"{base}/act_{account.account_id}/insights"
        params = {
            "access_token": token, "level": "ad",
            "fields": "ad_id,spend,impressions,actions,action_values",
            "time_range": json.dumps({"since": day.isoformat(), "until": day.isoformat()}),
            "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
            # 500 makes Meta answer code 2 part-way through an
            # account-day: ad x hour x actions is too much for one page.
            # 200 pages cleanly at ~40 requests per account-day.
            "limit": 200,
        }
        while True:
            body = await meta_get(client, url, params)
            if "error" in body:
                raise RuntimeError(f"{account.name}: {body['error'].get('message')}")
            for row in body.get("data", []):
                label = row.get("hourly_stats_aggregated_by_advertiser_time_zone", "")
                if not label:
                    continue
                spend = float(row.get("spend") or 0)
                ad_id = row.get("ad_id") or ""
                # Already the advertiser's timezone, which is the store's.
                hour = ist_hour_utc(day, int(label.split(":", 1)[0]))

                # (a) the page the ad POINTS AT, from its creative.
                path = ad_paths.get(ad_id)
                if path:
                    b = acc[(hour, path)]
                    b["spend"] += spend
                    b["impressions"] += int(float(row.get("impressions") or 0))
                    b["conv_value"] += _first(row.get("action_values"),
                                              ("omni_purchase", "purchase"))
                    b["purchases"] += _first(row.get("actions"),
                                             ("omni_purchase", "purchase"))
                    b["ncp"] += sum(float(a.get("value") or 0)
                                    for a in (row.get("actions") or [])
                                    if a.get("action_type") in ncp_types)
                else:
                    unmapped += spend

                # (b) the pages the ad's own ORDERS landed on, by share.
                mix = ad_mix.get(ad_id)
                if mix:
                    for page, share in mix.items():
                        acc[(hour, page)]["order_spend"] += spend * share
                else:
                    unplaced += spend
            nxt = (body.get("paging") or {}).get("next")
            if not nxt:
                break
            url, params = nxt, None

    rows = [{"hour": h, "path": p, "spend": round(b["spend"], 2),
             "order_spend": round(b["order_spend"], 2),
             "impressions": b["impressions"], "conv_value": round(b["conv_value"], 2),
             "purchases": b["purchases"], "ncp": b["ncp"]}
            for (h, p), b in acc.items()]
    return rows, unmapped, unplaced


# -------------------------------------------------------------------- main
async def run(days: list[date], only: set[str]) -> None:
    from shopify_client import discover_stores  # noqa: PLC0415

    lo, hi = days[0], days[-1]
    store = list(discover_stores().values())[0]

    async with httpx.AsyncClient(timeout=300) as client:
        if "sessions" in only:
            rows: list[dict] = []
            for day in days:
                rows += await fetch_sessions(client, store, day)
            print(f"  sessions: {write('sessions', rows, lo, hi):,} (hour, page) rows")

        if "store" in only:
            rows = await fetch_store_totals(client, store, lo, hi)
            with connect(autocommit=False, statement_timeout="600s") as conn, \
                    conn.cursor() as cur:
                for r in rows:
                    cur.execute(STORE_UPSERT, r)
                conn.commit()
            tot = sum(r["total"] for r in rows)
            gro = sum(r["gross"] for r in rows)
            print(f"  store:    {len(rows)} day(s) | total sales {tot:,.0f} "
                  f"| gross {gro:,.0f} | {sum(r['orders'] for r in rows):,} orders")

        if "orders" in only:
            rows, total = [], dict(seen=0, excluded=0, no_url=0, placed=0,
                                   lost_revenue=0.0)
            total["with_ad_id"] = 0
            mixed = 0
            for day in days:
                r, st, mix = await fetch_orders(client, store, day)
                rows += r
                for k in total:
                    total[k] += st[k]
                mixed += write_mix(day, mix)
            print(f"  orders:   {write('orders', rows, lo, hi):,} (hour, page) rows "
                  f"| {total['placed']:,} of {total['seen']:,} orders placed "
                  f"({total['excluded']:,} excluded, {total['no_url']:,} with no landing "
                  f"URL worth Rs {total['lost_revenue']:,.0f})")
            print(f"            {total['with_ad_id']:,} orders carry a Meta ad id "
                  f"-> {mixed:,} (ad, page) pairs for spend allocation")

        if "meta" in only:
            ad_paths, ncp_types = load_ad_paths(), ncp_action_types()
            print(f"  {len(ad_paths):,} ads carry a readable landing URL; "
                  f"{len(ncp_types)} NCP custom conversion(s)")
            rows, unmapped, unplaced = [], 0.0, 0.0
            for day in days:
                ad_mix = load_ad_mix(day)
                r, u, n = await fetch_meta_day(client, day, ad_paths, ncp_types,
                                               ad_mix)
                rows += r
                unmapped += u
                unplaced += n
            print(f"  meta:     {write('meta', rows, lo, hi):,} (hour, page) rows")
            print(f"            by creative URL: Rs {unmapped:,.0f} unplaced "
                  f"(ad has no readable landing URL)")
            print(f"            by order:        Rs {unplaced:,.0f} unplaced "
                  f"(ad earned no order with a usable URL)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=1,
                    help="how many days back from today, inclusive (default 1)")
    ap.add_argument("--from", dest="from_day", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="to_day", help="YYYY-MM-DD")
    ap.add_argument("--only", default="store,sessions,orders,meta",
                    help="comma-separated subset of store,sessions,orders,meta")
    args = ap.parse_args()

    if args.from_day or args.to_day:
        lo = date.fromisoformat(args.from_day or args.to_day)
        hi = date.fromisoformat(args.to_day or args.from_day)
    else:
        hi = datetime.now(IST).date()
        lo = hi - timedelta(days=args.days - 1)
    days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    bad = only - {"store", "sessions", "orders", "meta"}
    if bad:
        raise SystemExit(f"--only: unknown source(s) {', '.join(sorted(bad))}")

    print(f"hourly_landing_tracker: {lo} .. {hi} ({len(days)} day(s)) "
          f"| sources: {', '.join(sorted(only))}")

    with connect(autocommit=False, statement_timeout="600s") as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(MIGRATE)
        cur.execute(MIGRATE_KEY)
        conn.commit()

    asyncio.run(run(days, only))

    with connect(autocommit=False, statement_timeout="600s") as conn, conn.cursor() as cur:
        bounds = {"from_ts": ist_hour_utc(lo, 0),
                  "to_ts": ist_hour_utc(hi + timedelta(days=1), 0)}
        cur.execute(DELETE_EMPTY, bounds)
        gone = cur.rowcount
        conn.commit()
        cur.execute(
            "SELECT COUNT(*), COUNT(DISTINCT landing_page_path), COALESCE(SUM(sessions),0), "
            "       COALESCE(SUM(orders),0), COALESCE(SUM(revenue),0), "
            "       COALESCE(SUM(meta_spend),0) "
            "  FROM hourly_landing_tracker WHERE hour >= %(from_ts)s AND hour < %(to_ts)s",
            bounds)
        rows, pages, sess, orders, rev, spend = cur.fetchone()
    print(f"  dropped {gone:,} empty rows")
    print(f"  window: {rows:,} rows across {pages:,} pages | {sess:,} sessions "
          f"| {orders:,} orders | revenue {rev:,.0f} | spend {spend:,.0f}")


if __name__ == "__main__":
    main()
