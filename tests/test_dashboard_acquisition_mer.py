"""Acquisition MER's inputs: what newly acquired customers spent, how
many there were, and the ad spend both are divided by.

The ratio itself (new-customer sales / spend) is computed in the client
and tested in admin/tests/acquisition-mer.test.mjs. What matters here is
that the figures it divides describe the SAME window, and that "new
customer" means acquired-in-the-window rather than active-in-it.
"""

from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics


@pytest.fixture(autouse=True)
def clear_cache():
    analytics.get_dashboard_kpis.analytics_cache.entries.clear()
    yield
    analytics.get_dashboard_kpis.analytics_cache.entries.clear()


@pytest.fixture
def session():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC, impressions NUMERIC);
        INSERT INTO insights_daily_by_ad VALUES
            ('a','2026-10-01',1000,10000), ('a','2026-10-02',1000,10000),
            ('a','2026-10-03',1000,10000);

        -- Four customers. Two acquired inside 1-2 Oct, one acquired on
        -- the 3rd, and one REPEAT order on the 2nd that must not count:
        -- active in the window, but acquired long before it.
        CREATE TABLE order_customer_type(
            order_id TEXT, is_new_customer INT, order_day TEXT, total_price NUMERIC);
        INSERT INTO order_customer_type VALUES
            ('o1', 1, '2026-10-01', 500),
            ('o2', 1, '2026-10-02', 700),
            ('o3', 0, '2026-10-02', 900),
            ('o4', 1, '2026-10-03', 300);

        CREATE TABLE shopify_order_attribution(
            order_id TEXT, created_at TEXT, total_price NUMERIC,
            utm_source TEXT, utm_content TEXT);
    """)

    def _typed(value):
        """sqlite hands back the date columns as text; asyncpg hands back
        `date` objects, and the endpoint compares the spend floor with
        `<`. Converting here keeps the fake honest about the driver
        rather than making the endpoint tolerate a type the real one
        never produces."""
        if isinstance(value, str) and len(value) == 10 and value[4] == value[7] == "-":
            try:
                return date.fromisoformat(value)
            except ValueError:
                return value
        return value

    async def execute(query, params=None):
        sql = str(query).replace("public.", "")
        raw = db.execute(sql, {k: str(v) for k, v in (params or {}).items()}).fetchall()
        rows = [tuple(_typed(v) for v in r) for r in raw]
        return SimpleNamespace(one=lambda: rows[0], all=lambda: rows,
                               __iter__=lambda self=None: iter(rows))

    yield SimpleNamespace(execute=AsyncMock(side_effect=execute))
    db.close()


async def test_new_customers_are_those_acquired_in_the_window(session):
    """o3 is a repeat order inside the window. It is an order the window
    saw; it is not a customer the window acquired, and counting it would
    make every mature account look like it acquires its whole base every
    month."""
    r = await analytics.get_dashboard_kpis(session, "2026-10-01", "2026-10-02")
    assert r.new_customers == 2
    assert r.new_customer_revenue == 1200.0


async def test_the_window_bounds_both_halves_of_the_ratio(session):
    """Spend and new customers must cover the same days. 1-2 Oct is two
    days of spend (2,000) and two acquisitions; adding the 3rd adds one
    of each, so the ratio moves for a real reason rather than because
    the two sides disagree about the period."""
    two = await analytics.get_dashboard_kpis(session, "2026-10-01", "2026-10-02")
    assert (two.new_customers, two.total_spend) == (2, 2000.0)

    three = await analytics.get_dashboard_kpis(session, "2026-10-01", "2026-10-03")
    assert (three.new_customers, three.total_spend) == (3, 3000.0)


async def test_end_day_is_inclusive(session):
    """order_day is a date, so the last day of the range belongs to it.
    A half-open bound here would drop a whole day of acquisitions
    against a whole day of spend."""
    r = await analytics.get_dashboard_kpis(session, "2026-10-03", "2026-10-03")
    assert r.new_customers == 1
    assert r.total_spend == 1000.0


async def test_window_with_no_acquisitions_reports_zero_not_an_error(session):
    r = await analytics.get_dashboard_kpis(session, "2026-10-10", "2026-10-11")
    assert r.new_customers == 0
    assert r.new_customer_revenue == 0.0
    # Spend is zero too, so the client renders an em dash rather than
    # dividing by it -- asserted in the model's defaults, not here.
    assert r.total_spend == 0.0


def test_response_defaults_keep_old_callers_working():
    """Both fields default, so a cached or third-party response without
    them still validates rather than 500ing the whole Dashboard."""
    fields = analytics.KpisResponse.model_fields
    assert fields["new_customers"].default == 0
    assert fields["new_customer_revenue"].default == 0.0
