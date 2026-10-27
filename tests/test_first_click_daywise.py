"""The day-wise view, and the one thing it has to get right.

A window-level view never has to say which DAY an order belongs to. A
daily series does, and the two existing bases each answer it in a way
that is wrong for a chart:

  * `basis='order'` puts an order on its order date, so a journey opened
    on the 3rd and closed on the 11th draws a bar on the 11th -- the day
    the money arrived, not the day the ad did its work.
  * `basis='first_touch'` drops it, because the 3rd is outside a 6th-to-
    11th window. Measured on one real ad, that lost Rs 3,112 of the
    window's Rs 26,471 with nothing on the page to say so.

This keeps every order and places it on GREATEST(first_seen, window
start), but reports the clamped part separately. Folding it into day one
turned Rs 806 of real same-day opening into a Rs 3,918 bar -- 4.9x, an
artifact of where the window was cut, which moves when you scroll it.

So the invariants are:

  * opened + carried_in equals the windowed table exactly. A daily
    series whose days do not add to its own window is worse than no
    series.
  * carried_in is only ever on the first day, and is never silently
    merged into opened.
  * the closed side needs no clamp at all and must not get one.
"""
from datetime import date

import pytest

from app.api.routers import analytics


def test_the_day_wise_endpoint_is_registered_apart_from_the_table():
    # A separate endpoint, not a third `basis`: at window level the clamp
    # produces exactly the numbers `basis='order'` already gives, so a
    # third option on that selector would be an inert control.
    assert set(analytics._FIRST_CLICK_GRAINS) == {"source", "ad", "adset"}
    assert "first_touch_clamped" not in str(analytics.FirstClickResponse.model_fields)


def test_the_response_separates_carried_in_from_opened():
    f = analytics.FirstClickDailyRow.model_fields
    assert {"opened_revenue", "carried_in_revenue", "closed_revenue"} <= set(f)
    # Counts too, so a reader can see three orders carried Rs 3,112
    # rather than guessing at the size of the tail.
    assert {"opened_orders", "carried_in_orders", "closed_orders"} <= set(f)
    totals = analytics.FirstClickDailyResponse.model_fields
    assert {"opened_total", "carried_in_total", "closed_total"} <= set(totals)


@pytest.mark.parametrize("grain", ["ad", "adset", "source"])
async def test_an_unknown_grain_is_refused_before_any_query(grain, monkeypatch):
    from fastapi import HTTPException

    def forbidden(*a, **k):
        pytest.fail("validation must happen before the session is used")

    with pytest.raises(HTTPException) as e:
        await analytics.get_first_click_daily.__wrapped__(
            type("S", (), {"execute": forbidden})(), grain="campaign")
    assert e.value.status_code == 400


async def test_a_reversed_window_is_refused():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        await analytics.get_first_click_daily.__wrapped__(
            None, from_date=date(2026, 10, 11), to_date=date(2026, 10, 6), grain="ad")
    assert e.value.status_code == 400


def test_the_closed_side_is_never_clamped():
    # The last touch IS the converting session, so it is always inside
    # the window by construction. Clamping it would be meaningless, and
    # worse, it would stop the closed series reconciling with the
    # last-click table.
    import inspect
    src = inspect.getsource(analytics.get_first_click_daily)
    closed = src.split("closed_revenue")[0].rsplit("carried_in_orders", 1)[-1]
    assert "o.od = d.day" in closed
    assert "GREATEST" not in src, "the clamp is expressed as fd < a on day a, not GREATEST"


def test_carried_in_can_only_land_on_the_first_day():
    import inspect
    src = inspect.getsource(analytics.get_first_click_daily)
    # Both halves of the predicate, or the tail spreads across the window.
    assert "o.fd < b.a AND d.day = b.a" in src
    # ...and the opened series must exclude it, or it is counted twice.
    assert "o.fd = d.day AND o.fd >= b.a" in src


def test_source_grain_reports_no_spend():
    # Same rule as the windowed table: a source like kwikengage or
    # affiliate is not a billable entity, and a zero would claim the
    # orders were free.
    import inspect
    src = inspect.getsource(analytics.get_first_click_daily)
    assert 'if grain != "source"' in src
    assert "spend=spend_by_day.get(r[\"day\"]) if grain != \"source\" else None" in src
