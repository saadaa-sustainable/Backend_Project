"""Verify source timing, consistent filtering, and lifetime date serialization."""

from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import asyncpg

from app.api.routers import analytics
from app.services.ad_efficiency import EfficiencyAnchors


@pytest.fixture(autouse=True)
def clear_cache():
    analytics.get_ads_analyse.analytics_cache.entries.clear()
    yield
    analytics.get_ads_analyse.analytics_cache.entries.clear()


def _parse(query):
    pglast = pytest.importorskip("pglast")
    return pglast.parse_sql(str(text(query).compile(dialect=asyncpg.dialect())))[0].stmt


def _relations(statement):
    from pglast.visitors import Visitor

    names = set()

    class Relations(Visitor):
        def visit_RangeVar(self, ancestors, node):
            names.add(node.relname)

    Relations()(statement)
    return names


def test_timing_projection_preserves_authoritative_nulls_without_local_day_counts():
    from pglast import ast

    statement = _parse(analytics._ads_analyse_rows_sql("", "aps.spend"))
    fields = {}
    for target in statement.targetList:
        if isinstance(target.val, ast.ColumnRef):
            parts = [field.sval for field in target.val.fields]
            fields[target.name or parts[-1]] = parts
    for field in ("impressions_50k_date", "days_to_50k", "date_of_result", "days_to_result"):
        assert fields[field] == ["ame", field]
    assert fields["category_at_day_14"] == ["ahm", "category_at_day_14"]


def test_first_seen_uses_source_nulls_and_falls_back_only_for_unmirrored_ads():
    from pglast.stream import RawStream
    from pglast.visitors import Visitor

    expressions = []

    class Cases(Visitor):
        def visit_CaseExpr(self, ancestors, node):
            expressions.append(RawStream()(node))

    statement = _parse("SELECT * FROM ad_performance_summary aps" + analytics._ROWS_PICK_FS)
    Cases()(statement)
    assert len(expressions) == 1
    # Execute the exact portable CASE expression from the production SQL.
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript("""
            CREATE TABLE ad_performance_summary (ad_id TEXT);
            CREATE TABLE ad_metrics_external (ad_id TEXT, first_seen_date TEXT);
            CREATE TABLE ad_insights (ad_id TEXT, date_start TEXT);
            INSERT INTO ad_performance_summary VALUES ('known'), ('unknown'), ('local');
            INSERT INTO ad_metrics_external VALUES ('known', '2025-01-09'), ('unknown', NULL);
            INSERT INTO ad_insights VALUES ('known', '2026-01-01'),
                ('unknown', '2026-02-01'), ('local', '2026-03-05'), ('local', '2026-03-01');
        """)
        result = connection.execute(
            f"SELECT aps.ad_id, {expressions[0]} FROM ad_performance_summary aps "
            "LEFT JOIN ad_metrics_external ame ON ame.ad_id = aps.ad_id"
        ).fetchall()
    finally:
        connection.close()
    assert dict(result) == {"known": "2025-01-09", "unknown": None, "local": "2026-03-01"}


@pytest.mark.parametrize("first_seen_filter", [False, True])
def test_first_seen_filter_reaches_page_counts_categories_and_totals(first_seen_filter):
    from pglast.enums import CTEMaterialize

    where = "WHERE fs.first_seen_date BETWEEN :from_date AND :to_date" if first_seen_filter else ""
    rows = _parse(analytics._ads_analyse_rows_sql(where, "aps.spend"))
    picked = rows.withClause.ctes[0]
    assert picked.ctematerialized == CTEMaterialize.CTEMaterializeAlways
    assert picked.ctequery.limitCount is not None
    assert picked.ctequery.limitOffset is not None
    assert ("ad_metrics_external" in _relations(picked.ctequery)) == first_seen_filter
    assert "ad_asset_map" not in _relations(picked.ctequery)
    queries = [
        analytics._ads_analyse_count_sql(where),
        analytics._ads_analyse_category_counts_sql(where),
        analytics._ads_analyse_totals_sql(where, windowed=False),
        analytics._ads_analyse_totals_sql(where, windowed=True),
    ]
    for query in queries:
        parsed = _parse(query)
        assert ("ad_metrics_external" in _relations(parsed)) == first_seen_filter
        assert (analytics._ROWS_PICK_FS in query) == first_seen_filter
        assert (parsed.whereClause is not None) == first_seen_filter


def _rows_result(*rows):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    return result


@pytest.mark.parametrize("date_field", ["created", "delivery"])
async def test_lifetime_timing_serializes_unchanged_when_delivery_metrics_change(
    monkeypatch, date_field,
):
    row = dict.fromkeys(analytics.AdsAnalyseRow.model_fields)
    row.update(
        ad_id="known", ad_created_date=date(2025, 1, 1), first_seen_date=date(2025, 1, 9),
        impressions_50k_date=date(2025, 2, 18), days_to_50k=40,
        date_of_result=date(2025, 2, 18), days_to_result=40, spend=100,
    )
    unknown = dict.fromkeys(analytics.AdsAnalyseRow.model_fields)
    unknown.update(ad_id="unknown", date_of_result=date(2026, 10, 3), spend=0)
    rows = _rows_result(SimpleNamespace(_mapping=row), SimpleNamespace(_mapping=unknown))
    count = MagicMock()
    count.scalar_one.return_value = 2
    totals = MagicMock()
    totals.one.return_value = SimpleNamespace(**dict.fromkeys(analytics.AdsAnalyseTotals.model_fields, 0))
    results = [rows]
    if date_field == "delivery":
        daily = MagicMock()
        daily.all.return_value = [("known", 10, 200, 100, 20, 1, 5, 1, 2, None, None)]
        results.append(daily)
    results.extend([count, _rows_result(("Winner", 2)), totals])
    session = SimpleNamespace(execute=AsyncMock(side_effect=results))
    monkeypatch.setattr(analytics, "_daily_mirror_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(analytics, "get_efficiency_anchors", AsyncMock(return_value=EfficiencyAnchors(
        **dict.fromkeys(EfficiencyAnchors.__dataclass_fields__),
    )))

    response = await analytics.get_ads_analyse(
        session, date_field=date_field, from_date=date(2026, 9, 1), to_date=date(2026, 9, 19),
    )
    known, unknown = response.model_dump(mode="json")["rows"]
    assert known["first_seen_date"] == "2025-01-09"
    assert known["date_of_result"] == known["impressions_50k_date"] == "2025-02-18"
    assert known["days_to_result"] == known["days_to_50k"] == 40
    assert known["spend"] == (10 if date_field == "delivery" else 100)
    assert unknown["date_of_result"] == "2026-10-03"
    assert unknown["first_seen_date"] is None
    assert unknown["impressions_50k_date"] is None
    assert unknown["days_to_50k"] is None
    assert unknown["days_to_result"] is None
