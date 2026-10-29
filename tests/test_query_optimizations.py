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


class _Result:
    """What SQLAlchemy hands back, to the extent these tests use it.

    A real Result is iterable as well as having .one() and .all(), and
    code that loops over rows directly is perfectly ordinary -- so the
    fake has to be iterable too. It cannot be a SimpleNamespace with an
    __iter__ attribute: Python looks dunder methods up on the type, not
    the instance, so that silently stays non-iterable.
    """

    def __init__(self, rows):
        self._rows = rows

    def one(self):
        return self._rows[0]

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


@pytest.fixture
def session():
    db = sqlite3.connect(":memory:")
    # btrim is Postgres' name for the standard no-argument trim. The
    # Meta source rule the dashboard shares with the session rollup
    # uses it, so the harness has to answer to it.
    db.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
    db.executescript("""
        -- Blended spend sources. Google reports a day behind; the
        -- Kwikchat row is the flat placeholder, and days past its last
        -- one are filled at the same rate by the endpoint.
        CREATE TABLE google_ads_spend_daily(day TEXT, spend NUMERIC);
        INSERT INTO google_ads_spend_daily VALUES
            ('2026-09-02', 10), ('2026-09-03', 20);
        CREATE TABLE kwikchat_spend_daily(day TEXT, spend NUMERIC, is_estimate INT);
        INSERT INTO kwikchat_spend_daily VALUES
            ('2026-09-02', 30000, 1);
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
        -- Acquisition MER's numerator. 'repeat' is inside the window
        -- but is not an acquisition, so the windowed count is 2 while
        -- the lifetime count is 3.
        CREATE TABLE order_customer_type(
            order_id TEXT, is_new_customer INT, order_day TEXT, total_price NUMERIC);
        INSERT INTO order_customer_type VALUES
            ('first', 1, '2026-09-02', 100),
            ('repeat', 0, '2026-09-02', 150),
            ('last',  1, '2026-09-03', 200),
            ('older', 1, '2026-08-20', 400);
    """)

    async def execute(query, params=None):
        await asyncio.sleep(0)  # Exercise overlapping widget requests.
        sql = str(query).replace("public.", "")
        values = {k: str(v) for k, v in (params or {}).items()}
        if "CAST(:df AS date)" in sql:
            sql = sql.replace("CAST(:df AS date)", ":start").replace("(CAST(:dt AS date) + 1)", ":end")
            values.update(start=str(params['df']) + ' 00:00:00',
                          end=str(params['dt'] + timedelta(days=1)) + ' 00:00:00')
        rows = db.execute(sql, values).fetchall()
        if "MIN(day)" in sql:
            rows = [(*rows[0][:2], date.fromisoformat(rows[0][2]))]
        return _Result(rows)

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
    # The Meta slice the session band divides by Meta sessions. 'first'
    # (meta, 100) and 'last' (instagram, 200) qualify; 'middle' carries
    # a null utm_source and so is in the all-traffic total but not this
    # one -- which is the whole point of keeping the two apart.
    assert (kpis.meta_shopify_revenue, kpis.meta_shopify_orders) == (300, 2)
    assert sum(row.value for row in channels) == 300
    assert any(row.label == analytics._classify_channel("instagram", "link_in_bio")
               and row.value == 200 for row in channels)
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    # Three: one ad aggregate (carrying the spend floor), one order
    # aggregate SHARED with the channel widget, and one acquisition
    # count. The third was added for Acquisition MER and is a separate
    # statement on purpose -- it reads order_customer_type, a different
    # table on a different key, and folding it into the shared order
    # scan would make BOTH widgets pay for a join only one of them
    # reads. What this assertion protects is the shared scan: still one
    # pass over shopify_order_attribution for two widgets.
    # Five: the ad aggregate, the shared order scan, the acquisition
    # count, the Meta-source classification, and one statement that
    # reads Google and Kwikchat spend together for the blended figure.
    assert len(statements) == 5
    assert sum("FROM shopify_order_attribution" in q for q in statements) == 1
    assert sum("FROM public.order_customer_type" in q for q in statements) == 1
    assert all("created_at::date" not in q for q in statements)
    # The fourth classifies the handful of utm_source values the shared
    # scan already returned. It reads no table at all -- measured at 0
    # blocks -- which is why it does not weaken the one-scan contract
    # above. Folding it into that scan's GROUP BY instead flipped the
    # plan from an Index Scan to a parallel Gather Merge, 3,884 blocks
    # to 10,058.
    classify = [q for q in statements if "UNION ALL" in q and "AS utm_source" in q]
    assert len(classify) == 1
    assert "FROM shopify_order_attribution" not in classify[0]


async def test_dashboard_cache_keeps_ranges_separate_and_empty_counts_zero(session):
    result = await analytics.get_dashboard_kpis(session, date_from="2026-09-02", date_to="2026-09-02")
    assert result.total_shopify_orders == 2
    assert result.total_shopify_revenue == 100
    # Two acquisitions on 2 Sep ('first' is new, 'repeat' is not) --
    # the figure Acquisition MER divides by spend.
    assert result.new_customers == 1
    repeated = await analytics.get_dashboard_kpis(session, date_from="2026-09-02", date_to="2026-09-02")
    assert repeated == result
    # 5 per windowed call: ad aggregate, order aggregate, acquisition
    # count, the Meta-source classification -- which reads no table,
    # only the handful of utm_source keys the order aggregate already
    # returned -- and the blended spend read. The repeat is served from
    # cache and costs none.
    assert session.execute.await_count == 5
    empty = await analytics.get_dashboard_kpis(session, date_from="2026-10-01", date_to="2026-10-01")
    assert empty.total_shopify_orders == empty.total_shopify_revenue == empty.total_spend == 0
    assert empty.new_customers == 0
    # 9, not 10: an empty window returns no order groups, so there are
    # no utm_source values left to classify and that query is skipped
    # rather than run against an empty list.
    assert session.execute.await_count == 9


async def test_lifetime_keeps_gold_totals_and_spend_floor_stays_visible(session):
    lifetime = await analytics.get_dashboard_kpis(session)
    assert (lifetime.total_shopify_orders, lifetime.total_shopify_revenue) == (20, 2000)
    # Lifetime counts every acquisition ever, including 'older' outside
    # any window the other tests use.
    assert lifetime.new_customers == 3
    # Four: the gold table, the acquisition count, the Meta order
    # slice, and the blended spend. Lifetime takes its headline from
    # ad_performance_summary, which is per-AD and so already Meta's,
    # but the session band's numerator is still read from the orders
    # table under the session rule rather than assumed equal to it.
    assert session.execute.await_count == 4
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
