"""Run the optimized SQL against boundary fixtures; never use the live DB."""

import asyncio
from datetime import date, timedelta
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import asyncpg

from app.api.routers import analytics


@pytest.fixture(autouse=True)
def clear_dashboard_cache():
    functions = (analytics.get_dashboard_kpis, analytics.get_dashboard_channel_breakdown,
                 analytics._get_dashboard_order_groups)
    for fn in functions:
        fn.analytics_cache.entries.clear()
    yield
    for fn in functions:
        fn.analytics_cache.entries.clear()


@pytest.fixture
def session():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE shopify_order_attribution (
            order_id TEXT PRIMARY KEY, created_at TEXT, total_price NUMERIC,
            utm_source TEXT, utm_content TEXT);
        INSERT INTO shopify_order_attribution VALUES
            ('before','2026-09-01 23:59:59',9999,'meta','1'),
            ('first','2026-09-02 00:00:00',100,'meta','1'),
            ('middle','2026-09-02 12:00:00',NULL,NULL,NULL),
            ('last','2026-09-03 23:59:59.999999',200,'instagram','link_in_bio'),
            ('after','2026-09-04 00:00:00',9999,'meta','2');
        CREATE TABLE insights_daily_by_ad(day TEXT, spend NUMERIC, impressions INTEGER);
        INSERT INTO insights_daily_by_ad VALUES
            ('2026-09-01',9999,9999),('2026-09-02',10,100),('2026-09-03',20,200);
        CREATE TABLE ad_performance_summary(
            spend NUMERIC, impressions INTEGER, shopify_revenue NUMERIC, shopify_orders INTEGER);
        INSERT INTO ad_performance_summary VALUES (500,5000,2000,20);
    """)

    async def execute(query, params=None):
        await asyncio.sleep(0)  # Exercise overlapping widget requests.
        sql = str(query)
        values = {k: str(v) for k, v in (params or {}).items()}
        if "CAST(:df AS date)" in sql:
            sql = sql.replace("CAST(:df AS date)", ":start").replace("(CAST(:dt AS date) + 1)", ":end")
            values.update(start=str(params['df']) + ' 00:00:00',
                          end=str(params['dt'] + timedelta(days=1)) + ' 00:00:00')
        rows = db.execute(sql, values).fetchall()
        if "MIN(day)" in sql:
            rows = [(*rows[0][:2], date.fromisoformat(rows[0][2]))]
        return SimpleNamespace(one=lambda: rows[0], all=lambda: rows)

    fake = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    yield fake
    db.close()


async def test_dashboard_widgets_share_one_scan_and_include_end_day(session):
    kpis, channels = await asyncio.gather(
        analytics.get_dashboard_kpis(session, date_from="2026-09-02", date_to="2026-09-03"),
        analytics.get_dashboard_channel_breakdown(session, date_from="2026-09-02", date_to="2026-09-03"),
    )
    assert (kpis.total_spend, kpis.total_impressions) == (30, 300)
    assert (kpis.total_shopify_revenue, kpis.total_shopify_orders) == (300, 3)
    assert sum(row.value for row in channels) == 300
    assert any(row.label == analytics._classify_channel("instagram", "link_in_bio")
               and row.value == 200 for row in channels)
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert len(statements) == 2  # One ad aggregate (including floor), one order aggregate.
    assert sum("FROM shopify_order_attribution" in q for q in statements) == 1
    assert all("created_at::date" not in q for q in statements)


async def test_dashboard_cache_keeps_ranges_separate_and_empty_counts_zero(session):
    result = await analytics.get_dashboard_kpis(session, date_from="2026-09-02", date_to="2026-09-02")
    assert result.total_shopify_orders == 2
    assert result.total_shopify_revenue == 100
    repeated = await analytics.get_dashboard_kpis(session, date_from="2026-09-02", date_to="2026-09-02")
    assert repeated == result
    assert session.execute.await_count == 2
    empty = await analytics.get_dashboard_kpis(session, date_from="2026-10-01", date_to="2026-10-01")
    assert empty.total_shopify_orders == empty.total_shopify_revenue == empty.total_spend == 0
    assert session.execute.await_count == 4


async def test_lifetime_keeps_gold_totals_and_spend_floor_stays_visible(session):
    lifetime = await analytics.get_dashboard_kpis(session)
    assert (lifetime.total_shopify_orders, lifetime.total_shopify_revenue) == (20, 2000)
    session.execute.assert_awaited_once()
    window = await analytics.get_dashboard_kpis(session, date_from="2026-08-01", date_to="2026-09-03")
    assert window.spend_data_from == "2026-09-01"


@pytest.mark.parametrize("level", ["campaign", "adset"])
def test_rolling_revenue_preserves_inclusive_calendar_windows(level):
    db = sqlite3.connect(":memory:")
    db.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
    db.create_function("regexp", 2, lambda pattern, value: bool(re.search(pattern, value or "")))
    try:
        db.executescript("""
            CREATE TABLE shopify_order_attribution(created_at TEXT,total_price NUMERIC,
                matched_campaign_id TEXT,utm_term TEXT,utm_source TEXT);
            CREATE TABLE meta_adsets(adset_id TEXT PRIMARY KEY);
            INSERT INTO meta_adsets VALUES ('set');
        """)
        last = date(2026, 10, 14)
        fixtures = [(last - timedelta(days=n), str(last - timedelta(days=n)) + hour, n + 2)
                    for n in range(-1, max(analytics._ROLLING_PERIODS) + 1)
                    for hour in (' 00:00:00', ' 23:59:59.999999')]
        db.executemany("INSERT INTO shopify_order_attribution VALUES (?,?,'campaign','set','meta')",
                       [(stamp, amount) for day, stamp, amount in fixtures])
        original = analytics._rolling_lc_sql(level)
        parse_sql = pytest.importorskip("pglast").parse_sql
        parse_sql(str(text(original).compile(dialect=asyncpg.dialect())))
        assert "created_at::date" not in original
        sql = re.sub(r"CAST\(:last_date AS date\) - (\d+)",
                     lambda m: "date(:last_date, '-" + m[1] + " days')", original)
        sql = (sql.replace("CAST(:last_date AS date) + 1", "date(:last_date, '+1 day')")
               .replace("public.", "").replace(" ~ ", " REGEXP "))
        row = db.execute(sql, {"last_date": str(last)}).fetchone()
        assert row[1:] == tuple(sum(amount for day, _, amount in fixtures
                                    if last - timedelta(days=p - 1) <= day <= last)
                                for p in analytics._ROLLING_PERIODS)
    finally:
        db.close()


def test_cpis_grouped_orders_preserve_buckets_and_distinct_order_count():
    db = sqlite3.connect(":memory:")
    try:
        db.executescript("""
            CREATE TABLE orders_in_window(order_id TEXT PRIMARY KEY, ad_id TEXT, d TEXT, has_items BOOLEAN);
            INSERT INTO orders_in_window VALUES
                ('1','a','2026-09-01',1),('2','a','2026-09-01',1),('3','a','2026-09-01',0),
                ('4','b','2026-09-01',0),('5','c','2026-09-01',1),('6','c','2026-09-01',1);
            CREATE TABLE ad_lifecycle(ad_id TEXT PRIMARY KEY);
            INSERT INTO ad_lifecycle VALUES ('a'),('b');
            CREATE TABLE spend(ad_id TEXT, d TEXT, spend NUMERIC);
            INSERT INTO spend VALUES ('a','2026-09-01',100),('a','2026-09-02',10),
                ('b','2026-09-01',20),('c','2026-09-01',30),('d','2026-09-01',40),
                ('e','2026-09-01',-5);
        """)
        sql = ('WITH ' + analytics._CPIS_BREAKDOWN_CTES +
               ' SELECT b.*, (SELECT COALESCE(SUM(orders_with_items),0) FROM attributable) FROM breakdown b')
        assert db.execute(sql).fetchone() == (50, 40, 2)
        db.execute('DELETE FROM orders_in_window')
        assert db.execute(sql).fetchone() == (0, 200, 0)
    finally:
        db.close()


def test_creative_order_metrics_do_not_multiply_for_repeated_scope_ids():
    db = sqlite3.connect(":memory:")
    try:
        db.executescript("""
            CREATE TABLE scoped_ads(ad_id TEXT);
            INSERT INTO scoped_ads VALUES ('a'),('a'),('b');
            CREATE TABLE shopify_order_attribution(matched_ad_id TEXT,created_at TEXT,total_price NUMERIC);
            INSERT INTO shopify_order_attribution VALUES
                ('a','2026-09-01 00:00:00',10),('a','2026-09-02 23:59:59',20),
                ('a','2026-09-03 00:00:00',999),('outside','2026-09-01 00:00:00',999);
        """)
        sql = ('WITH scoped_ad_ids AS MATERIALIZED (SELECT DISTINCT ad_id FROM scoped_ads) ' +
               analytics._CT_WINDOW_SHOPIFY.replace('public.', '')
               .replace('CAST(:from_date AS date)', ':start')
               .replace('(CAST(:to_date AS date) + 1)', ':end'))
        assert db.execute(sql, {'start':'2026-09-01 00:00:00','end':'2026-09-03 00:00:00'}).fetchall() == [('a',2,30)]
    finally:
        db.close()
