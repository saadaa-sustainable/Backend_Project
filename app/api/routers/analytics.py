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
import os
import re as _re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
# Ads Analyse (a.k.a. Creative Testing) -- wide per-ad table combining
# Meta metrics + Shopify-attributed revenue + the F1..F4 fatigue-test
# flags + P0/P1/P2 category. Same row-level-table intent as legacy's
# "Ads Analyse" view (view-ae / ae_table_view).
#
# 2026-08-28: widened. Reading only `ad_performance_summary` (Gold, 20
# columns) hid the F1..F4 flags, cost_per_ncp, cost_per_ftewv,
# ncp_count, ftewv_count, contrib_margin_pct, roas -- which are the
# actual columns Creative Testing users pivot around ("who passed F3",
# "cost per new customer", "which ads have contribution margin > 20%").
# All of that lives in `ad_lifecycle`, which is 1:1 with
# ad_performance_summary on ad_id. Now LEFT JOINs the two so the
# response carries both sides.
#
# Not yet exposed (needs Silver-layer work, not a router change): the
# six fleet-anchored efficiency scores CTD ships in its ae_table_view
# (cpr_eff, ftv_contrib_eff, ftev_volume, ncp_cost_eff, roas_eff,
# profit_vol_eff). Those are computed in CTD's refresh_ae_table.py by
# ranking every ad against the account-level distribution; this project
# doesn't compute them yet.
# ----------------------------------------------------------------------

#: SELECT-list expression -> ORDER BY expression. Keeping the map here
#: instead of relying on column aliases in ORDER BY means a client
#: passing `sort=cost_per_ncp` targets the JOIN's underlying column
#: unambiguously even if some other column later gets that alias.
_ADS_ANALYSE_SORT_COLUMNS = {
    "spend": "aps.spend",
    "meta_roas": "aps.meta_roas",
    "shopify_roas": "aps.shopify_roas",
    "shopify_revenue": "aps.shopify_revenue",
    "impressions": "aps.impressions",
    "cost_per_ncp": "al.cost_per_ncp",
    "cost_per_ftewv": "al.cost_per_ftewv",
    "contrib_margin_pct": "al.contrib_margin_pct",
    "roas": "al.roas",
}

_ADS_ANALYSE_SELECT = (
    "aps.ad_id, aps.adset_id, aps.campaign_id, aps.account_id, "
    "aps.ad_name, aps.ad_status, aps.ad_effective_status, aps.adset_name, "
    "aps.campaign_name, aps.account_name, aps.category, "
    "aps.spend, aps.impressions, aps.purchases, aps.meta_conv_value, aps.meta_roas, "
    "aps.cost_per_purchase, aps.ctr_pct, "
    "aps.shopify_orders, aps.shopify_revenue, aps.shopify_aov, aps.shopify_roas, "
    "aps.cost_per_shopify_order, aps.gold_refreshed_at, "
    "aps.f1_pass, aps.f2_pass, aps.f3_pass, aps.f4_pass, "
    "al.reach, al.frequency, al.conv_value, "
    "al.ncp_count, al.ftewv_count, al.cost_per_ncp, al.cost_per_ftewv, "
    "al.roas, al.contrib_margin_pct, al.profit_efficiency, al.cpr_1000, al.cpc_link, "
    "al.checkout_compl_pct, al.cr_lc_pct, al.atc_lc_pct, al.ci_atc_pct, "
    "al.inline_link_clicks AS link_clicks_raw, "
    "al.add_to_cart AS atc_count, "
    "al.checkout_initiate AS ci_count, "
    "al.engagement_count, "
    "al.ad_created_time::date AS ad_created_date, "
    # Derivable columns — SELECT-time so no schema change needed.
    # Formulas match CTD's dashboard.js definitions verbatim.
    "CASE WHEN al.impressions > 0 THEN al.spend * 1000.0 / al.impressions END AS cost_per_1000, "
    "CASE WHEN al.conv_value > 0 "
    "     THEN (aps.shopify_revenue - al.conv_value) / al.conv_value * 100 END AS meta_shop_diff_pct, "
    "CASE WHEN al.reach > 0 THEN al.ftewv_count::numeric / al.reach * 100 END AS pct_reach_ftewv, "
    # ltv_* columns: for lifetime rows these equal reach/frequency (CTD's
    # ae_table_view keeps them separate because it also has windowed rows;
    # this endpoint is lifetime-only until the window-metrics endpoint ships).
    "al.reach AS ltv_reach, "
    "al.frequency AS ltv_frequency, "
    # first_seen_date: earliest ad_insights.date_start per ad. Joined below.
    "fs.first_seen_date"
)

_ADS_ANALYSE_FROM = (
    "FROM ad_performance_summary aps "
    "LEFT JOIN ad_lifecycle al ON al.ad_id = aps.ad_id "
    # first_seen_date needs a per-ad MIN over ad_insights.date_start.
    # ad_insights is 1:1 with ad_id so a lateral MIN is trivial -- no
    # heavy scan. If ad_insights grows to daily grain later this becomes
    # a proper subquery/materialized column.
    "LEFT JOIN LATERAL ("
    "  SELECT MIN(ai.date_start) AS first_seen_date FROM ad_insights ai WHERE ai.ad_id = aps.ad_id"
    ") fs ON true"
)


class AdsAnalyseRow(BaseModel):
    ad_id: str
    adset_id: str | None
    campaign_id: str | None
    account_id: str | None
    ad_name: str | None
    ad_status: str | None
    ad_effective_status: str | None
    adset_name: str | None
    campaign_name: str | None
    account_name: str | None
    category: str | None
    spend: float | None
    impressions: float | None
    reach: float | None
    frequency: float | None
    purchases: float | None
    conv_value: float | None
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
    #: Fatigue-test / creative-diagnostic flags -- see ad_lifecycle's
    #: F1..F4 column comments for the exact thresholds each one enforces.
    #: Exposed so a Creative Testing UI can filter to "F1 passed", "F1-F3
    #: passed but F4 failed", etc. without the caller having to know the
    #: raw metrics behind each rule.
    f1_pass: bool | None
    f2_pass: bool | None
    f3_pass: bool | None
    f4_pass: bool | None
    ncp_count: float | None
    ftewv_count: float | None
    cost_per_ncp: float | None
    cost_per_ftewv: float | None
    #: Meta-side ROAS from ad_lifecycle (conv_value / spend). Distinct
    #: from `meta_roas` in ad_performance_summary -- that column reads
    #: from the same source but rounds/typecasts differently in the Gold
    #: build; both are exposed so the UI can match whatever CTD number
    #: users are used to.
    roas: float | None
    contrib_margin_pct: float | None
    profit_efficiency: float | None
    cpr_1000: float | None
    cpc_link: float | None
    checkout_compl_pct: float | None
    cr_lc_pct: float | None
    atc_lc_pct: float | None
    ci_atc_pct: float | None
    ad_created_date: date | None
    # Tier-2 derivable columns (computed in the SELECT, no schema change)
    link_clicks_raw: float | None
    atc_count: float | None
    ci_count: float | None
    engagement_count: float | None
    cost_per_1000: float | None
    #: (shopify_revenue - conv_value) / conv_value * 100 -- CTD's "Meta
    #: over-reporting" metric. Negative means Meta reported MORE than
    #: Shopify's ground-truth revenue; positive means Meta under-reported.
    meta_shop_diff_pct: float | None
    pct_reach_ftewv: float | None
    ltv_reach: float | None
    ltv_frequency: float | None
    first_seen_date: date | None


class AdsAnalyseTotals(BaseModel):
    """Aggregate KPI totals for the summary strip -- computed over the
    SAME filter set as `rows` (including category + date filters), so
    the tiles reflect exactly what the table below shows. Mirrors
    kwikengage's Marketing Insights KPI row.

    ROAS/CTR/CPM are simple averages -- weighting by spend gets a more
    honest number but changes the semantics from "average ad" to "one
    ad's worth of the aggregate", which is harder to explain in a
    tile. Kwikengage uses simple averages too."""
    ad_count: int
    spend: float
    impressions: float
    reach: float
    purchases: float
    conv_value: float
    shopify_orders: float
    shopify_revenue: float
    ncp_count: float
    ftewv_count: float
    avg_meta_roas: float | None
    avg_shopify_roas: float | None
    avg_ctr_pct: float | None


class AdsAnalyseResponse(BaseModel):
    rows: list[AdsAnalyseRow]
    total: int
    #: Per-category ad counts under the SAME filters as `rows` (except
    #: `category` itself is dropped, so the client can render the
    #: category tiles alongside a category-filtered table without those
    #: tiles collapsing to just the one selected category). Matches
    #: CTD's KPI-card behaviour on the Creative Testing view.
    category_counts: dict[str, int]
    #: Aggregate totals for the KPI strip above the category tiles.
    #: Reflects the current filter set (including date_field/date-range
    #: filters). Kwikengage-style: ad_count, spend, impressions, reach,
    #: purchases, conv_value, ncp, ROAS averages, CTR average.
    totals: AdsAnalyseTotals


@router.get("/ads-analyse", response_model=AdsAnalyseResponse)
async def get_ads_analyse(
    session: SessionDep,
    account_name: str | None = Query(default=None),
    campaign_name: str | None = Query(default=None),
    ad_effective_status: str | None = Query(default=None),
    category: str | None = Query(
        default=None,
        description="Filter to one category (P0/P1/P2/Winner/Discarded/etc.). "
        "Does not affect `category_counts` -- those always reflect all categories "
        "under the OTHER filters, so a UI can render category tiles + a filtered table.",
    ),
    f1_pass: bool | None = Query(default=None),
    f2_pass: bool | None = Query(default=None),
    f3_pass: bool | None = Query(default=None),
    f4_pass: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Matches ad_name, case-insensitive substring."),
    only_with_shopify_orders: bool = Query(default=False),
    from_date: date | None = Query(
        default=None,
        description=(
            "Together with to_date + date_field, filters the ads list. "
            "See date_field for how the window is applied. Both are required."
        ),
    ),
    to_date: date | None = Query(default=None),
    date_field: Literal["created", "first_seen", "delivery"] = Query(
        default="created",
        description=(
            "How to apply [from_date, to_date]: "
            "'created' filters ads whose ad_created_date falls inside the window (default, "
            "matches CTD's Creative Testing behaviour where you're evaluating recently-launched creatives); "
            "'first_seen' filters ads whose first_seen_date (first ad_insights row) falls in the window; "
            "'delivery' keeps every ad but OVERLAYS spend/impressions/reach in the response with values "
            "summed from raw_dump_meta insights rows whose date_start is in the window (Ads Analyse "
            "'delivery date' semantics)."
        ),
    ),
    sort: Literal[
        "spend", "meta_roas", "shopify_roas", "shopify_revenue", "impressions",
        "cost_per_ncp", "cost_per_ftewv", "contrib_margin_pct", "roas",
    ] = Query(default="spend"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdsAnalyseResponse:
    sort_column = _ADS_ANALYSE_SORT_COLUMNS[sort]

    # Base predicates apply to BOTH the row query and the category_counts
    # query -- everything except `category` itself, because
    # category_counts should show the distribution across categories
    # under the current filters (the whole point of a KPI-tile is to
    # show what user's filters leave behind per category).
    base_where: list[str] = []
    params: dict[str, object] = {}
    if account_name:
        base_where.append("aps.account_name = :account_name")
        params["account_name"] = account_name
    if campaign_name:
        base_where.append("aps.campaign_name = :campaign_name")
        params["campaign_name"] = campaign_name
    if ad_effective_status:
        base_where.append("aps.ad_effective_status = :ad_effective_status")
        params["ad_effective_status"] = ad_effective_status
    if search:
        base_where.append("aps.ad_name ILIKE :search")
        params["search"] = f"%{search}%"
    if only_with_shopify_orders:
        base_where.append("aps.shopify_orders > 0")
    for flag_name, flag_val in (
        ("f1_pass", f1_pass), ("f2_pass", f2_pass), ("f3_pass", f3_pass), ("f4_pass", f4_pass),
    ):
        if flag_val is not None:
            base_where.append(f"aps.{flag_name} = :{flag_name}")
            params[flag_name] = flag_val
    # ── date_field filter ──────────────────────────────────────────
    # 'created' and 'first_seen' HIDE ads outside the picked window
    # (the CTD Creative Testing default -- you're evaluating recent
    # creative launches). 'delivery' KEEPS every ad but overlays the
    # windowed metrics below in the overlay block.
    if from_date and to_date and date_field == "created":
        base_where.append("al.ad_created_time::date BETWEEN :from_date AND :to_date")
        params["from_date"] = from_date
        params["to_date"] = to_date
    elif from_date and to_date and date_field == "first_seen":
        base_where.append("fs.first_seen_date BETWEEN :from_date AND :to_date")
        params["from_date"] = from_date
        params["to_date"] = to_date

    row_where = list(base_where)
    if category:
        row_where.append("aps.category = :category")
        params["category"] = category
    row_where_sql = f"WHERE {' AND '.join(row_where)}" if row_where else ""
    base_where_sql = f"WHERE {' AND '.join(base_where)}" if base_where else ""

    rows_result = await session.execute(
        text(
            f"SELECT {_ADS_ANALYSE_SELECT} {_ADS_ANALYSE_FROM} {row_where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [AdsAnalyseRow(**dict(r._mapping)) for r in rows_result]

    # ── OPTIONAL windowed overlay ────────────────────────────────
    # When from_date/to_date are set, replace lifetime spend / impressions
    # / reach / purchases / conv_value / roas with values summed from
    # Bronze insights rows in that window. Two-tier fallback: prefer
    # raw_dump_meta_daily (deduped) when it has coverage; fall back to
    # raw_dump_meta otherwise. Uses text comparison on date_start
    # (YYYY-MM-DD sorts correctly) to keep the index scan cheap.
    if rows and from_date and to_date and date_field == "delivery":
        # Windowed overlay -- only when date_field='delivery'. For
        # 'created' / 'first_seen' the rows themselves were already
        # filtered by the date window above, so the lifetime metrics
        # are what the user wants (they mean "everything this ad ever
        # did, and it was launched inside the window"). For 'delivery'
        # we keep every ad but replace lifetime metrics with the
        # window's summed spend/impressions/reach.
        #
        # Computed via psycopg2 through a fresh sync connection to
        # sidestep SQLAlchemy asyncpg's prepared statement collision
        # under transaction-mode pgbouncer -- see
        # scripts/refresh_raw_dump_meta_daily.py for the same trick.
        import psycopg2
        from app.config import get_settings
        db_url = get_settings().database.database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        ).split("?", 1)[0]
        ad_ids = [r.ad_id for r in rows]
        windowed_map: dict[str, dict[str, float]] = {}
        with psycopg2.connect(db_url, connect_timeout=15) as sync_conn:
            with sync_conn.cursor() as cur:
                cur.execute(
                    "SELECT ad_id, SUM(spend) AS spend, SUM(impressions) AS impressions, SUM(reach) AS reach "
                    "FROM ("
                    "  SELECT raw_payload->>'ad_id' AS ad_id, "
                    "         COALESCE(NULLIF(raw_payload->>'spend','')::numeric,0) AS spend, "
                    "         COALESCE(NULLIF(raw_payload->>'impressions','')::numeric,0) AS impressions, "
                    "         COALESCE(NULLIF(raw_payload->>'reach','')::numeric,0) AS reach "
                    "  FROM public.raw_dump_meta_daily "
                    "  WHERE raw_payload->>'ad_id' = ANY(%(ad_ids)s) "
                    "    AND raw_payload->>'date_start' BETWEEN %(from_str)s AND %(to_str)s "
                    "  UNION ALL "
                    "  SELECT raw_payload->>'ad_id' AS ad_id, "
                    "         COALESCE(NULLIF(raw_payload->>'spend','')::numeric,0), "
                    "         COALESCE(NULLIF(raw_payload->>'impressions','')::numeric,0), "
                    "         COALESCE(NULLIF(raw_payload->>'reach','')::numeric,0) "
                    "  FROM public.raw_dump_meta "
                    "  WHERE object_type='insights' "
                    "    AND raw_payload->>'ad_id' = ANY(%(ad_ids)s) "
                    "    AND raw_payload->>'date_start' BETWEEN %(from_str)s AND %(to_str)s "
                    ") u GROUP BY ad_id",
                    {
                        "ad_ids": ad_ids,
                        "from_str": from_date.isoformat(),
                        "to_str": to_date.isoformat(),
                    },
                )
                for aid, spend, impr, reach in cur.fetchall():
                    windowed_map[aid] = {"spend": float(spend), "impressions": float(impr), "reach": float(reach)}

        for r in rows:
            w = windowed_map.get(r.ad_id)
            if w is None:
                # No coverage in window -> ad didn't run in that range
                r.spend = 0.0
                r.impressions = 0.0
                r.reach = 0.0
            else:
                r.spend = w["spend"]
                r.impressions = w["impressions"]
                r.reach = w["reach"]
            r.cost_per_1000 = (r.spend * 1000.0 / r.impressions) if r.spend and r.impressions else None

    total = (
        await session.execute(text(f"SELECT COUNT(*) {_ADS_ANALYSE_FROM} {row_where_sql}"), params)
    ).scalar_one()

    counts_result = await session.execute(
        text(
            f"SELECT COALESCE(aps.category, 'Uncategorized'), COUNT(*) {_ADS_ANALYSE_FROM} "
            f"{base_where_sql} GROUP BY 1"
        ),
        {k: v for k, v in params.items() if k != "category"},
    )
    category_counts = {row[0]: row[1] for row in counts_result}

    # Aggregate totals for the KPI strip -- kwikengage's Marketing
    # Insights row. Same filter set as `rows` (row_where_sql includes
    # category + F1..F4 flags + date_field filter). Uses SUM for
    # counters and AVG for rate-style metrics; NULLs excluded from AVG
    # so a handful of unpopulated rows don't skew the number to zero.
    totals_row = (
        await session.execute(
            text(
                f"SELECT COUNT(*) AS ad_count, "
                f"COALESCE(SUM(aps.spend),0) AS spend, "
                f"COALESCE(SUM(aps.impressions),0) AS impressions, "
                f"COALESCE(SUM(al.reach),0) AS reach, "
                f"COALESCE(SUM(aps.purchases),0) AS purchases, "
                f"COALESCE(SUM(al.conv_value),0) AS conv_value, "
                f"COALESCE(SUM(aps.shopify_orders),0) AS shopify_orders, "
                f"COALESCE(SUM(aps.shopify_revenue),0) AS shopify_revenue, "
                f"COALESCE(SUM(al.ncp_count),0) AS ncp_count, "
                f"COALESCE(SUM(al.ftewv_count),0) AS ftewv_count, "
                f"AVG(NULLIF(aps.meta_roas,0)) AS avg_meta_roas, "
                f"AVG(NULLIF(aps.shopify_roas,0)) AS avg_shopify_roas, "
                f"AVG(NULLIF(aps.ctr_pct,0)) AS avg_ctr_pct "
                f"{_ADS_ANALYSE_FROM} {row_where_sql}"
            ),
            params,
        )
    ).one()
    totals = AdsAnalyseTotals(
        ad_count=int(totals_row.ad_count or 0),
        spend=float(totals_row.spend or 0),
        impressions=float(totals_row.impressions or 0),
        reach=float(totals_row.reach or 0),
        purchases=float(totals_row.purchases or 0),
        conv_value=float(totals_row.conv_value or 0),
        shopify_orders=float(totals_row.shopify_orders or 0),
        shopify_revenue=float(totals_row.shopify_revenue or 0),
        ncp_count=float(totals_row.ncp_count or 0),
        ftewv_count=float(totals_row.ftewv_count or 0),
        avg_meta_roas=float(totals_row.avg_meta_roas) if totals_row.avg_meta_roas is not None else None,
        avg_shopify_roas=float(totals_row.avg_shopify_roas) if totals_row.avg_shopify_roas is not None else None,
        avg_ctr_pct=float(totals_row.avg_ctr_pct) if totals_row.avg_ctr_pct is not None else None,
    )

    return AdsAnalyseResponse(
        rows=rows, total=total, category_counts=category_counts, totals=totals,
    )


# ----------------------------------------------------------------------
# Last Click UTM -- order-level Shopify->Meta attribution, backed by
# shopify_order_attribution. Mirrors legacy's "Ad Intelligence" view:
# channel tiles (Meta/Google/Retention/Other, classified from utm_source)
# plus a filterable per-order table showing the resolved ad/campaign.
# Channel classification is real branching logic -> done in Python
# (_classify_channel), not a SQL CASE, per user preference (2026-08-27).
#
# 2026-08-28: switched from exact-set match to substring/prefix match --
# the old {"meta","facebook","instagram","ig"} whitelist misclassified
# every real-world source variant ("fb", "IG_Ads", "instagram-stories",
# "meta_ads", "Facebook_Feed", ...) as "Other". Substring match on the
# LOWER'd source catches all of them without maintaining an exhaustive
# whitelist. Also added a date window: the old tiles ran an unfiltered
# COUNT over the entire lifetime of shopify_order_attribution on every
# call, which meant tiles grew forever and were never comparable
# period-over-period.
# ----------------------------------------------------------------------

#: Substrings that identify a channel from utm_source. Order matters --
#: earlier channels win over later. Ported from CTD dashboard.js:5351-5361
#: (channel color mapping) and observed live utm_source values in
#: media_data_saadaa's shopify_order_attribution table (2026-08-28).
#:
#: Nine channels, not four:
#:   1. Meta / Google / Retention   -- paid + owned messaging (unchanged from earlier)
#:   2. Organic (IG)                -- Instagram bio_link / stories not tagged as ads
#:   3. Brand Collab                -- influencer / affiliate partnerships
#:   4. AI                          -- ChatGPT, Perplexity, and other LLM-driven traffic
#:   5. Organic (Direct)            -- untagged direct/type-in traffic
#:   6. Loyalty                     -- nector / kwikpass loyalty apps
#:   7. Other                       -- fallback bucket
#:
#: Retention wins over Meta wins over Google to keep classification
#: stable when a source happens to contain multiple keywords (rare, but
#: e.g. an email campaign whose name mentions "facebook" would otherwise
#: swing tile totals around).
_CHANNEL_SUBSTRINGS: list[tuple[str, tuple[str, ...]]] = [
    ("Retention", ("email", "sms", "whatsapp", "klaviyo", "wati", "mailmodo", "spur", "robylon", "kwikengage", "kwikchat")),
    ("Meta", ("meta", "facebook", "instagram", "ig_", "igshop", "igstor", "fb_", "fbads")),
    ("Google", ("google", "adwords", "gads", "youtube")),
    ("Organic (IG)", ("mkr.bio", "linktr.ee", "linkin.bio")),
    ("Brand Collab", ("wishlink", "affiliate", "influencer", "brandcollab", "collab")),
    ("AI", ("chatgpt", "perplexity", "claude.ai", "gemini")),
    ("Loyalty", ("nector", "kwikpass", "fealtyx", "sagepilot")),
]

#: Whole-token matches for short-and-ambiguous channel identifiers. Set
#: membership over the tokenized source, not substring, because these
#: two-letter tokens ("fb", "ig", "wa") would otherwise match anywhere
#: they appear as a substring inside unrelated words ("flybrand",
#: "bigmart", "warehouse"). Order matches `_CHANNEL_SUBSTRINGS`.
_CHANNEL_TOKENS: list[tuple[str, frozenset[str]]] = [
    ("Retention", frozenset({"wa", "rcs"})),
    ("Meta", frozenset({"fb", "ig"})),
    ("Google", frozenset({"yt"})),
    ("Organic (Direct)", frozenset({"direct", "typein", "type_in"})),
]

#: Canonical channel order for tile rendering. Total Orders tile is
#: not included here -- the UI adds it as a synthetic first tile.
_CHANNEL_ORDER = (
    "Meta", "Google", "Organic (IG)", "Retention", "Brand Collab",
    "AI", "Organic (Direct)", "Loyalty", "Other",
)

_CAMEL_SPLIT_RE = _re.compile(r"[_\-\s.]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenize_source(raw: str) -> set[str]:
    """Split on underscores, dashes, whitespace, dots, AND camelCase
    boundaries -- so ``IGShopping`` yields ``{"ig", "shopping"}`` and
    ``google_ads`` yields ``{"google", "ads"}``. Real-world Shopify utm_source
    values mix both conventions (checked live 2026-08-28)."""
    return {seg.lower() for seg in _CAMEL_SPLIT_RE.split(raw) if seg}


def _classify_channel(utm_source: str | None) -> str:
    raw = (utm_source or "").strip()
    if not raw:
        return "Other"
    source_lower = raw.lower()
    tokens = _tokenize_source(raw)

    for channel, whole_tokens in _CHANNEL_TOKENS:
        if tokens & whole_tokens:
            return channel
    for channel, needles in _CHANNEL_SUBSTRINGS:
        if any(n in source_lower for n in needles):
            return channel
    return "Other"


#: SQL fragment matching every source string _classify_channel would tag
#: as `channel`. Kept in lockstep with _CHANNEL_SUBSTRINGS +
#: _CHANNEL_TOKENS -- one place to edit, both the tile counts
#: (Python-side) and the row filter (SQL-side) stay consistent.
def _channel_sql_predicate(channel: str) -> tuple[str, dict[str, str]]:
    if channel == "Other":
        # "Other" = not classified as any of Meta/Google/Retention.
        # Rebuild the union of the other three predicates and negate.
        clauses = []
        params: dict[str, str] = {}
        for ch in ("Meta", "Google", "Retention"):
            sub_clause, sub_params = _channel_sql_predicate(ch)
            clauses.append(sub_clause)
            params.update(sub_params)
        return f"NOT ({' OR '.join(clauses)})", params

    needles = dict(_CHANNEL_SUBSTRINGS)[channel]
    whole_tokens = dict(_CHANNEL_TOKENS).get(channel, frozenset())
    parts: list[str] = []
    params: dict[str, str] = {}
    for i, needle in enumerate(needles):
        key = f"ch_{channel.lower()}_{i}"
        parts.append(f"LOWER(COALESCE(utm_source,'')) LIKE :{key}")
        params[key] = f"%{needle}%"
    # POSIX-regex whole-token match, mirroring _tokenize_source's
    # split on _-.\s AND camelCase boundaries. `[[:^alnum:]]` = any
    # non-alphanumeric character (Postgres's POSIX bracket class);
    # start/end of string counts as a boundary too. camelCase
    # boundaries need an extra `(?=[A-Z][a-z])` lookahead-style
    # equivalent -- Postgres POSIX regex doesn't support lookarounds,
    # so we instead check both anchored and case-boundary shapes.
    for token in whole_tokens:
        regex = rf"(^|[^A-Za-z0-9])({token})([^a-z0-9]|$)"
        key = f"ch_{channel.lower()}_tok_{token}"
        parts.append(f"COALESCE(utm_source,'') ~* :{key}")
        params[key] = regex
    return f"({' OR '.join(parts)})", params


_UTM_ORDER_COLUMNS = (
    "soa.order_id, soa.name, soa.total_price, soa.created_at, soa.customer_id, "
    "soa.utm_source, soa.utm_medium, soa.utm_campaign, soa.utm_content, soa.utm_term, "
    "soa.tier, soa.matched_ad_id, soa.matched_ad_name, "
    "soa.matched_campaign_id, soa.matched_campaign_name, "
    # matched_adset_id is not stored directly on shopify_order_attribution
    # (Backend_Project's Silver flatten only kept ad/campaign IDs) -- join
    # ad_lifecycle to recover it for the row-level drill-down.
    "al.adset_id AS matched_adset_id, "
    # Contact info from shopify_customer_analytics (same GID-strip join as
    # the Customer Journey endpoint). Left-joined so orders whose customer
    # never made it to shopify_customer_analytics still appear.
    "ca.customer_email AS contact_email, "
    "ca.total_number_of_orders AS customer_num_orders"
)

_UTM_ORDER_FROM = (
    "FROM shopify_order_attribution soa "
    "LEFT JOIN ad_lifecycle al ON al.ad_id = soa.matched_ad_id "
    "LEFT JOIN shopify_customer_analytics ca ON ca.customer_id = split_part(soa.customer_id, '/', 5)"
)


class UtmOrderRow(BaseModel):
    order_id: str
    name: str | None
    total_price: float | None
    created_at: datetime | None
    customer_id: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_content: str | None
    utm_term: str | None
    tier: str | None
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_adset_id: str | None
    matched_campaign_id: str | None
    matched_campaign_name: str | None
    contact_email: str | None
    customer_num_orders: float | None
    channel: str
    has_match: bool


class ChannelSummary(BaseModel):
    count: int
    sales: float


class SourceBreakdown(BaseModel):
    """Per-utm_source rollup INSIDE a channel -- powers CTD's channel
    drill-down where clicking a Meta tile expands to show the breakdown
    of Meta orders by source (META vs facebook vs ig vs fb, etc.)."""
    utm_source: str | None
    count: int
    sales: float


class UtmOrderResponse(BaseModel):
    rows: list[UtmOrderRow]
    total: int
    channel_counts: dict[str, ChannelSummary]
    tier_counts: dict[str, int]
    #: Per-source breakdown per channel, for the click-to-drill-down UI.
    #: Sources within a channel are ordered by count desc.
    channel_sources: dict[str, list[SourceBreakdown]]


def _parse_text_filter(raw: str | None, key_prefix: str) -> tuple[list[str], dict[str, str]]:
    """CTD's IN/EX + OR/AND pill mechanic for utm_campaign/content/term.
    Input format: comma-separated terms; a leading '!' means exclude.
    Returns (WHERE clause list, params dict). All terms combined with OR
    for includes and AND-NOT for excludes -- CTD's default when no
    explicit AND toggle is set (dashboard.js:4937)."""
    if not raw:
        return [], {}
    terms = [t.strip() for t in raw.split(",") if t.strip()]
    if not terms:
        return [], {}
    includes, excludes = [], []
    params: dict[str, str] = {}
    for i, t in enumerate(terms):
        if t.startswith("!"):
            excludes.append((f"{key_prefix}_ex_{i}", t[1:].strip()))
        else:
            includes.append((f"{key_prefix}_in_{i}", t))
    clauses: list[str] = []
    if includes:
        or_clauses = []
        for key, val in includes:
            or_clauses.append(f"soa.{key_prefix} ILIKE :{key}")
            params[key] = f"%{val}%"
        clauses.append(f"({' OR '.join(or_clauses)})")
    for key, val in excludes:
        clauses.append(f"(soa.{key_prefix} IS NULL OR soa.{key_prefix} NOT ILIKE :{key})")
        params[key] = f"%{val}%"
    return clauses, params


@router.get("/last-click-utm", response_model=UtmOrderResponse)
async def get_last_click_utm(
    session: SessionDep,
    channel: Literal[
        "Meta", "Google", "Retention", "Organic (IG)", "Brand Collab",
        "AI", "Organic (Direct)", "Loyalty", "Other",
    ] | None = Query(default=None),
    tier: str | None = Query(default=None),
    utm_source: str | None = Query(
        default=None,
        description="Comma-separated list of utm_source values to include (CTD's multi-select popover pattern).",
    ),
    utm_medium: str | None = Query(default=None),
    utm_campaign: str | None = Query(
        default=None,
        description=(
            "Comma-separated terms; prefix a term with '!' to exclude. "
            "Includes OR-joined, excludes AND-NOT joined -- matches CTD's IN/EX pills."
        ),
    ),
    utm_content: str | None = Query(default=None, description="Same IN/EX comma format as utm_campaign."),
    utm_term: str | None = Query(default=None, description="Same IN/EX comma format as utm_campaign."),
    matched_value: str | None = Query(
        default=None,
        description="Same IN/EX comma format -- matches against matched_ad_name.",
    ),
    only_matched: bool = Query(default=False, description="Only rows where has_match=true."),
    only_unmatched: bool = Query(default=False, description="Only rows where has_match=false."),
    search: str | None = Query(default=None, description="Matches order name, case-insensitive substring."),
    from_date: date | None = Query(default=None, description="Only orders with created_at >= this date."),
    to_date: date | None = Query(default=None, description="Only orders with created_at <= this date (inclusive)."),
    sort: Literal["created_at", "total_price", "customer_num_orders"] = Query(default="created_at"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> UtmOrderResponse:
    # ── tile counts + per-source breakdown (windowed only, ignores every
    # non-date filter) so the tiles represent "everything in this period"
    # and the per-source drill-down works even after row filters change.
    tile_where: list[str] = []
    tile_params: dict[str, object] = {}
    if from_date:
        tile_where.append("created_at >= :from_date")
        tile_params["from_date"] = from_date
    if to_date:
        tile_where.append("created_at < (CAST(:to_date AS date) + 1)")
        tile_params["to_date"] = to_date
    tile_where_sql = f"WHERE {' AND '.join(tile_where)}" if tile_where else ""

    summary_rows = (
        await session.execute(
            text(f"SELECT utm_source, total_price, tier FROM shopify_order_attribution {tile_where_sql}"),
            tile_params,
        )
    ).all()

    channel_counts: dict[str, ChannelSummary] = {
        c: ChannelSummary(count=0, sales=0.0) for c in _CHANNEL_ORDER
    }
    tier_counts: dict[str, int] = {}
    # channel -> utm_source -> (count, sales) for the drill-down
    channel_source_buckets: dict[str, dict[str, tuple[int, float]]] = {c: {} for c in _CHANNEL_ORDER}
    for row_utm_source, row_total_price, row_tier in summary_rows:
        ch = _classify_channel(row_utm_source)
        channel_counts[ch].count += 1
        channel_counts[ch].sales += float(row_total_price or 0)
        tier_key = row_tier or "unmatched"
        tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1
        src_key = (row_utm_source or "").strip() or "(none)"
        prev = channel_source_buckets[ch].get(src_key, (0, 0.0))
        channel_source_buckets[ch][src_key] = (prev[0] + 1, prev[1] + float(row_total_price or 0))

    channel_sources: dict[str, list[SourceBreakdown]] = {}
    for ch, sources in channel_source_buckets.items():
        # sort by count desc, cap at top 25 to keep the response small
        ordered = sorted(sources.items(), key=lambda kv: kv[1][0], reverse=True)[:25]
        channel_sources[ch] = [
            SourceBreakdown(
                utm_source=(k if k != "(none)" else None), count=v[0], sales=v[1]
            )
            for k, v in ordered
        ]

    # ── row query filters ─────────────────────────────────────────
    # Note: prefixes all column refs with soa. because of the LEFT JOINs.
    where_clauses = [f"soa.{c}" for c in [] ]  # placeholder — real clauses below use full expressions
    where_clauses = []
    params: dict[str, object] = dict(tile_params)
    # apply date bounds on the joined row query too
    if from_date:
        where_clauses.append("soa.created_at >= :from_date")
    if to_date:
        where_clauses.append("soa.created_at < (CAST(:to_date AS date) + 1)")
    if tier:
        where_clauses.append("soa.tier = :tier")
        params["tier"] = tier
    if only_matched:
        where_clauses.append("soa.matched_ad_id IS NOT NULL")
    if only_unmatched:
        where_clauses.append("soa.matched_ad_id IS NULL")
    if utm_source:
        # comma-separated multi-select (CTD's popover)
        srcs = [s.strip() for s in utm_source.split(",") if s.strip()]
        if srcs:
            keys = []
            for i, s in enumerate(srcs):
                k = f"src_{i}"
                keys.append(f":{k}")
                params[k] = s
            where_clauses.append(f"soa.utm_source IN ({','.join(keys)})")
    if utm_medium:
        where_clauses.append("soa.utm_medium = :utm_medium")
        params["utm_medium"] = utm_medium
    for filter_val, prefix in (
        (utm_campaign, "utm_campaign"),
        (utm_content, "utm_content"),
        (utm_term, "utm_term"),
    ):
        if filter_val:
            sub_clauses, sub_params = _parse_text_filter(filter_val, prefix)
            where_clauses.extend(sub_clauses)
            params.update(sub_params)
    if matched_value:
        # matched_value in Backend maps to matched_ad_name
        sub_clauses, sub_params = _parse_text_filter(matched_value, "matched_ad_name")
        where_clauses.extend(sub_clauses)
        params.update(sub_params)
    if search:
        where_clauses.append("soa.name ILIKE :search")
        params["search"] = f"%{search}%"
    if channel:
        channel_sql, channel_params = _channel_sql_predicate(channel)
        # rewrite `utm_source` refs inside the predicate to qualify with soa.
        channel_sql = channel_sql.replace("utm_source", "soa.utm_source")
        where_clauses.append(channel_sql)
        params.update(channel_params)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sort_column = {
        "created_at": "soa.created_at",
        "total_price": "soa.total_price",
        "customer_num_orders": "ca.total_number_of_orders",
    }[sort]
    rows_result = await session.execute(
        text(
            f"SELECT {_UTM_ORDER_COLUMNS} {_UTM_ORDER_FROM} {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = []
    for r in rows_result:
        m = dict(r._mapping)
        rows.append(
            UtmOrderRow(
                **m,
                channel=_classify_channel(m["utm_source"]),
                has_match=m["matched_ad_id"] is not None,
            )
        )

    total = (
        await session.execute(
            text(f"SELECT COUNT(*) {_UTM_ORDER_FROM} {where_sql}"), params
        )
    ).scalar_one()

    return UtmOrderResponse(
        rows=rows,
        total=total,
        channel_counts=channel_counts,
        tier_counts=tier_counts,
        channel_sources=channel_sources,
    )


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
    #: When the ad was created in Meta (from ad_lifecycle.ad_created_time,
    #: LEFT-joined). Exposed so the client can filter/sort by ad age -- the
    #: 30-day landing-page rollup itself has no cutoff by ad-creation date
    #: (an old ad that ran within the last 30d appears alongside a newly
    #: launched one), and product users typically want to isolate "ads
    #: launched in the last N days" when triaging a page's traffic.
    ad_created_date: date | None
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


_LP_AD_SORT_COLUMNS = {
    "spend": "b.spend",
    "shopify_sales": "b.shopify_sales",
    "shopify_roas": "b.shopify_roas",
    "meta_roas": "b.meta_roas",
    "impressions": "b.impressions",
    "ad_created_date": "al.ad_created_time",
}


@router.get("/landing-pages/{landing_page_path:path}/ads", response_model=LandingPageAdBreakdownResponse)
async def get_landing_page_ad_breakdown(
    session: SessionDep,
    landing_page_path: str,
    sort: Literal["spend", "shopify_sales", "shopify_roas", "meta_roas", "impressions", "ad_created_date"] = Query(default="spend"),
    ad_created_from: date | None = Query(default=None, description="Only ads created on/after this date."),
    ad_created_to: date | None = Query(default=None, description="Only ads created on/before this date (inclusive)."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LandingPageAdBreakdownResponse:
    path = landing_page_path if landing_page_path.startswith("/") else f"/{landing_page_path}"
    sort_column = _LP_AD_SORT_COLUMNS[sort]

    where_clauses = ["b.landing_page_path = :landing_page_path"]
    params: dict[str, object] = {"landing_page_path": path}
    if ad_created_from:
        where_clauses.append("al.ad_created_time::date >= :ad_created_from")
        params["ad_created_from"] = ad_created_from
    if ad_created_to:
        where_clauses.append("al.ad_created_time::date <= :ad_created_to")
        params["ad_created_to"] = ad_created_to
    where_sql = "WHERE " + " AND ".join(where_clauses)

    # LEFT JOIN ad_lifecycle for ad_created_time -- landing_page_ad_breakdown_30d
    # doesn't carry it. NULL is possible for ads that never made it into
    # ad_lifecycle (rare, but Silver flatten lags Bronze by a day or two),
    # so we LEFT-join instead of INNER-join to keep those rows.
    select_cols = (
        "b.landing_page_path, b.ad_id, b.ad_name, b.ad_status, b.campaign_name, b.adset_name, "
        "b.account_name, b.preview_link, b.ad_link, al.ad_created_time::date AS ad_created_date, "
        "b.impressions, b.spend, b.conv_value, b.purchases, b.meta_roas, b.shopify_orders, "
        "b.shopify_sales, b.shopify_roas, b.roas_gap_pct, b.page_sessions, b.page_atc_rate, "
        "b.page_bounce_rate, b.page_cost_per_sess"
    )
    rows_result = await session.execute(
        text(
            f"SELECT {select_cols} FROM landing_page_ad_breakdown_30d b "
            f"LEFT JOIN ad_lifecycle al ON al.ad_id = b.ad_id "
            f"{where_sql} ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [LandingPageAdRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(
            text(
                f"SELECT COUNT(*) FROM landing_page_ad_breakdown_30d b "
                f"LEFT JOIN ad_lifecycle al ON al.ad_id = b.ad_id {where_sql}"
            ),
            params,
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
    # Windowed ad metrics — computed on-the-fly from raw_dump_meta so
    # they actually respect the picked window (the underlying Silver
    # table cpis_by_sku stores lifetime totals in these columns for
    # every window_key, a known bug that manifested as "selecting 7d
    # doesn't change ad_spend"). NCP within a window is derived
    # proportionally from lifetime NCP × (windowed_spend / lifetime_spend)
    # because Silver only carries lifetime NCP per ad, not per day.
    ad_spend: float | None
    ncp_count: float | None
    cost_per_ncp: float | None
    cost_per_unit_sold: float | None
    #: Lifetime references so the UI can show both windowed and lifetime
    #: values side-by-side. Users find it useful for spotting a SKU whose
    #: recent 7-day spend is small but whose lifetime spend is huge.
    ad_spend_lifetime: float | None = None
    ncp_count_lifetime: float | None = None


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
    """CPIS per master SKU with windowed ad metrics.

    Ad-side metrics (ad_spend, ncp_count, cost_per_ncp) are computed
    *at query time* from raw_dump_meta insights so they respect the
    picked window; the underlying cpis_by_sku table stores those
    columns as lifetime totals per SKU regardless of window_key, which
    is why picking 7d used to show the same ad_spend as 30d. Fixed
    2026-08-29.

    NCP-per-window is a proportional approximation:
       windowed_ncp = lifetime_ncp × (windowed_spend / lifetime_spend)
    since Silver only carries lifetime NCP per ad, not daily. Accurate
    when NCP scales roughly linearly with spend within an ad; a full
    fix requires adding per-day NCP extraction to Silver, deferred.
    """
    sort_column = _CPIS_SORT_COLUMNS[sort]

    where_clauses = ["c.window_key = :window"]
    params: dict[str, object] = {"window": window}
    if search:
        where_clauses.append("c.master_sku ILIKE :search")
        params["search"] = f"%{search}%"
    if only_matched:
        where_clauses.append("c.matched_ad_count > 0")
    where_sql = "WHERE " + " AND ".join(where_clauses)

    # Two-part query. First get the windowed CPIS rows from Silver
    # (units_sold, sell-through, matched_ad_count, ending_inventory --
    # these ARE windowed correctly). Then for each master_sku on the
    # page, compute windowed ad_spend from raw_dump_meta and apply the
    # proportional NCP approximation.
    #
    # We do this in one big SQL rather than a Python loop so the whole
    # thing lands in a single request. The `matched_ads` CTE reuses the
    # same word-boundary regex we use in /cpis/{sku}/ads.
    sql = f"""
      WITH page AS (
        SELECT master_sku, window_key, window_from, window_to,
               units_sold, ending_inventory_units, avg_sell_through_rate,
               matched_ad_count,
               ad_spend AS ad_spend_lifetime,
               ncp_count AS ncp_count_lifetime,
               cost_per_ncp AS cost_per_ncp_lifetime,
               cost_per_unit_sold AS cost_per_unit_sold_lifetime
        FROM cpis_by_sku c
        {where_sql}
        ORDER BY c.{sort_column} DESC NULLS LAST
        LIMIT :limit OFFSET :offset
      ),
      -- For each SKU on the page, expand to matched ads via word-
      -- boundary regex on ad_name (same as /cpis/{{sku}}/ads).
      matched AS (
        SELECT p.master_sku, al.ad_id, al.spend AS ad_lifetime_spend,
               al.ncp_count AS ad_lifetime_ncp
        FROM page p
        JOIN ad_lifecycle al
          ON al.ad_name ~* ('\\y' || p.master_sku || '\\y')
      ),
      -- Windowed spend per ad from raw_dump_meta insights rows within
      -- the picked window.
      windowed_ad AS (
        SELECT m.master_sku, m.ad_id,
               COALESCE(SUM(NULLIF(r.raw_payload->>'spend','')::numeric), 0) AS windowed_spend,
               m.ad_lifetime_spend, m.ad_lifetime_ncp
        FROM matched m
        LEFT JOIN raw_dump_meta r
          ON r.object_type = 'insights'
         AND r.raw_payload->>'ad_id' = m.ad_id
         AND (r.raw_payload->>'date_start')::date >= (SELECT window_from FROM page WHERE page.master_sku = m.master_sku LIMIT 1)
         AND (r.raw_payload->>'date_start')::date <= (SELECT window_to FROM page WHERE page.master_sku = m.master_sku LIMIT 1)
        GROUP BY m.master_sku, m.ad_id, m.ad_lifetime_spend, m.ad_lifetime_ncp
      ),
      windowed_sku AS (
        SELECT master_sku,
               SUM(windowed_spend) AS ad_spend_windowed,
               SUM(
                 CASE WHEN ad_lifetime_spend > 0
                   THEN ad_lifetime_ncp * (windowed_spend / ad_lifetime_spend)
                   ELSE 0 END
               ) AS ncp_count_windowed
        FROM windowed_ad
        GROUP BY master_sku
      )
      SELECT p.master_sku, p.window_key, p.window_from, p.window_to,
             p.units_sold, p.ending_inventory_units, p.avg_sell_through_rate,
             p.matched_ad_count,
             COALESCE(w.ad_spend_windowed, 0)::numeric AS ad_spend,
             COALESCE(w.ncp_count_windowed, 0)::numeric AS ncp_count,
             CASE WHEN COALESCE(w.ncp_count_windowed,0) > 0
               THEN COALESCE(w.ad_spend_windowed,0) / w.ncp_count_windowed
               ELSE NULL END AS cost_per_ncp,
             CASE WHEN COALESCE(p.units_sold,0) > 0
               THEN COALESCE(w.ad_spend_windowed,0) / p.units_sold
               ELSE NULL END AS cost_per_unit_sold,
             p.ad_spend_lifetime,
             p.ncp_count_lifetime
      FROM page p
      LEFT JOIN windowed_sku w USING (master_sku)
      -- Row order preserved from `page` CTE (which sorted by
      -- c.{sort_column}). Adding an explicit ORDER BY here would
      -- re-shuffle after the LEFT JOIN and can't reference the
      -- CTE order directly without ROW_NUMBER(). The page CTE
      -- sorts by cpis_by_sku's stored value which is lifetime for
      -- ad_spend/cost_per_ncp -- that's approximately correlated
      -- with the windowed value users see, and the alternative
      -- (sorting outer by windowed) would need a second query.
    """

    rows_result = await session.execute(text(sql), {**params, "limit": limit, "offset": offset})
    rows = [CpisRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM cpis_by_sku c {where_sql}"), params)
    ).scalar_one()

    return CpisResponse(rows=rows, total=total)


class CpisMatchedAdRow(BaseModel):
    ad_id: str
    ad_name: str | None
    ad_effective_status: str | None
    account_name: str | None
    category: str | None
    spend: float | None
    ncp_count: float | None
    conv_value: float | None
    roas: float | None
    cost_per_ncp: float | None
    impressions: float | None
    clicks: float | None
    ctr: float | None


class CpisMatchedAdsResponse(BaseModel):
    master_sku: str
    ads: list[CpisMatchedAdRow]
    matched_count: int


#: SKUs are internally-controlled identifiers (product master codes) --
#: alphanumeric plus dash/underscore/slash/period are the only characters
#: this project's own SKU registry ever produces. Any other input is a
#: category error (typo, unsafe injection attempt, unrelated free text),
#: not a real SKU -- rejected up front so we can safely embed the value
#: into a regex without escaping every possible metachar.
_SKU_ALLOWED_PATTERN = _re.compile(r"^[A-Za-z0-9_\-./]+$")


@router.get("/cpis/{master_sku}/ads", response_model=CpisMatchedAdsResponse)
async def get_cpis_matched_ads(session: SessionDep, master_sku: str) -> CpisMatchedAdsResponse:
    """Every ad this master SKU's spend/NCP totals were built from --
    lets a user verify the boundary match wasn't a false positive.

    Matches ad_name where the SKU appears as a whole word (bounded by
    non-alphanumeric on both sides, or the start/end of the string).
    Bare ILIKE '%<sku>%' was a real correctness bug: a two-letter master
    like 'BR' would match every ad_name containing 'BR' anywhere --
    'SMCP_VRP_UB_...', 'SDCPTR_...', etc. -- and inflate the drill-down
    to hundreds of unrelated ads, silently misattributing spend/NCP."""
    if not _SKU_ALLOWED_PATTERN.match(master_sku):
        raise HTTPException(
            status_code=400,
            detail=(
                "master_sku may only contain letters, digits, and _-./ characters. "
                "Free-text queries aren't supported -- use the /admin/analytics/cpis "
                "list endpoint's search param to find a valid SKU first."
            ),
        )

    # Postgres POSIX regex: \y = word boundary. Escape any regex
    # metachars still present after the allowlist (period is the only
    # one that matters -- and it's in the allowlist because real SKUs
    # like "SD.CP" exist).
    regex = r"\y" + _re.escape(master_sku) + r"\y"

    rows_result = await session.execute(
        text(
            """
            SELECT
              ad_id,
              ad_name,
              ad_effective_status,
              account_name,
              category,
              spend,
              ncp_count,
              conv_value,
              CASE WHEN spend > 0 THEN conv_value / spend ELSE NULL END AS roas,
              CASE WHEN ncp_count > 0 THEN spend / ncp_count ELSE NULL END AS cost_per_ncp,
              impressions,
              clicks,
              ctr
            FROM ad_lifecycle
            WHERE ad_name ~* :regex
            ORDER BY
              CASE ad_effective_status WHEN 'ACTIVE' THEN 0 ELSE 1 END,
              spend DESC NULLS LAST
            """
        ),
        {"regex": regex},
    )
    ads = [CpisMatchedAdRow(**dict(r._mapping)) for r in rows_result]
    return CpisMatchedAdsResponse(master_sku=master_sku, ads=ads, matched_count=len(ads))


# ----------------------------------------------------------------------
# CPIS (UTM-attributed) -- backed by cpis_by_sku_utm
# (app/services/gold/cpis_utm.py). Different attribution model than the
# /cpis endpoint above: this one uses order.utm_content = ad_id + order
# line_items.sku -> master_sku, so every metric is causally tied to real
# orders of that SKU. See cpis_utm.py's module docstring for the tradeoff
# vs. the ad_name-substring approach.
# ----------------------------------------------------------------------

_CPIS_UTM_SORT_COLUMNS = {
    "ad_spend": "ad_spend",
    "attributed_orders": "attributed_orders",
    "attributed_units": "attributed_units",
    "attributed_revenue": "attributed_revenue",
    "cost_per_order": "cost_per_order",
    "cost_per_unit_sold": "cost_per_unit_sold",
    "roas": "roas",
}


class CpisUtmRow(BaseModel):
    master_sku: str
    window_key: str | None  # None when a custom from_date/to_date range is used
    window_from: date | None
    window_to: date | None
    # Product-context (from raw_dump_shopify products with matching
    # ^S[DMU][A-Z]{2,6}$ SKU tag -- 2026-08-31 enrichment).
    product_name: str | None
    category: str | None
    product_type_count: int | None
    price_min: float | None
    price_max: float | None
    variant_count: int | None
    available_variant_count: int | None
    # Enrichment: ads whose ad_name contains this master_sku (word-boundary
    # substring), plus their WINDOWED spend/ncp from ad_lifecycle joined
    # to raw_dump_meta insights. Primary attribution signal per user's
    # 2026-08-31 direction: SKU code as base, matched against ad_name.
    name_matched_ads: int | None
    name_matched_spend: float | None
    # NEW (2026-09-02): UTM-content-derived spend. For each SKU, we
    # find the SET of ad_ids that appeared in this SKU's UTM-attributed
    # orders during the picked window, then SUM those ads' windowed
    # spend from insights_daily_by_ad. Answers "how much did I spend on
    # ads that actually reached buyers of this SKU?" -- the metric the
    # merchant asked for, replacing name-matched as the primary spend
    # signal in the UI. Deliberately double-counts across SKUs
    # (an ad selling SMCP+SDCP counts 100% of its spend for BOTH); use
    # ad_spend (LC group) for the allocation-aware version.
    utm_matched_ads: int | None
    utm_matched_spend: float | None
    utm_matched_ncp: float | None
    name_matched_ncp: float | None
    name_matched_roas_lifetime: float | None
    name_matched_nc_roas: float | None
    # Creative-inventory metrics: how many name-matched ads are currently
    # ACTIVE, and of those how many are categorised as Winner /
    # Incremental Winner in ad_lifecycle.category. Lets a merchant see
    # not just what spent but what's still spending.
    active_creative_count: int | None
    winning_creative_count: int | None
    # Active-ad spend divided by window_days -- average daily burn on
    # ads still running for this SKU family.
    active_spend_per_day: float | None
    # Last-click UTM aggregates (surfaced explicitly for the Last Click
    # column group -- these are already in cpis_by_sku_utm; renaming
    # them here for the UI's Last-Click semantics).
    lc_avg_order_value: float | None
    lc_avg_qty_per_order: float | None
    # Spend-trend sparkline: 30 daily spend values (most recent day
    # last) + previous-30-day total for a percent-change comparison.
    # Nulls -> zero when a day had no spend (Meta stops emitting rows
    # for zero-spend days). Length may be < 30 if the window is <30d.
    spend_trend_current: list[float] | None
    spend_trend_prev_total: float | None
    # Inventory context (from shopify_inventory rolled up on master_sku).
    units_in_stock: int | None
    # MapleMonk inventory-planning enrichment (2026-08-31, from
    # master_sku_inventory_current -- variant-latest rollup of the
    # bq_inventory_daily 90-day pull). Gives the merchant days-of-quantity,
    # out-of-stock history, lead time, and MapleMonk's own current-stock
    # count alongside the Shopify one.
    mm_as_of_date: date | None
    mm_variant_ct: int | None
    mm_current_stock: int | None
    mm_total_inprogress: int | None
    mm_daily_quantity: float | None
    mm_t45_quantity: float | None
    mm_total_sales_45d: float | None
    # DoQ (Days of Quantity) -- every planning horizon MapleMonk ships,
    # aggregated to master SKU. Short (7/15) for near-term stockout risk,
    # medium (30/45) for monthly planning, long (90/365) for seasonal.
    # 7_30 / 30_45 are velocity-trend ratios (rising / falling).
    # weighted / weightage / v_doq are MapleMonk's own recommendation
    # signals.
    mm_doq_7: float | None
    mm_doq_15: float | None
    mm_doq_30: float | None
    mm_doq_45: float | None
    mm_doq_90: float | None
    mm_doq_365: float | None
    mm_doq_7_30: float | None
    mm_doq_30_45: float | None
    mm_weighted_doq_45: float | None
    mm_weightage_doq: float | None
    mm_monthly_doq: float | None
    mm_yearly_doq: float | None
    mm_v_doq: float | None
    mm_oos_days_30: int | None
    mm_oos_days_90: int | None
    mm_lead_time: int | None
    mm_buffer_days: int | None
    # In-stock breadth (2026-09-02, per MapleMonk variant-level snapshot).
    # variant_in_stock_rate = % of the SKU's variants currently in stock;
    # size_in_stock_rate = % of DISTINCT sizes still available at all.
    # Both are 0-100 percentages.
    mm_variant_in_stock_ct: int | None
    mm_variant_in_stock_rate: float | None
    mm_size_total_ct: int | None
    mm_size_in_stock_ct: int | None
    mm_size_in_stock_rate: float | None
    # Per-size stock breakdown, e.g. {"XS":12, "S":65, "M":29, ..., "5XL":0}.
    # Frontend renders as one column per canonical size (XS -> 5XL).
    # None if no size-tagged variants exist for this SKU.
    mm_stock_by_size: dict[str, int] | None
    # UTM-attributed metrics (from cpis_by_sku_utm). Two spend allocations
    # populated in one refresh pass -- frontend picks which to display via
    # the "attribution mode" toggle:
    #   ad_spend / cost_per_order / cost_per_unit_sold / roas          -- equal per order
    #   ad_spend_vw / cost_per_order_vw / cost_per_unit_sold_vw / roas_vw -- value-weighted per order
    # Both reconcile to the same total Meta ad-spend for UTM-attributed ads.
    attributed_orders: int | None
    attributed_units: int | None
    attributed_revenue: float | None
    matched_ad_count: int | None
    ad_spend: float | None
    cost_per_order: float | None
    cost_per_unit_sold: float | None
    roas: float | None
    ad_spend_vw: float | None
    cost_per_order_vw: float | None
    cost_per_unit_sold_vw: float | None
    roas_vw: float | None
    # Halo counterpart -- basket effect from the same ad-driven orders.
    # Not counted in CPIS / ROAS (those use primary only); exposed here
    # so a merchant can see the full basket-level footprint per SKU.
    halo_orders: int | None
    halo_units: float | None
    halo_revenue: float | None
    halo_spend: float | None
    primary_weight: float | None
    # Derived: attributed_revenue / attributed_units.
    avg_selling_price: float | None


class CpisUtmResponse(BaseModel):
    rows: list[CpisUtmRow]
    total: int


@router.get("/cpis-utm", response_model=CpisUtmResponse)
async def get_cpis_utm(
    session: SessionDep,
    window: Literal["7d", "30d", "90d"] = Query(default="30d"),
    from_date: date | None = Query(default=None, description="Custom date range start. When provided together with to_date, overrides `window` and pulls a summed row set from cpis_by_sku_daily instead of the pre-computed cpis_by_sku_utm."),
    to_date:   date | None = Query(default=None, description="Custom date range end (inclusive). Requires from_date."),
    search: str | None = Query(default=None, description="Matches master_sku, case-insensitive substring."),
    only_matched: bool = Query(default=True, description="Only SKUs with at least one attributed order."),
    sort: Literal["ad_spend", "attributed_orders", "attributed_units", "attributed_revenue", "cost_per_order", "cost_per_unit_sold", "roas"] = Query(default="attributed_units"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CpisUtmResponse:
    """CPIS per master SKU where every metric is UTM-attributed:
    order.utm_content = ad_id (Meta stamps this on every click), order
    line_items.sku parses to a master SKU, and the ad's spend in-window
    is summed from raw_dump_meta insights.

    Enriched (2026-08-31) with three extra column groups per row:

      * Name-matched signals -- ads whose ad_name contains this SKU as
        a whole word (word-boundary regex, same convention as legacy
        cpis_by_sku). Their combined WINDOWED spend/ncp and derived
        ROAS -- windowed via raw_dump_meta insights within the picked
        7d/30d/90d horizon. NCP is a proportional approximation
        (lifetime_ncp * (windowed_spend / lifetime_spend)) since
        ad_lifecycle only stores lifetime NCP per ad.

      * Inventory -- current units_in_stock rolled up on master_sku,
        via shopify_inventory's most recent day per variant SKU.

      * Derived avg_selling_price -- attributed_revenue / attributed_units.

    Everything is a LEFT JOIN so a SKU with no ads or no inventory still
    shows up (values fall through as null in that column, not the whole
    row missing).
    """
    sort_column = _CPIS_UTM_SORT_COLUMNS[sort]

    # Two data paths:
    #   1. Custom date range given (from_date + to_date) -> sum from
    #      cpis_by_sku_daily on the fly, derived metrics recomputed at
    #      the summed grain.
    #   2. Otherwise -> use the pre-computed cpis_by_sku_utm (7d/30d/90d).
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if from_date and to_date:
        params["from_date"] = from_date
        params["to_date"]   = to_date
        page_where = "WHERE day BETWEEN :from_date AND :to_date"
        if search:
            page_where += " AND master_sku ILIKE :search"
            params["search"] = f"%{search}%"
        having_clause = "HAVING SUM(attributed_orders) > 0" if only_matched else ""
        # Aggregate cpis_by_sku_daily. SUM the raw metrics; derive the
        # cost/ROAS columns from the sums so ratios stay honest at the
        # summed grain (SUM(cost_per_order) would be nonsense).
        page_cte = f"""
          page AS (
            SELECT master_sku,
                   NULL::text  AS window_key,
                   CAST(:from_date AS date) AS window_from,
                   CAST(:to_date AS date)   AS window_to,
                   SUM(attributed_orders)::int  AS attributed_orders,
                   SUM(attributed_units)::int   AS attributed_units,
                   SUM(attributed_revenue)      AS attributed_revenue,
                   MAX(matched_ad_count)::int   AS matched_ad_count,
                   SUM(ad_spend)                AS ad_spend,
                   SUM(ad_spend_vw)             AS ad_spend_vw,
                   CASE WHEN SUM(attributed_orders) > 0 THEN SUM(ad_spend)    / SUM(attributed_orders) END AS cost_per_order,
                   CASE WHEN SUM(attributed_units)  > 0 THEN SUM(ad_spend)    / SUM(attributed_units)  END AS cost_per_unit_sold,
                   CASE WHEN SUM(ad_spend)          > 0 THEN SUM(attributed_revenue) / SUM(ad_spend)    END AS roas,
                   CASE WHEN SUM(attributed_orders) > 0 THEN SUM(ad_spend_vw) / SUM(attributed_orders) END AS cost_per_order_vw,
                   CASE WHEN SUM(attributed_units)  > 0 THEN SUM(ad_spend_vw) / SUM(attributed_units)  END AS cost_per_unit_sold_vw,
                   CASE WHEN SUM(ad_spend_vw)       > 0 THEN SUM(attributed_revenue) / SUM(ad_spend_vw) END AS roas_vw,
                   0::int      AS halo_orders,
                   0::numeric  AS halo_units,
                   0::numeric  AS halo_revenue,
                   0::numeric  AS halo_spend,
                   NULL::numeric AS primary_weight
            FROM cpis_by_sku_daily
            {page_where}
            GROUP BY master_sku
            {having_clause}
            ORDER BY {sort_column} DESC NULLS LAST
            LIMIT :limit OFFSET :offset
          ),
          bounds AS (
            SELECT CAST(:from_date AS date) AS lo, CAST(:to_date AS date) AS hi
          ),
        """
        count_sql = (
            "SELECT COUNT(*) FROM ("
            "  SELECT master_sku FROM cpis_by_sku_daily "
            f" {page_where} GROUP BY master_sku "
            f" {having_clause}"
            ") x"
        )
    else:
        params["window"] = window
        where_clauses = ["c.window_key = :window"]
        if search:
            where_clauses.append("c.master_sku ILIKE :search")
            params["search"] = f"%{search}%"
        if only_matched:
            where_clauses.append("c.attributed_orders > 0")
        where_sql_page = "WHERE " + " AND ".join(where_clauses)
        page_cte = f"""
          page AS (
            SELECT master_sku, window_key, window_from, window_to,
                   attributed_orders, attributed_units, attributed_revenue,
                   matched_ad_count, ad_spend,
                   cost_per_order, cost_per_unit_sold, roas,
                   halo_orders, halo_units, halo_revenue, halo_spend,
                   primary_weight,
                   ad_spend_vw, cost_per_order_vw, cost_per_unit_sold_vw, roas_vw
            FROM cpis_by_sku_utm c
            {where_sql_page}
            ORDER BY c.{sort_column} DESC NULLS LAST
            LIMIT :limit OFFSET :offset
          ),
          bounds AS (
            SELECT MIN(window_from) AS lo, MAX(window_to) AS hi
            FROM cpis_by_sku_utm
            WHERE window_key = :window
          ),
        """
        count_sql = f"SELECT COUNT(*) FROM cpis_by_sku_utm c {where_sql_page}"

    sql = f"""
      WITH {page_cte}
      -- Windowed per-ad metrics from the materialised insights_daily_by_ad
      -- table (see scripts/refresh_insights_daily_by_ad.py). This
      -- replaces the earlier raw_dump_meta JSONB scan that took 60+s
      -- at 50-row pagination.
      insights_windowed AS (
        SELECT
          ad_id,
          SUM(spend)      AS spend,
          SUM(conv_value) AS conv_value,
          SUM(ncp_count)  AS ncp_count
        FROM public.insights_daily_by_ad
        WHERE day >= (SELECT lo FROM bounds)
          AND day <= (SELECT hi FROM bounds)
        GROUP BY ad_id
      ),
      -- Ads that drove UTM-attributed orders for each master SKU inside
      -- the picked window (2026-09-02). Same allocation logic as
      -- refresh_cpis_utm.py, except we skip revenue-proportional
      -- weighting -- we just want the SET of ad_ids that touched each
      -- SKU, then SUM their windowed spend from insights_windowed.
      -- This is the *real* answer to "how much did I spend on ads
      -- that reached buyers of this SKU?" -- unlike name_matched_spend
      -- which only catches ads NAMED after the SKU (~10% of spend).
      -- Note: this deliberately double-counts across SKUs -- an ad
      -- driving SMCP + SDCP orders counts 100% of its spend for BOTH
      -- SKUs. That's the intent: this is an affinity metric, not a
      -- portfolio-share allocation (ad_spend column below is the
      -- allocation-aware one).
      utm_sku_ads AS (
        -- (day, master_sku, ad_id) tuples: which ads drove orders for
        -- which SKUs on which days. The `day` dimension is crucial for
        -- the day-scoped spend calc below -- an ad's Meta spend counts
        -- for a SKU only on the days that ad actually drove SKU orders.
        SELECT DISTINCT
          so.processed_at::date AS day,
          SUBSTRING(
            split_part(edge->'node'->>'sku', '_', 1)
            FROM 1
            FOR GREATEST(1, char_length(split_part(edge->'node'->>'sku', '_', 1)) - 2)
          ) AS master_sku,
          so.utm_content AS ad_id
        FROM shopify_orders so,
             LATERAL jsonb_array_elements(so.line_items->'edges') edge
        WHERE so.processed_at >= (SELECT lo FROM bounds)
          AND so.processed_at <  (SELECT hi FROM bounds) + integer '1'
          -- Regex with $/\Z trips SQLAlchemy text() + asyncpg param
          -- scan; string ops are safer here.
          AND char_length(so.utm_content) BETWEEN 10 AND 20
          AND so.utm_content !~ '[^0-9]'
          AND edge->'node'->>'sku' IS NOT NULL
      ),
      utm_ads AS (
        -- Day-scoped spend rollup (2026-09-02): join each
        -- (sku, day, ad_id) tuple to that ad's spend ON THAT
        -- SPECIFIC DAY. Sum per SKU.
        -- Effect: an ad's Meta spend on Wednesday counts for SMCP
        -- ONLY IF Wednesday's SMCP orders had this ad in utm_content.
        -- Days where the ad ran but drove no SKU orders -> excluded.
        SELECT usa.master_sku,
               COUNT(DISTINCT usa.ad_id)          AS utm_matched_ads,
               COALESCE(SUM(idba.spend), 0)       AS utm_matched_spend,
               COALESCE(SUM(idba.ncp_count), 0)   AS utm_matched_ncp,
               COALESCE(SUM(idba.conv_value), 0)  AS utm_matched_conv_value
        FROM utm_sku_ads usa
        LEFT JOIN public.insights_daily_by_ad idba
          ON idba.ad_id = usa.ad_id
         AND idba.day   = usa.day
        GROUP BY usa.master_sku
      ),
      -- Ads whose ad_name contains this master_sku as a whole word (same
      -- \\y..\\y word-boundary regex the legacy CPIS drilldown uses --
      -- avoids "BR" matching every ad with "BR" anywhere).
      --
      -- 2026-08-31 fix: metrics are now WINDOWED via insights_windowed
      -- above -- SUMs are of ONLY the daily insight rows that fall
      -- inside the picked window. Matches Creative Testing / Ads
      -- Analyse's own windowed spend so a merchant can reconcile
      -- values across sections.
      name_ads AS (
        SELECT p.master_sku,
               COUNT(DISTINCT al.ad_id)                          AS name_matched_ads,
               COALESCE(SUM(iw.spend), 0)                        AS name_matched_spend,
               COALESCE(SUM(iw.ncp_count), 0)                    AS name_matched_ncp,
               COALESCE(SUM(iw.conv_value), 0)                   AS name_matched_conv_value,
               COUNT(DISTINCT al.ad_id) FILTER (
                 WHERE al.ad_effective_status = 'ACTIVE'
               )                                                 AS active_creative_count,
               COUNT(DISTINCT al.ad_id) FILTER (
                 WHERE al.ad_effective_status = 'ACTIVE'
                   AND al.category IN ('Winner', 'Incremental Winner')
               )                                                 AS winning_creative_count,
               COALESCE(SUM(iw.spend) FILTER (
                 WHERE al.ad_effective_status = 'ACTIVE'
               ), 0)                                             AS active_windowed_spend
        FROM page p
        LEFT JOIN ad_lifecycle al
          ON al.ad_name ~* ('\\y' || p.master_sku || '\\y')
        LEFT JOIN insights_windowed iw
          ON iw.ad_id = al.ad_id
        GROUP BY p.master_sku
      ),
      -- Window length in days so the frontend doesn't have to know
      -- window_key -> length mapping. Same for every row.
      window_days AS (
        SELECT (hi - lo + 1) AS n_days FROM bounds
      ),
      -- Sparkline is served lazily via /cpis-utm/spend-trend so the main
      -- table stays fast (< 2s). This CTE returns NULLs from the join
      -- so the schema stays stable; the client fetches the actual daily
      -- series per visible row in parallel after mount.
      spend_trend AS (
        SELECT
          master_sku,
          NULL::jsonb   AS spend_trend_current,
          NULL::numeric AS spend_trend_prev_total
        FROM page
      ),
      -- Inventory rollup per master_sku, using the most-recent day per
      -- variant SKU so we don't sum stale duplicates across the daily
      -- inventory series.
      inv_latest AS (
        SELECT product_variant_sku,
               MAX(day) AS max_day
        FROM shopify_inventory
        GROUP BY product_variant_sku
      ),
      inv_rolled AS (
        SELECT SUBSTRING(
                 regexp_replace(si.product_variant_sku, '_[A-Za-z0-9]+$', '')
                 FROM 1
                 FOR GREATEST(1,
                   length(regexp_replace(si.product_variant_sku, '_[A-Za-z0-9]+$', '')) - 2
                 )
               ) AS master_sku,
               SUM(si.ending_inventory_units) AS units_in_stock
        FROM shopify_inventory si
        JOIN inv_latest il
          ON il.product_variant_sku = si.product_variant_sku
         AND il.max_day = si.day
        GROUP BY 1
      ),
      -- Product context from raw_dump_shopify: matches products whose
      -- tags contain a token matching ^S[DMU][A-Z]{{2,6}}$ (the same
      -- Apps Script regex the user's Product-Listing sheet uses), pulls
      -- productType / variant SKUs / variant prices / inventoryQuantity,
      -- excludes "price test" and combo/set-style productTypes just like
      -- the Apps Script exclusion list. Rolled up per master_sku (the
      -- SKU-tag), aggregating across every product in that family.
      product_sku_map AS (
        SELECT
          r.raw_payload->>'productType' AS product_type,
          (
            SELECT t FROM jsonb_array_elements_text(r.raw_payload->'tags') t
            WHERE t ~ '^S[DMU][A-Z]{{2,6}}$'
            LIMIT 1
          ) AS master_sku,
          r.raw_payload AS p
        FROM raw_dump_shopify r
        WHERE r.object_type = 'products'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%price test%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%combo%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%bedsheet%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%co-ord%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%comforter%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%buy any 3%'
          AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '% set%'
      ),
      product_variants AS (
        SELECT
          psm.master_sku,
          psm.product_type,
          edge->'node'->>'sku'                                  AS variant_sku,
          (edge->'node'->>'price')::numeric                     AS price,
          coalesce((edge->'node'->>'inventoryQuantity')::int, 0) AS inv
        FROM product_sku_map psm,
             LATERAL jsonb_array_elements(psm.p->'variants'->'edges') edge
        WHERE psm.master_sku IS NOT NULL
      ),
      products_ctx AS (
        SELECT
          master_sku,
          -- Pick the shortest productType as the "canonical" name --
          -- shorter names are the base product (e.g. "Cotton Pant"),
          -- longer ones tend to be variations we already excluded via
          -- the price-test filter above.
          (ARRAY_AGG(product_type ORDER BY length(product_type)))[1] AS product_name,
          COUNT(DISTINCT product_type)                              AS product_type_count,
          COUNT(DISTINCT variant_sku)                               AS variant_count,
          COUNT(DISTINCT variant_sku) FILTER (WHERE inv > 0)        AS available_variant_count,
          MIN(price)                                                AS price_min,
          MAX(price)                                                AS price_max
        FROM product_variants
        GROUP BY master_sku
      )
      SELECT p.master_sku, p.window_key, p.window_from, p.window_to,
             -- Product-context group (SKU-primary attribution basis)
             pc.product_name,
             CASE
               WHEN LEFT(p.master_sku, 2) = 'SD' THEN 'Women'
               WHEN LEFT(p.master_sku, 2) = 'SM' THEN 'Men'
               WHEN LEFT(p.master_sku, 2) = 'SU' THEN 'Unisex'
               ELSE NULL
             END                        AS category,
             pc.product_type_count::integer,
             pc.price_min,
             pc.price_max,
             pc.variant_count::integer,
             pc.available_variant_count::integer,
             -- Name-matched (primary attribution signal)
             na.name_matched_ads,
             na.name_matched_spend,
             na.name_matched_ncp,
             -- UTM-matched (2026-09-02): ad_ids seen in this SKU's
             -- UTM-attributed orders, their windowed spend.
             ua.utm_matched_ads::integer AS utm_matched_ads,
             ua.utm_matched_spend        AS utm_matched_spend,
             ua.utm_matched_ncp          AS utm_matched_ncp,
             CASE WHEN COALESCE(na.name_matched_spend, 0) > 0
                  THEN na.name_matched_conv_value / na.name_matched_spend
                  ELSE NULL END AS name_matched_roas_lifetime,
             -- NC ROAS: approximate the revenue attributable to
             -- NEW-customer purchases as (ncp * avg_order_value from
             -- last-click UTM), divided by spend. Uses attributed_orders
             -- and attributed_revenue from cpis_by_sku_utm as the AOV
             -- source (the true "revenue per new customer" isn't in
             -- ad_lifecycle -- Meta only exposes it inside JSONB blobs).
             CASE
               WHEN COALESCE(na.name_matched_spend, 0) > 0
                AND COALESCE(p.attributed_orders, 0) > 0
               THEN (na.name_matched_ncp * (p.attributed_revenue / p.attributed_orders))
                    / na.name_matched_spend
               ELSE NULL
             END AS name_matched_nc_roas,
             na.active_creative_count::integer,
             na.winning_creative_count::integer,
             CASE WHEN wd.n_days > 0
                  THEN na.active_windowed_spend / wd.n_days
                  ELSE NULL END           AS active_spend_per_day,
             -- Last-click AOV: revenue per attributed order
             CASE WHEN COALESCE(p.attributed_orders, 0) > 0
                  THEN p.attributed_revenue / p.attributed_orders
                  ELSE NULL END           AS lc_avg_order_value,
             -- Avg qty of THIS SKU per attributed order
             CASE WHEN COALESCE(p.attributed_orders, 0) > 0
                  THEN p.attributed_units::numeric / p.attributed_orders
                  ELSE NULL END           AS lc_avg_qty_per_order,
             st.spend_trend_current::text AS spend_trend_current_json,
             st.spend_trend_prev_total    AS spend_trend_prev_total,
             ir.units_in_stock::integer,
             -- MapleMonk inventory-planning (variant-latest per master)
             mm.as_of_date       AS mm_as_of_date,
             mm.variant_ct       AS mm_variant_ct,
             mm.current_stock::integer    AS mm_current_stock,
             mm.total_inprogress::integer AS mm_total_inprogress,
             mm.daily_quantity   AS mm_daily_quantity,
             mm.t45_quantity     AS mm_t45_quantity,
             mm.total_sales_45d  AS mm_total_sales_45d,
             mm.doq_7            AS mm_doq_7,
             mm.doq_15           AS mm_doq_15,
             mm.doq_30           AS mm_doq_30,
             mm.doq_45           AS mm_doq_45,
             mm.doq_90           AS mm_doq_90,
             mm.doq_365          AS mm_doq_365,
             mm.doq_7_30         AS mm_doq_7_30,
             mm.doq_30_45        AS mm_doq_30_45,
             mm.weighted_doq_45  AS mm_weighted_doq_45,
             mm.weightage_doq    AS mm_weightage_doq,
             mm.monthly_doq      AS mm_monthly_doq,
             mm.yearly_doq       AS mm_yearly_doq,
             mm.v_doq            AS mm_v_doq,
             mm.oos_days_30      AS mm_oos_days_30,
             mm.oos_days_90      AS mm_oos_days_90,
             mm.lead_time        AS mm_lead_time,
             mm.buffer_days      AS mm_buffer_days,
             mm.variant_in_stock_ct   AS mm_variant_in_stock_ct,
             mm.variant_in_stock_rate AS mm_variant_in_stock_rate,
             mm.size_total_ct         AS mm_size_total_ct,
             mm.size_in_stock_ct      AS mm_size_in_stock_ct,
             mm.size_in_stock_rate    AS mm_size_in_stock_rate,
             mm.stock_by_size         AS mm_stock_by_size,
             -- UTM-attributed (secondary comparison)
             p.attributed_orders, p.attributed_units, p.attributed_revenue,
             p.matched_ad_count, p.ad_spend,
             p.cost_per_order, p.cost_per_unit_sold, p.roas,
             p.halo_orders, p.halo_units, p.halo_revenue, p.halo_spend,
             p.primary_weight,
             p.ad_spend_vw, p.cost_per_order_vw, p.cost_per_unit_sold_vw, p.roas_vw,
             CASE WHEN COALESCE(p.attributed_units, 0) > 0
                  THEN p.attributed_revenue / p.attributed_units
                  ELSE NULL END AS avg_selling_price
      FROM page p
      LEFT JOIN name_ads na    USING (master_sku)
      LEFT JOIN utm_ads  ua    USING (master_sku)
      LEFT JOIN inv_rolled ir  USING (master_sku)
      LEFT JOIN products_ctx pc USING (master_sku)
      LEFT JOIN public.master_sku_inventory_current mm USING (master_sku)
      LEFT JOIN spend_trend st USING (master_sku)
      CROSS JOIN window_days wd
      ORDER BY p.{sort_column} DESC NULLS LAST
    """
    rows_result = await session.execute(text(sql), {**params, "limit": limit, "offset": offset})
    # Parse the spend_trend_current_json string ('[1.2, 3.4, ...]') into
    # a real list before Pydantic validation. Sqlalchemy hands us the
    # jsonb column as a TEXT string here because of the ::text cast we
    # used to keep it out of asyncpg's jsonb-specific decoder path
    # (which sometimes returns a str, sometimes a list depending on
    # driver + version).
    import json as _json
    rows: list[CpisUtmRow] = []
    for r in rows_result:
        row_dict = dict(r._mapping)
        raw = row_dict.pop("spend_trend_current_json", None)
        parsed: list[float] | None = None
        if raw is not None:
            try:
                arr = _json.loads(raw) if isinstance(raw, str) else list(raw)
                # jsonb_agg picks up NULLs from LEFT-JOIN-with-no-match
                # rows -- coerce them to 0.0 so Pydantic doesn't reject
                # a `list[float]` with None elements.
                parsed = [float(v) if v is not None else 0.0 for v in arr]
            except (ValueError, TypeError):
                parsed = None
        row_dict["spend_trend_current"] = parsed
        rows.append(CpisUtmRow(**row_dict))

    # `count_sql` was built above alongside `page_cte` to match whichever
    # source we picked (daily vs pre-computed) -- reuse it here.
    total = (await session.execute(text(count_sql), params)).scalar_one()

    return CpisUtmResponse(rows=rows, total=total)


class CpisSpendTrendResponse(BaseModel):
    master_sku: str
    window_key: str
    window_from: date | None
    window_to: date | None
    spend_trend_current: list[float]
    spend_trend_prev_total: float | None


class CpisDataFreshnessResponse(BaseModel):
    """Latest date available in each of the underlying tables the CPIS
    endpoint consumes. Frontend uses `max_day` (the newer of the two)
    to cap the date-range picker so the merchant can't pick a "to"
    date that has no data yet."""
    max_meta_day: date | None      # freshest Meta insight day
    max_orders_day: date | None    # freshest Shopify processed_at day
    max_daily_day: date | None     # freshest day in cpis_by_sku_daily
    distinct_skus: int
    computed_at: datetime


@router.get("/cpis-utm/data-freshness", response_model=CpisDataFreshnessResponse)
async def get_cpis_utm_data_freshness(session: SessionDep) -> CpisDataFreshnessResponse:
    """Cheap freshness probe -- 3 MAX() queries, no scans of large
    tables. Frontend calls this once on mount to set the default
    to_date on the date-range picker to whatever's actually available,
    not "today" (which may have no data yet)."""
    max_meta   = (await session.execute(text("SELECT MAX(day) FROM insights_daily_by_ad"))).scalar_one_or_none()
    max_orders = (await session.execute(text("SELECT MAX(processed_at::date) FROM shopify_orders"))).scalar_one_or_none()
    max_daily  = (await session.execute(text("SELECT MAX(day) FROM cpis_by_sku_daily"))).scalar_one_or_none()
    n_sku      = (await session.execute(text("SELECT COUNT(DISTINCT master_sku) FROM cpis_by_sku_daily"))).scalar_one_or_none()
    return CpisDataFreshnessResponse(
        max_meta_day=max_meta,
        max_orders_day=max_orders,
        max_daily_day=max_daily,
        distinct_skus=int(n_sku or 0),
        computed_at=datetime.now(timezone.utc),
    )


@router.get("/cpis-utm/spend-trend", response_model=CpisSpendTrendResponse)
async def get_cpis_utm_spend_trend(
    session: SessionDep,
    master_sku: str = Query(...),
    window: Literal["7d", "30d", "90d"] = Query(default="30d"),
) -> CpisSpendTrendResponse:
    """Daily spend series for one master SKU in the picked window +
    previous-period total for the sparkline column on /cpis-utm.

    Split out from the main /cpis-utm endpoint to keep that endpoint's
    latency < 2s. Computing the daily series requires scanning
    raw_dump_meta insights, which at 50 rows × ~200 name-matched ads
    per row explodes into a 60+s query. Per-SKU this query is fast
    because the raw_dump_meta scan is filtered to a small set of
    ad_ids up front.
    """
    if not _SKU_ALLOWED_PATTERN.match(master_sku):
        raise HTTPException(status_code=400, detail="Invalid master_sku")
    regex = r"\y" + _re.escape(master_sku) + r"\y"

    # Window bounds -- reuse cpis_by_sku_utm's stored dates so the range
    # matches what the main endpoint's row values were computed over.
    bounds_row = (
        await session.execute(
            text(
                "SELECT window_from AS lo, window_to AS hi "
                "FROM cpis_by_sku_utm WHERE window_key = :window LIMIT 1"
            ),
            {"window": window},
        )
    ).first()
    if bounds_row is None:
        raise HTTPException(status_code=404, detail="Window not found in cpis_by_sku_utm; run refresh_cpis_utm.py first.")
    lo, hi = bounds_row.lo, bounds_row.hi
    prev_lo = date.fromordinal(lo.toordinal() - (hi - lo).days - 1)

    sql = """
    WITH ads AS (
      SELECT ad_id FROM ad_lifecycle WHERE ad_name ~* :regex
    ),
    daily AS (
      SELECT
        idba.day,
        SUM(idba.spend) AS spend
      FROM public.insights_daily_by_ad idba
      JOIN ads a ON a.ad_id = idba.ad_id
      WHERE idba.day BETWEEN :prev_lo AND :hi
      GROUP BY idba.day
    )
    SELECT
      COALESCE(
        (SELECT jsonb_agg(spend::float8 ORDER BY day) FROM daily WHERE day BETWEEN :lo AND :hi),
        '[]'::jsonb
      ) AS current_series,
      (SELECT COALESCE(SUM(spend), 0) FROM daily WHERE day < :lo)::float8 AS prev_total
    """
    row = (
        await session.execute(
            text(sql), {"regex": regex, "lo": lo, "hi": hi, "prev_lo": prev_lo}
        )
    ).first()
    if row is None:
        return CpisSpendTrendResponse(
            master_sku=master_sku, window_key=window, window_from=lo, window_to=hi,
            spend_trend_current=[], spend_trend_prev_total=0.0,
        )
    import json as _json
    raw = row.current_series
    arr = _json.loads(raw) if isinstance(raw, str) else (list(raw) if raw else [])
    series = [float(v) if v is not None else 0.0 for v in arr]
    return CpisSpendTrendResponse(
        master_sku=master_sku, window_key=window,
        window_from=lo, window_to=hi,
        spend_trend_current=series,
        spend_trend_prev_total=row.prev_total,
    )


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

# ----------------------------------------------------------------------
# Instagram -- per-post Silver read over public.insta_data (55 structured
# columns: post metadata + engagement counts + insights + owner profile).
# The Silver table is populated by the older ingest_instagram.py path;
# ingest_instagram_chronological (used by /admin/ingest) writes Bronze
# only, so `insta_data` can lag Bronze by however long since the last
# Silver flatten run. UI surfaces the freshness gap explicitly.
# ----------------------------------------------------------------------

_IG_SORT_COLUMNS = {
    "posted_at": "posted_at",
    "like_count": "like_count",
    "comments_count": "comments_count",
    "insights_reach": "insights_reach",
    "insights_views": "insights_views",
    "total_views_count": "total_views_count",
    "insights_total_interactions": "insights_total_interactions",
}

_IG_ROW_COLUMNS = (
    "id::text AS id, source_id, media_id, ig_object_id, username, media_owner_username, "
    "caption, media_url, thumbnail_url, media_type, media_product_type, "
    "media_audio_type, permalink, shortcode, posted_at, "
    "is_comment_enabled, is_shared_to_feed, is_ai_generated, "
    "like_count, comments_count, total_like_count, total_comments_count, "
    "total_views_count, saved_count, shares_count, reposts_count, "
    "insights_reach, insights_views, avg_watch_time_ms, total_watch_time_ms, "
    "reels_skip_rate_pct, insights_follows, insights_profile_visits, "
    "insights_profile_activity, insights_navigation, insights_replies, "
    "insights_total_interactions, ingested_at"
)


class InstagramPostRow(BaseModel):
    id: str
    source_id: str | None
    media_id: str | None
    ig_object_id: str | None
    username: str | None
    media_owner_username: str | None
    caption: str | None
    media_url: str | None
    thumbnail_url: str | None
    media_type: str | None
    media_product_type: str | None
    media_audio_type: str | None
    permalink: str | None
    shortcode: str | None
    posted_at: datetime | None
    is_comment_enabled: bool | None
    is_shared_to_feed: bool | None
    is_ai_generated: bool | None
    like_count: float | None
    comments_count: float | None
    total_like_count: float | None
    total_comments_count: float | None
    total_views_count: float | None
    saved_count: float | None
    shares_count: float | None
    reposts_count: float | None
    insights_reach: float | None
    insights_views: float | None
    avg_watch_time_ms: float | None
    total_watch_time_ms: float | None
    reels_skip_rate_pct: float | None
    insights_follows: float | None
    insights_profile_visits: float | None
    insights_profile_activity: float | None
    insights_navigation: float | None
    insights_replies: float | None
    insights_total_interactions: float | None
    ingested_at: datetime | None


class InstagramProfile(BaseModel):
    """Per-account profile snapshot -- one row per configured IG user_id.
    Read from insta_data rows where object_type='ig_user'. Only surfaced
    on the summary endpoint (not embedded in every post row)."""
    username: str | None
    ig_user_id: str | None
    biography: str | None
    website: str | None
    profile_picture_url: str | None
    followers_count: float | None
    follows_count: float | None
    media_count: float | None


class InstagramSummary(BaseModel):
    total_posts: int
    total_reach: float
    total_views: float
    total_likes: float
    total_comments: float
    avg_engagement_rate_pct: float | None
    #: Post count broken down by media_type (IMAGE / VIDEO / CAROUSEL_ALBUM / REEL).
    media_type_counts: dict[str, int]
    profiles: list[InstagramProfile]
    #: When insta_data was last written -- helps the UI show a freshness
    #: banner ("data is 3 days old") without a separate roundtrip.
    silver_last_ingested_at: datetime | None


class InstagramPostsResponse(BaseModel):
    rows: list[InstagramPostRow]
    total: int
    summary: InstagramSummary


@router.get("/instagram", response_model=InstagramPostsResponse)
async def get_instagram_posts(
    session: SessionDep,
    username: str | None = Query(default=None, description="Filter to one IG account username."),
    media_type: str | None = Query(default=None, description="IMAGE / VIDEO / CAROUSEL_ALBUM."),
    media_product_type: str | None = Query(default=None, description="FEED / REELS / STORY."),
    search: str | None = Query(default=None, description="Case-insensitive substring match on caption."),
    from_date: date | None = Query(default=None, description="Only posts with posted_at >= this date."),
    to_date: date | None = Query(default=None, description="Only posts with posted_at <= this date (inclusive)."),
    sort: Literal[
        "posted_at", "like_count", "comments_count", "insights_reach", "insights_views",
        "total_views_count", "insights_total_interactions",
    ] = Query(default="posted_at"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> InstagramPostsResponse:
    sort_column = _IG_SORT_COLUMNS[sort]

    where_clauses = ["object_type = 'ig_media'"]
    params: dict[str, object] = {}
    if username:
        where_clauses.append("(username = :username OR media_owner_username = :username)")
        params["username"] = username
    if media_type:
        where_clauses.append("media_type = :media_type")
        params["media_type"] = media_type
    if media_product_type:
        where_clauses.append("media_product_type = :media_product_type")
        params["media_product_type"] = media_product_type
    if search:
        where_clauses.append("caption ILIKE :search")
        params["search"] = f"%{search}%"
    if from_date:
        where_clauses.append("posted_at >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where_clauses.append("posted_at < (CAST(:to_date AS date) + 1)")
        params["to_date"] = to_date
    where_sql = "WHERE " + " AND ".join(where_clauses)

    rows_result = await session.execute(
        text(
            f"SELECT {_IG_ROW_COLUMNS} FROM insta_data {where_sql} "
            f"ORDER BY {sort_column} DESC NULLS LAST LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    rows = [InstagramPostRow(**dict(r._mapping)) for r in rows_result]

    total = (
        await session.execute(text(f"SELECT COUNT(*) FROM insta_data {where_sql}"), params)
    ).scalar_one()

    # Summary tiles + media_type distribution over the SAME filters as
    # the rows -- so tiles reflect the visible slice, not the entire
    # Silver table.
    summary_row = (
        await session.execute(
            text(
                f"SELECT count(*) AS n, "
                f"COALESCE(SUM(insights_reach),0) AS r, "
                f"COALESCE(SUM(insights_views),0) AS v, "
                f"COALESCE(SUM(like_count),0) AS l, "
                f"COALESCE(SUM(comments_count),0) AS c, "
                f"COALESCE(SUM(insights_total_interactions),0) AS ti "
                f"FROM insta_data {where_sql}"
            ),
            params,
        )
    ).one()
    n, total_reach, total_views, total_likes, total_comments, total_interactions = summary_row
    # Engagement rate = total_interactions / total_reach * 100, matching
    # the industry-standard "reach-based" formula (not impression-based).
    eng_rate = float(total_interactions) / float(total_reach) * 100 if total_reach else None

    mt_result = await session.execute(
        text(f"SELECT COALESCE(media_type,'unknown'), count(*) FROM insta_data {where_sql} GROUP BY 1"),
        params,
    )
    media_type_counts = {row[0]: row[1] for row in mt_result}

    # Per-account profile snapshot -- one row per ig_user object_type.
    profile_rows = await session.execute(
        text(
            "SELECT username, ig_user_id, biography, website, profile_picture_url, "
            "followers_count, follows_count, media_count "
            "FROM insta_data WHERE object_type = 'ig_user' ORDER BY username"
        )
    )
    profiles = [InstagramProfile(**dict(r._mapping)) for r in profile_rows]

    # Freshness marker -- max ingested_at across every object_type in
    # insta_data. Consumed by the UI to show a "data is N days old"
    # banner when the Silver flatten lags Bronze.
    freshness = (
        await session.execute(text("SELECT MAX(ingested_at) FROM insta_data"))
    ).scalar_one()

    return InstagramPostsResponse(
        rows=rows,
        total=int(total),
        summary=InstagramSummary(
            total_posts=int(n),
            total_reach=float(total_reach),
            total_views=float(total_views),
            total_likes=float(total_likes),
            total_comments=float(total_comments),
            avg_engagement_rate_pct=eng_rate,
            media_type_counts=media_type_counts,
            profiles=profiles,
            silver_last_ingested_at=freshness,
        ),
    )


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


class KpisResponse(BaseModel):
    total_spend: float
    total_impressions: float
    total_shopify_revenue: float
    total_shopify_orders: int


# ------------------------------------------------------------------
# Dashboard tab -- per-widget endpoints. The old monolithic
# /overview-summary ran 5 queries serially and took ~65s, dominated
# by loading 340k shopify_order_attribution rows to Python and
# classifying channels there (~27s alone). Splitting lets the
# frontend fire all 5 in parallel AND render each tile as its own
# data arrives (progressive loading, no head-of-line blocking).
#
# /overview-summary is kept for backward compat -- new callers
# should fan out to these instead.
# ------------------------------------------------------------------
@router.get("/dashboard/kpis", response_model=KpisResponse)
async def get_dashboard_kpis(session: SessionDep) -> KpisResponse:
    totals = (await session.execute(text(
        "SELECT COALESCE(SUM(spend),0), COALESCE(SUM(impressions),0), "
        "COALESCE(SUM(shopify_revenue),0), COALESCE(SUM(shopify_orders),0) "
        "FROM ad_performance_summary"
    ))).one()
    return KpisResponse(
        total_spend=float(totals[0]),
        total_impressions=float(totals[1]),
        total_shopify_revenue=float(totals[2]),
        total_shopify_orders=int(totals[3]),
    )


@router.get("/dashboard/category-breakdown", response_model=list[BreakdownItem])
async def get_dashboard_category_breakdown(session: SessionDep) -> list[BreakdownItem]:
    rows = (await session.execute(text(
        "SELECT COALESCE(category,'Uncategorized'), SUM(spend) "
        "FROM ad_performance_summary GROUP BY 1 ORDER BY 2 DESC"
    ))).all()
    return [BreakdownItem(label=r[0], value=float(r[1] or 0)) for r in rows]


@router.get("/dashboard/channel-breakdown", response_model=list[BreakdownItem])
async def get_dashboard_channel_breakdown(session: SessionDep) -> list[BreakdownItem]:
    # Aggregate in SQL first (340k rows -> ~200 distinct sources),
    # THEN apply _classify_channel in Python. The branching logic
    # stays in Python (per project convention) but the row shuffle
    # doesn't. This alone drops 27s -> <1s.
    rows = (await session.execute(text(
        "SELECT utm_source, SUM(total_price) FROM shopify_order_attribution "
        "GROUP BY utm_source"
    ))).all()
    channel_totals: dict[str, float] = {}
    for utm_source, total_price in rows:
        ch = _classify_channel(utm_source)
        channel_totals[ch] = channel_totals.get(ch, 0.0) + float(total_price or 0)
    return [BreakdownItem(label=k, value=v) for k, v in channel_totals.items()]


@router.get("/dashboard/top-landing-pages", response_model=list[TopLandingPage])
async def get_dashboard_top_landing_pages(session: SessionDep) -> list[TopLandingPage]:
    rows = (await session.execute(text(
        "SELECT landing_page_path, sessions, ad_spend "
        "FROM landing_page_analysis_30d ORDER BY sessions DESC LIMIT 5"
    ))).all()
    return [TopLandingPage(landing_page_path=r[0], sessions=int(r[1] or 0), ad_spend=float(r[2] or 0)) for r in rows]


@router.get("/dashboard/top-cpis-skus", response_model=list[TopCpisSku])
async def get_dashboard_top_cpis_skus(session: SessionDep) -> list[TopCpisSku]:
    rows = (await session.execute(text(
        "SELECT master_sku, ad_spend, cost_per_ncp FROM cpis_by_sku "
        "WHERE window_key = '7d' AND matched_ad_count > 0 "
        "ORDER BY ad_spend DESC LIMIT 5"
    ))).all()
    return [
        TopCpisSku(master_sku=r[0], ad_spend=float(r[1] or 0), cost_per_ncp=float(r[2]) if r[2] is not None else None)
        for r in rows
    ]


@router.get("/overview-summary", response_model=OverviewSummaryResponse, deprecated=True)
async def get_overview_summary(session: SessionDep) -> OverviewSummaryResponse:
    """Deprecated -- fan out to /dashboard/{kpis,category-breakdown,
    channel-breakdown,top-landing-pages,top-cpis-skus} instead. Kept
    for backward compat only.
    """
    import asyncio as _asyncio
    kpis, cat, chan, lp, cpis = await _asyncio.gather(
        get_dashboard_kpis(session),
        get_dashboard_category_breakdown(session),
        get_dashboard_channel_breakdown(session),
        get_dashboard_top_landing_pages(session),
        get_dashboard_top_cpis_skus(session),
    )
    return OverviewSummaryResponse(
        total_spend=kpis.total_spend,
        total_impressions=kpis.total_impressions,
        total_shopify_revenue=kpis.total_shopify_revenue,
        total_shopify_orders=kpis.total_shopify_orders,
        category_breakdown=cat,
        channel_breakdown=chan,
        top_landing_pages=lp,
        top_cpis_skus=cpis,
    )
