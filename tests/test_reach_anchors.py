"""A reach anchor measured on its own as-of date is not an answer yet.

Meta keeps revising a cumulative window's de-duplicated reach for as
long as the window's LAST DAY is still accruing -- and stops the moment
it closes. Measured 2026-10-21 against Meta at campaign level:

    measured      as-of        campaigns   exact   worst error
    same day      2026-10-04          62      46        24.19%
    same day      2026-10-12          63      52        13.58%
    +1 day        2026-09-20          52      52         0.00%
    +7 days       2026-09-14          50      50         0.00%
    +90 days      2026-07-15          32      32         0.00%

Everything here follows from that one fact: a same-day row is
PROVISIONAL and must be re-measured once its day closes; a later row is
FINAL and can be subtracted from any other final row, however far apart
the two were measured. Getting this wrong is what made the 7-day reach
columns read ~14% high.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import reach_anchors as R


EPOCH = date(2026, 1, 1)
PREV = date(2026, 10, 4)
LATEST = date(2026, 10, 12)
IDS = ["c1", "c2"]


def at(day: date, *, plus_days: int, hour: int = 2) -> datetime:
    """A `fetched_at` `plus_days` after `day` -- 0 meaning same-day."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc) \
        + timedelta(days=plus_days)


@pytest.fixture(autouse=True)
def clear_cooldown():
    R._cooldown.clear()
    yield
    R._cooldown.clear()


# ----------------------------------------------------------------- _is_final


@pytest.mark.parametrize("plus_days,expected", [
    (0, False),   # measured while the last day was still accruing
    (1, True),    # the whole of the grace period, per the table above
    (7, True),
    (90, True),
])
def test_finality_turns_on_the_day_after(plus_days, expected):
    assert R._is_final(PREV, at(PREV, plus_days=plus_days)) is expected


def test_a_missing_measurement_is_not_final():
    assert R._is_final(PREV, None) is False


# ------------------------------------------------------- refusing to answer


async def test_no_entities_is_not_an_answer():
    assert await R.window_anchors(
        None, level="campaign", entity_ids=[],
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH) is None


async def test_an_inverted_window_is_not_an_answer():
    assert await R.window_anchors(
        None, level="campaign", entity_ids=IDS,
        prev_day=LATEST, latest_day=PREV, epoch=EPOCH) is None


async def test_a_whole_fleet_is_the_nightlys_job_not_a_requests():
    """Past MAX_ENTITIES this declines rather than fanning out, so one
    page view cannot turn into a backfill."""
    assert await R.window_anchors(
        None, level="campaign", entity_ids=[f"c{i}" for i in range(R.MAX_ENTITIES + 1)],
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH) is None


# ------------------------------------------------------- serving from store


async def test_two_final_anchors_serve_without_calling_meta(monkeypatch):
    """Measured 8 days apart on purpose: once both are final, the gap
    between the two measurements does not matter, and that is what makes
    a custom range servable from stored rows at all."""
    stored = {
        ("c1", PREV): (100, at(PREV, plus_days=1)),
        ("c1", LATEST): (175, at(LATEST, plus_days=9)),
    }
    monkeypatch.setattr(R, "_stored", _fake_stored(stored))
    monkeypatch.setattr(R, "_measure", _forbidden)

    got = await R.window_anchors(
        None, level="campaign", entity_ids=["c1"],
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH)
    assert got == {"c1": (100, 175)}


async def test_a_provisional_anchor_is_re_measured_once_its_day_has_closed(monkeypatch):
    stored = {
        ("c1", PREV): (100, at(PREV, plus_days=0)),      # provisional
        ("c1", LATEST): (175, at(LATEST, plus_days=9)),  # final
    }
    calls = []

    async def fake_measure(session, *, level, entity_ids, days, epoch):
        calls.append(sorted(entity_ids))
        return {("c1", PREV): 123, ("c1", LATEST): 180}

    monkeypatch.setattr(R, "_stored", _fake_stored(stored))
    monkeypatch.setattr(R, "_measure", fake_measure)

    got = await R.window_anchors(
        None, level="campaign", entity_ids=["c1"],
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH)
    assert calls == [["c1"]], "the provisional anchor should have been re-measured"
    assert got == {"c1": (123, 180)}


async def test_an_anchor_on_today_is_not_re_measured_and_not_answered(monkeypatch):
    """No measurement can settle a day that has not ended, so spending a
    call on it would buy another provisional number. Declining lets the
    caller fall back to a nearest-snapshot value its cell labels."""
    today = date.today()
    stored = {
        ("c1", PREV): (100, at(PREV, plus_days=1)),
        ("c1", today): (175, at(today, plus_days=0)),
    }
    monkeypatch.setattr(R, "_stored", _fake_stored(stored))
    monkeypatch.setattr(R, "_measure", _forbidden)

    assert await R.window_anchors(
        None, level="campaign", entity_ids=["c1"],
        prev_day=PREV, latest_day=today, epoch=EPOCH) is None


async def test_half_a_subtraction_is_dropped_not_guessed(monkeypatch):
    """c2 resolves on only one of the two days. Returning it would mean
    subtracting from nothing; it is left out and c1 is still served."""
    stored = {
        ("c1", PREV): (100, at(PREV, plus_days=1)),
        ("c1", LATEST): (175, at(LATEST, plus_days=9)),
        ("c2", LATEST): (900, at(LATEST, plus_days=9)),
    }

    async def fake_measure(session, *, level, entity_ids, days, epoch):
        return {}       # Meta had nothing for c2's earlier anchor

    monkeypatch.setattr(R, "_stored", _fake_stored(stored))
    monkeypatch.setattr(R, "_measure", fake_measure)

    got = await R.window_anchors(
        None, level="campaign", entity_ids=IDS,
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH)
    assert got == {"c1": (100, 175)}


async def test_a_failed_measure_falls_back_rather_than_failing_the_page(monkeypatch):
    stored = {("c1", PREV): (100, at(PREV, plus_days=0))}

    async def boom(session, *, level, entity_ids, days, epoch):
        raise RuntimeError("Meta is having a day")

    monkeypatch.setattr(R, "_stored", _fake_stored(stored))
    monkeypatch.setattr(R, "_measure", boom)

    assert await R.window_anchors(
        None, level="campaign", entity_ids=["c1"],
        prev_day=PREV, latest_day=LATEST, epoch=EPOCH) is None


# ------------------------------------------------------------------ cooldown


def test_a_cooled_account_is_skipped_until_it_expires(monkeypatch):
    assert R._cooling("act1") is False
    R._cool_off("act1")
    assert R._cooling("act1") is True

    # Expiry is read off the clock, and a lapsed entry is dropped so the
    # dict cannot grow without bound.
    monkeypatch.setattr(R.time, "monotonic",
                        lambda: R._cooldown["act1"] + 1.0)
    assert R._cooling("act1") is False
    assert "act1" not in R._cooldown


# ------------------------------------------- the fetcher's own skip rule


def test_the_fetcher_only_skips_anchors_that_are_final():
    """The nightly's skip used to be "is it stored", which froze every
    provisional row in place. It must compare `fetched_at` to the as-of
    date, and it must require the WHOLE snapshot to be final (min, not
    max) so one account fetched early cannot settle the rest."""
    import pathlib
    src = pathlib.Path("scripts/fetch_reach_cumulative.py").read_text()
    body = src[src.index("def _existing_windows("):]
    body = body[:body.index("def _write(")]
    assert "min(fetched_at)::date > as_of_date" in body
    assert "max(fetched_at)" not in body


# ----------------------------------------------------------------- helpers


def _fake_stored(mapping):
    async def _stored(session, *, level, entity_ids, days, epoch):
        return {k: v for k, v in mapping.items()
                if k[0] in entity_ids and k[1] in days}
    return _stored


async def _forbidden(session, **kwargs):
    raise AssertionError("Meta must not be called here")
