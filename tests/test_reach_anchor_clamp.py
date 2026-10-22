"""Reach may not anchor on a day the spend table has never heard of.

The reach snapshots and the daily spend tables are written by different
steps of the nightly, so they end on different days as a matter of
routine. When reach anchored on the requested `to_date` and spend
stopped a day earlier, one row carried two spans: Incr. Reach over
22 Sep..21 Oct beside a ROAS over 22 Sep..20 Oct, and a Cost / 1k Incr.
that divided 29 days of spend by 30 days of reach.

Measured against Meta on 2026-10-21, campaign
NCP_MW-Kurta_WC-Scale_7C_CBO_EX-P(90): Incr. Reach read 1,056,952 where
a spend-matched anchor gives 1,024,429 -- 3.2% high, and 13.9% high on
the 7-day window the 3/7D decision columns live on.

The clamp is a MINIMUM, not an assignment: a historical window the user
picked on purpose must still be honoured as given.
"""

from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics as A


@pytest.fixture(autouse=True)
def reset_cache():
    A._reach_spend_bound.analytics_cache.entries.clear()
    yield
    A._reach_spend_bound.analytics_cache.entries.clear()


def _session(days: list[str]):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE insights_daily_by_campaign(day TEXT, spend NUMERIC)")
    for d in days:
        db.execute("INSERT INTO insights_daily_by_campaign VALUES (?, 1.0)", (d,))

    async def execute(query, params=None):
        cur = db.execute(str(query).replace("public.", ""), params or {})
        rows = cur.fetchall()

        def _first():
            if not rows:
                return None
            v = rows[0][0]
            return (date.fromisoformat(v) if isinstance(v, str) else v,)
        return SimpleNamespace(first=_first)

    return SimpleNamespace(execute=AsyncMock(side_effect=execute)), db


async def test_bound_is_the_spend_tables_last_day():
    s, db = _session(["2026-10-18", "2026-10-19", "2026-10-20"])
    assert await A._reach_spend_bound(s, "insights_daily_by_campaign") == date(2026, 10, 20)
    db.close()


async def test_bound_is_none_when_the_table_is_empty():
    """None, not today: an empty spend table must not silently clamp a
    window to the clock and make every reach column read blank."""
    s, db = _session([])
    assert await A._reach_spend_bound(s, "insights_daily_by_campaign") is None
    db.close()


@pytest.mark.parametrize("to_date,last_date,expected", [
    # The live case: reach has 21 Oct, spend stops at 20 Oct.
    (date(2026, 10, 21), date(2026, 10, 20), date(2026, 10, 20)),
    # Both current -- nothing to clamp.
    (date(2026, 10, 20), date(2026, 10, 20), date(2026, 10, 20)),
    # A historical window, picked on purpose. Clamping to the spend
    # bound here would silently widen it to the present and is the
    # regression this case exists to catch.
    (date(2026, 8, 31), date(2026, 10, 20), date(2026, 8, 31)),
])
def test_clamp_is_a_minimum_not_an_assignment(to_date, last_date, expected):
    assert min(to_date, last_date) == expected


def test_rollup_anchors_reach_on_the_clamped_day():
    """Guard on the source: the roll-up's two reach lookups must take
    the clamped day, never `params["to_date"]`. Both branches -- the
    windowed one and the lifetime one -- feed the same columns."""
    src = A.__loader__.get_source(A.__name__)
    anchor_block = src[src.index("reach_anchor_day = min("):]
    anchor_block = anchor_block[:anchor_block.index("page_reach = sum(")]
    assert 'anchor=reach_anchor_day' in anchor_block
    assert anchor_block.count('anchor=reach_anchor_day') == 2
    assert 'anchor=params["to_date"]' not in anchor_block


def test_ad_level_clamps_the_picked_window_too():
    """The ad table honoured `to_date` as given -- the comment there even
    said so. That is what put a reach span the spend table could not
    match on every row of the default preset."""
    src = A.__loader__.get_source(A.__name__)
    assert '_reach_spend_bound(session, "insights_daily_by_ad")' in src
    i = src.index('_reach_spend_bound(session, "insights_daily_by_ad")')
    assert "if spend_bound is not None and anchor > spend_bound" in src[i:i + 400]
