"""Legacy Ads Analyse efficiency ratios against the full lifetime ad population.

Formulas come from CTD's ae_table_view (_consolidate_ae_views.py, commit
0232121). The view's cost_per_1000 is populated from CPR, spend / reach *
1000, so its equivalent here is cpr_1000, not the impressions-based CPM.
Scores remain lifetime scores when delivery-window metrics are displayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics_cache import cached_analytics


_ANCHORS_SQL = """
SELECT NULLIF(SUM(spend), 0) AS g_spend,
       NULLIF(SUM(reach), 0) AS g_reach,
       NULLIF(SUM(ftewv_count), 0) AS g_ftewv,
       NULLIF(SUM(ncp_count), 0) AS g_ncp,
       NULLIF(SUM(conv_value), 0) AS g_conv,
       (percentile_cont(0.5) WITHIN GROUP (ORDER BY ftewv_count))::numeric AS med_ftewv,
       (percentile_cont(0.5) WITHIN GROUP (ORDER BY (conv_value - spend)))::numeric AS med_profit
FROM ad_lifecycle
"""


@dataclass(frozen=True)
class EfficiencyAnchors:
    g_spend: Decimal | None
    g_reach: Decimal | None
    g_ftewv: Decimal | None
    g_ncp: Decimal | None
    g_conv: Decimal | None
    med_ftewv: Decimal | None
    med_profit: Decimal | None


@cached_analytics(ttl=300, max_entries=1)
async def get_efficiency_anchors(session: AsyncSession) -> EfficiencyAnchors:
    """One small aggregate per five minutes, shared across filters and pages.

    Do not apply account, date, category or page filters here: the original
    benchmark is all lifetime ads, including zero-delivery ads in medians.
    """
    result = await session.execute(text(_ANCHORS_SQL))
    return EfficiencyAnchors(**{
        key: None if value is None else Decimal(str(value))
        for key, value in result.mappings().one().items()
    })


def calculate_efficiency_scores(
    row: Mapping[str, float | None], anchors: EfficiencyAnchors,
) -> dict[str, float | None]:
    """Port the view's guards and NULL propagation, rounding only final scores."""
    zero = Decimal(0)

    def value(key: str) -> Decimal | None:
        raw = row.get(key)
        return None if raw is None else Decimal(str(raw))

    def positive(number: Decimal | None) -> bool:
        return number is not None and number > 0

    def has_global(number: Decimal | None) -> bool:
        # Match NULLIF(SUM(...), 0), including for callers supplying zeros.
        return number is not None and number != 0

    def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
        # A NULL operand in SQL arithmetic remains NULL. Global zero sums
        # are already NULLIF'd by the aggregate; also protect direct callers.
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator

    def weighted_sum(*terms: tuple[str, Decimal | None]) -> Decimal | None:
        if any(component is None for _, component in terms):
            return None
        return sum((Decimal(weight) * component for weight, component in terms
                    if component is not None), zero)

    a = anchors
    cpr, reach, ftewv = value("cpr_1000"), value("reach"), value("ftewv_count")
    cpn, cpf, roas = value("cost_per_ncp"), value("cost_per_ftewv"), value("roas")
    spend, conv = value("spend"), value("conv_value")

    cpr_anchor = ratio(a.g_spend, a.g_reach)
    cpr_eff = (
        ratio(None if cpr_anchor is None else cpr_anchor * 1000, cpr)
        if positive(cpr) and has_global(a.g_reach) else zero
    )
    ftv_eff = (
        ratio(ratio(ftewv, reach), ratio(a.g_ftewv, a.g_reach))
        if positive(reach) and has_global(a.g_ftewv) and has_global(a.g_reach) else zero
    )
    volume = ratio(ftewv, a.med_ftewv) if positive(a.med_ftewv) else zero
    ncp_eff = (
        ratio(ratio(a.g_spend, a.g_ncp), cpn)
        if positive(cpn) and has_global(a.g_ncp) else zero
    )
    roas_eff = (
        ratio(roas, ratio(a.g_conv, a.g_spend))
        if positive(roas) and has_global(a.g_spend) else zero
    )
    profit = None if conv is None or spend is None else conv - spend
    profit_eff = (
        ratio(profit, a.med_profit)
        if a.med_profit is not None and a.med_profit != 0 else zero
    )
    cpf_eff = (
        ratio(ratio(a.g_spend, a.g_ftewv), cpf)
        if positive(cpf) and has_global(a.g_ftewv) else zero
    )
    scores = {
        "cpr_eff": cpr_eff,
        "ftv_contrib_eff": ftv_eff,
        "ftev_volume": volume,
        "ncp_cost_eff": ncp_eff,
        "roas_eff": roas_eff,
        "profit_vol_eff": profit_eff,
        "delivery_eff": weighted_sum(("1", cpr_eff), ("1", ftv_eff), ("1", cpf_eff)),
        "sales_spend_eff": weighted_sum(("1", ncp_eff), ("1", roas_eff)),
        "blended_eff": weighted_sum(
            ("0.10", cpr_eff), ("0.25", ftv_eff), ("0.15", volume),
            ("0.20", ncp_eff), ("0.20", roas_eff), ("0.10", profit_eff),
        ),
    }
    return {
        key: None if score is None else float(score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
        for key, score in scores.items()
    }
