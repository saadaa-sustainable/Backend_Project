"""The comparative section must compare like days, and only like days.

Three things here are easy to get wrong and expensive to notice:
  * the bases must land on the right calendar days -- a Friday against a
    Friday, the 16th against the 16th;
  * the anchor must clamp to what the source actually holds, because GA4
    runs a day behind Shopify;
  * a conversion rate must not be averaged across rows. A plain mean
    lets a 12-session page weigh the same as a 40,000-session one.
"""

from datetime import date
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics


@pytest.fixture(autouse=True)
def reset_cache():
    analytics.get_dashboard_comparative.analytics_cache.entries.clear()
    yield
    analytics.get_dashboard_comparative.analytics_cache.entries.clear()


#: Postgres date arithmetic, rewritten for sqlite. The production SQL
#: subtracts an INTERVAL so a month lands on the same DATE; sqlite's
#: date(x, '-1 month') clamps the same way, so the rule under test
#: survives the translation.
def _to_sqlite(sql: str) -> str:
    sql = re.sub(r"CAST\(CAST\(:a AS date\) - INTERVAL '([^']+)' AS date\)",
                 r"date(:a, '-\1')", sql)
    return sql.replace("public.", "")


def _make_session(db: sqlite3.Connection):
    async def execute(query, params=None):
        sql = _to_sqlite(str(query))
        bound = {k: (v.isoformat() if isinstance(v, date) else v)
                 for k, v in (params or {}).items()}
        cur = db.execute(sql, bound)
        cols = [c[0] for c in cur.description]
        raw = cur.fetchall()
        dicts = [dict(zip(cols, r)) for r in raw]

        def mappings():
            return SimpleNamespace(all=lambda: dicts,
                                   one=lambda: dicts[0])
        return SimpleNamespace(
            scalar=lambda: (date.fromisoformat(raw[0][0])
                            if raw and raw[0][0] is not None else None),
            mappings=mappings)

    return SimpleNamespace(execute=AsyncMock(side_effect=execute))


@pytest.fixture
def products():
    """16 Oct 2026 is a Friday; 9 Oct is the Friday before it."""
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE cpis_by_sku_daily(
            master_sku TEXT, day TEXT, order_revenue NUMERIC, order_units INTEGER);
        INSERT INTO cpis_by_sku_daily VALUES
            ('SMCP','2026-10-16', 100, 10),
            ('SMCP','2026-10-15', 200, 20),
            ('SMCP','2026-10-09', 400, 40),
            ('SMCP','2026-10-14', 999, 99),   -- Thursday: must NOT be a basis
            ('SMCP','2026-09-16', 800, 80),
            ('SDCP','2026-10-16',  50,  5),
            -- No 15 Oct row for SDCP: the slot must come back 0, not null,
            -- so the row still renders a real "down from" figure.
            ('SDCP','2026-10-09',  10,  1);
    """)
    yield _make_session(db)
    db.close()


@pytest.fixture
def landing_ga4():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE ga4_daily_landing(
            landing_page TEXT, day TEXT, sessions INTEGER,
            add_to_carts INTEGER, purchases INTEGER);
        -- Deliberately lopsided: /big carries the volume at a poor rate,
        -- /small converts beautifully on almost nothing. A plain mean of
        -- the two rates gives 25.5%; weighting by sessions gives 1.1%.
        INSERT INTO ga4_daily_landing VALUES
            ('/big',  '2026-10-15', 10000, 500, 100),
            ('/small','2026-10-15',    10,   8,   5),
            ('/big',  '2026-10-14',  8000, 400,  80),
            ('/small','2026-10-14',    10,   8,   5);
    """)
    yield _make_session(db)
    db.close()


async def test_bases_land_on_the_same_weekday_and_the_same_date(products):
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2026, 10, 16))
    assert r.anchor == date(2026, 10, 16)
    assert r.basis_days == {
        "yesterday": date(2026, 10, 15),
        "last_week": date(2026, 10, 9),
        "last_month": date(2026, 9, 16),
    }
    # Friday meets Friday, not the Thursday sitting next to it.
    assert r.anchor.weekday() == r.basis_days["last_week"].weekday()
    smcp = next(row for row in r.rows if row.key == "SMCP")
    assert (smcp.current.sales, smcp.yesterday.sales) == (100, 200)
    assert (smcp.last_week.sales, smcp.last_month.sales) == (400, 800)
    assert 999 not in (smcp.yesterday.sales, smcp.last_week.sales, smcp.last_month.sales)


async def test_a_day_with_no_row_reads_zero_not_null(products):
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2026, 10, 16))
    sdcp = next(row for row in r.rows if row.key == "SDCP")
    assert sdcp.yesterday.sales == 0
    assert sdcp.yesterday.units == 0


async def test_rows_sort_by_current_volume_and_totals_sum_them(products):
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2026, 10, 16))
    assert [row.key for row in r.rows] == ["SMCP", "SDCP"]
    assert r.totals.current.sales == 150
    assert r.totals.current.units == 15
    assert r.totals.last_week.sales == 410
    assert r.row_count == 2


async def test_anchor_clamps_to_the_newest_day_the_source_holds(products):
    """GA4 runs a day behind Shopify, so asking for a day the source has
    not landed is a normal request, not an error."""
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2027, 1, 1))
    assert r.anchor == date(2026, 10, 16)
    assert r.basis_days["yesterday"] == date(2026, 10, 15)


async def test_no_anchor_given_uses_the_newest_day(products):
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", None)
    assert r.anchor == date(2026, 10, 16)


async def test_partial_flag_is_set_only_for_the_current_date(products, monkeypatch):
    r = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2026, 10, 16))
    # The fixture's newest day is in the past relative to a real clock.
    assert r.anchor_is_partial is (date(2026, 10, 16) >= date.today())

    db = sqlite3.connect(":memory:")
    today = date.today()
    db.executescript(
        "CREATE TABLE cpis_by_sku_daily("
        "  master_sku TEXT, day TEXT, order_revenue NUMERIC, order_units INTEGER);"
        f"INSERT INTO cpis_by_sku_daily VALUES ('X','{today}', 1, 1);")
    live = _make_session(db)
    r2 = await analytics.get_dashboard_comparative(live, "products", "ga4", None)
    assert r2.anchor == today
    assert r2.anchor_is_partial is True
    db.close()


async def test_conversion_rate_totals_are_session_weighted_not_averaged(landing_ga4):
    """The whole point of the totals line: one huge page must not be
    outvoted by a tiny one with a flattering rate."""
    r = await analytics.get_dashboard_comparative(
        landing_ga4, "landing-pages", "ga4", date(2026, 10, 15))
    big = next(row for row in r.rows if row.key == "/big")
    small = next(row for row in r.rows if row.key == "/small")
    assert big.current.conversion_rate == 1.0      # 100 / 10000
    assert small.current.conversion_rate == 50.0   # 5 / 10

    naive_mean = (big.current.conversion_rate + small.current.conversion_rate) / 2
    assert naive_mean == 25.5
    # 105 purchases over 10,010 sessions.
    assert r.totals.current.conversion_rate == 1.05
    assert r.totals.current.conversion_rate != naive_mean
    assert r.totals.current.sessions == 10010
    assert r.totals.current.atc == 508


async def test_products_report_no_source_landing_pages_do(products, landing_ga4):
    prod = await analytics.get_dashboard_comparative(products, "products", "ga4", date(2026, 10, 16))
    assert prod.source is None
    assert prod.dimension == "products"
    lp = await analytics.get_dashboard_comparative(
        landing_ga4, "landing-pages", "ga4", date(2026, 10, 15))
    assert lp.source == "ga4"


async def test_empty_source_returns_an_anchor_rather_than_failing():
    db = sqlite3.connect(":memory:")
    db.executescript(
        "CREATE TABLE cpis_by_sku_daily("
        "  master_sku TEXT, day TEXT, order_revenue NUMERIC, order_units INTEGER);")
    r = await analytics.get_dashboard_comparative(_make_session(db), "products", "ga4", None)
    assert r.rows == []
    assert r.row_count == 0
    assert r.anchor == date.today()
    db.close()


def test_last_month_is_a_calendar_month_not_thirty_days():
    """The month basis exists so the 16th meets the 16th. "30 days" would
    drift the date by one or two every month and land on a different
    weekday as well, which is what `last_week` is already for.

    The month-end clamp is Postgres's and cannot be checked here: this
    suite runs on sqlite, where date('2026-03-31','-1 month') rolls
    FORWARD to 3 March instead of clamping back. Measured on the live
    database 2026-10-16, which is the behaviour the endpoint relies on:

        2026-03-31 - INTERVAL '1 month'  ->  2026-02-28
        2026-05-31 - INTERVAL '1 month'  ->  2026-04-30
        2026-10-16 - INTERVAL '1 month'  ->  2026-09-16

    So this guards the interval unit itself. Swapping it for '30 days',
    or for a timedelta in Python, breaks both properties at once.
    """
    assert analytics._COMPARATIVE_BASES["last_month"] == "1 month"
    assert analytics._COMPARATIVE_BASES["last_week"] == "7 days"
    assert analytics._COMPARATIVE_BASES["yesterday"] == "1 day"
