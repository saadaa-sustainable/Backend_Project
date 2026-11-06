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
    -- Shopify's own quantity_ordered for the hour. NOT pnl_qty: that
    -- one is counted from the orders and drops the gift coin, so the
    -- two legitimately differ and neither is a correction of the
    -- other.
    qty_ordered             integer,
    -- Shopify's OWN first-time/returning split, kept apart from the
    -- tracker's new_customers (derived from each order's lifetime
    -- count). The two use different bases and will not agree; neither
    -- is a correction of the other.
    --
    -- The rate and the average order value are NOT stored: both are
    -- ratios, and a stored ratio cannot be re-divided when hours are
    -- summed. They are computed on read from these counts.
    ql_orders               integer,
    ql_net_sales            numeric,
    ql_customers            integer,
    ql_new_customers        integer,
    ql_returning_customers  integer,
    ql_sales_returning      numeric,
    ql_sales_first_time     numeric,
    -- Basket-size mix for the hour: an object keyed by
    -- number_of_products_bought_together, each holding qty, orders and
    -- sales. Stored whole rather than as columns because the set of
    -- basket sizes is open-ended -- a single eight-item order creates
    -- a bucket that did not exist yesterday.
    basket_mix              jsonb,
    -- Shopify's own Total sales for the hour, stored verbatim so the
    -- headline can EQUAL what the Shopify admin shows rather than
    -- approach it. Gross, less discounts, less returns, plus shipping
    -- and tax.
    --
    -- Returns here are dated by the day the REFUND was issued, not the
    -- day the order was placed, so an hour can be pulled down by a
    -- refund on a much older order. That is Shopify's convention and
    -- the price of matching it exactly.
    shopify_total_sales     numeric,
    -- Negative, as ShopifyQL reports it.
    shopify_returns         numeric,
    revenue_meta            numeric,
    revenue_google          numeric,
    revenue_paid            numeric,
    orders_meta             integer,
    -- Order counts on the same denominators as the session buckets, so
    -- a conversion rate can be taken per channel. orders_paid is every
    -- order carrying a utm_source that is not direct/none; the two sum
    -- to `orders`.
    orders_paid             integer,
    orders_direct           integer,
    -- Orders the hour produced that this tracker does NOT count:
    -- cancelled, or returned without an exchange. Stored rather than
    -- silently dropped, because "where did the gap come from" is the
    -- first question when this row stops matching Shopify's own admin.
    orders_excluded         integer,
    revenue_excluded        numeric,

    -- The P&L basis, which is NOT the revenue basis above.
    --
    -- It drops orders tagged `inf` (the daily-report / influencer
    -- orders) and `Return_Prime`, and it KEEPS cancelled orders, which
    -- are then counted separately below and deducted on their own line.
    -- Keeping them is what lets the statement show the deduction
    -- instead of a number that has already quietly had it taken out.
    pnl_sales               numeric,
    pnl_orders              integer,
    -- Units sold, with the Saadaa Silver Coin taken out: it is a gift
    -- line, not an item sold, and counting it would deflate ASP.
    pnl_qty                 integer,
    -- Cancellations WITHIN the P&L population, measured rather than
    -- assumed. These are a subset of pnl_sales/pnl_orders above, not a
    -- separate population: the statement shows total sales and then
    -- deducts these to reach net sales, so counting them in both
    -- places is the point.
    --
    -- A cancellation is dated by the order's own hour, not by the hour
    -- it was cancelled in -- an order placed at 10:00 and cancelled at
    -- 16:00 belongs to 10:00 in every other figure on the row, and
    -- splitting it would stop the hours summing to the day.
    pnl_cancelled_orders    integer,
    pnl_cancelled_sales     numeric,
    -- Units on those orders, so ASP can divide a net numerator by a net
    -- denominator. Without this the sales figure would have the
    -- cancellations taken out while the unit count still carried them,
    -- which understates ASP by exactly the cancelled share.
    pnl_cancelled_qty       integer,
    -- Money refunded on orders this day PLACED, counted only on orders
    -- that were not cancelled -- a cancelled order is already deducted
    -- at its full price above, so adding its refund would deduct it
    -- twice.
    --
    -- This is NOT Shopify's `returns` figure and cannot be made to
    -- match it. ShopifyQL counts refunds by the day they were ISSUED,
    -- against an order from any day; this counts them against the day
    -- the order was placed. An hourly campaign tracker has to do the
    -- latter -- otherwise a refund on a three-week-old order makes this
    -- afternoon's hour look bad.
    pnl_refunds             numeric,
    -- How much of the CANCELLED value Shopify has already refunded.
    --
    -- This exists because Shopify's Total sales removes a cancellation
    -- only when it was refunded. A COD order cancelled before payment
    -- produces no refund, so it stays inside Total sales -- money that
    -- will never arrive. The P&L deducts exactly the unrefunded part:
    --   pnl_cancelled_sales - pnl_cancelled_refunded
    -- Deducting the whole cancelled value instead would double-count
    -- the part Shopify had already taken out.
    pnl_cancelled_refunded  numeric,
    -- Orders CONTAINING a coin, and the number of COINS in them.
    -- They are not the same: an order can ship more than one, so
    -- costing per order undercharges. silver_coin_qty is what the
    -- cost should be taken on.
    silver_coin_orders      integer,
    silver_coin_qty         integer,
    -- The dispatch desk's breakdown of the SAME coin population.
    -- Payment and fulfilment are read at INGEST time and both move
    -- afterwards -- a COD order becomes paid on delivery, an
    -- unfulfilled one ships -- so a past day holds the state as it was
    -- when that day was last ingested, not as it is now. Re-ingest the
    -- window to refresh them.
    coin_only_orders        integer,
    coin_shipped_orders     integer,
    -- The dispatch buckets, so the KPI strip does not have to read
    -- every order row to count them.
    coin_ship_now_orders    integer,
    coin_call_list_orders   integer,
    coin_address_bad_orders integer,
    coin_prepaid_orders     integer,
    coin_partial_orders     integer,
    coin_cod_orders         integer,
    -- Orders that look eligible for the offer but went out WITHOUT a
    -- coin: two or more product units and no coin line. Outside the
    -- coin counts entirely, which is why it is not a split of them.
    bundle_no_coin_orders   integer,
    new_customers           integer,
    new_customer_revenue    numeric,

    -- Spend. Meta is real and genuinely hourly. The other two are a
    -- DAILY total shared out across the hours, and neither pretends
    -- otherwise: google_spend_as_of carries the moment its daily total
    -- was captured, so a partial day can be seen rather than guessed at.
    meta_spend              numeric,
    meta_impressions        bigint,
    kwikchat_spend          numeric,
    google_spend            numeric,
    google_spend_as_of      timestamptz,

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
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS orders_paid integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS orders_direct integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS orders_excluded integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS revenue_excluded numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS google_spend numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS google_spend_as_of timestamptz",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_sales numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_qty integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS silver_coin_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS silver_coin_qty integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS bundle_no_coin_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_cod_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_partial_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_prepaid_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_shipped_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_only_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_address_bad_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_call_list_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS coin_ship_now_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_cancelled_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_cancelled_sales numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_cancelled_qty integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_refunds numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS shopify_total_sales numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS shopify_returns numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS qty_ordered integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS basket_mix jsonb",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_orders integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_net_sales numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_customers integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_new_customers integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_returning_customers integer",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_sales_returning numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS ql_sales_first_time numeric",
    f"ALTER TABLE IF EXISTS {TABLE} ADD COLUMN IF NOT EXISTS pnl_cancelled_refunded numeric",
]

COLUMNS = [
    "hour", "day_ist", "hour_of_day",
    "sessions", "sessions_paid", "sessions_direct", "sessions_meta", "sessions_google",
    "sessions_by_source",
    "revenue", "orders", "revenue_shopifyql",
    "shopify_total_sales", "shopify_returns", "qty_ordered", "basket_mix",
    "ql_orders", "ql_net_sales", "ql_customers", "ql_new_customers", "ql_returning_customers",
    "ql_sales_returning", "ql_sales_first_time",
    "revenue_meta", "revenue_google",
    "revenue_paid", "orders_meta", "orders_paid", "orders_direct",
    "orders_excluded", "revenue_excluded",
    "pnl_sales", "pnl_orders", "pnl_qty", "silver_coin_orders", "silver_coin_qty",
    "coin_only_orders", "coin_shipped_orders", "coin_ship_now_orders",
    "coin_call_list_orders", "coin_address_bad_orders", "coin_prepaid_orders",
    "coin_partial_orders", "coin_cod_orders", "bundle_no_coin_orders",
    "pnl_cancelled_orders", "pnl_cancelled_sales", "pnl_cancelled_qty",
    "pnl_refunds", "pnl_cancelled_refunded",
    "new_customers", "new_customer_revenue",
    "meta_spend", "meta_impressions", "kwikchat_spend",
    "google_spend", "google_spend_as_of",
    "ga4_sessions", "ga4_revenue", "ga4_active_users",
]

#: Columns a FAILED fetch must not erase.
#:
#: The GA4 read needs a service-account credential the CI job does not
#: have ("GOOGLE_CREDS_JSON not set -- GA4 columns will be null"), so
#: there it raises, returns nothing, and these arrive NULL. With a
#: plain `c = EXCLUDED.c` that NULL was written straight over figures a
#: local run had just put in, every hour, on the hour. A hand-filled
#: day survived fourteen minutes.
#:
#: NULL from this fetch means "could not read", never "genuinely none":
#: an hour GA4 really reports nothing for is written as 0, and a zero
#: still overwrites.
#:
#: NOT the Google spend columns. Those are legitimately NULL for the
#: hours after the daily export, and the allocation is recomputed on
#: every run, so preserving an old value there would freeze a share
#: that is no longer correct.
_KEEP_IF_NULL = {"ga4_sessions", "ga4_revenue", "ga4_active_users"}

#: Unqualified: inside ON CONFLICT DO UPDATE the target is referenced
#: by its bare table name, never schema-qualified.
_TARGET = TABLE.split(".")[-1]

UPSERT = f"""
INSERT INTO {TABLE} ({", ".join(COLUMNS)})
VALUES %s
ON CONFLICT (hour) DO UPDATE SET
  {", ".join(
      f"{c} = COALESCE(EXCLUDED.{c}, {_TARGET}.{c})" if c in _KEEP_IF_NULL
      else f"{c} = EXCLUDED.{c}"
      for c in COLUMNS if c != "hour")},
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


def is_excluded_order(cancelled_at: str | None, tags: list[str] | None) -> bool:
    """Orders this tracker does not count as revenue.

    Cancelled, returned, or carrying `Return_Prime`. An EXCHANGE is
    kept: the customer swapped for something of equal value, so the
    money stayed. An order tagged both Return and Exchange is the
    exchange leg of a swap, not a refund, and is kept for the same
    reason.

    `Return_Prime` marks a return flowing back through the returns
    platform, so it is not a sale and does not belong in revenue. It is
    dropped UNCONDITIONALLY -- an Exchange tag does not rescue it, the
    way it rescues a plain `Return`, because the tag means the order
    itself is the return leg rather than an order that was later
    returned.

    These orders are overwhelmingly worth ZERO, so dropping them barely
    moves revenue but removes of the order of a hundred orders a day
    from the count -- which lifts AOV and lowers conversion rate. That
    is the point: a return flowing backwards was never an order this
    campaign hour won.

    `inf` is deliberately NOT excluded here, though the P&L drops it.
    The P&L asks what the day earned, and goods that went out with no
    sale behind them did not earn anything; the tracker asks what the
    hour produced, and a report order is still something the hour
    produced.

    This deliberately differs from the daily dashboard, which drops
    exchanges too. The tracker answers "what did this campaign hour
    bring in"; the dashboard answers "what did we end up keeping".

    Return Prime processes returns OUTSIDE Shopify's native returns
    API, so `returnStatus` stays NO_RETURN on genuinely returned
    orders. The tags are the only signal there is.
    """
    if cancelled_at:
        return True
    t = {str(x).strip().lower() for x in (tags or [])}
    if "return_prime" in t:
        return True
    return "return" in t and "exchange" not in t


#: The gift coin, identified by SKU rather than title: the title
#: carries an emoji that moves around ("Saadaa Silver Coin\U0001F381",
#: "\U0001F381 Saadaa Silver Coin", and one with a stray space), so
#: matching on it would miss orders. The SKU is stable.
SILVER_COIN_SKU = "SDSILVER"

#: Orders the P&L does not count. `inf` marks the daily-report and
#: influencer orders -- goods that went out without a sale behind them
#: -- and `Return_Prime` marks a return flowing back through the returns
#: partner. Neither belongs in a contribution margin.
#:
#: Matched case-insensitively, because these are typed by hand: the
#: warehouse holds `inf`, `influencer-order` and `Return_Prime`, and a
#: capitalisation that drifts should not quietly re-admit an order.
PNL_EXCLUDED_TAGS = {"inf", "influencer-order", "return_prime"}


def is_pnl_excluded(tags: list[str] | None) -> bool:
    """Out of the P&L basis -- which is NOT the revenue basis.

    Cancelled orders stay IN. Cancellation is modelled as a rate in the
    P&L, so dropping them here as well would deduct it twice.
    """
    return bool(PNL_EXCLUDED_TAGS & {str(t).strip().lower() for t in (tags or [])})


#: The silver coin went live on Shopify at this instant. Orders before
#: it carry the SAME SKU but belong to the earlier "Saadaa Sagun"
#: offer, so counting them would merge two promotions into one figure.
COIN_CAMPAIGN_START = datetime(2026, 10, 30, 2, 37, tzinfo=IST)

#: Internal accounts. Orders from these are staff and supplier tests,
#: not customers who were given a coin.
COIN_INTERNAL_DOMAINS = ("@saadaa.in", "@robylon.ai")


def is_coin_excluded(order: dict, created: datetime) -> str | None:
    """Why this order is NOT a silver-coin order, or None if it counts.

    DELIBERATELY STRICTER THAN THE P&L BASIS, and the two must not be
    merged. The P&L keeps cancelled orders in and models cancellation
    as a rate, because it is asking what the day earned. This is asking
    HOW MANY COINS WE ARE LIABLE FOR, and a cancelled or refunded order
    never shipped one.

    The rules are the dispatch desk's, so the dashboard and the desk
    agree on what a coin order is. Returns a reason rather than a bool
    so a surprising total can be explained without re-running anything.
    """
    if created < COIN_CAMPAIGN_START:
        return "before the campaign"
    if order.get("cancelledAt"):
        return "cancelled"
    refunded = float((order.get("totalRefundedSet") or {})
                     .get("shopMoney", {}).get("amount") or 0)
    if refunded > 0:
        return "refunded"
    tags = {str(t).strip().lower() for t in (order.get("tags") or [])}
    if "test order" in tags:
        return "test order"
    email = (order.get("email") or "").strip().lower()
    if email.endswith(COIN_INTERNAL_DOMAINS):
        return "internal account"
    return None


COIN_TABLE = "public.silver_coin_order"

#: One row per silver-coin ORDER, which the hourly table cannot hold:
#: it stores counts per hour, and a list needs the orders themselves.
#: Keyed on the Shopify order id so a re-ingest CORRECTS a row rather
#: than duplicating it -- payment and fulfilment both move after the
#: order is placed, and keeping them current is the whole reason to
#: re-ingest a past day.
COIN_DDL = f"""
CREATE TABLE IF NOT EXISTS {COIN_TABLE} (
    order_id        text PRIMARY KEY,
    order_name      text,
    created_at      timestamptz NOT NULL,
    day_ist         date NOT NULL,
    coins           integer NOT NULL,
    units           integer NOT NULL,
    amount          numeric,
    payment         text,
    fulfillment     text,
    -- GoKwik scores COD checkouts only, so a blank here on a COD
    -- order means NEVER SCORED, which is not the same as low risk.
    risk_tag        text,
    customer_orders integer,
    is_returning    boolean,
    city            text,
    state           text,
    pincode         text,
    -- The desk's tables are worked from, not just read: a caller
    -- needs the name and number in front of them, and an address
    -- cannot be fixed without seeing what is wrong with it.
    customer_name   text,
    phone           text,
    address1        text,
    address2        text,
    channel         text,
    item_count      integer,
    -- "Pick Any 3 Men Airy Linen Short Kurtas" and the like, so the
    -- Bundle tab can say WHICH bundle went out without a coin.
    bundles         text,
    coin_only       boolean,
    -- Exactly one of: shipped, coin_only, address_bad, call_list,
    -- ship_now. The reason is stored beside it so a held order can be
    -- explained to the person who has to act on it.
    bucket          text,
    bucket_reason   text,
    -- Semicolon-joined keys, because an order can trip SEVERAL rules
    -- and the desk shows them all as separate pills. Storing only the
    -- first would make "why is this on the call list" unanswerable.
    call_reasons    text,
    address_issues  text,
    -- An OVERLAY, not a bucket: a watchlisted order still sits in
    -- Ship now or the Call list and still has to be dispatched or
    -- called. This only says it is worth a second look.
    watchlist       text,
    -- "flag" means deliverable but worth knowing -- a shop or a
    -- hostel room. It never holds the order.
    address_flag    text,
    -- A COD the desk has already rung and confirmed, read from the
    -- order's `silver-cod-verified` tag at ingest. Kept as a column
    -- because the alternative -- matching that tag in shopify_orders
    -- at query time -- cannot use an index and costs a sequential
    -- scan of the whole order book.
    cod_verified    boolean,
    fetched_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_coin_order_created ON {COIN_TABLE} (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_coin_order_day ON {COIN_TABLE} (day_ist);
-- CREATE TABLE IF NOT EXISTS does nothing to a table that already
-- exists, so every column added after the first deploy needs its own
-- ALTER here or the insert fails on a warehouse built yesterday.
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS bucket text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS bucket_reason text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS address_flag text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS watchlist text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS address_issues text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS call_reasons text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS bundles text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS item_count integer;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS channel text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS address2 text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS address1 text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS customer_name text;
ALTER TABLE {COIN_TABLE} ADD COLUMN IF NOT EXISTS cod_verified boolean;
CREATE INDEX IF NOT EXISTS ix_coin_order_bucket ON {COIN_TABLE} (bucket);
"""

COIN_COLUMNS = ["order_id", "order_name", "created_at", "day_ist", "coins", "units",
                "amount", "payment", "fulfillment", "risk_tag", "customer_orders",
                "is_returning", "city", "state", "pincode", "coin_only",
                 "cod_verified",
                "bucket", "bucket_reason", "address_flag", "watchlist",
                "customer_name", "phone", "address1", "address2", "channel",
                "item_count", "bundles", "call_reasons", "address_issues"]

#: How far back to re-check fulfilment on every run.
#:
#: A coin row records the order's fulfilment at the hour it was PLACED
#: and the ingest never revisits that hour, so a parcel shipping days
#: later stayed "not yet fulfilled" for good. Measured against Shopify
#: before this was added, the dispatch strip had less than half the
#: orders that had actually gone out, and the error grew with order
#: age -- always understating dispatch and overstating the backlog.
#:
#: Twenty days is well past the point where orders stop moving, and the
#: join rides the orders table's primary key.
COIN_REFRESH_DAYS = 20

REFRESH_FULFILMENT = """
UPDATE public.silver_coin_order c
   SET fulfillment = 'FULFILLED',
       -- Shipped wins over every other bucket -- a parcel that has gone
       -- cannot be held for anything -- which is why promoting it here
       -- is enough and the rest of classify() need not be re-run.
       bucket = 'shipped'
  FROM public.shopify_orders o
 -- order_id, not name: it is the orders table's PRIMARY KEY, while
 -- `name` carries no index at all and joining on it costs a sequential
 -- scan of the whole order book.
 WHERE o.order_id = c.order_id
   AND c.day_ist >= (now() AT TIME ZONE 'Asia/Kolkata')::date - CAST(%(days)s AS int)
   -- PROMOTE ONLY. shopify_orders is a flattened MIRROR refreshed by a
   -- separate job, and it lags -- by fourteen hours when this was
   -- written. The coin row, by contrast, is filled from a live
   -- GraphQL read at ingest. Copying the mirror wholesale therefore
   -- overwrote fresh `Fulfilled` rows with the mirror's stale
   -- `UNFULFILLED`, leaving hundreds of rows a day whose bucket said
   -- shipped while their own fulfilment column denied it.
   --
   -- Taking only the transition to fulfilled makes this purely
   -- additive: it catches up the old orders the ingest never revisits
   -- and can never contradict a fresher read. Fulfilment is one-way in
   -- practice; a cancelled one is corrected by re-ingesting the day.
   AND o.fulfillment_status ILIKE 'fulfilled'
   AND c.fulfillment IS DISTINCT FROM 'FULFILLED'
"""


COIN_UPSERT = f"""
INSERT INTO {COIN_TABLE} ({", ".join(COIN_COLUMNS)}) VALUES %s
ON CONFLICT (order_id) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in COIN_COLUMNS if c != "order_id")},
  fetched_at = now()
"""

#: GoKwik writes exactly one of these onto a COD checkout.
RISK_TAGS = ("high risk", "medium risk", "low risk")


#: What each customer did BEFORE this campaign: how many parcels
#: actually arrived, and how many came back. Read from our own
#: warehouse rather than from Shopify, because Shopify's order
#: object carries no delivery outcome -- only the courier knows, and
#: that lands in shopify_fulfillments.
CUSTOMER_HISTORY_SQL = """
WITH prior AS (
    SELECT o.customer_id,
           o.name,
           COALESCE(f.orders_delivered, 0) > 0 AS delivered,
           (COALESCE(f.orders_delivered, 0) = 0
            -- tags is jsonb, so cast to text and match as a string: the
            -- tag vocabulary is not fixed and an exact-element test would
            -- miss "RTO-Delivered" and the like.
            AND (lower(COALESCE(o.tags::text, '')) LIKE '%%rto%%'
                 OR lower(COALESCE(o.return_status, '')) LIKE '%%return%%origin%%'))
               AS rto,
           o.fulfillment_status IS NOT NULL AS shipped,
           row_number() OVER (PARTITION BY o.customer_id
                              ORDER BY o.created_at DESC) AS rn
      FROM public.shopify_orders o
      LEFT JOIN public.shopify_fulfillments f ON f.order_name = o.name
     WHERE o.customer_id = ANY(%s)
       AND o.created_at < %s
       AND o.cancelled_at IS NULL
)
SELECT customer_id,
       count(*) FILTER (WHERE delivered) AS delivered,
       count(*) FILTER (WHERE shipped)   AS shipped,
       count(*) FILTER (WHERE rto)       AS rto
  FROM prior
 WHERE rn <= 10
 GROUP BY customer_id
"""


def fetch_customer_history(customer_ids: list[str]) -> dict[str, dict]:
    """Prior delivery and RTO counts, over each customer's last 10 orders."""
    if not customer_ids:
        return {}
    out: dict[str, dict] = {}
    # Chunked: the Supabase pooler drops an oversized statement, and a
    # busy day carries a few thousand distinct customers.
    with connect() as conn:
        for i in range(0, len(customer_ids), 1000):
            with conn.cursor() as cur:
                cur.execute(CUSTOMER_HISTORY_SQL,
                            (customer_ids[i:i + 1000], COIN_CAMPAIGN_START))
                for cid, delivered, shipped, rto in cur.fetchall():
                    out[cid] = {"delivered": delivered, "shipped": shipped, "rto": rto}
    return out


def risk_of(tags: list[str] | None) -> str | None:
    low = {str(t).strip().lower() for t in (tags or [])}
    for r in RISK_TAGS:
        if r in low:
            return r.split()[0].capitalize()
    return None


PAYMENT_LABEL = {"PAID": "Prepaid", "PARTIALLY_PAID": "Partial COD", "PENDING": "COD"}

#: Shopify names a multi-buy bundle in the line-item title. There is
#: no bundle FIELD to read, so the title is matched -- which is why
#: this is a list to extend rather than a regex to be clever with.
BUNDLE_WORDS = ("pick any", "combo", "bundle", "set of")


def bundle_titles(line_items: dict | None) -> list[str]:
    out = []
    for edge in ((line_items or {}).get("edges") or []):
        title = ((edge.get("node") or {}).get("title") or "").strip()
        if title and any(w in title.lower() for w in BUNDLE_WORDS):
            if title not in out:
                out.append(title)
    return out


def order_channel(order: dict) -> str | None:
    """Where the order came from.

    `channelInformation` is empty on most orders here -- it was set on
    about 3% of a day's coin orders -- so the APP that created the
    order is the usable answer: GoKwik's checkout, Draft Orders, the
    Online Store. Falls back to the channel definition where it does
    exist.
    """
    app = (order.get("app") or {}).get("name")
    if app:
        return app
    cd = (order.get("channelInformation") or {}).get("channelDefinition") or {}
    return cd.get("channelName") or cd.get("handle") or None


def count_units(line_items: dict | None) -> tuple[int, int]:
    """(units sold excluding the gift coin, HOW MANY coins it carried).

    The coin is a gift line, not an item sold. Leaving it in the unit
    count deflates ASP, and on 2,490 coins over a fortnight that is not
    a rounding error.

    The second value used to be a boolean. It is a COUNT because an
    order can ship more than one coin -- measured on 2026-11-01,
    2,465 orders carried 2,479 coins, fourteen of them two apiece and
    one order three. Costing them per ORDER undercharges every such
    order, and "how many coins have we given away" is unanswerable
    from a flag.
    """
    units, coins = 0, 0
    for edge in ((line_items or {}).get("edges") or []):
        node = edge.get("node") or {}
        qty = int(node.get("quantity") or 0)
        if (node.get("sku") or "").strip().upper() == SILVER_COIN_SKU:
            coins += qty
            continue
        units += qty
    return units, coins


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
    """Shopify's OWN sales figures per hour, straight from ShopifyQL.

    `shopify_total_sales` is the number Shopify's admin shows as Total
    sales: gross, less discounts, less returns, plus shipping and tax.
    It is stored verbatim so the dashboard's headline can equal what
    anyone sees in Shopify, rather than approaching it.

    It is NOT the same measure as the order-derived `revenue` beside
    it, and the difference is not drift:

      * RETURNS are dated by the day the REFUND was issued, against an
        order from any day. Our order-derived figures date everything by
        the order. So an hour's total_sales can be pulled down by a
        refund on a three-week-old order.
      * Cancelled orders that were never REFUNDED stay inside it. A COD
        order cancelled before payment produces no refund, so Shopify
        still counts it; the P&L deducts it separately.

    Both are kept because they answer different questions, and a single
    number cannot be both Shopify-identical and attributable by channel.
    """
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    q = (f"FROM sales SHOW total_sales, returns, gross_sales, net_sales, "
         f"orders, quantity_ordered, "
         f"customers, new_customers, returning_customers, "
         f"total_sales_returning, total_sales_first_time "
         # Return Prime's zero-value return orders are excluded, the
         # same exclusion the Shopify report uses. Checked on three
         # days: total_sales, returns and gross_sales come back
         # IDENTICAL either way, because those orders carry no money --
         # so the headline stays exact to the paisa while the COUNTS
         # stop being inflated. Left unfiltered they ran a few percent
         # over the report on both orders and units.
         f"WHERE sales_channel != 'Return Prime: Order Return' "
         f"SINCE {day.isoformat()} UNTIL {day.isoformat()} "
         f"GROUP BY hour ORDER BY hour LIMIT 100")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"sales parseErrors: {resp['parseErrors']}")
    out = {}
    for row in (resp.get("tableData") or {}).get("rows", []):
        hour = ist_hour(datetime.fromisoformat(row["hour"].replace("Z", "+00:00")))
        total = float(row.get("total_sales") or 0)
        # `returns` arrives NEGATIVE. Subtracting it adds the refunds
        # back, which is the like-for-like comparison against the
        # order-derived figure -- that one has no returns in it either.
        rets = float(row.get("returns") or 0)
        out[hour] = {
            "shopify_total_sales": total,
            "shopify_returns": rets,
            "revenue_shopifyql": total - rets,
            # Shopify's own units count. Deliberately kept apart from
            # pnl_qty, which is derived from the orders and excludes
            # the gift coin: the two answer different questions and a
            # difference between them is informative, not an error.
            "qty_ordered": int(float(row.get("quantity_ordered") or 0)),
            # Shopify's own order count, kept apart from the tracker's
            # `orders`, which is derived from the orders themselves and
            # drops a different set. Units per order and AOV are
            # divided by THIS one, so both numerator and denominator
            # come from the same population.
            "ql_orders": int(float(row.get("orders") or 0)),
            # The numerator of Shopify's average_order_value, which is
            # NOT total_sales / orders: that reads a few percent low.
            # Shopify divides net sales BEFORE returns, i.e.
            # net_sales - returns (returns arrive negative). Checked
            # against its own average_order_value on four days at both
            # day and hour grain -- nearly every row agreed to five
            # significant figures, the two others to within a percent.
            # Stored as the numerator, never as the ratio: a stored
            # average cannot be re-divided when hours are summed.
            "ql_net_sales": round(float(row.get("net_sales") or 0), 2),
            # Shopify's own first-time/returning split. The tracker
            # already derives new_customers from the orders using
            # Shopify's lifetime order count, but THIS is Shopify's own
            # classification on its own basis -- kept under distinct
            # names so a difference between the two is visible rather
            # than one silently overwriting the other.
            # Shopify's returning_customer_rate is
            # returning_customers / customers -- NOT
            # returning / (new + returning). Verified against a
            # day-grain pull: returning / customers reproduced its rate
            # to six decimals, while new + returning summed HIGHER than
            # the customer count, so the buckets overlap and cannot
            # serve as the denominator. `customers` is a DISTINCT
            # count, so summing the hours overstates the day by about
            # two percent, moving the rate a quarter of a point.
            # Stored per hour anyway, because that makes each hour's
            # rate exact and the day's near enough to read.
            "ql_customers": int(float(row.get("customers") or 0)),
            "ql_new_customers": int(float(row.get("new_customers") or 0)),
            "ql_returning_customers": int(float(row.get("returning_customers") or 0)),
            "ql_sales_returning": round(float(row.get("total_sales_returning") or 0), 2),
            "ql_sales_first_time": round(float(row.get("total_sales_first_time") or 0), 2),
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
        totalRefundedSet { shopMoney { amount } }
        cancelledAt
        tags
        lineItems(first: 100) {
          edges { node { sku quantity title } }
        }
        app { name }
        channelInformation { channelDefinition { handle channelName } }
        name
        email
        displayFinancialStatus
        displayFulfillmentStatus
        shippingAddress { name address1 address2 city province zip phone }
        customer { id numberOfOrders }
        customAttributes { key value }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def coin_order_row(n: dict, cust: dict, created: datetime,
                   coins: int, units: int, price: float) -> dict:
    """One row for the order list, coin or bundle.

    Built in one place so the two branches cannot drift: a bundle row
    with a missing column would show as a blank cell rather than an
    error, which is the kind of gap nobody reports.
    """
    addr = n.get("shippingAddress") or {}
    nord = cust.get("numberOfOrders")
    nord = int(nord) if str(nord or "").isdigit() else None
    items = sum(int((e.get("node") or {}).get("quantity") or 0)
                for e in ((n.get("lineItems") or {}).get("edges") or []))
    bundles = bundle_titles(n.get("lineItems"))
    return {
        "order_id": n["id"], "order_name": n.get("name"), "created_at": created,
        "day_ist": created.astimezone(IST).date(),
        "coins": coins, "units": units, "amount": price,
        "payment": PAYMENT_LABEL.get((n.get("displayFinancialStatus") or "").upper()),
        "fulfillment": (n.get("displayFulfillmentStatus") or "").title() or None,
        "risk_tag": risk_of(n.get("tags")),
        # A COD the desk has already rung and confirmed. Stored here
        # rather than read from shopify_orders.tags at query time: that
        # join cannot use an index on a `tags::text ILIKE` and costs a
        # sequential scan of every order in the shop -- about 89,000
        # blocks for one KPI card, on a page that loads it every visit.
        "cod_verified": any(
            (t or "").strip().lower() == "silver-cod-verified"
            for t in (n.get("tags") or [])),
        "customer_orders": nord,
        "is_returning": (nord > 1) if nord is not None else None,
        "city": addr.get("city"), "state": addr.get("province"),
        "pincode": addr.get("zip"), "coin_only": coins > 0 and units == 0,
        "customer_name": (addr.get("name") or "").strip() or None,
        "phone": (addr.get("phone") or "").strip() or None,
        "address1": addr.get("address1"), "address2": addr.get("address2"),
        "channel": order_channel(n), "item_count": items,
        "bundles": "; ".join(bundles) or None,
        # Classified after the day is gathered: the duplicate-COD test
        # needs the other orders of the same day, which do not exist
        # yet when this row is built.
        "_customer_id": (cust.get("id") or None),
        "_fake_order": "fake order" in {
            str(t).strip().lower() for t in (n.get("tags") or [])},
    }


async def fetch_orders(client, store, day: date,
                       coin_rows: list | None = None) -> dict[datetime, dict]:
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
                                          orders_meta=0, orders_paid=0, orders_direct=0,
                                          orders_excluded=0, revenue_excluded=0.0,
                                          new_customers=0, new_customer_revenue=0.0,
                                          pnl_sales=0.0, pnl_orders=0, pnl_qty=0,
                                          silver_coin_orders=0, silver_coin_qty=0,
                                          coin_only_orders=0, coin_shipped_orders=0,
                                          coin_prepaid_orders=0, coin_partial_orders=0,
                                          coin_cod_orders=0, bundle_no_coin_orders=0,
                                          pnl_cancelled_orders=0,
                                          pnl_cancelled_sales=0.0,
                                          pnl_cancelled_qty=0, pnl_refunds=0.0,
                                          pnl_cancelled_refunded=0.0))

            # The P&L basis is accumulated BEFORE the revenue
            # exclusions, because the two answer different questions
            # and share only the order feed.
            if not is_pnl_excluded(n.get("tags")):
                units, coins = count_units(n.get("lineItems"))
                b["pnl_sales"] += price
                b["pnl_orders"] += 1
                b["pnl_qty"] += units
                # The coin count runs its own exclusions; see
                # is_coin_excluded for why they are stricter than the
                # P&L's. Units and sales above are unaffected.
                coin_ok = is_coin_excluded(n, created) is None
                if coins and coin_ok:
                    b["silver_coin_orders"] += 1
                    b["silver_coin_qty"] += coins
                    # Coin only: the coin is the whole order. `units`
                    # already excludes the coin, so zero units with a
                    # coin present IS the definition -- no second pass
                    # over the line items, which could disagree.
                    if units == 0:
                        b["coin_only_orders"] += 1
                    if coin_rows is not None:
                        coin_rows.append(coin_order_row(n, cust, created, coins, units,
                                                        price))
                    if (n.get("displayFulfillmentStatus") or "").upper() == "FULFILLED":
                        b["coin_shipped_orders"] += 1
                    fin = (n.get("displayFinancialStatus") or "").upper()
                    if fin == "PAID":
                        b["coin_prepaid_orders"] += 1
                    elif fin == "PARTIALLY_PAID":
                        b["coin_partial_orders"] += 1
                    elif fin == "PENDING":
                        b["coin_cod_orders"] += 1
                # Eligible-looking but no coin. Deliberately NOT a
                # split of the coin counts: these orders have no coin
                # at all, so they sit outside them. Same exclusions,
                # because the question is the same one -- who should
                # have had a coin.
                elif not coins and units >= 2 and coin_ok:
                    b["bundle_no_coin_orders"] += 1
                    if coin_rows is not None:
                        coin_rows.append(coin_order_row(n, cust, created, 0, units,
                                                        price))
                refunded = float((n.get("totalRefundedSet") or {})
                                 .get("shopMoney", {}).get("amount") or 0)
                if n.get("cancelledAt"):
                    b["pnl_cancelled_orders"] += 1
                    b["pnl_cancelled_sales"] += price
                    b["pnl_cancelled_qty"] += units
                    # Shopify has already taken this part out of Total
                    # sales, via `returns`. Only the rest is still in.
                    b["pnl_cancelled_refunded"] += refunded
                else:
                    # Only on orders that stand. A cancelled order is
                    # deducted at full price above; refunding it too
                    # would deduct the same money twice.
                    b["pnl_refunds"] += refunded

            # Counted and set aside, not skipped silently: an hour whose
            # orders do not match Shopify's admin should say why.
            if is_excluded_order(n.get("cancelledAt"), n.get("tags")):
                b["orders_excluded"] += 1
                b["revenue_excluded"] += price
                continue

            b["revenue"] += price
            b["orders"] += 1
            if is_meta(src):
                b["revenue_meta"] += price
                b["orders_meta"] += 1
            if is_google(src):
                b["revenue_google"] += price
            if is_direct(src):
                b["orders_direct"] += 1
            else:
                b["revenue_paid"] += price
                b["orders_paid"] += 1
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
def fetch_kwikchat_spend(day: date) -> float:
    """The day's Kwikchat spend, read from the table rather than assumed.

    It used to be the module constant, which meant the figure could only
    be changed by editing this file and redeploying -- and the table the
    rest of the warehouse reads (`kwikchat_spend_daily`, filled by
    scripts/seed_kwikchat_spend.py) had no effect on the tracker at all.
    Updating the placeholder in one place left the two disagreeing.

    Measured for the months whose console export has been loaded by
    scripts/import_kwikchat_spend.py; the flat constant is only the
    fallback for a day with no row, and `is_estimate` on the row is what
    tells the two apart.

    The fallback stays rather than returning None, because a tracker
    that silently drops a spend component reads flatteringly on every
    ratio that divides by spend. But it is a BAD guess and knowingly so:
    real Kwikchat spend is spiky -- a few campaign blasts a month
    against a near-zero trickle between them -- so the flat rate is
    wrong on essentially every day, in one direction or the other.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT spend FROM public.kwikchat_spend_daily WHERE day = %s", (day,))
        row = cur.fetchone()
    if row and row[0] is not None:
        return float(row[0])
    print(f"  [warn] no kwikchat_spend_daily row for {day}; "
          f"falling back to {KWIKCHAT_DAILY:,.0f}/day")
    return KWIKCHAT_DAILY


def fetch_google_spend(day: date) -> tuple[float | None, datetime | None]:
    """The day's Google Ads spend, and when that figure was captured.

    Google arrives as ONE NUMBER PER DAY from a BigQuery export that
    refreshes each morning -- there is no hourly feed to be had, and
    the Ads API would deliver the same daily grain. So the total is
    read here and shared out by `distribute_daily` below.

    The second value is when the SOURCE was last current for this day,
    which is not when we fetched it -- re-running the fetcher moves
    fetched_at forward without the numbers getting any fresher.
    MapleMonk syncs once each morning, so a day still running is only
    covered up to that sync, and `data_as_of` carries it. Rows written
    by the Google Ads API have no sync to speak of (the API answers
    live), so for those the fetch time IS the as-of, hence the
    COALESCE.

    Returns (None, None) when the day has no row at all, which is the
    honest answer for a day the export has not reached yet. A zero
    would read as "Google spent nothing", which is a different claim.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT SUM(spend), MAX(COALESCE(data_as_of, fetched_at))
            FROM public.google_ads_spend_daily
            WHERE day = %s
        """, (day,))
        total, as_of = cur.fetchone()
    return (float(total) if total is not None else None), as_of


def distribute_daily(total: float, weights: dict[datetime, float]) -> dict[datetime, float]:
    """Share one daily figure across hours, in proportion to `weights`.

    The weight used for Google is that hour's GOOGLE-DRIVEN SESSIONS,
    not an even 24th. Ad delivery follows demand, and the two curves
    agree closely: on 29 Oct the Google session share and the Meta
    spend share tracked each other within about a point and a half at
    every hour, troughing together at 03:00 and peaking together in the
    evening. An even split would put as much spend at 4am as at 8pm.

    This is an ALLOCATION, not a measurement. The day's total is real;
    its shape is inferred, and every caller labels it as such.

    With no weights to go on -- a day with no Google sessions at all --
    it falls back to an even split, which is a worse answer but is the
    only one left and still sums to the right total.
    """
    hours = list(weights)
    if not hours:
        return {}
    denom = sum(weights.values())
    if denom <= 0:
        return {h: total / len(hours) for h in hours}
    return {h: total * (w / denom) for h, w in weights.items()}


def is_unsettled(day: date, last_write: datetime | None,
                 latest_hour: int | None) -> bool:
    """The decision, separated from the query so it can be tested.

    None for `last_write` means the day was never ingested at all --
    that is a backfill, not a settle, and this returns False so a gap
    in history is never silently filled by a job meant to tidy the
    edge of yesterday.
    """
    if last_write is None:
        return False
    day_end = datetime.combine(day, datetime.min.time(), IST) + timedelta(days=1)
    return last_write < day_end or (latest_hour if latest_hour is not None else -1) < 23


def needs_settling(day: date) -> bool:
    """Was this day last written BEFORE it had actually finished?

    The hour a run writes is the hour in progress, so it is partial by
    construction. That is fine while the day is live -- the next run
    replaces it. It stops being fine at midnight: the last run of a day
    stores an incomplete final hour, the date rolls over, and nothing
    ever goes back for the rest of it.

    Measured 2026-10-30: the day was last written 23:16 IST and kept
    1,293 orders / Rs 18.94L against Shopify's own 1,399 / Rs 19.57L.
    Re-pulling the closed day recovered 43 orders and Rs 72,943 -- the
    last forty-four minutes, missing permanently.

    Checked rather than scheduled on purpose. A "re-pull yesterday if
    the hour is 0 or 1" rule only works if a run actually happens in
    that window, and the whole reason this job exists is that the
    scheduler cannot be relied on to fire.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(fetched_at), MAX(hour_of_day)
            FROM public.hourly_campaign_tracker WHERE day_ist = %s
        """, (day,))
        last_write, latest_hour = cur.fetchone() or (None, None)
    return is_unsettled(day, last_write, latest_hour)


async def fetch_basket_mix(client, store, day: date) -> dict[datetime, dict]:
    """Basket-size mix per hour: how many items people bought at once.

    `number_of_products_bought_together` is Shopify's own dimension, so
    this is the hourly version of the Quantity report rather than a
    reconstruction of it.

    Return Prime's channel is excluded, matching the report: a return
    flowing back is not a basket. Without that filter a refund lands in
    a phantom bucket 0 carrying negative sales and no orders.
    """
    from ingest_shopify import SHOPIFYQL_QUERY  # noqa: PLC0415
    from shopify_client import graphql_request  # noqa: PLC0415

    q = (f"FROM sales SHOW quantity_ordered, orders, total_sales "
         f"WHERE sales_channel != 'Return Prime: Order Return' "
         f"GROUP BY hour, number_of_products_bought_together "
         f"SINCE {day.isoformat()} UNTIL {day.isoformat()} LIMIT 1000")
    resp = (await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q}))["shopifyqlQuery"]
    if resp.get("parseErrors"):
        raise RuntimeError(f"basket mix parseErrors: {resp['parseErrors']}")

    out: dict[datetime, dict] = {}
    for row in (resp.get("tableData") or {}).get("rows", []):
        if not row.get("hour"):
            continue
        hour = ist_hour(datetime.fromisoformat(row["hour"].replace("Z", "+00:00")))
        size = str(row.get("number_of_products_bought_together") or "").strip()
        # Bucket 0 is the refund residue the channel filter does not
        # always catch. It has no orders and carries negative sales, so
        # it is not a basket anyone bought.
        if not size or size == "0":
            continue
        bucket = out.setdefault(hour, {"basket_mix": {}})["basket_mix"]
        bucket[size] = {
            "qty": int(float(row.get("quantity_ordered") or 0)),
            "orders": int(float(row.get("orders") or 0)),
            "sales": round(float(row.get("total_sales") or 0), 2),
        }
    return out


def classify_coin_rows(coin_rows: list[dict]) -> None:
    """Put every coin order in exactly one bucket, in place.

    Runs AFTER the day is gathered, because the duplicate-same-day-COD
    test needs to see the day's other orders.
    """
    from coin_dispatch import (address_issues, classify,  # noqa: PLC0415
                               is_watchlisted)

    hist = fetch_customer_history(
        sorted({r["_customer_id"] for r in coin_rows if r.get("_customer_id")}))

    # Two or more COD orders on one day to the same phone or address.
    seen: dict[tuple, int] = {}
    for r in coin_rows:
        if r.get("payment") != "COD":
            continue
        key = (r["day_ist"], r.get("phone") or (r.get("address1") or "").lower())
        if key[1]:
            seen[key] = seen.get(key, 0) + 1

    # Repeat buyers: the same phone or address on two or more COIN
    # orders, across the whole campaign rather than one day. Counted
    # on coin orders only, because that is the promotion being
    # watched.
    repeat: dict[str, int] = {}
    for r in coin_rows:
        if not r.get("coins"):
            continue
        who = r.get("phone") or (r.get("address1") or "").lower()
        if who:
            repeat[who] = repeat.get(who, 0) + 1

    for r in coin_rows:
        issues, flag = address_issues(r.get("address1"), r.get("address2"))
        r["address_flag"] = flag
        r["address_issues"] = ";".join(issues) or None
        who = r.get("phone") or (r.get("address1") or "").lower()
        key = (r["day_ist"], who)
        dup = r.get("payment") == "COD" and who and seen.get(key, 0) > 1
        bucket, reasons = classify(
            {**r, "address_issues": issues, "fake_order": r.get("_fake_order")},
            hist.get(r.get("_customer_id") or ""), bool(dup))
        r["bucket"] = bucket
        # The call reasons are the ONLY thing stored for a call-list
        # row; bucket_reason keeps the single headline for the other
        # buckets so every row can still say one thing about itself.
        r["call_reasons"] = ";".join(reasons) if bucket == "call_list" else None
        r["bucket_reason"] = (
            "coin and nothing else" if bucket == "coin_only"
            else "2+ units, no coin" if bucket == "bundle_no_coin" else None)
        r["watchlist"] = is_watchlisted(
            {**r, "fake_order": r.get("_fake_order")},
            bool(who and repeat.get(who, 0) > 1))
        for k in ("_customer_id", "_fake_order"):
            r.pop(k, None)


async def build_day(client, store, day: date,
                    coin_rows: list | None = None) -> list[dict]:
    sessions, sales, orders, meta, baskets = await asyncio.gather(
        fetch_sessions(client, store, day),
        fetch_sales(client, store, day),
        fetch_orders(client, store, day, coin_rows),
        fetch_meta(client, day),
        fetch_basket_mix(client, store, day),
    )
    ga4 = fetch_ga4(day)
    google_total, google_as_of = fetch_google_spend(day)
    kwikchat_total = fetch_kwikchat_spend(day)

    hours = sorted(set(sessions) | set(sales) | set(orders) | set(meta) | set(ga4)
                   | set(baskets))

    # Spread over the hours that HAVE HAPPENED, not all 24. Giving a
    # future hour its share would silently inflate the day's spend and
    # make cost per session read high from the first hour onward.
    #
    # Only across the hours the capture COVERS. Today's total is read
    # from an export that ran this morning, so it is the spend placed
    # up to that moment -- spreading it over the evening too would move
    # money into hours it demonstrably was not spent in. For a finished
    # day the export ran after midnight and every hour qualifies, so
    # this is a no-op there.
    google_by_hour: dict[datetime, float] = {}
    if google_total is not None:
        covered = [h for h in hours if google_as_of is None or h < google_as_of]
        google_by_hour = distribute_daily(
            google_total,
            {h: float(sessions.get(h, {}).get("sessions_google") or 0) for h in covered},
        )
    rows = []
    for hour in hours:
        local = hour.astimezone(IST)
        row = {
            "hour": hour, "day_ist": local.date(), "hour_of_day": local.hour,
            # The placeholder, spread evenly. Only for hours that have
            # actually happened -- giving a future hour its share would
            # make cost per session read high all day.
            # A rate, not a budget poured into the hours so far: the
            # divisor is the day's length, so a part-finished day
            # accumulates proportionally.
            "kwikchat_spend": round(kwikchat_total / 24.0, 4),
        }
        if google_total is not None:
            if hour in google_by_hour:
                row["google_spend"] = round(google_by_hour[hour], 4)
            row["google_spend_as_of"] = google_as_of
        for source in (sessions, sales, orders, meta, ga4, baskets):
            row.update(source.get(hour, {}))
        # psycopg2 has no adapter for a dict; jsonb wants text.
        if isinstance(row.get("basket_mix"), dict):
            row["basket_mix"] = json.dumps(row["basket_mix"])
        rows.append(row)
    return rows


def write(rows: list[dict], coin_rows: list[dict] | None = None) -> int:
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
        if coin_rows:
            cur.execute(COIN_DDL)
            # Written in the same transaction as the hourly counts, so
            # the list and the totals above it can never be from
            # different runs of the same day.
            psycopg2.extras.execute_values(
                cur, COIN_UPSERT,
                [tuple(r.get(c) for c in COIN_COLUMNS) for r in coin_rows],
                page_size=200)
            cur.execute(REFRESH_FULFILMENT, {"days": COIN_REFRESH_DAYS})
            moved = cur.rowcount
            if moved:
                print(f"          {moved:,} coin order(s) caught up on fulfilment",
                      flush=True)
        conn.commit()
    return len(tuples)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="One IST day. Default: today.")
    ap.add_argument("--days", type=int, default=1,
                    help="Trailing days ending at --date (default today).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-settle", action="store_true",
                    help="Skip the automatic re-pull of a day that was last "
                         "written before it ended. Only affects the default "
                         "run; an explicit --date is never extended.")
    args = ap.parse_args()

    from shopify_client import discover_stores  # noqa: PLC0415

    end = args.date or datetime.now(IST).date()
    days = [end - timedelta(days=i) for i in range(args.days - 1, -1, -1)]

    # Settle the previous day if its stored copy predates its own
    # midnight. Only on the default run: an explicit --date is a
    # deliberate request for those days and nothing else.
    if args.date is None and not args.no_settle:
        prev = end - timedelta(days=1)
        if prev not in days and needs_settling(prev):
            print(f"Settling {prev}: last written before the day ended.")
            days.insert(0, prev)
    store = list(discover_stores().values())[0]

    total = 0
    async with httpx.AsyncClient(timeout=120) as client:
        for day in days:
            coin_rows: list[dict] = []
            rows = await build_day(client, store, day, coin_rows)
            if coin_rows:
                classify_coin_rows(coin_rows)
                # Fold the buckets back onto the hour each order
                # belongs to, so the KPI strip reads the hourly table
                # rather than scanning every order row.
                by_hour: dict[int, dict] = {}
                for r in coin_rows:
                    h = r["created_at"].astimezone(IST).hour
                    b = by_hour.setdefault(h, {})
                    b[r["bucket"]] = b.get(r["bucket"], 0) + 1
                for row in rows:
                    b = by_hour.get(row["hour_of_day"], {})
                    row["coin_ship_now_orders"] = b.get("ship_now", 0)
                    row["coin_call_list_orders"] = b.get("call_list", 0)
                    row["coin_address_bad_orders"] = b.get("address_bad", 0)
            sess = sum(r.get("sessions") or 0 for r in rows)
            spend = sum((r.get("meta_spend") or 0) + (r.get("kwikchat_spend") or 0)
                        + (r.get("google_spend") or 0) for r in rows)
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
            if coin_rows:
                tally: dict[str, int] = {}
                for r in coin_rows:
                    tally[r["bucket"]] = tally.get(r["bucket"], 0) + 1
                print(f"          {len(coin_rows):,} silver-coin orders listed  "
                      + " ".join(f"{k} {v}" for k, v in sorted(tally.items())))
            if not args.dry_run:
                total += write(rows, coin_rows)

    print(f"\n[{'DRY RUN' if args.dry_run else 'OK'}] "
          f"{total:,} hourly rows {'built' if args.dry_run else 'written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
