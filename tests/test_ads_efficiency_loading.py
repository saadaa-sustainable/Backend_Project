"""Ensure efficiency scoring uses cached global lifetime benchmarks."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routers import analytics
from app.services import ad_efficiency


@pytest.fixture(autouse=True)
def clear_caches():
    caches = [fn.analytics_cache for fn in (
        analytics.get_ads_analyse, analytics._daily_mirror_ready,
        ad_efficiency.get_efficiency_anchors,
    )]
    for cache in caches:
        cache.entries.clear()
    yield
    for cache in caches:
        cache.entries.clear()


def _rows_result(*rows):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


def _lifetime_row(ad_id="1"):
    row = dict.fromkeys(analytics.AdsAnalyseRow.model_fields)
    row.update(
        ad_id=ad_id, spend=100, conv_value=300, reach=500, cpr_1000=200,
        impressions=1000, ftewv_count=10, ncp_count=2, cost_per_ncp=50,
        cost_per_ftewv=10, roas=3,
    )
    return SimpleNamespace(_mapping=row)


def _anchor_result():
    result = MagicMock()
    result.mappings.return_value.one.return_value = {
        key: Decimal(value) for key, value in dict(
            g_spend=1000, g_reach=10000, g_ftewv=100, g_ncp=20,
            g_conv=2000, med_ftewv=5, med_profit=100,
        ).items()
    }
    return result


def _response_results():
    count = MagicMock()
    count.scalar_one.return_value = 2
    totals = MagicMock()
    totals.one.return_value = SimpleNamespace(**dict.fromkeys(
        analytics.AdsAnalyseTotals.model_fields, 0,
    ))
    return [count, _rows_result(("Winner", 2)), totals]


EXPECTED = {
    "cpr_eff": 0.5, "ftv_contrib_eff": 2, "ftev_volume": 2,
    "ncp_cost_eff": 1, "roas_eff": 1.5, "profit_vol_eff": 2,
    "delivery_eff": 3.5, "sales_spend_eff": 2.5, "blended_eff": 1.55,
}


async def test_scores_serialize_and_reuse_global_anchors_across_filters_and_pages():
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        _rows_result(_lifetime_row()), _anchor_result(), *_response_results(),
        _rows_result(_lifetime_row()), *_response_results(),
    ]))

    first = await analytics.get_ads_analyse(session, limit=1)
    second = await analytics.get_ads_analyse(
        session, limit=1, offset=1, account_name="Another account", category="Winner",
        from_date=date(2026, 9, 1), to_date=date(2026, 9, 19), date_field="created",
    )

    for response in (first, second):
        payload = response.model_dump(mode="json")["rows"][0]
        assert {key: payload[key] for key in EXPECTED} == EXPECTED
    anchor_calls = [call for call in session.execute.call_args_list
                    if str(call.args[0]) == ad_efficiency._ANCHORS_SQL]
    assert len(anchor_calls) == 1
    assert len(anchor_calls[0].args) == 1  # No row filters or page parameters.
    assert "WHERE" not in ad_efficiency._ANCHORS_SQL
    assert "LIMIT" not in ad_efficiency._ANCHORS_SQL
    assert session.execute.await_count == 9


async def test_delivery_overlay_keeps_original_lifetime_efficiencies():
    exists = MagicMock()
    exists.first.return_value = (1,)
    daily = MagicMock()
    # Distinct window inputs must not silently replace the lifetime scores.
    daily.all.return_value = [("1", 10, 200, 100, 20, 1, 5, 1, 2, None, None)]
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        exists, exists, _rows_result(_lifetime_row()), _anchor_result(), daily,
        *_response_results(),
    ]))

    response = await analytics.get_ads_analyse(
        session, date_field="delivery", from_date=date(2026, 9, 1), to_date=date(2026, 9, 19),
    )

    row = response.rows[0]
    assert row.spend == 10
    assert row.roas == 2
    assert {key: getattr(row, key) for key in EXPECTED} == EXPECTED


async def test_empty_page_does_not_query_efficiency_anchors():
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        _rows_result(), *_response_results(),
    ]))
    response = await analytics.get_ads_analyse(session, search="missing ad")
    assert response.rows == []
    assert session.execute.await_count == 4


def test_anchor_query_is_valid_postgres_and_keeps_zero_ads_in_medians():
    pglast = pytest.importorskip("pglast")
    from pglast.stream import RawStream
    statement = pglast.parse_sql(ad_efficiency._ANCHORS_SQL)[0].stmt
    assert statement.fromClause[0].relname == "ad_lifecycle"
    assert statement.whereClause is None
    # Zeros participate in medians; only global sums have NULLIF guards.
    for target in statement.targetList:
        if target.name.startswith("med_"):
            assert "NULLIF" not in RawStream()(target).upper()
