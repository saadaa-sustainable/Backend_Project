"""Read-only ad performance dashboard endpoint -- backs the "User" section's
Analytics page (admin/src/app/user/analytics). Unlike the Schema Browser's
generic table introspection or the admin-authoring endpoints (Build Table,
Customise Columns) that create new tables, this is a purpose-built,
filterable read over `ad_lifecycle` -- no generic "browse any table" endpoint
exists in this project, deliberately (a generic table/column pass-through
would need to defend against SQL injection on identifiers, not just values;
a fixed target table with an allowlisted sort column sidesteps that
entirely).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep

router = APIRouter(prefix="/admin/analytics", tags=["analytics"])

_SORT_COLUMNS = {
    "spend": "spend",
    "roas": "roas",
    "impressions": "impressions",
    "cost_per_ncp": "cost_per_ncp",
    "cost_per_ftewv": "cost_per_ftewv",
}

_DASHBOARD_COLUMNS = (
    "ad_id, ad_name, account_name, campaign_name, ad_effective_status, category, "
    "spend, roas, cost_per_ncp, cost_per_ftewv, purchases, ncp_count, ftewv_count, "
    "impressions, ctr_pct, f1_pass, f2_pass, f3_pass, f4_pass, lifecycle_refreshed_at"
)


class AdLifecycleRow(BaseModel):
    ad_id: str
    ad_name: str | None
    account_name: str | None
    campaign_name: str | None
    ad_effective_status: str | None
    category: str | None
    spend: float | None
    roas: float | None
    cost_per_ncp: float | None
    cost_per_ftewv: float | None
    purchases: float | None
    ncp_count: float | None
    ftewv_count: float | None
    impressions: float | None
    ctr_pct: float | None
    f1_pass: bool | None
    f2_pass: bool | None
    f3_pass: bool | None
    f4_pass: bool | None
    lifecycle_refreshed_at: datetime | None


class AdLifecycleResponse(BaseModel):
    rows: list[AdLifecycleRow]
    total: int
    category_counts: dict[str, int]


@router.get("/ad-lifecycle", response_model=AdLifecycleResponse)
async def get_ad_lifecycle(
    session: SessionDep,
    account_name: str | None = Query(default=None),
    category: str | None = Query(default=None),
    ad_effective_status: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Matches ad_name, case-insensitive substring."),
    sort: Literal["spend", "roas", "impressions", "cost_per_ncp", "cost_per_ftewv"] = Query(default="spend"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdLifecycleResponse:
    sort_column = _SORT_COLUMNS[sort]  # `sort` is already Literal-validated by FastAPI

    where_clauses = []
    params: dict[str, object] = {}
    if account_name:
        where_clauses.append("account_name = :account_name")
        params["account_name"] = account_name
    if category:
        where_clauses.append("category = :category")
        params["category"] = category
    if ad_effective_status:
        where_clauses.append("ad_effective_status = :ad_effective_status")
        params["ad_effective_status"] = ad_effective_status
    if search:
        where_clauses.append("ad_name ILIKE :search")
        params["search"] = f"%{search}%"
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    rows_result = await session.execute(
        text(
            f"SELECT {_DASHBOARD_COLUMNS} FROM ad_lifecycle {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [AdLifecycleRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM ad_lifecycle {where_sql}"), params)
    ).scalar_one()

    counts_result = await session.execute(
        text(f"SELECT category, COUNT(*) FROM ad_lifecycle {where_sql} GROUP BY category"), params
    )
    category_counts = {row[0] or "Uncategorized": row[1] for row in counts_result}

    return AdLifecycleResponse(rows=rows, total=total, category_counts=category_counts)


# ----------------------------------------------------------------------
# Ads Analyse -- wide per-ad table (Meta metrics + Shopify-attributed
# revenue), backed by the Gold ad_performance_summary table. Same
# row-level-table intent as legacy's "Ads Analyse" view (view-ae), just
# reading a table that already carries real Shopify revenue alongside
# Meta's own numbers instead of Meta-only columns.
# ----------------------------------------------------------------------

_ADS_ANALYSE_SORT_COLUMNS = {
    "spend": "spend",
    "meta_roas": "meta_roas",
    "shopify_roas": "shopify_roas",
    "shopify_revenue": "shopify_revenue",
    "impressions": "impressions",
}

_ADS_ANALYSE_COLUMNS = (
    "ad_id, ad_name, ad_status, ad_effective_status, adset_name, campaign_name, account_name, category, "
    "spend, impressions, purchases, meta_conv_value, meta_roas, cost_per_purchase, ctr_pct, "
    "shopify_orders, shopify_revenue, shopify_aov, shopify_roas, cost_per_shopify_order, gold_refreshed_at"
)


class AdsAnalyseRow(BaseModel):
    ad_id: str
    ad_name: str | None
    ad_status: str | None
    ad_effective_status: str | None
    adset_name: str | None
    campaign_name: str | None
    account_name: str | None
    category: str | None
    spend: float | None
    impressions: float | None
    purchases: float | None
    meta_conv_value: float | None
    meta_roas: float | None
    cost_per_purchase: float | None
    ctr_pct: float | None
    shopify_orders: float | None
    shopify_revenue: float | None
    shopify_aov: float | None
    shopify_roas: float | None
    cost_per_shopify_order: float | None
    gold_refreshed_at: datetime | None


class AdsAnalyseResponse(BaseModel):
    rows: list[AdsAnalyseRow]
    total: int


@router.get("/ads-analyse", response_model=AdsAnalyseResponse)
async def get_ads_analyse(
    session: SessionDep,
    account_name: str | None = Query(default=None),
    campaign_name: str | None = Query(default=None),
    ad_effective_status: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Matches ad_name, case-insensitive substring."),
    only_with_shopify_orders: bool = Query(default=False),
    sort: Literal["spend", "meta_roas", "shopify_roas", "shopify_revenue", "impressions"] = Query(default="spend"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdsAnalyseResponse:
    sort_column = _ADS_ANALYSE_SORT_COLUMNS[sort]

    where_clauses = []
    params: dict[str, object] = {}
    if account_name:
        where_clauses.append("account_name = :account_name")
        params["account_name"] = account_name
    if campaign_name:
        where_clauses.append("campaign_name = :campaign_name")
        params["campaign_name"] = campaign_name
    if ad_effective_status:
        where_clauses.append("ad_effective_status = :ad_effective_status")
        params["ad_effective_status"] = ad_effective_status
    if search:
        where_clauses.append("ad_name ILIKE :search")
        params["search"] = f"%{search}%"
    if only_with_shopify_orders:
        where_clauses.append("shopify_orders > 0")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    rows_result = await session.execute(
        text(
            f"SELECT {_ADS_ANALYSE_COLUMNS} FROM ad_performance_summary {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [AdsAnalyseRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM ad_performance_summary {where_sql}"), params)
    ).scalar_one()

    return AdsAnalyseResponse(rows=rows, total=total)


# ----------------------------------------------------------------------
# Last Click UTM -- order-level Shopify->Meta attribution, backed by
# shopify_order_attribution. Mirrors legacy's "Ad Intelligence" view:
# channel tiles (Meta/Google/Retention/Other, classified from utm_source)
# plus a filterable per-order table showing the resolved ad/campaign.
# Channel classification is real branching logic -> done in Python
# (_classify_channel), not a SQL CASE, per user preference (2026-08-27).
# ----------------------------------------------------------------------

_META_UTM_SOURCES = {"meta", "facebook", "instagram", "ig"}
_GOOGLE_UTM_SOURCES = {"google", "adwords"}
_RETENTION_UTM_SOURCES = {"email", "sms", "whatsapp", "klaviyo"}


def _classify_channel(utm_source: str | None) -> str:
    source = (utm_source or "").strip().lower()
    if source in _META_UTM_SOURCES:
        return "Meta"
    if source in _GOOGLE_UTM_SOURCES:
        return "Google"
    if source in _RETENTION_UTM_SOURCES:
        return "Retention"
    return "Other"


_UTM_ORDER_COLUMNS = (
    "order_id, name, total_price, created_at, utm_source, utm_medium, utm_campaign, utm_content, utm_term, "
    "tier, matched_ad_id, matched_ad_name, matched_campaign_id, matched_campaign_name"
)


class UtmOrderRow(BaseModel):
    order_id: str
    name: str | None
    total_price: float | None
    created_at: datetime | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None
    utm_term: str | None
    tier: str | None
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_campaign_id: str | None
    matched_campaign_name: str | None
    channel: str


class ChannelSummary(BaseModel):
    count: int
    sales: float


class UtmOrderResponse(BaseModel):
    rows: list[UtmOrderRow]
    total: int
    channel_counts: dict[str, ChannelSummary]
    tier_counts: dict[str, int]


@router.get("/last-click-utm", response_model=UtmOrderResponse)
async def get_last_click_utm(
    session: SessionDep,
    channel: Literal["Meta", "Google", "Retention", "Other"] | None = Query(default=None),
    tier: str | None = Query(default=None),
    utm_source: str | None = Query(default=None),
    utm_campaign: str | None = Query(default=None, description="Case-insensitive substring match."),
    search: str | None = Query(default=None, description="Matches order name, case-insensitive substring."),
    sort: Literal["created_at", "total_price"] = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> UtmOrderResponse:
    # Channel tiles + tier counts are computed over the FULL table (not
    # this page's filters other than channel/tier itself would be
    # circular) -- fetch the light columns needed for classification once,
    # classify in Python, then run the heavier paginated row query
    # separately with all filters applied.
    summary_rows = (
        await session.execute(text("SELECT utm_source, total_price, tier FROM shopify_order_attribution"))
    ).all()

    channel_counts: dict[str, ChannelSummary] = {
        c: ChannelSummary(count=0, sales=0.0) for c in ("Meta", "Google", "Retention", "Other")
    }
    tier_counts: dict[str, int] = {}
    for row_utm_source, row_total_price, row_tier in summary_rows:
        ch = _classify_channel(row_utm_source)
        channel_counts[ch].count += 1
        channel_counts[ch].sales += float(row_total_price or 0)
        tier_key = row_tier or "unmatched"
        tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1

    where_clauses = []
    params: dict[str, object] = {}
    if tier:
        where_clauses.append("tier = :tier")
        params["tier"] = tier
    if utm_source:
        where_clauses.append("utm_source = :utm_source")
        params["utm_source"] = utm_source
    if utm_campaign:
        where_clauses.append("utm_campaign ILIKE :utm_campaign")
        params["utm_campaign"] = f"%{utm_campaign}%"
    if search:
        where_clauses.append("name ILIKE :search")
        params["search"] = f"%{search}%"
    if channel:
        sources = {"Meta": _META_UTM_SOURCES, "Google": _GOOGLE_UTM_SOURCES, "Retention": _RETENTION_UTM_SOURCES}.get(channel)
        if sources is not None:
            where_clauses.append("LOWER(utm_source) = ANY(:channel_sources)")
            params["channel_sources"] = list(sources)
        else:  # "Other" -- anything not in any known channel's source set, or NULL
            where_clauses.append(
                "(utm_source IS NULL OR LOWER(utm_source) NOT IN :all_known_sources)"
            )
            params["all_known_sources"] = tuple(_META_UTM_SOURCES | _GOOGLE_UTM_SOURCES | _RETENTION_UTM_SOURCES)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sort_column = "created_at" if sort == "created_at" else "total_price"
    rows_result = await session.execute(
        text(
            f"SELECT {_UTM_ORDER_COLUMNS} FROM shopify_order_attribution {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [
        UtmOrderRow(**dict(r._mapping), channel=_classify_channel(r._mapping["utm_source"]))
        for r in rows_result
    ]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM shopify_order_attribution {where_sql}"), params)
    ).scalar_one()

    return UtmOrderResponse(rows=rows, total=total, channel_counts=channel_counts, tier_counts=tier_counts)


# ----------------------------------------------------------------------
# Customer Journey -- extends Last Click UTM's ad<->order match
# (shopify_order_attribution) one hop further: order -> customer, via
# shopify_customer_analytics (name/email/location, RFM group, predicted
# spend tier, lifetime orders & spend, cohort month). One row per order
# (same grain as Last Click UTM), plus a per-customer drill-down endpoint
# showing that customer's full order history and every ad that touched
# it -- the actual "journey", not just a single order's last-click match.
#
# `shopify_customers` (the GraphQL customer sync) was deliberately NOT
# used here despite having its own customer_id column -- checked live
# 2026-08-27: it only has 5 rows (that object type barely got fetched),
# while shopify_customer_analytics (the ShopifyQL customer_analytics
# table) has 5,496 rows and already carries name/email/location/RFM, so
# it's the only viable customer-profile source right now.
#
# Also found live: shopify_order_attribution.customer_id is a full GID
# ("gid://shopify/Customer/9343486460150") but
# shopify_customer_analytics.customer_id is the bare numeric id
# ("9343486460150") -- two different ingestion paths (GraphQL orders vs.
# ShopifyQL customer_analytics) format the same id differently. The join
# strips the GID prefix via split_part(..., '/', 5) rather than silently
# returning zero matches (confirmed live: 0 matches with a naive `=` join,
# 5,790 with the prefix stripped).
# ----------------------------------------------------------------------

_JOURNEY_ORDER_COLUMNS = (
    "soa.order_id, soa.name, soa.total_price, soa.created_at, soa.tier, "
    "soa.matched_ad_id, soa.matched_ad_name, soa.matched_campaign_id, soa.matched_campaign_name, "
    "soa.customer_id, "
    "ca.customer_name, ca.customer_email, ca.customer_city, ca.customer_country, "
    "ca.total_number_of_orders AS customer_lifetime_orders, ca.total_amount_spent AS customer_lifetime_spend, "
    "ca.rfm_group, ca.predicted_spend_tier, ca.customer_cohort_month, ca.days_since_last_order"
)

_JOURNEY_JOIN = (
    "FROM shopify_order_attribution soa "
    "LEFT JOIN shopify_customer_analytics ca ON ca.customer_id = split_part(soa.customer_id, '/', 5)"
)


class CustomerJourneyOrderRow(BaseModel):
    order_id: str
    name: str | None
    total_price: float | None
    created_at: datetime | None
    tier: str | None
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_campaign_id: str | None
    matched_campaign_name: str | None
    customer_id: str | None
    customer_name: str | None
    customer_email: str | None
    customer_city: str | None
    customer_country: str | None
    customer_lifetime_orders: float | None
    customer_lifetime_spend: float | None
    rfm_group: str | None
    predicted_spend_tier: str | None
    customer_cohort_month: date | None
    days_since_last_order: float | None


class CustomerJourneyResponse(BaseModel):
    rows: list[CustomerJourneyOrderRow]
    total: int
    rfm_counts: dict[str, int]


@router.get("/customer-journey", response_model=CustomerJourneyResponse)
async def get_customer_journey(
    session: SessionDep,
    rfm_group: str | None = Query(default=None),
    tier: str | None = Query(default=None, description="Ad-match tier, same values as Last Click UTM."),
    only_matched: bool = Query(default=False, description="Only orders that resolved to a specific ad."),
    only_with_customer: bool = Query(default=False, description="Only orders that joined to a known customer."),
    search: str | None = Query(default=None, description="Matches order name, customer name, or email."),
    sort: Literal["created_at", "total_price", "customer_lifetime_spend"] = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CustomerJourneyResponse:
    where_clauses = []
    params: dict[str, object] = {}
    if rfm_group:
        where_clauses.append("ca.rfm_group = :rfm_group")
        params["rfm_group"] = rfm_group
    if tier:
        where_clauses.append("soa.tier = :tier")
        params["tier"] = tier
    if only_matched:
        where_clauses.append("soa.matched_ad_id IS NOT NULL")
    if only_with_customer:
        where_clauses.append("soa.customer_id IS NOT NULL AND ca.customer_id IS NOT NULL")
    if search:
        where_clauses.append("(soa.name ILIKE :search OR ca.customer_email ILIKE :search OR ca.customer_name ILIKE :search)")
        params["search"] = f"%{search}%"
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sort_column = {"created_at": "soa.created_at", "total_price": "soa.total_price", "customer_lifetime_spend": "ca.total_amount_spent"}[sort]

    rows_result = await session.execute(
        text(
            f"SELECT {_JOURNEY_ORDER_COLUMNS} {_JOURNEY_JOIN} {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [CustomerJourneyOrderRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) {_JOURNEY_JOIN} {where_sql}"), params)
    ).scalar_one()

    rfm_result = await session.execute(
        text(f"SELECT COALESCE(ca.rfm_group, 'Unknown'), COUNT(*) {_JOURNEY_JOIN} {where_sql} GROUP BY 1"), params
    )
    rfm_counts = {row[0]: row[1] for row in rfm_result}

    return CustomerJourneyResponse(rows=rows, total=total, rfm_counts=rfm_counts)


class CustomerJourneyDetailOrderRow(BaseModel):
    order_id: str
    name: str | None
    total_price: float | None
    created_at: datetime | None
    tier: str | None
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_campaign_name: str | None


class CustomerJourneyDetailResponse(BaseModel):
    customer_id: str
    customer_name: str | None
    email: str | None
    lifetime_orders: float | None
    lifetime_spend: float | None
    rfm_group: str | None
    predicted_spend_tier: str | None
    first_order_date: date | None
    last_order_date: date | None
    orders: list[CustomerJourneyDetailOrderRow]
    ads_touched: list[str]


@router.get("/customer-journey/{customer_id}", response_model=CustomerJourneyDetailResponse)
async def get_customer_journey_detail(session: SessionDep, customer_id: str) -> CustomerJourneyDetailResponse:
    """`customer_id` is the bare numeric id as shopify_customer_analytics
    stores it (what the list endpoint above returns/links) -- matched
    against shopify_order_attribution's full-GID customer_id the same
    prefix-stripped way the list query does."""
    profile_result = await session.execute(
        text(
            "SELECT customer_id, customer_name, customer_email AS email, "
            "total_number_of_orders AS lifetime_orders, total_amount_spent AS lifetime_spend, "
            "rfm_group, predicted_spend_tier, first_order_date, last_order_date "
            "FROM shopify_customer_analytics WHERE customer_id = :customer_id"
        ),
        {"customer_id": customer_id},
    )
    profile = profile_result.mappings().first()
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No customer found with id '{customer_id}'.")

    orders_result = await session.execute(
        text(
            "SELECT order_id, name, total_price, created_at, tier, matched_ad_id, matched_ad_name, matched_campaign_name "
            "FROM shopify_order_attribution WHERE split_part(customer_id, '/', 5) = :customer_id ORDER BY created_at DESC"
        ),
        {"customer_id": customer_id},
    )
    orders = [CustomerJourneyDetailOrderRow(**dict(r._mapping)) for r in orders_result]
    ads_touched = sorted({o.matched_ad_name for o in orders if o.matched_ad_name})

    return CustomerJourneyDetailResponse(**dict(profile), orders=orders, ads_touched=ads_touched)


# ----------------------------------------------------------------------
# Landing Page Analysis -- backed by landing_page_analysis_30d (page grain)
# and landing_page_ad_breakdown_30d (page x ad grain), ported from the
# legacy Meta_ads_data Postgres functions of the same name.
# ----------------------------------------------------------------------

_LANDING_PAGE_SORT_COLUMNS = {
    "sessions": "sessions",
    "ad_spend": "ad_spend",
    "cost_per_session": "cost_per_session",
    "checkout_rate": "checkout_rate",
}


class LandingPageRow(BaseModel):
    landing_page_path: str
    window_from: date | None
    window_to: date | None
    sessions: int | None
    visitors: int | None
    cart_addition_sessions: int | None
    checkout_sessions: int | None
    bounces: int | None
    ad_spend: float | None
    ad_impressions: int | None
    ad_conv_value: float | None
    distinct_ads: int | None
    atc_rate: float | None
    checkout_rate: float | None
    bounce_rate: float | None
    cost_per_session: float | None


class LandingPageResponse(BaseModel):
    rows: list[LandingPageRow]
    total: int


@router.get("/landing-pages", response_model=LandingPageResponse)
async def get_landing_pages(
    session: SessionDep,
    search: str | None = Query(default=None, description="Matches landing_page_path, case-insensitive substring."),
    sort: Literal["sessions", "ad_spend", "cost_per_session", "checkout_rate"] = Query(default="sessions"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LandingPageResponse:
    sort_column = _LANDING_PAGE_SORT_COLUMNS[sort]

    where_clauses = []
    params: dict[str, object] = {}
    if search:
        where_clauses.append("landing_page_path ILIKE :search")
        params["search"] = f"%{search}%"
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    rows_result = await session.execute(
        text(
            f"SELECT * FROM landing_page_analysis_30d {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [LandingPageRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM landing_page_analysis_30d {where_sql}"), params)
    ).scalar_one()

    return LandingPageResponse(rows=rows, total=total)


class LandingPageAdRow(BaseModel):
    landing_page_path: str
    ad_id: str
    ad_name: str | None
    ad_status: str | None
    campaign_name: str | None
    adset_name: str | None
    account_name: str | None
    preview_link: str | None
    ad_link: str | None
    impressions: int | None
    spend: float | None
    conv_value: float | None
    purchases: int | None
    meta_roas: float | None
    shopify_orders: int | None
    shopify_sales: float | None
    shopify_roas: float | None
    roas_gap_pct: float | None
    page_sessions: int | None
    page_atc_rate: float | None
    page_bounce_rate: float | None
    page_cost_per_sess: float | None


class LandingPageAdBreakdownResponse(BaseModel):
    rows: list[LandingPageAdRow]
    total: int


@router.get("/landing-pages/{landing_page_path:path}/ads", response_model=LandingPageAdBreakdownResponse)
async def get_landing_page_ad_breakdown(
    session: SessionDep,
    landing_page_path: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LandingPageAdBreakdownResponse:
    path = landing_page_path if landing_page_path.startswith("/") else f"/{landing_page_path}"
    params = {"landing_page_path": path, "limit": limit, "offset": offset}

    rows_result = await session.execute(
        text(
            "SELECT * FROM landing_page_ad_breakdown_30d WHERE landing_page_path = :landing_page_path "
            "ORDER BY spend DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = [LandingPageAdRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(
            text("SELECT COUNT(*) FROM landing_page_ad_breakdown_30d WHERE landing_page_path = :landing_page_path"),
            {"landing_page_path": path},
        )
    ).scalar_one()

    return LandingPageAdBreakdownResponse(rows=rows, total=total)


# ----------------------------------------------------------------------
# Shopify Explorer -- ad-hoc metric x dimension pivot over the Shopify
# Silver tables, so a user can pick what they want to see (e.g. "sessions
# by landing_page_path and utm_source" or "gross_profit by day and
# new_or_returning_customer") instead of only reading fixed pre-built
# tables. Each "dataset" below is one Silver table with an EXPLICIT
# allowlist of which columns can be a dimension/metric and how a metric
# aggregates -- same reasoning as this module's other endpoints (see the
# module docstring): a generic "GROUP BY whatever column names the client
# sends" endpoint would need to defend against SQL injection on
# identifiers, not just values, so the allowlist is the whole defense,
# not a formality. Resolving a request against that allowlist (which
# columns exist, what SQL expression/aggregate they map to) is real
# branching logic -> done in Python (_resolve_query), not embedded in a
# dynamically-built SQL string beyond the final parameterized SELECT.
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Dimension:
    label: str
    expr: str  # a column name or a safe cast expression, e.g. "created_at::date" -- always server-defined, never client text


@dataclass(frozen=True)
class _Metric:
    label: str
    agg: Literal["sum", "count"]
    expr: str | None = None  # column name to aggregate; None means COUNT(*)


@dataclass(frozen=True)
class _Dataset:
    label: str
    table: str
    dimensions: dict[str, _Dimension]
    metrics: dict[str, _Metric]


_DATASETS: dict[str, _Dataset] = {
    "sessions": _Dataset(
        label="Sessions (shopify_sessions)",
        table="shopify_sessions",
        dimensions={
            "day": _Dimension("Day", "day"),
            "landing_page_path": _Dimension("Landing page", "landing_page_path"),
            "landing_page_type": _Dimension("Landing page type", "landing_page_type"),
            "referrer_source": _Dimension("Referrer source", "referrer_source"),
            "utm_source": _Dimension("UTM source", "utm_source"),
            "utm_campaign": _Dimension("UTM campaign", "utm_campaign"),
            "utm_medium": _Dimension("UTM medium", "utm_medium"),
        },
        metrics={
            "sessions": _Metric("Sessions", "sum", "sessions"),
            "pageviews": _Metric("Pageviews", "sum", "pageviews"),
            "online_store_visitors": _Metric("Visitors", "sum", "online_store_visitors"),
            "bounces": _Metric("Bounces", "sum", "bounces"),
            "sessions_with_cart_additions": _Metric("Sessions w/ cart add", "sum", "sessions_with_cart_additions"),
            "sessions_that_reached_checkout": _Metric("Sessions reached checkout", "sum", "sessions_that_reached_checkout"),
            "sessions_that_completed_checkout": _Metric("Sessions completed checkout", "sum", "sessions_that_completed_checkout"),
        },
    ),
    "sales": _Dataset(
        label="Sales (shopify_sales)",
        table="shopify_sales",
        dimensions={
            "day": _Dimension("Day", "day"),
            "new_or_returning_customer": _Dimension("New/returning customer", "new_or_returning_customer"),
            "is_pos_sale": _Dimension("POS sale?", "is_pos_sale"),
        },
        metrics={
            "orders": _Metric("Orders", "sum", "orders"),
            "gross_sales": _Metric("Gross sales", "sum", "gross_sales"),
            "net_sales": _Metric("Net sales", "sum", "net_sales"),
            "total_sales": _Metric("Total sales", "sum", "total_sales"),
            "discounts": _Metric("Discounts", "sum", "discounts"),
            "shipping_charges": _Metric("Shipping charges", "sum", "shipping_charges"),
            "taxes": _Metric("Taxes", "sum", "taxes"),
            "cost_of_goods_sold": _Metric("Cost of goods sold", "sum", "cost_of_goods_sold"),
            "gross_profit": _Metric("Gross profit", "sum", "gross_profit"),
            "quantity_ordered": _Metric("Quantity ordered", "sum", "quantity_ordered"),
        },
    ),
    "orders": _Dataset(
        label="Orders (shopify_orders)",
        table="shopify_orders",
        dimensions={
            "day": _Dimension("Day", "created_at::date"),
            "utm_source": _Dimension("UTM source", "utm_source"),
            "utm_campaign": _Dimension("UTM campaign", "utm_campaign"),
            "utm_medium": _Dimension("UTM medium", "utm_medium"),
            "financial_status": _Dimension("Financial status", "financial_status"),
            "fulfillment_status": _Dimension("Fulfillment status", "fulfillment_status"),
            "currency": _Dimension("Currency", "currency"),
        },
        metrics={
            "order_count": _Metric("Order count", "count"),
            "total_price": _Metric("Total price", "sum", "total_price"),
            "subtotal_price": _Metric("Subtotal price", "sum", "subtotal_price"),
        },
    ),
    "customer_analytics": _Dataset(
        label="Customer analytics (shopify_customer_analytics)",
        table="shopify_customer_analytics",
        dimensions={
            "customer_cohort_month": _Dimension("Cohort month", "customer_cohort_month"),
            "rfm_group": _Dimension("RFM group", "rfm_group"),
            "predicted_spend_tier": _Dimension("Predicted spend tier", "predicted_spend_tier"),
            "customer_country": _Dimension("Country", "customer_country"),
            "customer_region": _Dimension("Region", "customer_region"),
            "customer_account_status": _Dimension("Account status", "customer_account_status"),
        },
        metrics={
            "customer_count": _Metric("Customer count", "count"),
            "total_amount_spent": _Metric("Total amount spent", "sum", "total_amount_spent"),
            "total_number_of_orders": _Metric("Total number of orders", "sum", "total_number_of_orders"),
        },
    ),
    "discounts": _Dataset(
        label="Discounts (shopify_discounts)",
        table="shopify_discounts",
        dimensions={
            "day": _Dimension("Day", "day"),
            "discount_code": _Dimension("Discount code", "discount_code"),
            "discount_type": _Dimension("Discount type", "discount_type"),
            "discount_method": _Dimension("Discount method", "discount_method"),
            "discount_class": _Dimension("Discount class", "discount_class"),
        },
        metrics={
            "discounted_orders": _Metric("Discounted orders", "sum", "discounted_orders"),
            "applied_discounts": _Metric("Applied discounts", "sum", "applied_discounts"),
            "product_and_order_discounts": _Metric("Product/order discounts", "sum", "product_and_order_discounts"),
            "shipping_discounts": _Metric("Shipping discounts", "sum", "shipping_discounts"),
        },
    ),
    "inventory": _Dataset(
        label="Inventory (shopify_inventory)",
        table="shopify_inventory",
        dimensions={
            "day": _Dimension("Day", "day"),
            "product_title": _Dimension("Product", "product_title"),
            "product_type": _Dimension("Product type", "product_type"),
            "product_vendor": _Dimension("Vendor", "product_vendor"),
            "product_status": _Dimension("Product status", "product_status"),
        },
        metrics={
            "ending_inventory_units": _Metric("Ending inventory units", "sum", "ending_inventory_units"),
            "ending_inventory_value": _Metric("Ending inventory value", "sum", "ending_inventory_value"),
            "inventory_units_sold": _Metric("Units sold", "sum", "inventory_units_sold"),
            "starting_inventory_units": _Metric("Starting inventory units", "sum", "starting_inventory_units"),
        },
    ),
}


class ShopifyExplorerSchemaDataset(BaseModel):
    key: str
    label: str
    date_dimension: str | None
    dimensions: list[dict[str, str]]
    metrics: list[dict[str, str]]


class ShopifyExplorerSchemaResponse(BaseModel):
    datasets: list[ShopifyExplorerSchemaDataset]


@router.get("/shopify-explorer/schema", response_model=ShopifyExplorerSchemaResponse)
async def get_shopify_explorer_schema() -> ShopifyExplorerSchemaResponse:
    """Every selectable dataset/dimension/metric -- drives the picker UI so
    the frontend never hardcodes column names, only ever echoes back keys
    this endpoint handed out."""
    datasets = []
    for key, ds in _DATASETS.items():
        datasets.append(
            ShopifyExplorerSchemaDataset(
                key=key,
                label=ds.label,
                date_dimension="day" if "day" in ds.dimensions else None,
                dimensions=[{"key": k, "label": d.label} for k, d in ds.dimensions.items()],
                metrics=[{"key": k, "label": m.label} for k, m in ds.metrics.items()],
            )
        )
    return ShopifyExplorerSchemaResponse(datasets=datasets)


class ShopifyExplorerQueryRequest(BaseModel):
    dataset: str
    dimensions: list[str] = []
    metrics: list[str]
    date_from: date | None = None
    date_to: date | None = None
    limit: int = 200


class ShopifyExplorerQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


def _resolve_shopify_explorer_query(body: ShopifyExplorerQueryRequest) -> tuple[str, dict[str, Any]]:
    """All the branching lives here, not in the SQL: validate the dataset
    and every requested dimension/metric key against the allowlist, then
    assemble a SELECT built entirely from server-defined expressions
    (`_Dimension.expr` / `_Metric.expr`) -- client input only ever selects
    *which* of those pre-approved expressions to use, never supplies SQL
    text itself."""
    dataset = _DATASETS.get(body.dataset)
    if dataset is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset '{body.dataset}'. See /shopify-explorer/schema.")
    if not body.metrics:
        raise HTTPException(status_code=400, detail="At least one metric is required.")

    unknown_dims = [d for d in body.dimensions if d not in dataset.dimensions]
    if unknown_dims:
        raise HTTPException(status_code=400, detail=f"Unknown dimension(s) for dataset '{body.dataset}': {unknown_dims}")
    unknown_metrics = [m for m in body.metrics if m not in dataset.metrics]
    if unknown_metrics:
        raise HTTPException(status_code=400, detail=f"Unknown metric(s) for dataset '{body.dataset}': {unknown_metrics}")

    dim_select = [f"{dataset.dimensions[d].expr} AS {d}" for d in body.dimensions]
    metric_select = []
    for m in body.metrics:
        metric = dataset.metrics[m]
        if metric.agg == "count":
            metric_select.append(f"COUNT(*) AS {m}")
        else:
            metric_select.append(f"SUM({metric.expr}) AS {m}")

    where_clauses = []
    params: dict[str, Any] = {}
    date_dim = dataset.dimensions.get("day")
    if date_dim is not None and (body.date_from or body.date_to):
        if body.date_from:
            where_clauses.append(f"{date_dim.expr} >= :date_from")
            params["date_from"] = body.date_from
        if body.date_to:
            where_clauses.append(f"{date_dim.expr} <= :date_to")
            params["date_to"] = body.date_to
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    group_by_sql = f"GROUP BY {', '.join(body.dimensions)}" if body.dimensions else ""
    order_by_sql = f"ORDER BY {body.metrics[0]} DESC NULLS LAST"

    sql = (
        f"SELECT {', '.join(dim_select + metric_select)} FROM {dataset.table} "
        f"{where_sql} {group_by_sql} {order_by_sql} LIMIT :limit"
    )
    params["limit"] = min(body.limit, 1000)
    return sql, params


@router.post("/shopify-explorer/query", response_model=ShopifyExplorerQueryResponse)
async def query_shopify_explorer(session: SessionDep, body: ShopifyExplorerQueryRequest) -> ShopifyExplorerQueryResponse:
    sql, params = _resolve_shopify_explorer_query(body)
    result = await session.execute(text(sql), params)
    columns = list(result.keys())
    rows = [dict(r._mapping) for r in result]
    return ShopifyExplorerQueryResponse(columns=columns, rows=rows)


# ----------------------------------------------------------------------
# Meta Explorer -- same ad-hoc pivot idea as Shopify Explorer, but over
# `ad_lifecycle` / `adset_insights` / `campaign_insights`. Those tables
# already carry the FULL Meta Insights registry per row (~169 fields --
# ad_lifecycle.py's own docstring: "EVERY raw metric from ad_insights...
# not a narrow curated subset"), so unlike Shopify Explorer's hand-written
# per-dataset allowlist, hand-typing ~95 usable (non-jsonb) columns per
# table here would just be re-transcribing what Postgres already knows.
# Instead the allowlist is built by INTROSPECTING information_schema at
# request time -- still exactly as safe (every dimension/metric key the
# client can send is one this endpoint itself read from the live schema
# moments earlier, same "server defines the universe of valid identifiers"
# guarantee as Shopify Explorer's hardcoded dict), just generated instead
# of transcribed. jsonb columns (actions[], action_values[], etc. -- the
# 102 raw per-action-type arrays) are excluded: they're not scalar, so
# "SUM" or "GROUP BY" on them isn't meaningful -- the useful numbers
# inside them (purchases, conv_value, roas, ncp_count, ...) are already
# extracted into ad_lifecycle's own numeric computed columns, which DO
# show up here.
#
# Known gap, flagged rather than faked: demographic (age/gender) and
# placement/device breakdown dimensions are NOT available -- this project
# has never fetched breakdown-split Insights data (every backfill so far
# used breakdowns=[[]]). That's a separate, materially larger fetch (each
# breakdown combo multiplies row count the same way high entity-count
# levels do -- see insights_flatten.py's own notes on this), not something
# this endpoint can surface from data that doesn't exist yet.
# `attribution_setting` / `anchor_event_attribution_setting` (the actual
# per-ad attribution CONFIGURATION, not a breakdown) ARE already fetched
# and appear below as ordinary dimensions.
# ----------------------------------------------------------------------

_META_DATASETS: dict[str, dict[str, str | None]] = {
    "ad_performance": {"label": "Ad performance (ad_lifecycle -- full ~195-column width)", "table": "ad_lifecycle", "date_column": None},
    "adset_insights": {"label": "Adset insights", "table": "adset_insights", "date_column": "date_start"},
    "campaign_insights": {"label": "Campaign insights", "table": "campaign_insights", "date_column": "date_start"},
}

#: column_name -> extra columns to exclude even though their type would
#: otherwise qualify (housekeeping timestamps, not something anyone wants
#: to group-by or sum).
_META_EXCLUDED_COLUMNS = {"extracted_at", "updated_at", "flattened_at", "lifecycle_refreshed_at"}

_DIMENSION_TYPES = {"text", "boolean", "date", "timestamp with time zone"}
_METRIC_TYPES = {"numeric", "integer", "bigint", "double precision", "real"}


def _humanize_column(name: str) -> str:
    overrides = {"roas": "ROAS", "ctr": "CTR", "cpc": "CPC", "cpm": "CPM", "cpp": "CPP", "ncp": "NCP", "ftewv": "FTEWV", "utm": "UTM", "id": "ID"}
    words = [overrides.get(w, w.capitalize()) for w in name.split("_")]
    return " ".join(words)


async def _introspect_meta_dataset(session: AsyncSession, table: str) -> tuple[dict[str, str], dict[str, str]]:
    result = await session.execute(
        text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :t"), {"t": table}
    )
    dimensions: dict[str, str] = {}
    metrics: dict[str, str] = {}
    for column_name, data_type in result.all():
        if column_name in _META_EXCLUDED_COLUMNS:
            continue
        if data_type in _METRIC_TYPES:
            metrics[column_name] = _humanize_column(column_name)
        elif data_type in _DIMENSION_TYPES:
            dimensions[column_name] = _humanize_column(column_name)
    return dimensions, metrics


class MetaExplorerSchemaDataset(BaseModel):
    key: str
    label: str
    date_dimension: str | None
    dimensions: list[dict[str, str]]
    metrics: list[dict[str, str]]


class MetaExplorerSchemaResponse(BaseModel):
    datasets: list[MetaExplorerSchemaDataset]


@router.get("/meta-explorer/schema", response_model=MetaExplorerSchemaResponse)
async def get_meta_explorer_schema(session: SessionDep) -> MetaExplorerSchemaResponse:
    datasets = []
    for key, cfg in _META_DATASETS.items():
        dims, metrics = await _introspect_meta_dataset(session, cfg["table"])
        datasets.append(
            MetaExplorerSchemaDataset(
                key=key,
                label=cfg["label"],
                date_dimension=cfg["date_column"],
                dimensions=[{"key": k, "label": v} for k, v in sorted(dims.items())],
                metrics=[{"key": k, "label": v} for k, v in sorted(metrics.items())],
            )
        )
    return MetaExplorerSchemaResponse(datasets=datasets)


class MetaExplorerQueryRequest(BaseModel):
    dataset: str
    dimensions: list[str] = []
    metrics: list[str]
    date_from: date | None = None
    date_to: date | None = None
    limit: int = 200


class MetaExplorerQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


async def _resolve_meta_explorer_query(session: AsyncSession, body: MetaExplorerQueryRequest) -> tuple[str, dict[str, Any]]:
    cfg = _META_DATASETS.get(body.dataset)
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset '{body.dataset}'. See /meta-explorer/schema.")
    if not body.metrics:
        raise HTTPException(status_code=400, detail="At least one metric is required.")

    dims, metrics = await _introspect_meta_dataset(session, cfg["table"])

    unknown_dims = [d for d in body.dimensions if d not in dims]
    if unknown_dims:
        raise HTTPException(status_code=400, detail=f"Unknown dimension(s) for dataset '{body.dataset}': {unknown_dims}")
    unknown_metrics = [m for m in body.metrics if m not in metrics]
    if unknown_metrics:
        raise HTTPException(status_code=400, detail=f"Unknown metric(s) for dataset '{body.dataset}': {unknown_metrics}")

    dim_select = [f"{d} AS {d}" for d in body.dimensions]
    metric_select = [f"SUM({m}) AS {m}" for m in body.metrics]

    where_clauses = []
    params: dict[str, Any] = {}
    date_column = cfg["date_column"]
    if date_column and (body.date_from or body.date_to):
        if body.date_from:
            where_clauses.append(f"{date_column} >= :date_from")
            params["date_from"] = body.date_from
        if body.date_to:
            where_clauses.append(f"{date_column} <= :date_to")
            params["date_to"] = body.date_to
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    group_by_sql = f"GROUP BY {', '.join(body.dimensions)}" if body.dimensions else ""
    order_by_sql = f"ORDER BY {body.metrics[0]} DESC NULLS LAST"

    sql = (
        f"SELECT {', '.join(dim_select + metric_select)} FROM {cfg['table']} "
        f"{where_sql} {group_by_sql} {order_by_sql} LIMIT :limit"
    )
    params["limit"] = min(body.limit, 1000)
    return sql, params


@router.post("/meta-explorer/query", response_model=MetaExplorerQueryResponse)
async def query_meta_explorer(session: SessionDep, body: MetaExplorerQueryRequest) -> MetaExplorerQueryResponse:
    sql, params = await _resolve_meta_explorer_query(session, body)
    result = await session.execute(text(sql), params)
    columns = list(result.keys())
    rows = [dict(r._mapping) for r in result]
    return MetaExplorerQueryResponse(columns=columns, rows=rows)


# ----------------------------------------------------------------------
# CPIS -- backed by cpis_by_sku (app/services/gold/cpis.py). See that
# module's docstring for the full story: legacy's own `cpis` column was
# never actually computed (always written None); this reads the two
# metrics legacy actually shipped (cost_per_ncp) plus the literal CPIS
# formula legacy left unfinished (cost_per_unit_sold), per master SKU,
# across 1d/7d/30d windows. units_sold is genuinely windowed;
# ad_spend/ncp_count are lifetime totals (ad_lifecycle has no daily grain
# yet) -- surfaced as separate fields, not blended into one misleading
# number.
# ----------------------------------------------------------------------

_CPIS_SORT_COLUMNS = {
    "ad_spend": "ad_spend",
    "cost_per_ncp": "cost_per_ncp",
    "cost_per_unit_sold": "cost_per_unit_sold",
    "units_sold": "units_sold",
}


class CpisRow(BaseModel):
    master_sku: str
    window_key: str
    window_from: date | None
    window_to: date | None
    units_sold: float | None
    ending_inventory_units: float | None
    avg_sell_through_rate: float | None
    matched_ad_count: int | None
    ad_spend: float | None
    ncp_count: float | None
    cost_per_ncp: float | None
    cost_per_unit_sold: float | None


class CpisResponse(BaseModel):
    rows: list[CpisRow]
    total: int


@router.get("/cpis", response_model=CpisResponse)
async def get_cpis(
    session: SessionDep,
    window: Literal["1d", "7d", "30d"] = Query(default="7d"),
    search: str | None = Query(default=None, description="Matches master_sku, case-insensitive substring."),
    only_matched: bool = Query(default=False, description="Only SKUs with at least one matched ad."),
    sort: Literal["ad_spend", "cost_per_ncp", "cost_per_unit_sold", "units_sold"] = Query(default="ad_spend"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CpisResponse:
    sort_column = _CPIS_SORT_COLUMNS[sort]

    where_clauses = ["window_key = :window"]
    params: dict[str, object] = {"window": window}
    if search:
        where_clauses.append("master_sku ILIKE :search")
        params["search"] = f"%{search}%"
    if only_matched:
        where_clauses.append("matched_ad_count > 0")
    where_sql = f"WHERE {' AND '.join(where_clauses)}"

    rows_result = await session.execute(
        text(f"SELECT * FROM cpis_by_sku {where_sql} ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [CpisRow(**dict(r._mapping)) for r in rows_result]

    total = (await session.execute(text(f"SELECT COUNT(*) FROM cpis_by_sku {where_sql}"), params)).scalar_one()

    return CpisResponse(rows=rows, total=total)


class CpisMatchedAdRow(BaseModel):
    ad_id: str
    ad_name: str | None
    spend: float | None
    ncp_count: float | None
    category: str | None


class CpisMatchedAdsResponse(BaseModel):
    master_sku: str
    ads: list[CpisMatchedAdRow]


@router.get("/cpis/{master_sku}/ads", response_model=CpisMatchedAdsResponse)
async def get_cpis_matched_ads(session: SessionDep, master_sku: str) -> CpisMatchedAdsResponse:
    """Every ad this master SKU's spend/NCP totals were built from --
    lets a user verify the substring match wasn't a false positive."""
    rows_result = await session.execute(
        text(
            "SELECT ad_id, ad_name, spend, ncp_count, category FROM ad_lifecycle "
            "WHERE ad_name ILIKE :needle ORDER BY spend DESC NULLS LAST"
        ),
        {"needle": f"%{master_sku}%"},
    )
    ads = [CpisMatchedAdRow(**dict(r._mapping)) for r in rows_result]
    return CpisMatchedAdsResponse(master_sku=master_sku, ads=ads)


# ----------------------------------------------------------------------
# Saturation curve -- real Python computation (not a canned table read):
# fits a power-law diminishing-returns curve (y = a * spend^b) to a set
# of ads' (spend, conversions) points via log-log linear regression.
# b < 1 is the textbook signature of ad-spend saturation -- each
# additional rupee buys fewer incremental conversions than the last; b >=
# 1 means the data doesn't show diminishing returns (or there isn't
# enough spread to tell). Uses the stdlib's `statistics.linear_regression`
# (Python 3.10+) -- no numpy/scipy in this project's venv, and a
# log-log power-law fit doesn't need them (it's ordinary least squares on
# the logged values, which the stdlib already does correctly).
#
# This is deliberately scoped to `ad_lifecycle` -- real per-ad
# lifetime-total spend and conversions, same "as of last sync, not a
# daily series" caveat as everywhere else in this project (see
# ad_lifecycle.py). A per-ad scatter, not a per-day one -- the curve
# describes how conversions scale ACROSS this project's whole roster of
# ads at different spend levels, not one ad's spend ramping over time.
# ----------------------------------------------------------------------

_SATURATION_Y_METRICS = {
    "ncp_count": "NCP",
    "purchases": "Purchases",
    "ftewv_count": "First-time EWV",
}


class SaturationPoint(BaseModel):
    ad_id: str
    ad_name: str | None
    spend: float
    y: float


class SaturationFit(BaseModel):
    a: float
    b: float
    r_squared: float
    is_saturating: bool
    curve_points: list[dict[str, float]]


class SaturationCurveResponse(BaseModel):
    y_metric: str
    y_label: str
    points: list[SaturationPoint]
    fit: SaturationFit | None
    excluded_zero_or_missing: int


def _fit_power_law(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """OLS on log(x)/log(y) -> y = a * x^b. Returns (a, b, r_squared)."""
    log_x = [math.log(v) for v in xs]
    log_y = [math.log(v) for v in ys]
    b, log_a = statistics.linear_regression(log_x, log_y)
    a = math.exp(log_a)

    mean_log_y = sum(log_y) / len(log_y)
    ss_tot = sum((v - mean_log_y) ** 2 for v in log_y)
    ss_res = sum((ly - (log_a + b * lx)) ** 2 for lx, ly in zip(log_x, log_y))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, r_squared


@router.get("/saturation-curve", response_model=SaturationCurveResponse)
async def get_saturation_curve(
    session: SessionDep,
    y_metric: Literal["ncp_count", "purchases", "ftewv_count"] = Query(default="ncp_count"),
    master_sku: str | None = Query(default=None, description="Restrict to ads matching this master SKU (same substring match as CPIS)."),
    category: str | None = Query(default=None, description="Restrict to one ad_lifecycle category, e.g. 'Winner'."),
    account_name: str | None = Query(default=None),
) -> SaturationCurveResponse:
    where_clauses = ["spend IS NOT NULL"]
    params: dict[str, object] = {}
    if master_sku:
        where_clauses.append("ad_name ILIKE :needle")
        params["needle"] = f"%{master_sku}%"
    if category:
        where_clauses.append("category = :category")
        params["category"] = category
    if account_name:
        where_clauses.append("account_name = :account_name")
        params["account_name"] = account_name
    where_sql = f"WHERE {' AND '.join(where_clauses)}"

    rows = (
        await session.execute(
            text(f"SELECT ad_id, ad_name, spend, {y_metric} AS y FROM ad_lifecycle {where_sql}"), params
        )
    ).mappings().all()

    points = [
        SaturationPoint(ad_id=r["ad_id"], ad_name=r["ad_name"], spend=float(r["spend"]), y=float(r["y"] or 0))
        for r in rows
    ]

    # Power-law fit needs strictly positive x AND y (log undefined at/below 0).
    fittable = [p for p in points if p.spend > 0 and p.y > 0]
    excluded = len(points) - len(fittable)

    fit: SaturationFit | None = None
    if len(fittable) >= 5:
        xs = [p.spend for p in fittable]
        ys = [p.y for p in fittable]
        a, b, r_squared = _fit_power_law(xs, ys)

        x_min, x_max = min(xs), max(xs)
        steps = 40
        curve_points = [
            {"x": x_min + (x_max - x_min) * i / (steps - 1), "y": a * (x_min + (x_max - x_min) * i / (steps - 1)) ** b}
            for i in range(steps)
        ]
        fit = SaturationFit(a=a, b=b, r_squared=r_squared, is_saturating=b < 1.0, curve_points=curve_points)

    return SaturationCurveResponse(
        y_metric=y_metric,
        y_label=_SATURATION_Y_METRICS[y_metric],
        points=points,
        fit=fit,
        excluded_zero_or_missing=excluded,
    )


# ----------------------------------------------------------------------
# Overview summary -- powers the Dashboard tab's widget tiles. One
# efficient aggregate read instead of the widgets each composing several
# of the row-level endpoints above (which paginate and aren't meant for
# "give me the grand total"). Plain SQL aggregates only -- no branching
# logic here, so no reason to reach for Python per this project's own
# "prefer Python for real logic, SQL is fine for plain aggregates" rule.
# ----------------------------------------------------------------------

class BreakdownItem(BaseModel):
    label: str
    value: float


class TopLandingPage(BaseModel):
    landing_page_path: str
    sessions: int
    ad_spend: float


class TopCpisSku(BaseModel):
    master_sku: str
    ad_spend: float
    cost_per_ncp: float | None


class OverviewSummaryResponse(BaseModel):
    total_spend: float
    total_impressions: float
    total_shopify_revenue: float
    total_shopify_orders: int
    category_breakdown: list[BreakdownItem]
    channel_breakdown: list[BreakdownItem]
    top_landing_pages: list[TopLandingPage]
    top_cpis_skus: list[TopCpisSku]


@router.get("/overview-summary", response_model=OverviewSummaryResponse)
async def get_overview_summary(session: SessionDep) -> OverviewSummaryResponse:
    totals = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(spend),0), COALESCE(SUM(impressions),0), "
                "COALESCE(SUM(shopify_revenue),0), COALESCE(SUM(shopify_orders),0) FROM ad_performance_summary"
            )
        )
    ).one()

    category_rows = (
        await session.execute(
            text("SELECT COALESCE(category,'Uncategorized'), SUM(spend) FROM ad_performance_summary GROUP BY 1 ORDER BY 2 DESC")
        )
    ).all()

    channel_rows = (await session.execute(text("SELECT utm_source, total_price FROM shopify_order_attribution"))).all()
    channel_totals: dict[str, float] = {}
    for utm_source, total_price in channel_rows:
        ch = _classify_channel(utm_source)
        channel_totals[ch] = channel_totals.get(ch, 0.0) + float(total_price or 0)

    landing_rows = (
        await session.execute(
            text("SELECT landing_page_path, sessions, ad_spend FROM landing_page_analysis_30d ORDER BY sessions DESC LIMIT 5")
        )
    ).all()

    cpis_rows = (
        await session.execute(
            text(
                "SELECT master_sku, ad_spend, cost_per_ncp FROM cpis_by_sku WHERE window_key = '7d' AND matched_ad_count > 0 "
                "ORDER BY ad_spend DESC LIMIT 5"
            )
        )
    ).all()

    return OverviewSummaryResponse(
        total_spend=float(totals[0]),
        total_impressions=float(totals[1]),
        total_shopify_revenue=float(totals[2]),
        total_shopify_orders=int(totals[3]),
        category_breakdown=[BreakdownItem(label=r[0], value=float(r[1] or 0)) for r in category_rows],
        channel_breakdown=[BreakdownItem(label=k, value=v) for k, v in channel_totals.items()],
        top_landing_pages=[
            TopLandingPage(landing_page_path=r[0], sessions=int(r[1] or 0), ad_spend=float(r[2] or 0)) for r in landing_rows
        ],
        top_cpis_skus=[
            TopCpisSku(master_sku=r[0], ad_spend=float(r[1] or 0), cost_per_ncp=float(r[2]) if r[2] is not None else None)
            for r in cpis_rows
        ],
    )
