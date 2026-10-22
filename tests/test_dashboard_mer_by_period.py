"""A quarter's MER is its revenue over its spend -- never a mean of months.

The tempting shortcut is to roll the monthly results up: average three
monthly MERs into a quarter. That weighs a quiet month as heavily as a
loud one and gives a different, wrong number. Every grain here is
recomputed from the daily rows, and the first test is the one that
catches a regression to the shortcut.
"""

from datetime import date
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics as A


@pytest.fixture(autouse=True)
def reset_cache():
    A.get_dashboard_mer_by_period.analytics_cache.entries.clear()
    yield
    A.get_dashboard_mer_by_period.analytics_cache.entries.clear()


def _session(rows):
    """rows: (day, revenue, meta, google, kwikchat, new_customers)."""
    db = sqlite3.connect(":memory:")
    db.create_function("greatest", -1,
                       lambda *a: max([x for x in a if x is not None], default=None))
    db.create_function("least", -1,
                       lambda *a: min([x for x in a if x is not None], default=None))

    class _BoolOr:
        def __init__(self): self.v = False
        def step(self, value): self.v = self.v or bool(value)
        def finalize(self): return self.v
    db.create_aggregate("bool_or", 1, _BoolOr)

    # Postgres date_trunc(text, date). sqlite has no equivalent, and the
    # grain arrives as a BIND PARAMETER, so the shim has to honour it at
    # run time rather than being rewritten into the SQL.
    def _trunc(grain, day):
        y, m, _ = (int(p) for p in day.split("-"))
        if grain == "year":
            return f"{y:04d}-01-01"
        if grain == "quarter":
            return f"{y:04d}-{3 * ((m - 1) // 3) + 1:02d}-01"
        return f"{y:04d}-{m:02d}-01"
    db.create_function("date_trunc", 2, _trunc)

    db.executescript("""
        CREATE TABLE shopify_sales_daily(day TEXT, total_sales NUMERIC, gross_sales NUMERIC,
            new_customers INTEGER, returning_customers INTEGER,
            total_sales_first_time NUMERIC, total_sales_returning NUMERIC);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC, conv_value NUMERIC);
        CREATE TABLE google_ads_spend_daily(day TEXT, campaign_id TEXT, spend NUMERIC,
            conv_value NUMERIC);
        CREATE TABLE kwikchat_spend_daily(day TEXT, spend NUMERIC, is_estimate INTEGER);
    """)
    for day, rev, meta, goog, kwik, new_c in rows:
        db.execute("INSERT INTO shopify_sales_daily VALUES (?,?,?,?,?,?,?)",
                   (day, rev, rev * 1.21, new_c, 0, rev, 0.0))
        db.execute("INSERT INTO insights_daily_by_ad VALUES ('a',?,?,?)", (day, meta, meta * 3))
        # Google claims 4x its spend, Meta 3x (above). Different
        # multipliers on purpose: a single one would let a Platform MER
        # that silently used only one platform's claim still pass.
        db.execute("INSERT INTO google_ads_spend_daily VALUES (?,'c',?,?)",
                   (day, goog, goog * 4))
        if kwik is not None:
            db.execute("INSERT INTO kwikchat_spend_daily VALUES (?,?,1)", (day, kwik))

    async def execute(query, params=None):
        # sqlite has no `::` cast syntax and reads the colon as the
        # start of a bind parameter. The shim's date_trunc already
        # returns an ISO date string, so dropping the cast is exact.
        sql = str(query).replace("public.", "").replace("::date", "")
        cur = db.execute(sql, params or {})
        cols = [c[0] for c in cur.description]
        out = [dict(zip(cols, r)) for r in cur.fetchall()]
        for d in out:
            if isinstance(d.get("mo"), str):
                d["mo"] = date.fromisoformat(d["mo"])
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: out))

    return SimpleNamespace(execute=AsyncMock(side_effect=execute)), db


#: Jan is small and efficient, Feb and Mar are large and less so. A mean
#: of the three monthly MERs is NOT the quarter's MER, and the gap is
#: wide enough that no rounding could hide a regression.
QUARTER = [
    ("2026-01-15", 1000.0, 100.0, 0.0, None, 10),   # MER 10.0
    ("2026-02-15", 9000.0, 3000.0, 0.0, None, 90),  # MER  3.0
    ("2026-03-15", 9000.0, 3000.0, 0.0, None, 90),  # MER  3.0
]


async def test_a_quarter_is_recomputed_from_days_not_averaged_from_months():
    s, db = _session(QUARTER)
    q = await A.get_dashboard_mer_by_period(s, grain="quarter", periods=4)
    assert len(q) == 1
    assert q[0].month == date(2026, 1, 1)
    # 19,000 revenue over 6,100 spend.
    assert q[0].mer == round(19000 / 6100, 2) == 3.11
    mean_of_months = round((10.0 + 3.0 + 3.0) / 3, 2)
    assert mean_of_months == 5.33
    assert q[0].mer != mean_of_months
    db.close()


async def test_the_same_days_give_three_months_at_month_grain():
    s, db = _session(QUARTER)
    m = await A.get_dashboard_mer_by_period(s, grain="month", periods=12)
    assert [p.month for p in m] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert [p.mer for p in m] == [10.0, 3.0, 3.0]
    db.close()


async def test_year_grain_folds_everything_into_one_row():
    s, db = _session(QUARTER + [("2026-07-15", 2000.0, 400.0, 0.0, None, 20)])
    y = await A.get_dashboard_mer_by_period(s, grain="year", periods=5)
    assert len(y) == 1
    assert y[0].month == date(2026, 1, 1)
    assert y[0].revenue == 21000
    assert y[0].ad_spend == 6500
    db.close()


async def test_blended_cac_is_also_recomputed_per_period():
    s, db = _session(QUARTER)
    q = await A.get_dashboard_mer_by_period(s, grain="quarter", periods=4)
    assert q[0].new_customers == 190
    assert q[0].blended_cac == round(6100 / 190, 2)
    db.close()


async def test_incremental_roas_compares_against_the_prior_PERIOD():
    """At quarter grain the comparison is quarter-on-quarter, not the
    last month of one against the first of the next."""
    s, db = _session(QUARTER + [
        ("2026-04-15", 20000.0, 5000.0, 0.0, None, 100),
        ("2026-05-15", 20000.0, 5000.0, 0.0, None, 100),
    ])
    q = await A.get_dashboard_mer_by_period(s, grain="quarter", periods=4)
    assert [p.month for p in q] == [date(2026, 1, 1), date(2026, 4, 1)]
    assert q[0].incremental_roas is None          # nothing before it
    # Q2: revenue 40,000 vs 19,000; spend 10,000 vs 6,100.
    assert q[1].incremental_roas == round((40000 - 19000) / (10000 - 6100), 2)
    db.close()


async def test_kwikchat_rolls_up_and_keeps_its_estimate_flag():
    s, db = _session([("2026-01-15", 1000.0, 100.0, 0.0, 50.0, 10),
                      ("2026-02-15", 1000.0, 100.0, 0.0, 50.0, 10)])
    q = await A.get_dashboard_mer_by_period(s, grain="quarter", periods=4)
    assert q[0].kwikchat_spend == 100
    assert q[0].kwikchat_estimated is True
    assert q[0].ad_spend == 300
    db.close()


#: One month, both platforms spending, plus Kwikchat. Meta claims 3x its
#: spend and Google 4x, so every figure below is checkable by hand.
BOTH_PLATFORMS = [("2026-01-15", 10_000.0, 1_000.0, 500.0, 250.0, 100)]


async def test_google_claim_is_reported_not_dropped():
    """Google's claimed value was excluded from this block until
    2026-10-21 for diverging from the media plan. It is Google's own
    figure to the rupee, so the block now reports it -- a Platform
    section naming only Meta implied Google claimed nothing."""
    s, db = _session(BOTH_PLATFORMS)
    m = await A.get_dashboard_mer_by_period(s, grain="month", periods=12)
    assert m[0].google_claimed == 2_000.0        # 500 spend x 4
    assert m[0].google_mer == 4.0
    assert m[0].meta_claimed == 3_000.0          # 1,000 spend x 3
    assert m[0].meta_mer == 3.0
    db.close()


async def test_platform_mer_divides_by_only_the_platforms_that_claim():
    """Kwikchat spends but claims nothing, so putting it in the
    denominator would drag Platform MER down for a reason unrelated to
    what the platforms reported. The honest denominator is Meta + Google.
    """
    s, db = _session(BOTH_PLATFORMS)
    m = await A.get_dashboard_mer_by_period(s, grain="month", periods=12)
    row = m[0]
    assert row.platform_claimed == 5_000.0               # 3,000 + 2,000
    assert row.ad_spend == 1_750.0                       # incl. 250 Kwikchat
    assert row.platform_mer == round(5_000 / 1_500, 2)   # excl. Kwikchat
    # The trap: dividing by ad_spend instead.
    assert row.platform_mer != round(5_000 / 1_750, 2)
    db.close()


async def test_platform_mer_and_true_mer_are_different_questions():
    """Platform MER is what the platforms claim; MER is what Shopify
    banked. They disagree in both directions in real data (-8.5% in Oct
    2026, +14.0% in May), so neither may be derived from the other."""
    s, db = _session(BOTH_PLATFORMS)
    m = await A.get_dashboard_mer_by_period(s, grain="month", periods=12)
    row = m[0]
    assert row.mer == round(10_000 / 1_750, 2)        # Shopify / ALL spend
    assert row.platform_mer == round(5_000 / 1_500, 2)
    assert row.mer != row.platform_mer
    db.close()


async def test_a_platform_that_did_not_run_has_no_mer_rather_than_zero():
    """Google spent nothing in QUARTER, and 0/0 is not 0.0 -- a zero
    would render as a real ratio of zero return."""
    s, db = _session(QUARTER)
    m = await A.get_dashboard_mer_by_period(s, grain="month", periods=12)
    assert all(p.google_claimed == 0 for p in m)
    assert all(p.google_mer is None for p in m)
    # Meta still claims, so Platform MER is Meta's alone, not None.
    assert m[0].platform_mer == m[0].meta_mer
    db.close()


@pytest.mark.parametrize("grain,start,today,expected", [
    ("month",   date(2026, 10, 1), date(2026, 10, 19), True),
    ("month",   date(2026, 9, 1),  date(2026, 10, 19), False),
    ("quarter", date(2026, 10, 1), date(2026, 10, 19), True),
    ("quarter", date(2026, 7, 1),  date(2026, 10, 19), False),
    # The quarter containing 19 Oct starts on 1 Oct, so a Q3 start is past.
    ("quarter", date(2026, 7, 1),  date(2026, 9, 30),  True),
    ("year",    date(2026, 1, 1),  date(2026, 10, 19), True),
    ("year",    date(2025, 1, 1),  date(2026, 10, 19), False),
])
def test_partial_follows_the_grain(grain, start, today, expected):
    """September is finished when October starts; Q3 is not finished
    until October; 2026 is not finished until 2027."""
    assert A._period_is_current(start, grain, today) is expected


def test_grain_reaches_the_sql_as_a_bind_parameter():
    """Never interpolated: a grain spliced into the SQL would be an
    injection point, and the Literal that guards the query parameter
    does not guard a string built here."""
    assert "date_trunc(:grain," in A._MER_BY_PERIOD_SQL
    assert not re.search(r"date_trunc\('", A._MER_BY_PERIOD_SQL)
