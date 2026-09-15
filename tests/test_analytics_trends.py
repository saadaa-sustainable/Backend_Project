"""Batch-query contracts for CPIS trends, without application or live DB startup."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.analytics_trends import SpendTrendWindowNotFound, get_cpis_spend_trends


def _result(rows: list[dict[str, object]]) -> Mock:
    result = Mock()
    result.mappings.return_value = Mock(
        first=Mock(return_value=rows[0] if rows else None),
        __iter__=Mock(side_effect=lambda: iter(rows)),
    )
    return result


async def test_preset_batches_deduplicates_and_preserves_response_shape() -> None:
    session = Mock(execute=AsyncMock(side_effect=[
        _result([{"lo": date(2026, 8, 26), "hi": date(2026, 9, 1)}]),
        _result([
            {"master_sku": "SDCP", "current_series": [Decimal("1.25"), 4], "prev_total": 9},
            {"master_sku": "SMCP", "current_series": "[2.5, 0]", "prev_total": Decimal("3.5")},
            {"master_sku": "SUXX", "current_series": [], "prev_total": 0},
        ]),
    ]))

    rows = await get_cpis_spend_trends(session, ["SDCP", "SMCP", "SDCP", "SUXX"], window="7d")

    assert session.execute.await_count == 2
    assert session.execute.call_args_list[0].args[1] == {"window": "7d"}
    params = session.execute.call_args_list[1].args[1]
    assert params == {
        "master_skus": ["SDCP", "SMCP", "SUXX"],
        "patterns": [r"\ySDCP\y", r"\ySMCP\y", r"\ySUXX\y"],
        "lo": date(2026, 8, 26),
        "hi": date(2026, 9, 1),
        "prev_lo": date(2026, 8, 19),
    }
    assert rows == [
        {
            "master_sku": sku, "window_key": "7d",
            "window_from": date(2026, 8, 26), "window_to": date(2026, 9, 1),
            "spend_trend_current": series, "spend_trend_prev_total": previous,
        }
        for sku, series, previous in [("SDCP", [1.25, 4.0], 9.0), ("SMCP", [2.5, 0.0], 3.5),
                                      ("SUXX", [], 0.0)]
    ]


@pytest.mark.parametrize(("lo", "hi", "previous"), [
    (date(2026, 1, 1), date(2026, 1, 1), date(2025, 12, 31)),
    (date(2024, 3, 1), date(2024, 3, 3), date(2024, 2, 27)),
])
async def test_custom_dates_skip_preset_lookup_and_use_inclusive_previous_period(
    lo: date, hi: date, previous: date,
) -> None:
    session = Mock(execute=AsyncMock(return_value=_result([
        {"master_sku": "SD.CP/A-B", "current_series": [], "prev_total": 0},
    ])))

    rows = await get_cpis_spend_trends(
        session, ["SD.CP/A-B"], from_date=lo, to_date=hi,
    )

    session.execute.assert_awaited_once()
    params = session.execute.call_args.args[1]
    assert params["lo"] == lo
    assert params["hi"] == hi
    assert params["prev_lo"] == previous
    assert params["patterns"] == [r"\ySD\.CP/A\-B\y"]
    assert rows[0]["window_from"] == lo
    assert rows[0]["window_to"] == hi


@pytest.mark.parametrize("kwargs", [
    {"master_skus": []},
    {"master_skus": ["SDCP"] * 101},
    {"master_skus": "SDCP"},
    {"master_skus": [""]},
    {"master_skus": ["SDCP\n"]},
    {"master_skus": ["SDCP|SMCP"]},
    {"master_skus": ["SDCP'; DROP TABLE ads; --"]},
    {"master_skus": [None]},
    {"master_skus": ["SDCP"], "window": "14d"},
    {"master_skus": ["SDCP"], "from_date": date(2026, 9, 1)},
    {"master_skus": ["SDCP"], "to_date": date(2026, 9, 1)},
    {"master_skus": ["SDCP"], "from_date": date(2026, 9, 2), "to_date": date(2026, 9, 1)},
    {"master_skus": ["SDCP"], "from_date": date.min, "to_date": date.min},
])
async def test_invalid_requests_do_not_query_database(kwargs: dict[str, object]) -> None:
    session = Mock(execute=AsyncMock())
    with pytest.raises(ValueError):
        await get_cpis_spend_trends(session, **kwargs)
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("bounds", [[], [{"lo": None, "hi": None}]])
async def test_missing_preset_does_not_issue_aggregation(bounds: list[dict[str, object]]) -> None:
    session = Mock(execute=AsyncMock(return_value=_result(bounds)))
    with pytest.raises(SpendTrendWindowNotFound, match="Window not found"):
        await get_cpis_spend_trends(session, ["SDCP"])
    session.execute.assert_awaited_once()


async def test_batch_query_uses_bound_arrays_daily_grain_and_existing_regex_semantics() -> None:
    """Protect the query's grain and batching, not its incidental formatting."""
    skus = [f"SD{i}" for i in range(100)]
    session = Mock(execute=AsyncMock(return_value=_result([])))
    await get_cpis_spend_trends(
        session, skus, from_date=date(2026, 8, 1), to_date=date(2026, 8, 31),
    )
    session.execute.assert_awaited_once()
    query, params = session.execute.call_args.args
    compiled = query.compile(dialect=postgresql.asyncpg.dialect())
    assert set(compiled.params) == {"master_skus", "patterns", "lo", "hi", "prev_lo"}
    sql = " ".join(str(query).split())
    assert "unnest(CAST(:master_skus AS text[]), CAST(:patterns AS text[]))" in sql
    assert "al.ad_name ~* r.pattern" in sql
    assert "FROM public.insights_daily_by_ad d" in sql
    assert "d.day BETWEEN :prev_lo AND :hi" in sql
    assert "GROUP BY m.master_sku, d.day" in sql
    assert "ORDER BY d.day" in sql
    assert "LEFT JOIN daily d" in sql  # Include requested SKUs that had no delivery.
    assert "raw_dump_meta" not in sql
    assert params["master_skus"] == skus


async def test_exact_executed_queries_parse_as_postgresql() -> None:
    """Parse the bound statements themselves without connecting to a database."""
    pglast = pytest.importorskip("pglast")
    session = Mock(execute=AsyncMock(side_effect=[
        _result([{"lo": date(2026, 8, 1), "hi": date(2026, 8, 31)}]),
        _result([]),
    ]))
    await get_cpis_spend_trends(session, ["SDCP", "SMCP"])
    for call in session.execute.call_args_list:
        compiled = call.args[0].compile(dialect=postgresql.asyncpg.dialect())
        statements = pglast.parse_sql(str(compiled))
        assert len(statements) == 1
        assert isinstance(statements[0].stmt, pglast.ast.SelectStmt)
