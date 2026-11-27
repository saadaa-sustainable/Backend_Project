"""First Click sorts and cuts in Python, over one stored aggregate."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.routers import analytics


def _row(source, roas):
    return dict(source=source, label=source, ad_id=None, channel="meta", spend=None,
                first_click_spend=None, last_click_spend=None, lifetime_spend=None,
                lifetime_first_click_roas=None, first_click_revenue=1.0,
                last_click_revenue=1.0, first_click_roas=roas, last_click_roas=None,
                avg_days_to_convert=None, avg_sessions=None)


async def test_nulls_stay_last_and_a_new_sort_reads_nothing(monkeypatch):
    rows = AsyncMock(return_value=[_row("a", 2.0), _row("none", None), _row("b", 5.0)])
    head = AsyncMock(return_value=SimpleNamespace(
        orders_reattributed=0, orders_total=3, orders_unpaired=0, revenue_unpaired=0,
        first_click_revenue_total=3, last_click_revenue_total=3))
    monkeypatch.setattr(analytics, "_first_click_rows", rows)
    monkeypatch.setattr(analytics, "_first_click_head", head)
    analytics.get_first_click.analytics_cache.invalidate()
    window = dict(from_date=date(2026, 11, 1), to_date=date(2026, 11, 16), grain="ad",
                  sort="first_click_roas", basis="order")

    desc = await analytics.get_first_click(session=None, direction="desc", limit=2, **window)
    asc = await analytics.get_first_click(session=None, direction="asc", limit=200, **window)

    assert [r.source for r in desc.rows] == ["b", "a"]
    assert [r.source for r in asc.rows] == ["a", "b", "none"]
    assert desc.matched == 3 and desc.total == 2
    # Both requests asked the helper for the same window: one database read.
    assert rows.await_args_list[0] == rows.await_args_list[1]
