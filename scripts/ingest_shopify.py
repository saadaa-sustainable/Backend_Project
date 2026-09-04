"""Fetch Shopify data (shop, products, orders, customers, aggregated
sessions) via the Admin GraphQL API across every configured store, and
write it into ``raw_dump_shopify`` via a direct Postgres connection
(``DATABASE_URL``, asyncpg) -- mirrors ``scripts/ingest_instagram_chronological.py``'s
write path exactly (see that module's docstring for why direct Postgres
beat the original PostgREST approach: it lets the admin-panel wiring in
``app/api/routers/admin.py`` query the target table directly for resume
state, and upsert-in-place needs a real ``ON CONFLICT``, which PostgREST's
plain insert-only REST endpoint doesn't give you).

Why GraphQL changes the shape of this script vs the Meta ones: Shopify has
no equivalent of Meta's per-field 400 rejections -- there's no "fields"
list to prune. Each object type needs its own query string (not a flat
field list) since GraphQL requires you to describe nested shape up front.
Date-range filtering uses Shopify's `query: String` search argument on
each connection (e.g. ``orders(first: $first, after: $after, query:
$query)``), built as ``created_at:>='...' AND created_at:<='...'`` --
confirmed live that UNQUOTED date values 500 with an internal server
error; quoted ISO date strings work.

SESSIONS ARE NOT A GRAPHQL OBJECT. Confirmed via live schema introspection
-- no `sessions` field exists on any queryable type. Session data comes
from Shopify's ShopifyQL Analytics API (`shopifyqlQuery(query: String!)`),
a completely different query language embedded in a string, with its own
`SINCE`/`UNTIL` date syntax and no cursor pagination (a `LIMIT` clause
instead, default-capped at 1000 rows if omitted). Confirmed live this
store has ~66,000 RAW individual sessions on a single day -- almost
certainly bot/crawler traffic, not real visitors, and far too much volume
to fetch/store at that granularity for a marketing-attribution use case.
Explicit user decision (2026-08-25): fetch DAY x CHANNEL AGGREGATES
instead (`GROUP BY day, referrer_source, utm_source, utm_campaign,
utm_medium`), not raw per-session rows -- confirmed live this produces
real, useful data (utm_campaign values match actual Meta campaign IDs/
names 1:1), at ~100 rows/day instead of ~66,000.

KNOWN CAVEAT (well-documented Shopify behavior, not a bug found here):
the `orders` query only returns orders from roughly the last 60 days
unless the app has the `read_all_orders` access scope. If older orders
are missing, this is almost certainly why -- check the access token's
granted scopes, not this script's query.

REAL BUG FOUND AND FIXED (2026-08-26): the original ORDERS_QUERY only
fetched `customerJourneySummary` for UTM data, which Shopify leaves null
for the large majority of orders (~5% coverage, confirmed live) --
independent of whether the order actually has attribution data. The real,
much richer source is `customAttributes` (`{ key value }` on the order),
populated by this store's checkout accelerator (GoKwik) with
`utm_source`/`utm_campaign`/`utm_medium`/`utm_content`/`utm_term` plus a
`full_url`, `visitor_uniqId`, etc. -- confirmed live on an order where
`customerJourneySummary` was entirely null but `customAttributes` had
complete UTM data. Coverage via `customAttributes` measured at 64% across
a real 200-order sample, vs ~5% via `customerJourneySummary` alone. Also
checked ShopifyQL's `fulfillments` table's own `order_utm_*` dimensions as
a third candidate source -- only ~4.8% coverage, worse than
`customerJourneySummary`, not worth using for attribution (kept only for
its actual purpose: fulfillment/shipping/delivery metrics, see
FULFILLMENTS_GROUP_BY/FULFILLMENTS_METRICS below). `customAttributes` is
now fetched and is the primary UTM source (see
app/services/silver/shopify_flatten.py's order UTM extraction) --
`customerJourneySummary` stays fetched too as a fallback/reference, not
removed.

Reads SHOPIFY_STORE_<N>_DOMAIN / _NAME / _ACCESS_TOKEN (or the simpler
SHOP_DOMAIN / ADMIN_ACCESS_TOKEN single-store fallback, both handled by
shopify_client.discover_stores()) and DATABASE_URL from .env at runtime.

Usage:
    python3 scripts/ingest_shopify.py                                  # every store, all object types, full history, writes to Postgres
    python3 scripts/ingest_shopify.py --store 1
    python3 scripts/ingest_shopify.py --object-types orders,customers,sessions
    python3 scripts/ingest_shopify.py --date-start 2026-01-01 --date-end 2026-08-24
    python3 scripts/ingest_shopify.py --no-insert                      # fetch + time only
    python3 scripts/ingest_shopify.py --page-size 100 --max-pages 5    # cap a large store for a quick trial
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shopify_client import (  # noqa: E402
    DEFAULT_API_VERSION,
    ShopifyStore,
    describe_store_safely,
    discover_stores,
    graphql_request,
    paginate_connection,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = REPO_ROOT / "scripts" / "sql" / "raw_dump_shopify.sql"
ERROR_LOG_PATH = REPO_ROOT / "logs" / "shopify_ingest_errors.log"

#: 250 is Shopify's per-connection maximum. At the old value of 50, a
#: full-history orders walk was ~7,000 sequential requests (347k orders),
#: each a chance to be throttled -- run #7 (2026-09-04) spent 1079s on
#: orders and returned ZERO rows before failing. Five times fewer
#: requests is five times less throttle exposure for identical data.
DEFAULT_PAGE_SIZE = 250
DEFAULT_OBJECT_TYPES = [
    "shop", "products", "orders", "customers", "sessions", "fulfillments",
    "customer_analytics", "sales", "discounts", "inventory",
]
#: ShopifyQL has no cursor pagination for a date range -- chunk large
#: ranges the same way app/services/meta/insights.py chunks Insights date
#: ranges, so one call's LIMIT (see SESSIONS_LIMIT_PER_CHUNK) never has to
#: cover more than this many days at once. Confirmed live (2026-08-26)
#: adding landing_page_path to SESSIONS_GROUP_BY pushed real volume to
#: ~7,200 rows/day on this store (vs ~100/day for day+channel alone) --
#: 30-day chunks at that rate would need >200K rows each, so this shrank
#: from 30 to 3 (~22K rows/chunk, comfortably under the limit below).
SESSIONS_CHUNK_DAYS = 3
#: Raised from 20K to 30K alongside the SESSIONS_CHUNK_DAYS drop above --
#: 3 days x ~7,200/day is ~22K, this leaves real margin without the chunk
#: itself getting expensive to write in one executemany batch.
SESSIONS_LIMIT_PER_CHUNK = 30_000

# ----------------------------------------------------------------------
# GraphQL queries -- one per object type. Deliberately a starter field
# set (mirrors how the Meta trial scripts used trimmed field lists, not
# the full registry) -- extend here as real needs surface, same as the
# Meta side grew CAMPAIGN_FIELDS/ADSET_FIELDS/AD_FIELDS incrementally.
# ----------------------------------------------------------------------

SHOP_QUERY = """
query Shop {
  shop {
    id
    name
    myshopifyDomain
    email
    currencyCode
    ianaTimezone
    plan {
      displayName
    }
    createdAt
  }
}
"""

PRODUCTS_QUERY = """
query Products($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query) {
    edges {
      node {
        id
        title
        handle
        description
        status
        vendor
        productType
        tags
        createdAt
        updatedAt
        publishedAt
        totalInventory
        isGiftCard
        priceRangeV2 {
          minVariantPrice { amount currencyCode }
          maxVariantPrice { amount currencyCode }
        }
        variants(first: 25) {
          edges {
            node {
              id
              title
              sku
              price
              inventoryQuantity
              barcode
            }
          }
          # A product with more than VARIANTS_PAGE_SIZE variants is
          # truncated here. pageInfo lets _hydrate_product_variants()
          # detect that and re-fetch the full set -- without it the
          # truncation is silent and every downstream per-variant
          # rollup (stock, in-stock rate, price ladder) quietly
          # under-counts. Kept at 25 in THIS query on purpose: raising
          # it multiplies the query's cost by the page size of the
          # OUTER products connection too, and Shopify rejects the
          # whole request past its calculated-cost ceiling. The rare
          # wide product pays for a second round-trip instead.
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

#: Variants requested per page inside PRODUCTS_QUERY above. A product
#: with more than this many variants comes back truncated and is
#: completed by _hydrate_product_variants() via PRODUCT_VARIANTS_QUERY.
VARIANTS_PAGE_SIZE = 25

#: Page size for the follow-up variant fetch. Safe to be larger than
#: VARIANTS_PAGE_SIZE because this query walks ONE product, so the
#: cost isn't multiplied by an outer connection.
VARIANT_HYDRATE_PAGE_SIZE = 100

#: Re-fetches one product's variants as a standalone Relay connection so
#: paginate_connection() can walk it to exhaustion.
PRODUCT_VARIANTS_QUERY = """
query ProductVariants($id: ID!, $first: Int!, $after: String) {
  product(id: $id) {
    variants(first: $first, after: $after) {
      edges {
        node {
          id
          title
          sku
          price
          inventoryQuantity
          barcode
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

ORDERS_QUERY = """
query Orders($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query) {
    edges {
      node {
        id
        name
        email
        createdAt
        updatedAt
        processedAt
        displayFinancialStatus
        displayFulfillmentStatus
        currentTotalPriceSet {
          shopMoney { amount currencyCode }
        }
        subtotalPriceSet {
          shopMoney { amount currencyCode }
        }
        totalPriceSet {
          shopMoney { amount currencyCode }
        }
        customer {
          id
          email
        }
        customerJourneySummary {
          firstVisit {
            referrerUrl
            source
            sourceType
            landingPage
            utmParameters { source medium campaign content term }
          }
          lastVisit {
            referrerUrl
            source
            sourceType
            landingPage
            utmParameters { source medium campaign content term }
          }
        }
        customAttributes {
          key
          value
        }
        lineItems(first: 25) {
          edges {
            node {
              id
              title
              quantity
              sku
              originalUnitPriceSet {
                shopMoney { amount currencyCode }
              }
            }
          }
        }
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

CUSTOMERS_QUERY = """
query Customers($first: Int!, $after: String, $query: String) {
  customers(first: $first, after: $after, query: $query) {
    edges {
      node {
        id
        firstName
        lastName
        defaultEmailAddress {
          emailAddress
        }
        defaultPhoneNumber {
          phoneNumber
        }
        verifiedEmail
        state
        numberOfOrders
        amountSpent {
          amount
          currencyCode
        }
        taxExempt
        tags
        createdAt
        updatedAt
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

SHOPIFYQL_QUERY = """
query ShopifyqlQuery($q: String!) {
  shopifyqlQuery(query: $q) {
    parseErrors
    tableData {
      columns { name dataType }
      rows
    }
  }
}
"""

#: GROUP BY dims -- confirmed live (2026-08-25/26) as valid ShopifyQL
#: `sessions` table columns via trial-and-error against the real schema
#: (ShopifyQL has no introspection of its own analytics tables the way the
#: GraphQL schema does for objects). landing_page_path/landing_page_type
#: added 2026-08-26 (explicit user request -- "session per page, like
#: /men-cotton-pant") -- this is the page a session LANDED on, not a full
#: per-pageview breakdown (ShopifyQL's sessions table is session-level, one
#: row per visit's landing point, not a raw pageview log). Adding it raised
#: real volume from ~100 to ~7,200 rows/day on this store -- see
#: SESSIONS_CHUNK_DAYS/SESSIONS_LIMIT_PER_CHUNK above, sized for this.
SESSIONS_GROUP_BY = [
    "day", "referrer_source", "utm_source", "utm_campaign", "utm_medium",
    "landing_page_path", "landing_page_type",
]
#: The full documented metric set for this table -- shopify.dev/docs/api/
#: shopifyql/2026-10/schemas/sessions_and_behavior/sessions (fetched
#: 2026-08-26). All 16 confirmed live in one combined query against the
#: real store; the original 4 (sessions/pageviews/conversion_rate/
#: bounce_rate) covered volume + one conversion signal, the other 12 add
#: the actual purchase funnel (cart adds -> checkout reached -> checkout
#: completed) and visitor/duration metrics that were missing before.
SESSIONS_METRICS = [
    "sessions",
    "pageviews",
    "conversion_rate",
    "bounce_rate",
    "bounces",
    "average_session_duration",
    "pageviews_per_session",
    "online_store_visitors",
    "added_to_cart_rate",
    "sessions_with_cart_additions",
    "reached_checkout_rate",
    "sessions_that_reached_checkout",
    "checkout_conversion_rate",
    "completed_checkout_rate",
    "sessions_that_completed_checkout",
    "sessions_that_reached_and_completed_checkout",
]

#: ShopifyQL `fulfillments` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/orders/fulfillments (fetched 2026-08-26, re-verified field-by-
#: field live 2026-08-26 after the first pass only covered a small subset
#: -- user explicitly asked for every metric in the doc, not a curated
#: sample). ALL documented dimensions are included EXCEPT:
#: - 6 fields erroring "Attribution Syntax Required" on this table
#:   (activation_platform, agentic_referring_channel, marketing_activity_id,
#:   marketing_platform, page_host, page_path) -- these need a different
#:   ShopifyQL query form this project doesn't use elsewhere, not worth the
#:   extra complexity for fields this store shows as null anyway.
#: - array-typed fields (order_tags, markets, products_bought_together,
#:   products_bought_together_ids, variants_bought_together) -- would need
#:   per-tag row multiplication or jsonb-array handling; deferred.
#: - order_marketing_event_id alone (kept _target/_type, dropped the bare id
#:   -- redundant, this store never populates any of the three).
#: Its own `order_utm_*` dimensions were considered as a UTM source for
#: attribution but rejected: only ~4.8% coverage (worse than
#: customerJourneySummary's ~5%, far worse than orders' customAttributes'
#: 64%) -- see the module docstring's "REAL BUG FOUND" note. Confirmed live
#: the full combined SHOW/GROUP BY below returns real data with no parse
#: errors, at ~3,900 rows/day (up from ~3,000 with the smaller set -- the
#: minute/second timestamp dimensions add real but bounded granularity, not
#: an explosion).
FULFILLMENTS_GROUP_BY = [
    "day", "order_id", "order_name", "fulfillment_id", "order_fulfillment_status",
    "order_payment_status", "shipping_carrier", "fulfillment_provider",
    "shipping_city", "shipping_region", "shipping_country",
    "fulfillment_origin_country", "fulfillment_provider_id", "inventory_location_id",
    "inventory_location_name", "shop_id", "shop_name", "is_b2b_order", "is_canceled_order",
    "order_checkout_currency", "order_includes_duties", "order_sales_channel",
    "order_sales_channel_id", "is_shop_referral_order", "order_landing_page_path",
    "order_landing_page_url", "order_referrer_domain", "order_referrer_name",
    "order_referrer_source", "order_referrer_url", "order_utm_source", "order_utm_campaign",
    "order_utm_medium", "order_utm_content", "order_utm_term",
    "number_of_products_bought_together", "company_id", "company_name", "referring_channel",
    "referring_medium", "referring_platform", "traffic_type", "market",
    "order_cancellation_reason", "order_risk_level", "order_is_shopify_protect_covered",
    "shipping_company", "shipping_postal_code",
    "hour", "hour_of_day", "minute", "month", "month_of_year", "quarter", "second", "week",
    "week_of_year", "year", "fulfillment_event_days", "fulfillment_event_hours",
    "fulfillment_to_shipping_days", "fulfillment_to_shipping_hours", "order_to_delivery_days",
    "order_to_delivery_hours", "order_to_fulfillment_days", "order_to_fulfillment_hours",
    "order_to_shipping_days", "order_to_shipping_hours", "shipping_to_delivery_days",
    "shipping_to_delivery_hours", "shipping_address_id", "inventory_group_id",
    "order_marketing_event_target", "order_marketing_event_type",
    "order_is_shopify_protect_eligible", "order_is_shopify_protect_protected",
]
#: All 16 documented metrics except the 2 Shopify marks deprecated
#: (orders_delivered_fast_rate, orders_shipped_fast_rate).
FULFILLMENTS_METRICS = [
    "orders_fulfilled", "orders_shipped", "orders_delivered",
    "orders_with_tracking_included_rate",
    "median_days_order_to_fulfillment", "median_days_order_to_shipping",
    "median_days_order_to_delivery", "median_days_fulfillment_to_shipping",
    "median_days_shipping_to_delivery",
    "median_hours_order_to_fulfillment", "median_hours_order_to_shipping",
    "median_hours_order_to_delivery", "median_hours_fulfillment_to_shipping",
    "median_hours_shipping_to_delivery",
]
#: Which SQL type each fulfillments field should cast to in
#: app/services/silver/shopify_flatten.py -- boolean/timestamptz fields need
#: a different cast than the text/numeric default, and this is the single
#: source of truth both sides read from conceptually (shopify_flatten.py's
#: copy is kept in sync by hand, see that module's own comment).
FULFILLMENTS_BOOLEAN_COLUMNS = {
    "is_b2b_order", "is_canceled_order", "order_includes_duties", "is_shop_referral_order",
    "order_is_shopify_protect_covered", "order_is_shopify_protect_eligible",
    "order_is_shopify_protect_protected",
}
FULFILLMENTS_TIMESTAMP_COLUMNS = {"hour", "minute", "month", "quarter", "second", "week", "year"}
#: Confirmed live hit exactly 3000/3000 (the LIMIT) at day grain -- true
#: volume is somewhat higher. Kept to single-day chunks (unlike sessions'
#: 3-day chunks) specifically so one generous LIMIT comfortably covers a
#: whole chunk without needing SESSIONS-style multi-day batching.
FULFILLMENTS_CHUNK_DAYS = 1
FULFILLMENTS_LIMIT_PER_CHUNK = 10_000

#: ShopifyQL `customers` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/customers/customers (surveyed 2026-08-26, live-verified). Bronze
#: object_type is "customer_analytics", NOT "customers" -- that name is
#: already taken by the GraphQL Admin API's individual customer records
#: (ORDERS_QUERY-style, object_type="customers", a completely different
#: shape). This table is Shopify's own cohort/RFM/lifetime-value rollup,
#: one row per customer, grouped on customer_id (first_order_date etc. are
#: functionally dependent on the customer, not independent axes -- no
#: cardinality risk). Confirmed live: 765 rows for a 7-day window, RFM
#: segments and spend-tier populated with real values.
CUSTOMER_ANALYTICS_GROUP_BY = [
    "customer_id", "first_order_date", "last_order_date", "customer_email", "customer_name",
    "customer_city", "customer_country", "customer_region", "customer_cohort_month",
    "rfm_group", "predicted_spend_tier", "customer_account_status",
    "customer_email_subscription_status", "customer_sms_subscription_status",
]
CUSTOMER_ANALYTICS_METRICS = [
    "days_since_last_order", "new_customer_records", "total_amount_spent",
    "total_amount_spent_per_order", "total_number_of_orders",
]
CUSTOMER_ANALYTICS_CHUNK_DAYS = 7
CUSTOMER_ANALYTICS_LIMIT_PER_CHUNK = 20_000

#: ShopifyQL `sales` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/sales_revenue/sales. The richest table surveyed -- confirmed
#: live 2026-08-26: real gross/net revenue, but `cost_of_goods_sold` and
#: `gross_profit` came back 0 on every sampled row -- this store has NOT
#: entered per-product cost data in Shopify, so margin metrics are fetched
#: (in case that changes later) but will read as zero, not missing data.
#: Grain: (day, order_id) -- confirmed live ~1,300 rows/day, matching real
#: order volume (line items within an order are summed into one row at
#: this grain, which is what's wanted for order-level revenue, not a
#: line-item breakdown).
SALES_GROUP_BY = ["day", "order_id", "new_or_returning_customer", "is_pos_sale", "cost_is_recorded"]
SALES_METRICS = [
    "gross_sales", "net_sales", "total_sales", "discounts", "shipping_charges", "taxes", "duties",
    "cost_of_goods_sold", "gross_profit", "gross_margin", "orders", "quantity_ordered", "average_order_value",
]
SALES_CHUNK_DAYS = 1
SALES_LIMIT_PER_CHUNK = 10_000

#: ShopifyQL `discounts` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/sales_revenue/discounts. Confirmed live: ~890 rows/day at
#: (day, order_id, discount_code, discount_type) grain -- some orders carry
#: more than one discount line.
DISCOUNTS_GROUP_BY = ["day", "order_id", "discount_code", "discount_type", "discount_method", "discount_class"]
DISCOUNTS_METRICS = [
    "applied_discounts", "discounted_orders", "product_and_order_discounts", "shipping_discounts",
]
DISCOUNTS_CHUNK_DAYS = 1
DISCOUNTS_LIMIT_PER_CHUNK = 10_000

#: ShopifyQL `inventory` table -- shopify.dev/docs/api/shopifyql/2026-10/
#: schemas/inventory/inventory. Confirmed live: ~5,000 rows/day at
#: (day, product_variant_sku) grain -- matches this store's real apparel
#: catalog size (many size/color variants per style).
INVENTORY_GROUP_BY = ["day", "product_variant_sku", "product_title", "product_variant_title", "product_status", "product_type", "product_vendor"]
INVENTORY_METRICS = [
    "ending_inventory_units", "ending_inventory_value", "days_of_inventory_remaining",
    "sell_through_rate", "inventory_units_sold", "starting_inventory_units",
]
INVENTORY_CHUNK_DAYS = 1
INVENTORY_LIMIT_PER_CHUNK = 20_000

#: returns/sales_revenue/returns was checked live (2026-08-26) over an
#: 18-month window (2025-01-01..2026-08-25) and returned ZERO rows --
#: genuinely no return data in Shopify for this store (handled through a
#: different system, not a query bug: both a narrow and wide window came
#: back empty). Deliberately not built -- there's nothing to fetch.

OBJECT_TYPE_QUERIES = {
    "products": (PRODUCTS_QUERY, ["products"]),
    "orders": (ORDERS_QUERY, ["orders"]),
    "customers": (CUSTOMERS_QUERY, ["customers"]),
}
# Which object types need a synthetic GROUP-BY-hash source_id vs a real
# natural-key field vs the GraphQL "id" default -- see
# _GROUP_BY_ROW_KEY_FIELDS/_NATURAL_ID_FIELD_BY_TYPE below, used by
# _build_rows.


# ----------------------------------------------------------------------
# Date-range helpers
# ----------------------------------------------------------------------


def _date_chunks(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    if (end - start).days < chunk_days:
        return [(start, end)]
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _build_search_filter(
    date_start: date | None, date_end: date | None, *, field: str = "updated_at"
) -> str | None:
    """Shopify's connection `query` search syntax -- confirmed live that
    unquoted date values 500 with an internal server error; single-quoted
    ISO date strings work.

    Filters on `updated_at` by default, NOT `created_at`. Filtering on
    creation date silently misses edits to older records: an order
    refunded, cancelled or re-fulfilled today was created months ago, so
    a created_at window would never re-fetch it and bronze would keep
    serving the stale version forever. updated_at is what Shopify
    recommends for sync, and is what makes the incremental watermark
    below correct rather than merely fast.
    """
    if not date_start and not date_end:
        return None
    parts = []
    if date_start:
        parts.append(f"{field}:>='{date_start.isoformat()}'")
    if date_end:
        parts.append(f"{field}:<='{date_end.isoformat()}'")
    return " AND ".join(parts)


#: Object types whose fetch can be resumed from a watermark. ShopifyQL
#: tables are excluded: they already take an explicit date range and are
#: re-derived per day, so there is nothing to resume.
_INCREMENTAL_OBJECT_TYPES = {"orders", "customers", "products"}

#: Days of overlap re-fetched either side of the watermark. Absorbs clock
#: skew between Shopify and this database, and records edited during the
#: previous run's own walk. Re-fetching a day costs nothing: the write is
#: an upsert on (object_type, source_id), so an unchanged record is
#: updated in place rather than duplicated.
INCREMENTAL_OVERLAP_DAYS = 1


async def _resolve_incremental_start(
    database_url: str | None, table: str, object_type: str
) -> date | None:
    """Newest extracted_at already in bronze for this object type, minus
    the overlap, or None to mean "fetch everything".

    Returns None -- i.e. falls back to a full walk -- when bronze is
    empty for this type, when there is no database to ask, or on any
    error reading it. Fetching too much is slow; fetching too little is
    silent data loss, so every failure mode here errs toward the full
    walk.
    """
    if not database_url:
        return None
    try:
        import asyncpg
        conn = await asyncpg.connect(_to_asyncpg_dsn(database_url), statement_cache_size=0)
        try:
            newest = await conn.fetchval(
                f'SELECT MAX(extracted_at) FROM "{table}" WHERE object_type = $1',
                object_type,
            )
        finally:
            await conn.close()
    except Exception as exc:
        print(f"    [incremental] {object_type}: could not read watermark "
              f"({type(exc).__name__}: {exc}) -- falling back to full history")
        return None
    if newest is None:
        print(f"    [incremental] {object_type}: bronze empty -- full history")
        return None
    start = newest.date() - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    print(f"    [incremental] {object_type}: newest bronze row {newest:%Y-%m-%d %H:%M} "
          f"-> fetching updated_at >= {start} ({INCREMENTAL_OVERLAP_DAYS}d overlap)")
    return start


# ----------------------------------------------------------------------
# Fetch orchestration
# ----------------------------------------------------------------------


@dataclass
class FetchResult:
    store: ShopifyStore
    object_type: str
    items: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None


async def _fetch_shop(client: httpx.AsyncClient, store: ShopifyStore) -> FetchResult:
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type="shop")
    try:
        data = await graphql_request(client, store, SHOP_QUERY)
        result.items = [data["shop"]]
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _hydrate_product_variants(
    client: httpx.AsyncClient,
    store: ShopifyStore,
    products: list[dict[str, Any]],
) -> int:
    """Complete the variant list of any product PRODUCTS_QUERY truncated.

    The bulk query asks for `variants(first: VARIANTS_PAGE_SIZE)`; a
    product with more variants than that comes back with only the first
    page and `hasNextPage: true`. Nothing downstream can tell a truncated
    list from a complete one, so every per-variant rollup built on
    raw_dump_shopify -- units in stock, in-stock rates, the price ladder
    Selling Price is drawn from -- would silently under-count on exactly
    the widest products.

    Re-walks the affected product's variants as a standalone connection
    and REPLACES the truncated edge list with the full one. We refetch
    from the start rather than resuming at the first page's endCursor:
    paginate_connection() has no initial-cursor parameter, and at this
    catalogue's size the saved round-trip isn't worth widening a shared
    helper for. Mutates the product dicts in place -- they're the same
    objects paginate_connection() accumulates and hands to on_page.

    Returns the number of products that needed completing.
    """
    hydrated = 0
    for product in products:
        connection = product.get("variants") or {}
        if not (connection.get("pageInfo") or {}).get("hasNextPage"):
            continue
        product_id = product.get("id")
        if not product_id:
            continue
        all_variants = await paginate_connection(
            client, store, PRODUCT_VARIANTS_QUERY, ["product", "variants"],
            page_size=VARIANT_HYDRATE_PAGE_SIZE,
            variables={"id": product_id},
        )
        connection["edges"] = [{"node": node} for node in all_variants]
        # hasNextPage is now false by construction; leaving it true would
        # make a re-run think this product still needs hydrating.
        connection["pageInfo"] = {"hasNextPage": False, "endCursor": None}
        hydrated += 1
        # This module reports progress with print(), not a logger.
        print(
            f"    [variants] product {product_id} exceeded {VARIANTS_PAGE_SIZE} "
            f"variants -- refetched {len(all_variants)} in full"
        )
    return hydrated


async def _fetch_object_type(
    client: httpx.AsyncClient,
    store: ShopifyStore,
    object_type: str,
    *,
    page_size: int,
    max_pages: int | None,
    date_start: date | None,
    date_end: date | None,
    on_page: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> FetchResult:
    query, path = OBJECT_TYPE_QUERIES[object_type]
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type=object_type)

    page_callback = on_page
    if object_type == "products":
        # Hydrate BEFORE the caller's on_page runs -- on_page is what
        # writes the page to bronze, so a truncated variant list written
        # there would persist until the next full ingest.
        async def page_callback(nodes: list[dict[str, Any]]) -> None:  # noqa: F811
            await _hydrate_product_variants(client, store, nodes)
            if on_page:
                await on_page(nodes)

    try:
        search_filter = _build_search_filter(date_start, date_end)
        result.items = await paginate_connection(
            client, store, query, path, page_size=page_size, max_pages=max_pages,
            variables={"query": search_filter}, on_page=page_callback,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


#: (object_type, ShopifyQL FROM table, group_by fields, metric fields,
#: chunk_days, limit_per_chunk, order_by) for every aggregated ShopifyQL
#: object type this script fetches -- one shared fetch function
#: (_fetch_shopifyql_table below) reads this instead of six near-identical
#: per-table functions. `order_by` is None for every table except sessions
#: (kept for backward-compatible output ordering, not required by any of
#: the others).
_SHOPIFYQL_TABLE_CONFIG: dict[str, dict[str, Any]] = {
    "sessions": {
        "table": "sessions", "group_by": SESSIONS_GROUP_BY, "metrics": SESSIONS_METRICS,
        "chunk_days": SESSIONS_CHUNK_DAYS, "limit_per_chunk": SESSIONS_LIMIT_PER_CHUNK, "order_by": "day",
    },
    "fulfillments": {
        "table": "fulfillments", "group_by": FULFILLMENTS_GROUP_BY, "metrics": FULFILLMENTS_METRICS,
        "chunk_days": FULFILLMENTS_CHUNK_DAYS, "limit_per_chunk": FULFILLMENTS_LIMIT_PER_CHUNK, "order_by": None,
    },
    "customer_analytics": {
        "table": "customers", "group_by": CUSTOMER_ANALYTICS_GROUP_BY, "metrics": CUSTOMER_ANALYTICS_METRICS,
        "chunk_days": CUSTOMER_ANALYTICS_CHUNK_DAYS, "limit_per_chunk": CUSTOMER_ANALYTICS_LIMIT_PER_CHUNK, "order_by": None,
    },
    "sales": {
        "table": "sales", "group_by": SALES_GROUP_BY, "metrics": SALES_METRICS,
        "chunk_days": SALES_CHUNK_DAYS, "limit_per_chunk": SALES_LIMIT_PER_CHUNK, "order_by": None,
    },
    "discounts": {
        "table": "discounts", "group_by": DISCOUNTS_GROUP_BY, "metrics": DISCOUNTS_METRICS,
        "chunk_days": DISCOUNTS_CHUNK_DAYS, "limit_per_chunk": DISCOUNTS_LIMIT_PER_CHUNK, "order_by": None,
    },
    "inventory": {
        "table": "inventory", "group_by": INVENTORY_GROUP_BY, "metrics": INVENTORY_METRICS,
        "chunk_days": INVENTORY_CHUNK_DAYS, "limit_per_chunk": INVENTORY_LIMIT_PER_CHUNK, "order_by": None,
    },
}


async def _fetch_shopifyql_table(
    client: httpx.AsyncClient, store: ShopifyStore, object_type: str, date_start: date, date_end: date,
    *, on_chunk: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> FetchResult:
    """Shared fetch loop for every aggregated ShopifyQL object type (see
    _SHOPIFYQL_TABLE_CONFIG) -- date-chunked SINCE/UNTIL, GROUP BY, a
    generous per-chunk LIMIT with a truncation warning if actually hit.

    `on_chunk`, if given, is awaited with each chunk's rows right after
    that chunk is fetched, so a caller spanning many chunks (e.g. a
    full-year range at chunk_days=1) can write to the DB as it goes
    instead of holding everything in memory until the whole range is
    done. The full accumulated result is still returned either way."""
    cfg = _SHOPIFYQL_TABLE_CONFIG[object_type]
    t0 = time.monotonic()
    result = FetchResult(store=store, object_type=object_type)
    show_cols = ", ".join(cfg["group_by"] + cfg["metrics"])
    group_by = ", ".join(cfg["group_by"])
    order_by_clause = f" ORDER BY {cfg['order_by']}" if cfg["order_by"] else ""
    try:
        for chunk_start, chunk_end in _date_chunks(date_start, date_end, cfg["chunk_days"]):
            q = (
                f"FROM {cfg['table']} SHOW {show_cols} "
                f"SINCE {chunk_start.isoformat()} UNTIL {chunk_end.isoformat()} "
                f"GROUP BY {group_by}{order_by_clause} LIMIT {cfg['limit_per_chunk']}"
            )
            data = await graphql_request(client, store, SHOPIFYQL_QUERY, {"q": q})
            resp = data["shopifyqlQuery"]
            if resp.get("parseErrors"):
                raise RuntimeError(f"ShopifyQL parse errors: {resp['parseErrors']}")
            table_data = resp.get("tableData")
            rows = table_data["rows"] if table_data else []
            if len(rows) >= cfg["limit_per_chunk"]:
                print(
                    f"    [warning] {object_type} chunk {chunk_start}..{chunk_end} hit the "
                    f"{cfg['limit_per_chunk']}-row limit -- some rows may be missing"
                )
            result.items.extend(rows)
            if on_chunk and rows:
                await on_chunk(rows)
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _run(
    stores: list[ShopifyStore],
    object_types: list[str],
    *,
    page_size: int,
    max_pages: int | None,
    date_start: date | None,
    date_end: date | None,
    incremental: bool = False,
    database_url: str | None = None,
    table: str = "raw_dump_shopify",
) -> list[FetchResult]:
    # SEQUENTIAL, in the caller's object_types order -- deliberately not
    # asyncio.gather any more.
    #
    # Shopify rate-limits per SHOP, not per connection, so running the
    # object types concurrently just makes them fight over one bucket.
    # Run #7 (2026-09-04) fetched products, inventory and orders in
    # parallel and spent its time like this:
    #
    #     inventory  OK      227,475 rows   588.92s
    #     products   OK        1,054 rows    10.45s
    #     orders     FAILED        0 rows  1079.11s
    #     wall time (all 3 in parallel): 1079.15s
    #     ... with 10x "throttled (attempt 1/4), sleeping ~55s"
    #
    # Serialising costs nothing in throughput when the limiter is the
    # bottleneck -- and it buys two things worth more: the throttle
    # storm goes away, and the caller's cheapest-first ordering finally
    # means something, so a run killed part-way has still fetched the
    # cheap, high-value types (products lands in ~10s) instead of
    # spreading its failure across all three.
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    results: list[FetchResult] = []
    async with httpx.AsyncClient(limits=limits) as client:
        for store in stores:
            for object_type in object_types:
                if object_type == "shop":
                    results.append(await _fetch_shop(client, store))
                elif object_type in _SHOPIFYQL_TABLE_CONFIG:
                    ql_start = date_start or (datetime.now(timezone.utc).date() - timedelta(days=30))
                    ql_end = date_end or datetime.now(timezone.utc).date()
                    results.append(
                        await _fetch_shopifyql_table(client, store, object_type, ql_start, ql_end)
                    )
                else:
                    # An explicit --date-start always wins; the watermark
                    # only fills in when the caller didn't pin a range.
                    effective_start = date_start
                    if incremental and date_start is None and object_type in _INCREMENTAL_OBJECT_TYPES:
                        effective_start = await _resolve_incremental_start(
                            database_url, table, object_type
                        )
                    results.append(
                        await _fetch_object_type(
                            client, store, object_type, page_size=page_size,
                            max_pages=max_pages, date_start=effective_start, date_end=date_end,
                        )
                    )
                print(f"    [done] {object_type}: {len(results[-1].items)} rows "
                      f"in {results[-1].duration_seconds:.1f}s"
                      + (f" -- FAILED: {results[-1].error}" if results[-1].error else ""))
    return results


async def run_for_admin(
    stores: list[ShopifyStore],
    object_types: list[str],
    database_url: str,
    table: str,
    *,
    api_version: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    date_start: date | None,
    date_end: date | None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    """Admin-panel-triggered entry point (see app/api/routers/admin.py's
    `_run_shopify`, mirroring `_run_instagram`'s use of
    ingest_instagram_chronological.py's `_run()`). Unlike `_run()` above
    (fetch everything in parallel, THEN write everything, used by the CLI's
    timing-focused main()), this fetches AND writes each (store,
    object_type) unit one at a time so `on_progress` can report real
    incremental status -- a long Jan-Aug fetch shouldn't look frozen at 0%
    until the very end. Returns True if every unit succeeded.

    `on_progress` receives one dict per completed unit: `{"account": store
    key, "edge": object_type, "status": "succeeded"|"failed",
    "items_so_far": int, "inserted_so_far": int, "error": str | None}` --
    same shape as ingest_instagram_chronological.py's callback, so
    admin.py's existing `LevelStatus`/`SourceStatus` handling needs no
    changes to accept it.

    Writes happen batch-wise, not once per unit: the ShopifyQL tables
    write after every date chunk and the cursor-paginated types (orders/
    products/customers) write after every page, via `on_chunk`/`on_page`
    callbacks into `_write_batch` below -- so `on_progress` (and the DB
    itself) update continuously through a long fetch instead of going
    silent until an entire (store, object_type) unit -- which can span a
    full year and hundreds of chunks/pages -- finishes. `shop` is a
    single-item fetch, so it just writes once, same as before."""
    import asyncpg  # imported lazily -- only needed on a real (non-dry-run) run

    # statement_cache_size=0 is REQUIRED when DATABASE_URL points at
    # Supabase's pgbouncer (transaction mode). Without it, pgbouncer
    # rotates the underlying Postgres backend between transactions and
    # asyncpg's per-connection prepared-statement cache references a
    # __asyncpg_stmt_N__ that the next backend has never seen ->
    # "prepared statement does not exist" mid-write, dropping the
    # whole batch. Live-caught 2026-09-02 mid-orders-insert.
    conn = await asyncpg.connect(
        _to_asyncpg_dsn(database_url),
        statement_cache_size=0,
    )
    any_error = False
    items_so_far = 0
    inserted_so_far = 0
    try:
        await _ensure_unique_index(conn)
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        async with httpx.AsyncClient(limits=limits) as client:
            for store in stores:

                async def _write_batch(object_type: str, batch_items: list[dict[str, Any]]) -> None:
                    nonlocal items_so_far, inserted_so_far
                    batch_result = FetchResult(store=store, object_type=object_type, items=batch_items)
                    rows = _build_rows(
                        batch_result, batch_id=uuid.uuid4(), api_version=api_version,
                        extracted_at=datetime.now(timezone.utc),
                    )
                    written = await _insert_rows(conn, table, rows)
                    items_so_far += len(batch_items)
                    inserted_so_far += written
                    if on_progress:
                        on_progress({
                            "account": store.key, "edge": object_type, "status": "succeeded",
                            "items_so_far": items_so_far, "inserted_so_far": inserted_so_far,
                        })

                # Built in the CALLER'S object_types order, and run
                # sequentially below. It used to be grouped by kind --
                # shop, then every ShopifyQL table, then the GraphQL
                # connections -- which silently ignored the order asked
                # for. `--object-types products,inventory,orders` ran
                # INVENTORY first (a ShopifyQL table, ~1.28M rows)
                # because of the grouping, so `products` -- 635 rows,
                # seconds of work, and the source of Units in Stock and
                # Selling Price -- sat behind the heaviest fetch in the
                # set and never landed when the step hit its timeout.
                #
                # Honouring the given order lets the caller put the
                # cheap, high-value object types first, so a run that
                # is later killed has still committed the things that
                # matter. Writes are per page/chunk, so partial
                # progress is real progress.
                units: list[tuple[str, Callable[[], Any], bool]] = []
                for object_type in object_types:
                    if object_type == "shop":
                        units.append(("shop", lambda: _fetch_shop(client, store), False))
                    elif object_type in _SHOPIFYQL_TABLE_CONFIG:
                        ql_start = date_start or (datetime.now(timezone.utc).date() - timedelta(days=30))
                        ql_end = date_end or datetime.now(timezone.utc).date()
                        units.append((
                            object_type,
                            lambda ot=object_type, s=ql_start, e=ql_end: _fetch_shopifyql_table(
                                client, store, ot, s, e, on_chunk=lambda rows, ot=ot: _write_batch(ot, rows),
                            ),
                            True,
                        ))
                    else:
                        units.append((
                            object_type,
                            lambda ot=object_type: _fetch_object_type(
                                client, store, ot, page_size=page_size, max_pages=max_pages,
                                date_start=date_start, date_end=date_end,
                                on_page=lambda rows, ot=ot: _write_batch(ot, rows),
                            ),
                            True,
                        ))
                print("    [order] " + " -> ".join(ot for ot, _, _ in units))

                for object_type, fetch_fn, batched in units:
                    result = await fetch_fn()
                    if result.error:
                        any_error = True
                        _log_fetch_error(result)
                        if on_progress:
                            on_progress({
                                "account": store.key, "edge": object_type, "status": "failed",
                                "items_so_far": items_so_far, "inserted_so_far": inserted_so_far,
                                "error": result.error,
                            })
                        continue

                    if batched:
                        # Already written incrementally via _write_batch (on_chunk/on_page).
                        # An empty-range unit (zero chunks/pages had rows) never fired a
                        # progress event above -- emit one now so the admin UI still shows
                        # this unit as done rather than stuck.
                        if not result.items and on_progress:
                            on_progress({
                                "account": store.key, "edge": object_type, "status": "succeeded",
                                "items_so_far": items_so_far, "inserted_so_far": inserted_so_far,
                            })
                        continue

                    rows = _build_rows(
                        result, batch_id=uuid.uuid4(), api_version=api_version,
                        extracted_at=datetime.now(timezone.utc),
                    )
                    written = await _insert_rows(conn, table, rows)
                    items_so_far += len(result.items)
                    inserted_so_far += written
                    if on_progress:
                        on_progress({
                            "account": store.key, "edge": object_type, "status": "succeeded",
                            "items_so_far": items_so_far, "inserted_so_far": inserted_so_far,
                        })
    finally:
        await conn.close()
    return not any_error


# ----------------------------------------------------------------------
# Bronze row shaping (same envelope as raw_dump_meta / dump_instagram --
# see scripts/sql/raw_dump_shopify.sql)
# ----------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: ShopifyQL object types that have no single natural id field -- their
#: identity IS their GROUP BY dimensions, so a stable hash of those (not
#: the whole row, which also carries metrics that legitimately change on
#: refresh) is the closest analog to source_id. Each entry's prefix keeps
#: hashes from different tables visually distinguishable in the DB.
_GROUP_BY_ROW_KEY_FIELDS: dict[str, tuple[str, list[str]]] = {
    "sessions": ("sess", SESSIONS_GROUP_BY),
    "discounts": ("disc", DISCOUNTS_GROUP_BY),
    "inventory": ("inv", INVENTORY_GROUP_BY),
}


def _group_by_row_key(item: dict[str, Any], object_type: str) -> str:
    prefix, group_by_fields = _GROUP_BY_ROW_KEY_FIELDS[object_type]
    dims = {k: item.get(k) for k in group_by_fields}
    canonical = json.dumps(dims, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


#: ShopifyQL object types that DO have a real natural key, just under a
#: field name other than "id" (the GraphQL Admin API convention this
#: function otherwise assumes).
_NATURAL_ID_FIELD_BY_TYPE = {
    "fulfillments": "fulfillment_id",
    "customer_analytics": "customer_id",
    "sales": "order_id",
}


def _build_rows(
    result: FetchResult, *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime
) -> list[dict[str, Any]]:
    rows = []
    for item in result.items:
        if result.object_type in _GROUP_BY_ROW_KEY_FIELDS:
            source_id = _group_by_row_key(item, result.object_type)
        elif result.object_type in _NATURAL_ID_FIELD_BY_TYPE:
            source_id = item.get(_NATURAL_ID_FIELD_BY_TYPE[result.object_type])
        else:
            source_id = item.get("id")

        # A NULL source_id silently defeats deduplication. _insert_rows
        # upserts with `ON CONFLICT (object_type, source_id) WHERE
        # source_id IS NOT NULL`, and the backing unique index is partial
        # on the same predicate -- so a row whose natural key is missing
        # matches no conflict target and is INSERTED FRESH ON EVERY RUN,
        # accumulating one duplicate per run forever, silently.
        #
        # The natural key can genuinely be absent: item.get("id") for a
        # payload without one, or the order_id / fulfillment_id /
        # customer_id in _NATURAL_ID_FIELD_BY_TYPE being null on an
        # aggregate or guest row. Measured 2026-09-04: 20 object types in
        # raw_dump_shopify already carry a NULL source_id (one row each,
        # from a single discovery run) -- every one of them would have
        # duplicated on a second run.
        #
        # Falling back to the payload hash keeps the key DETERMINISTIC on
        # content, so re-fetching an unchanged row upserts onto itself
        # instead of duplicating. A changed payload legitimately becomes
        # a new row, which is the honest outcome when there is no natural
        # identity to update in place.
        if source_id is None or source_id == "":
            source_id = f"sha_{_hash_payload(item)[:32]}"

        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "raw_payload": item,
                "api_endpoint": result.object_type,
                "api_version": api_version,
                "batch_id": str(batch_id),
                "request_params": {"object_type": result.object_type},
                "extracted_at": extracted_at.isoformat(),
                "sync_type": "manual",
                "payload_hash": _hash_payload(item),
                "processing_status": "pending",
                "object_type": result.object_type,
                "parent_ids": {
                    "store_key": result.store.key,
                    "store_name": result.store.name,
                    "store_domain": result.store.domain,
                },
                "is_nested": False,
            }
        )
    return rows


def _log_fetch_error(result: FetchResult) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    block = (
        f"=== {timestamp} | store={result.store.key} ({result.store.name}) | "
        f"object_type={result.object_type} ===\nError: {result.error}\n\n"
    )
    print(f"    [error] store={result.store.key} object_type={result.object_type} -- logged to {ERROR_LOG_PATH.relative_to(REPO_ROOT)}")
    ERROR_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(ERROR_LOG_PATH, "a") as f:
        f.write(block)


# ----------------------------------------------------------------------
# Supabase REST Data API helpers -- kept only for
# scripts/ingest_shopify_all_objects.py's exploratory one-sample-row sweep
# (which imports these directly), no longer used by this script's own
# main() path below (see the direct-Postgres section that follows).
# ----------------------------------------------------------------------


def _resolve_supabase_creds() -> tuple[str, str] | None:
    supabase_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("DATABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not service_role_key:
        print(
            "A Supabase project URL (DATABASE_URL or SUPABASE_URL) and a service-role key "
            "(DATABASE_SERVICE_KEY, SUPABASE_KEY, or SUPABASE_SERVICE_ROLE_KEY) must both be set in .env.",
            file=sys.stderr,
        )
        return None
    if not supabase_url.startswith("http"):
        print(f"'{supabase_url}' doesn't look like a Supabase project URL.", file=sys.stderr)
        return None
    return supabase_url, service_role_key


async def _check_table_exists(client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str) -> bool:
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    resp = await client.get(
        f"{supabase_url.rstrip('/')}/rest/v1/{table}", headers=headers, params={"limit": "0"}, timeout=30.0
    )
    return resp.status_code == 200


async def _insert_rows_supabase(
    client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str,
    rows: list[dict[str, Any]], *, chunk_size: int,
) -> int:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
    inserted = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        resp = await client.post(endpoint, headers=headers, json=chunk, timeout=60.0)
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase insert failed ({resp.status_code}): {resp.text[:500]}")
        inserted += len(chunk)
    return inserted


# ----------------------------------------------------------------------
# Direct-Postgres write (asyncpg -- mirrors ingest_instagram_chronological.py
# exactly, see that module's docstring for why direct Postgres over PostgREST)
# ----------------------------------------------------------------------


def _to_asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


#: Created lazily on first write, same "safe to call every time" idiom
#: used throughout app/services/silver/ -- lets upsert-in-place work
#: (refreshing an order's financial_status, a customer's amount_spent, a
#: session-aggregate's counts) instead of duplicating a row every re-fetch.
_ENSURE_UNIQUE_INDEX_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_dump_shopify_object_type_source_id '
    'ON raw_dump_shopify (object_type, source_id) WHERE source_id IS NOT NULL'
)


async def _ensure_unique_index(conn: Any) -> None:
    await conn.execute(_ENSURE_UNIQUE_INDEX_SQL)


async def _insert_rows(conn: Any, table: str, rows: list[dict[str, Any]], *, chunk_size: int = 500) -> int:
    """Upserts on (object_type, source_id) -- same target semantics as
    ingest_instagram_chronological.py's `_insert_rows` (order
    financial_status/fulfillment_status, customer amount_spent/
    numberOfOrders, and session-aggregate counts all legitimately change
    after first fetch, so refreshing in place beats accumulating stale
    duplicate snapshots), but batched via `executemany` instead of one
    `fetchval` round-trip per row -- confirmed live a ~5,000-row sessions
    chunk took over 60s round-tripping one row at a time to the remote
    Supabase Postgres; batching is required for sessions' realistic volume.
    Trades away the inserted-vs-updated split Instagram's version reports
    (only obtainable per-row via RETURNING) for a total-rows-written count,
    which is what actually matters for a Bronze ingestion log."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
    update_cols = [c for c in columns if c not in ("id", "source_id", "object_type")]
    update_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols) + ', "ingested_at" = now()'
    sql = (
        f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders}) '
        f'ON CONFLICT (object_type, source_id) WHERE source_id IS NOT NULL '
        f'DO UPDATE SET {update_clause}'
    )
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        values_batch = [
            [
                uuid.UUID(row[c]) if c in ("id", "batch_id") else
                json.dumps(row[c]) if c in ("raw_payload", "request_params", "parent_ids") and row[c] is not None else
                datetime.fromisoformat(row[c]) if c == "extracted_at" else
                row[c]
                for c in columns
            ]
            for row in chunk
        ]
        await conn.executemany(sql, values_batch)
        total += len(chunk)
    return total


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=None, help="Restrict to one store key. Default: every configured store.")
    parser.add_argument(
        "--object-types", default=",".join(DEFAULT_OBJECT_TYPES),
        help=f"Comma-separated object types to fetch (default: all -- {','.join(DEFAULT_OBJECT_TYPES)}).",
    )
    parser.add_argument("--date-start", type=date.fromisoformat, default=None, help="ISO date, e.g. 2026-01-01. Omit to fetch full history (orders/products/customers) or the last 30 days (sessions).")
    parser.add_argument("--date-end", type=date.fromisoformat, default=None, help="ISO date, defaults to today.")
    parser.add_argument(
        "--incremental", action="store_true",
        help="For orders/customers/products, fetch only records whose updated_at is "
             "at or after the newest row already in the target table (minus "
             f"{INCREMENTAL_OVERLAP_DAYS}d overlap). Falls back to full history when the "
             "table is empty or the watermark can't be read. Ignored when --date-start "
             "is given.")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help=f"Items per GraphQL page (default {DEFAULT_PAGE_SIZE}).")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap pages per (store, object_type) -- useful for a quick trial on a large store.")
    parser.add_argument("--table", default="raw_dump_shopify", help="Target table (default: raw_dump_shopify).")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the write.")
    args = parser.parse_args()

    object_types = [t.strip() for t in args.object_types.split(",") if t.strip()]
    unknown = set(object_types) - set(DEFAULT_OBJECT_TYPES)
    if unknown:
        print(f"Unknown object type(s): {sorted(unknown)}. Valid: {DEFAULT_OBJECT_TYPES}", file=sys.stderr)
        return 1

    if load_dotenv is not None:
        load_dotenv()

    stores_by_key = discover_stores()
    if not stores_by_key:
        print(
            "No Shopify stores configured. Set at least SHOPIFY_STORE_1_DOMAIN and "
            "SHOPIFY_STORE_1_ACCESS_TOKEN (or SHOP_DOMAIN/ADMIN_ACCESS_TOKEN) in .env.",
            file=sys.stderr,
        )
        return 1
    if args.store:
        if args.store not in stores_by_key:
            print(f"No store with key '{args.store}'. Configured: {', '.join(sorted(stores_by_key, key=int))}", file=sys.stderr)
            return 1
        stores = [stores_by_key[args.store]]
    else:
        stores = [stores_by_key[k] for k in sorted(stores_by_key, key=int)]

    database_url = None
    if not args.no_insert:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url or not database_url.startswith("postgresql"):
            print(
                "DATABASE_URL must be a real postgresql(+asyncpg):// connection string to write -- "
                "use --no-insert to run without one.",
                file=sys.stderr,
            )
            return 1

    api_version = os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)

    print("Stores: " + ", ".join(describe_store_safely(s) for s in stores))
    print(f"Object types: {object_types}")
    if args.date_start:
        print(f"Date range: {args.date_start} .. {args.date_end or 'today'} (explicit, on updated_at)")
    elif args.incremental:
        print(f"Date range: incremental -- per-type watermark from {args.table}, "
              f"{INCREMENTAL_OVERLAP_DAYS}d overlap, on updated_at")
    else:
        print(f"Date range: (full history) .. {args.date_end or 'today'}")
    print(f"Page size: {args.page_size}" + (f"  max_pages: {args.max_pages}" if args.max_pages else ""))
    if database_url:
        print(f"Target table: {args.table}")
    else:
        print("--no-insert set: fetching and timing only, no write.")
    print("Access token(s): [redacted, not printed] -- loaded, present, not shown.\n")

    exit_code = asyncio.run(
        _run_and_report(
            stores, object_types, database_url, args.table,
            page_size=args.page_size, max_pages=args.max_pages,
            date_start=args.date_start, date_end=args.date_end,
            api_version=api_version, no_insert=args.no_insert,
            incremental=args.incremental,
        )
    )
    return exit_code


async def _run_and_report(
    stores: list[ShopifyStore],
    object_types: list[str],
    database_url: str | None,
    table: str,
    *,
    page_size: int,
    max_pages: int | None,
    date_start: date | None,
    date_end: date | None,
    api_version: str,
    no_insert: bool,
    incremental: bool = False,
) -> int:
    """CLI-only wrapper around `_run()`'s async core, adding the printed
    summary + write step -- kept separate from `_run()` itself so
    admin.py's `_run_shopify` (mirroring `_run_instagram`) can call `_run()`
    directly with its own on_progress callback instead of going through
    this print-heavy path."""
    fetch_start = time.monotonic()
    results = await _run(
        stores, object_types, page_size=page_size, max_pages=max_pages,
        date_start=date_start, date_end=date_end,
        incremental=incremental, database_url=database_url, table=table,
    )
    fetch_wall_time = time.monotonic() - fetch_start

    print("Fetch results:")
    total_rows = 0
    any_error = False
    for r in results:
        status = "OK" if not r.error else "FAILED"
        print(f"  [{r.store.key}] {r.store.name:<24} {r.object_type:<10} {status:<7} {len(r.items):>6} rows  {r.duration_seconds:6.2f}s")
        if r.error:
            any_error = True
            _log_fetch_error(r)
        total_rows += len(r.items)

    print(f"\nShopify fetch wall time ({len(results)} calls, sequential): {fetch_wall_time:.2f}s")
    print(f"Total rows fetched: {total_rows}")

    if no_insert:
        print("\n--no-insert set -- stopping before any write.")
        return 1 if any_error else 0

    import asyncpg  # imported lazily -- only needed on a real (non-dry-run) run

    # statement_cache_size=0 is REQUIRED when DATABASE_URL points at
    # Supabase's pgbouncer (transaction mode). Without it, pgbouncer
    # rotates the underlying Postgres backend between transactions and
    # asyncpg's per-connection prepared-statement cache references a
    # __asyncpg_stmt_N__ that the next backend has never seen ->
    # "prepared statement does not exist" mid-write, dropping the
    # whole batch. Live-caught 2026-09-02 mid-orders-insert.
    conn = await asyncpg.connect(
        _to_asyncpg_dsn(database_url),
        statement_cache_size=0,
    )
    write_start = time.monotonic()
    total_written = 0
    write_any_error = False
    try:
        await _ensure_unique_index(conn)
        extracted_at = datetime.now(timezone.utc)
        for r in results:
            if r.error:
                write_any_error = True
                continue
            batch_id = uuid.uuid4()
            rows = _build_rows(r, batch_id=batch_id, api_version=api_version, extracted_at=extracted_at)
            written = await _insert_rows(conn, table, rows)
            total_written += written
            print(f"  [{r.store.key}] {r.store.name:<24} {r.object_type:<10} wrote {written} rows")
    finally:
        await conn.close()
    write_wall_time = time.monotonic() - write_start

    print(f"\nWrite time: {write_wall_time:.2f}s")
    print(f"Total rows written: {total_written} into {table}")
    print(f"\nGrand total (fetch + write): {fetch_wall_time + write_wall_time:.2f}s")

    return 1 if (any_error or write_any_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
