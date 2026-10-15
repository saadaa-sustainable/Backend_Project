"""The optional customer breakdown must not take the whole ad page down."""

from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import sqlite3

import pytest
from sqlalchemy.exc import DBAPIError

from app.api.routers import analytics
from app.services import ad_customer_mix as mix
from app.services.ad_efficiency import EfficiencyAnchors


class DatabaseFailure(Exception):
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate


def session_with_savepoint(*, error=None):
    events = []

    @asynccontextmanager
    async def savepoint():
        events.append("begin")
        try:
            yield
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("release")

    async def execute(query, params):
        if "set_config" in str(query):
            events.append(params["timeout"])
            return None
        events.append("query")
        if error:
            raise error
        return SimpleNamespace(all=lambda: [("a", 2, 1, 100, 75)])

    return SimpleNamespace(
        begin_nested=savepoint,
        scalar=AsyncMock(return_value="2min"),
        execute=AsyncMock(side_effect=execute),
    ), events


async def test_success_restores_statement_timeout_and_preserves_metrics():
    session, events = session_with_savepoint()
    assert await mix.read_ad_customer_mix(session, ["a"], None, None) == {
        "a": (2, 1, 100.0, 75.0),
    }
    assert events == ["begin", f"{mix.CUSTOMER_MIX_TIMEOUT_MS}ms", "query", "2min", "release"]


async def test_timeout_rolls_back_savepoint_without_retrying_or_returning_zero():
    error = DBAPIError("SELECT", {}, DatabaseFailure("57014"), False)
    session, events = session_with_savepoint(error=error)
    assert await mix.read_ad_customer_mix(session, ["a"], None, None) is None
    assert events == ["begin", f"{mix.CUSTOMER_MIX_TIMEOUT_MS}ms", "query", "rollback"]
    assert session.execute.await_count == 2


@pytest.mark.parametrize("sqlstate", ["08006", "42P01"])
async def test_connection_and_schema_errors_are_not_hidden(sqlstate):
    error = DBAPIError("SELECT", {}, DatabaseFailure(sqlstate), False)
    session, events = session_with_savepoint(error=error)
    with pytest.raises(DBAPIError):
        await mix.read_ad_customer_mix(session, ["a"], None, None)
    assert events == ["begin", f"{mix.CUSTOMER_MIX_TIMEOUT_MS}ms", "query", "rollback"]


async def test_empty_page_does_not_open_a_transaction():
    assert await mix.read_ad_customer_mix(object(), [], None, None) == {}


@pytest.mark.parametrize("dated", [False, True])
async def test_scoped_query_keeps_lifetime_classification_and_distinct_people(dated):
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript("""
            CREATE TABLE shopify_order_attribution (order_id TEXT, matched_ad_id TEXT);
            CREATE TABLE order_customer_type (
                order_id TEXT PRIMARY KEY, customer_id TEXT, is_new_customer BOOLEAN,
                total_price NUMERIC, order_day TEXT
            );
            INSERT INTO shopify_order_attribution VALUES
                ('1','a'), ('2','a'), ('3','a'), ('4','b'), ('5','a'), ('6','outside');
            INSERT INTO order_customer_type VALUES
                ('1','person1',1,100,'2026-09-01'),
                ('2','person1',0,200,'2026-09-01'),
                ('3','person1',0,50,'2026-09-02'),
                ('4','person1',0,90,'2026-09-02'),
                ('5','person2',1,300,'2026-08-31'),
                ('6','person3',1,5000,'2026-09-01');
        """)

        async def execute(query, params):
            from sqlalchemy.dialects.postgresql import asyncpg
            import pglast
            pglast.parse_sql(str(query.compile(dialect=asyncpg.dialect())))
            # SQLite executes the production aggregation against fixture orders;
            # only PostgreSQL's schema, array binding and date casts are adapted.
            sql = str(query).replace("public.", "").replace(
                "= ANY(:ad_ids)", "IN (:first_ad, :second_ad)",
            ).replace("CAST(:from_str AS date)", ":from_str").replace(
                "CAST(:to_str AS date)", ":to_str",
            )
            values = {k: str(v) for k, v in params.items() if k != "ad_ids"}
            values.update(first_ad=params["ad_ids"][0], second_ad=params["ad_ids"][1])
            result = connection.execute(sql, values).fetchall()
            return SimpleNamespace(all=lambda: result)

        result = await mix.query_ad_customer_mix(
            SimpleNamespace(execute=execute), ["a", "b"],
            date(2026, 9, 1) if dated else None,
            date(2026, 9, 2) if dated else None,
        )
        assert result == {
            "a": (1, 1, 100.0, 250.0) if dated else (2, 1, 400.0, 250.0),
            "b": (0, 1, 0.0, 90.0),
        }
    finally:
        connection.close()


@pytest.mark.parametrize("customer_mix", [None, {}, {"a": (2, 1, 100.0, 75.0)}])
async def test_ad_response_keeps_main_metrics_when_customer_mix_is_unavailable(monkeypatch, customer_mix):
    analytics.get_ads_analyse.analytics_cache.entries.clear()
    monkeypatch.setattr(analytics, "read_ad_customer_mix", AsyncMock(return_value=customer_mix))
    monkeypatch.setattr(analytics, "get_efficiency_anchors", AsyncMock(return_value=EfficiencyAnchors(
        **dict.fromkeys(EfficiencyAnchors.__dataclass_fields__),
    )))
    monkeypatch.setattr(analytics, "_reach_snapshots_ready", AsyncMock(return_value=False))
    totals = {**dict.fromkeys(analytics.AdsAnalyseTotals.model_fields, 0), "ad_count": 1, "spend": 100}
    monkeypatch.setattr(analytics, "_get_ads_analyse_summary", AsyncMock(return_value={
        "totals": totals, "category_counts": {"Winner": 1},
    }))
    row = dict.fromkeys(analytics.AdsAnalyseRow.model_fields)
    row.update(ad_id="a", category="Winner", spend=100, roas=3, conv_value=300,
               impressions=1000, shopify_orders=3, shopify_revenue=175)
    result = MagicMock()
    result.__iter__.return_value = iter([SimpleNamespace(_mapping=row)])
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    try:
        response = await analytics.get_ads_analyse(session)
        assert response.total == 1
        assert response.rows[0].spend == 100
        assert response.rows[0].roas == 3
        assert response.rows[0].shopify_revenue == 175
        assert response.customer_mix_unavailable is (customer_mix is None)
        expected = None if customer_mix is None else (2 if customer_mix else 0)
        assert response.rows[0].new_customers == expected
        if customer_mix is None:
            assert all(getattr(response.rows[0], key) is None for key in (
                "new_customers", "repeat_customers", "new_customer_sales", "repeat_customer_sales",
            ))
        analytics._get_ads_analyse_summary.assert_awaited_once()
    finally:
        analytics.get_ads_analyse.analytics_cache.entries.clear()


def test_budget_clears_the_measured_cold_read():
    """The four Customers columns blank whenever this budget is missed,
    and a cold read of the top 100 ads over 30 days measured 3,097ms on
    2026-10-15 against a 3,000ms budget -- so they blanked on the first
    load after any cache eviction and filled on every load after it.

    Pinned at a multiple of that cold read rather than at the exact
    figure: the point is headroom, and a budget that merely scrapes
    past today's measurement is the same bug waiting for a busier day.
    """
    measured_cold_ms = 3097
    assert mix.CUSTOMER_MIX_TIMEOUT_MS >= measured_cold_ms * 3, (
        "budget must leave room above the measured cold read, or the "
        "columns silently go missing again"
    )
    # ...and still well inside the database's own 120s statement_timeout,
    # so a pathological query is cancelled rather than holding the page.
    assert mix.CUSTOMER_MIX_TIMEOUT_MS < 120_000
