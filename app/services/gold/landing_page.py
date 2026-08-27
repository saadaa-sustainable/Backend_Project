"""Gold layer: landing-page performance -- ported from the legacy Creative
Testing Dashboard's `landing_page_sessions_daily` / `landing_page_analysis_30d`
/ `landing_page_ad_breakdown_30d` tables. The legacy logic for these does
NOT live in the git repo (`saadaa-sustainable/Creative_Testing_Dashboard`) --
it's three Postgres functions (`_lpa_normalize_ad_link`,
`_lpa_normalize_session_path`, `refresh_landing_page_analysis_30d`,
`refresh_landing_page_ad_breakdown_30d`) that exist only in the live
`Meta_ads_data` Supabase project, pulled via direct SQL introspection
(`pg_get_functiondef`) 2026-08-27 and ported here faithfully.

Per user instruction (2026-08-27): prefer Python over long SQL for any
step with real logical/branching complexity -- path normalization here is
exactly that (regex + conditional host-allowlist), so it's a Python
function (`normalize_ad_link`/`normalize_session_path`), not a chain of
`regexp_replace`. Aggregation itself is a plain SUM/GROUP BY with no
branching, so that part stays a normal SQL insert (same as every other
Gold table in this project).

Grain and ad-linking mechanism, carried over exactly from legacy:
- landing_page_sessions_daily: (session_date, landing_page_path) daily
  rollup of session counts. Legacy sourced this from a SEPARATE Shopify
  Supabase project via a cross-project RPC call
  (`get_landing_page_sessions_agg`); this project already has the same
  raw session counts in `shopify_sessions` (Silver, same DB) at a finer
  grain (day, path, referrer/utm dims) -- no cross-project call needed,
  just summed down to (day, path).
- landing_page_analysis_30d: 30-day rolling session-vs-ad-spend rollup per
  page. Ad side keys off the ad CREATIVE's own `link_url`/`object_url`
  (normalized), NOT UTM matching -- an ad whose creative links to
  /collections/x counts toward that page regardless of what UTMs an order
  or session carries. This is a materially different (and more direct)
  mechanism than this project's existing `shopify_landing_page_analysis`
  (UTM-campaign-based) -- both are kept; they answer different questions.
- landing_page_ad_breakdown_30d: same 30-day window, one row per
  (page, ad) instead of per page -- adds Shopify-attributed orders/sales
  from shopify_order_attribution (this project's equivalent of legacy's
  shopify_ad_attribution, same has_match/ad_id shape).

Ad link_url source: raw_dump_meta object_type='ad' rows fetched with
`request_params={"include_creative_expansion": True}` (AD_URL_TRACKING_FIELDS,
app/core/meta_registry.py) -- written but never triggered before this;
run once via a one-off script, latest-per-ad_id read directly here rather
than adding link_url/preview_link columns to the shared meta_ads Silver
table (keeps this Gold module self-contained, avoids widening a table
several other jobs depend on for three landing-page-only columns).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

# ----------------------------------------------------------------------
# Path normalization -- ported verbatim from _lpa_normalize_ad_link /
# _lpa_normalize_session_path (live Meta_ads_data Postgres functions).
# ----------------------------------------------------------------------

_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)
_SAADAA_HOST_RE = re.compile(r"^https?://(www\.)?saadaa\.in/", re.IGNORECASE)
_SCHEME_HOST_RE = re.compile(r"^https?://[^/]+", re.IGNORECASE)
_QUERY_FRAGMENT_RE = re.compile(r"[?#].*$")
_TRAILING_SLASH_RE = re.compile(r"(.+)/$")


def normalize_ad_link(url: str | None) -> str | None:
    """Port of `_lpa_normalize_ad_link`: only saadaa.in URLs are tracked
    (drops fb.com/canvas_doc, m.me/*, and any other host); strips scheme
    + host, query string, fragment, and a trailing slash (but keeps a
    bare '/' as-is via the "not the root" guard in the trailing-slash
    strip, same as the SQL regex `(.+)/$` which requires ≥1 char before
    the slash)."""
    if not url or not _HTTP_RE.match(url):
        return None
    if not _SAADAA_HOST_RE.match(url):
        return None
    path = _SCHEME_HOST_RE.sub("", url)
    path = _QUERY_FRAGMENT_RE.sub("", path)
    match = _TRAILING_SLASH_RE.match(path)
    if match:
        path = match.group(1)
    return path or None


def normalize_session_path(path: str | None) -> str | None:
    """Port of `_lpa_normalize_session_path`: keeps a bare '/' as-is,
    strips a trailing slash from anything else."""
    if not path:
        return None
    if path == "/":
        return "/"
    match = _TRAILING_SLASH_RE.match(path)
    return match.group(1) if match else path


# ----------------------------------------------------------------------
# landing_page_sessions_daily
# ----------------------------------------------------------------------

_DDL_SESSIONS_DAILY = """
CREATE TABLE IF NOT EXISTS landing_page_sessions_daily (
    session_date date NOT NULL,
    landing_page_path text NOT NULL,
    sessions bigint NOT NULL,
    online_store_visitors bigint NOT NULL,
    sessions_with_cart_additions bigint NOT NULL,
    sessions_that_reached_checkout bigint NOT NULL,
    bounces bigint NOT NULL,
    synced_at timestamptz NOT NULL,
    PRIMARY KEY (session_date, landing_page_path)
)
"""

_SELECT_RAW_SESSIONS = """
SELECT day, landing_page_path, sessions, online_store_visitors,
       sessions_with_cart_additions, sessions_that_reached_checkout, bounces
FROM shopify_sessions
WHERE landing_page_path IS NOT NULL
"""

_UPSERT_SESSIONS_DAILY = """
INSERT INTO landing_page_sessions_daily
    (session_date, landing_page_path, sessions, online_store_visitors,
     sessions_with_cart_additions, sessions_that_reached_checkout, bounces, synced_at)
VALUES (:session_date, :landing_page_path, :sessions, :online_store_visitors,
        :sessions_with_cart_additions, :sessions_that_reached_checkout, :bounces, now())
ON CONFLICT (session_date, landing_page_path) DO UPDATE SET
    sessions = EXCLUDED.sessions,
    online_store_visitors = EXCLUDED.online_store_visitors,
    sessions_with_cart_additions = EXCLUDED.sessions_with_cart_additions,
    sessions_that_reached_checkout = EXCLUDED.sessions_that_reached_checkout,
    bounces = EXCLUDED.bounces,
    synced_at = now()
"""


@dataclass
class _SessionAgg:
    sessions: int = 0
    online_store_visitors: int = 0
    sessions_with_cart_additions: int = 0
    sessions_that_reached_checkout: int = 0
    bounces: int = 0


async def refresh_landing_page_sessions_daily(session: AsyncSession) -> int:
    """Sum shopify_sessions (which carries referrer/utm dims) down to the
    legacy grain (session_date, normalized landing_page_path). Path
    normalization has real conditional logic -- done in Python
    (normalize_session_path), not a SQL regex chain, per user preference."""
    await session.execute(text(_DDL_SESSIONS_DAILY))
    await session.commit()

    rows = (await session.execute(text(_SELECT_RAW_SESSIONS))).mappings().all()

    agg: dict[tuple[date, str], _SessionAgg] = defaultdict(_SessionAgg)
    for row in rows:
        path = normalize_session_path(row["landing_page_path"])
        if path is None:
            continue
        key = (row["day"], path)
        bucket = agg[key]
        bucket.sessions += int(row["sessions"] or 0)
        bucket.online_store_visitors += int(row["online_store_visitors"] or 0)
        bucket.sessions_with_cart_additions += int(row["sessions_with_cart_additions"] or 0)
        bucket.sessions_that_reached_checkout += int(row["sessions_that_reached_checkout"] or 0)
        bucket.bounces += int(row["bounces"] or 0)

    params = [
        {
            "session_date": session_date,
            "landing_page_path": path,
            "sessions": bucket.sessions,
            "online_store_visitors": bucket.online_store_visitors,
            "sessions_with_cart_additions": bucket.sessions_with_cart_additions,
            "sessions_that_reached_checkout": bucket.sessions_that_reached_checkout,
            "bounces": bucket.bounces,
        }
        for (session_date, path), bucket in agg.items()
    ]
    if params:
        await session.execute(text(_UPSERT_SESSIONS_DAILY), params)
        await session.commit()

    logger.info("landing_page_sessions_daily_refreshed", rows=len(params))
    return len(params)


# ----------------------------------------------------------------------
# Ad link resolution -- latest link_url/object_url/preview per ad_id from
# raw_dump_meta object_type='ad' rows fetched with the creative expansion.
# ----------------------------------------------------------------------

_SELECT_LATEST_AD_ROWS = """
WITH latest AS (
    SELECT DISTINCT ON (meta_id) meta_id, raw_payload
    FROM raw_dump_meta
    WHERE object_type = 'ad'
    ORDER BY meta_id, extracted_at DESC
)
SELECT meta_id AS ad_id, raw_payload FROM latest
"""


@dataclass
class _AdLinkInfo:
    ad_link: str | None
    preview_link: str | None
    normalized_path: str | None


def _resolve_ad_link(raw_payload: dict) -> _AdLinkInfo:
    creative = raw_payload.get("creative") or {}
    ad_link = (
        creative.get("link_url")
        or (creative.get("object_story_spec") or {}).get("link_data", {}).get("link")
        or creative.get("object_url")
        or creative.get("template_url")
    )
    preview_link = creative.get("effective_object_story_id") and (
        f"https://www.facebook.com/{creative['effective_object_story_id']}"
    )
    return _AdLinkInfo(
        ad_link=ad_link,
        preview_link=preview_link,
        normalized_path=normalize_ad_link(ad_link) if ad_link else None,
    )


async def _load_ad_link_index(session: AsyncSession) -> dict[str, _AdLinkInfo]:
    rows = (await session.execute(text(_SELECT_LATEST_AD_ROWS))).mappings().all()
    index: dict[str, _AdLinkInfo] = {}
    for row in rows:
        info = _resolve_ad_link(row["raw_payload"])
        if info.normalized_path:
            index[row["ad_id"]] = info
    return index


# ----------------------------------------------------------------------
# landing_page_analysis_30d
# ----------------------------------------------------------------------

_DDL_ANALYSIS_30D = """
CREATE TABLE IF NOT EXISTS landing_page_analysis_30d (
    landing_page_path text PRIMARY KEY,
    window_from date,
    window_to date,
    sessions bigint,
    visitors bigint,
    cart_addition_sessions bigint,
    checkout_sessions bigint,
    bounces bigint,
    ad_spend numeric(14,2),
    ad_impressions bigint,
    ad_conv_value numeric(14,2),
    distinct_ads integer,
    atc_rate numeric,
    checkout_rate numeric,
    bounce_rate numeric,
    cost_per_session numeric,
    computed_at timestamptz
)
"""

_SELECT_SESSIONS_WINDOW = """
SELECT landing_page_path, session_date, sessions, online_store_visitors,
       sessions_with_cart_additions, sessions_that_reached_checkout, bounces
FROM landing_page_sessions_daily
WHERE session_date >= :window_from AND session_date <= :window_to
"""

_SELECT_AD_LIFECYCLE_FOR_WINDOW = """
SELECT ad_id, spend, impressions, meta_conv_value
FROM ad_performance_summary
"""

_TRUNCATE_ANALYSIS_30D = "TRUNCATE landing_page_analysis_30d"

_INSERT_ANALYSIS_30D = """
INSERT INTO landing_page_analysis_30d (
    landing_page_path, window_from, window_to, sessions, visitors,
    cart_addition_sessions, checkout_sessions, bounces,
    ad_spend, ad_impressions, ad_conv_value, distinct_ads,
    atc_rate, checkout_rate, bounce_rate, cost_per_session, computed_at
) VALUES (
    :landing_page_path, :window_from, :window_to, :sessions, :visitors,
    :cart_addition_sessions, :checkout_sessions, :bounces,
    :ad_spend, :ad_impressions, :ad_conv_value, :distinct_ads,
    :atc_rate, :checkout_rate, :bounce_rate, :cost_per_session, now()
)
"""


@dataclass
class _PageSessionAgg:
    sessions: int = 0
    visitors: int = 0
    cart_addition_sessions: int = 0
    checkout_sessions: int = 0
    bounces: int = 0


@dataclass
class _PageAdAgg:
    ad_spend: float = 0.0
    ad_impressions: int = 0
    ad_conv_value: float = 0.0
    distinct_ads: int = 0


async def refresh_landing_page_analysis_30d(session: AsyncSession, *, days: int = 30) -> int:
    """Faithful port of `refresh_landing_page_analysis_30d(p_days)`. All
    the branching (rate calcs guarded by sessions>0, ad-link normalization,
    grouping) happens in Python; the DB only stores/reads plain rows."""
    await session.execute(text(_DDL_ANALYSIS_30D))
    await session.commit()

    window_to = date.today()
    window_from = window_to - timedelta(days=days - 1)

    sess_rows = (
        await session.execute(
            text(_SELECT_SESSIONS_WINDOW), {"window_from": window_from, "window_to": window_to}
        )
    ).mappings().all()
    sess_agg: dict[str, _PageSessionAgg] = defaultdict(_PageSessionAgg)
    for row in sess_rows:
        path = normalize_session_path(row["landing_page_path"])
        if path is None:
            continue
        bucket = sess_agg[path]
        bucket.sessions += int(row["sessions"] or 0)
        bucket.visitors += int(row["online_store_visitors"] or 0)
        bucket.cart_addition_sessions += int(row["sessions_with_cart_additions"] or 0)
        bucket.checkout_sessions += int(row["sessions_that_reached_checkout"] or 0)
        bucket.bounces += int(row["bounces"] or 0)

    ad_link_index = await _load_ad_link_index(session)
    ad_rows = (await session.execute(text(_SELECT_AD_LIFECYCLE_FOR_WINDOW))).mappings().all()
    ad_agg: dict[str, _PageAdAgg] = defaultdict(_PageAdAgg)
    for row in ad_rows:
        info = ad_link_index.get(row["ad_id"])
        if info is None or info.normalized_path is None:
            continue
        bucket = ad_agg[info.normalized_path]
        bucket.ad_spend += float(row["spend"] or 0)
        bucket.ad_impressions += int(row["impressions"] or 0)
        bucket.ad_conv_value += float(row["meta_conv_value"] or 0)
        bucket.distinct_ads += 1

    paths = set(sess_agg) | set(ad_agg)
    params = []
    for path in paths:
        s = sess_agg.get(path, _PageSessionAgg())
        a = ad_agg.get(path, _PageAdAgg())
        params.append({
            "landing_page_path": path,
            "window_from": window_from,
            "window_to": window_to,
            "sessions": s.sessions,
            "visitors": s.visitors,
            "cart_addition_sessions": s.cart_addition_sessions,
            "checkout_sessions": s.checkout_sessions,
            "bounces": s.bounces,
            "ad_spend": round(a.ad_spend, 2),
            "ad_impressions": a.ad_impressions,
            "ad_conv_value": round(a.ad_conv_value, 2),
            "distinct_ads": a.distinct_ads,
            "atc_rate": round(s.cart_addition_sessions / s.sessions * 100, 3) if s.sessions else 0,
            "checkout_rate": round(s.checkout_sessions / s.sessions * 100, 3) if s.sessions else 0,
            "bounce_rate": round(s.bounces / s.sessions * 100, 3) if s.sessions else 0,
            "cost_per_session": round(a.ad_spend / s.sessions, 2) if s.sessions else 0,
        })

    await session.execute(text(_TRUNCATE_ANALYSIS_30D))
    if params:
        await session.execute(text(_INSERT_ANALYSIS_30D), params)
    await session.commit()

    logger.info("landing_page_analysis_30d_refreshed", rows=len(params))
    return len(params)


# ----------------------------------------------------------------------
# landing_page_ad_breakdown_30d
# ----------------------------------------------------------------------

_DDL_AD_BREAKDOWN_30D = """
CREATE TABLE IF NOT EXISTS landing_page_ad_breakdown_30d (
    landing_page_path text NOT NULL,
    ad_id text NOT NULL,
    ad_name text,
    ad_status text,
    campaign_name text,
    adset_name text,
    account_name text,
    preview_link text,
    ad_link text,
    impressions bigint,
    spend numeric(14,2),
    conv_value numeric(14,2),
    purchases integer,
    meta_roas numeric,
    shopify_orders integer,
    shopify_sales numeric(14,2),
    shopify_roas numeric,
    roas_gap_pct numeric,
    page_sessions bigint,
    page_atc_rate numeric,
    page_bounce_rate numeric,
    page_cost_per_sess numeric,
    window_from date,
    window_to date,
    computed_at timestamptz,
    PRIMARY KEY (landing_page_path, ad_id)
)
"""

_SELECT_AD_PERFORMANCE_FOR_BREAKDOWN = """
SELECT ad_id, ad_name, ad_status, campaign_name, adset_name, account_name,
       impressions, spend, meta_conv_value AS conv_value, purchases
FROM ad_performance_summary
"""

_SELECT_SHOPIFY_ORDERS_BY_AD = """
SELECT matched_ad_id AS ad_id, COUNT(*) AS shopify_orders, SUM(total_price) AS shopify_sales
FROM shopify_order_attribution
WHERE matched_ad_id IS NOT NULL
GROUP BY matched_ad_id
"""

_TRUNCATE_AD_BREAKDOWN_30D = "TRUNCATE landing_page_ad_breakdown_30d"

_INSERT_AD_BREAKDOWN_30D = """
INSERT INTO landing_page_ad_breakdown_30d (
    landing_page_path, ad_id, ad_name, ad_status, campaign_name, adset_name,
    account_name, preview_link, ad_link, impressions, spend, conv_value,
    purchases, meta_roas, shopify_orders, shopify_sales, shopify_roas,
    roas_gap_pct, page_sessions, page_atc_rate, page_bounce_rate,
    page_cost_per_sess, window_from, window_to, computed_at
) VALUES (
    :landing_page_path, :ad_id, :ad_name, :ad_status, :campaign_name, :adset_name,
    :account_name, :preview_link, :ad_link, :impressions, :spend, :conv_value,
    :purchases, :meta_roas, :shopify_orders, :shopify_sales, :shopify_roas,
    :roas_gap_pct, :page_sessions, :page_atc_rate, :page_bounce_rate,
    :page_cost_per_sess, :window_from, :window_to, now()
)
"""


async def refresh_landing_page_ad_breakdown_30d(session: AsyncSession, *, days: int = 30) -> int:
    """Faithful port of `refresh_landing_page_ad_breakdown_30d(p_days)`:
    one row per (page, ad), joined against Shopify-attributed orders and
    this window's page-level session stats."""
    await session.execute(text(_DDL_AD_BREAKDOWN_30D))
    await session.commit()

    window_to = date.today()
    window_from = window_to - timedelta(days=days - 1)

    ad_link_index = await _load_ad_link_index(session)
    ad_rows = (await session.execute(text(_SELECT_AD_PERFORMANCE_FOR_BREAKDOWN))).mappings().all()

    shopify_rows = (await session.execute(text(_SELECT_SHOPIFY_ORDERS_BY_AD))).mappings().all()
    shopify_by_ad = {r["ad_id"]: r for r in shopify_rows}

    page_rows = (
        await session.execute(
            text(_SELECT_SESSIONS_WINDOW), {"window_from": window_from, "window_to": window_to}
        )
    ).mappings().all()
    page_sess_agg: dict[str, _PageSessionAgg] = defaultdict(_PageSessionAgg)
    for row in page_rows:
        path = normalize_session_path(row["landing_page_path"])
        if path is None:
            continue
        bucket = page_sess_agg[path]
        bucket.sessions += int(row["sessions"] or 0)
        bucket.cart_addition_sessions += int(row["sessions_with_cart_additions"] or 0)
        bucket.bounces += int(row["bounces"] or 0)

    params = []
    for row in ad_rows:
        info = ad_link_index.get(row["ad_id"])
        if info is None or info.normalized_path is None:
            continue
        path = info.normalized_path
        spend = float(row["spend"] or 0)
        conv_value = float(row["conv_value"] or 0)
        meta_roas = round(conv_value / spend, 3) if spend > 0 else 0

        shop = shopify_by_ad.get(row["ad_id"])
        shopify_orders = int(shop["shopify_orders"]) if shop else 0
        shopify_sales = float(shop["shopify_sales"] or 0) if shop else 0.0
        shopify_roas = round(shopify_sales / spend, 3) if spend > 0 else 0
        roas_gap_pct = round((shopify_sales - conv_value) / conv_value * 100, 2) if conv_value > 0 else None

        page = page_sess_agg.get(path, _PageSessionAgg())
        page_atc_rate = round(page.cart_addition_sessions / page.sessions * 100, 3) if page.sessions else 0
        page_bounce_rate = round(page.bounces / page.sessions * 100, 3) if page.sessions else 0
        page_cost_per_sess = round(spend / page.sessions, 2) if page.sessions else 0

        params.append({
            "landing_page_path": path,
            "ad_id": row["ad_id"],
            "ad_name": row["ad_name"],
            "ad_status": row["ad_status"],
            "campaign_name": row["campaign_name"],
            "adset_name": row["adset_name"],
            "account_name": row["account_name"],
            "preview_link": info.preview_link,
            "ad_link": info.ad_link,
            "impressions": int(row["impressions"] or 0),
            "spend": round(spend, 2),
            "conv_value": round(conv_value, 2),
            "purchases": int(row["purchases"] or 0),
            "meta_roas": meta_roas,
            "shopify_orders": shopify_orders,
            "shopify_sales": round(shopify_sales, 2),
            "shopify_roas": shopify_roas,
            "roas_gap_pct": roas_gap_pct,
            "page_sessions": page.sessions,
            "page_atc_rate": page_atc_rate,
            "page_bounce_rate": page_bounce_rate,
            "page_cost_per_sess": page_cost_per_sess,
            "window_from": window_from,
            "window_to": window_to,
        })

    await session.execute(text(_TRUNCATE_AD_BREAKDOWN_30D))
    if params:
        await session.execute(text(_INSERT_AD_BREAKDOWN_30D), params)
    await session.commit()

    logger.info("landing_page_ad_breakdown_30d_refreshed", rows=len(params))
    return len(params)


async def refresh_landing_page_tables(session: AsyncSession) -> dict[str, int]:
    daily = await refresh_landing_page_sessions_daily(session)
    analysis = await refresh_landing_page_analysis_30d(session)
    breakdown = await refresh_landing_page_ad_breakdown_30d(session)
    return {
        "landing_page_sessions_daily": daily,
        "landing_page_analysis_30d": analysis,
        "landing_page_ad_breakdown_30d": breakdown,
    }
