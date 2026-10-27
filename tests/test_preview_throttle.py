"""The shared rate-limit gate must always reopen.

Reproduces the 2026-10-27 deadlock: the worker that parks is itself
running under asyncio.wait_for(AD_DEADLINE), so a park longer than the
deadline cancels it before it can re-set the gate -- leaving every other
worker blocked in before_request() forever.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "scripts" / "backfill_landing_urls_from_preview.py"
_spec = importlib.util.spec_from_file_location("backfill_preview", _SRC)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

Throttle = backfill.Throttle


async def test_gate_reopens_after_the_parking_worker_is_cancelled() -> None:
    """The exact shape of the bug: park for longer than the deadline."""
    t = Throttle()

    # The worker that saw the 429 parks, and its own deadline kills it
    # well before the park is over.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(t.pause(0.25, "code=80004"), 0.05)

    assert t.pauses == 1

    # Another worker is waiting at the gate. It must get through once
    # the park elapses, even though nobody is left inside pause().
    await asyncio.wait_for(t.before_request(), 2.0)
    await t.aclose()


async def test_gate_stays_shut_for_the_duration_of_the_park() -> None:
    """Reopening must not be so eager that the park means nothing."""
    t = Throttle()
    parker = asyncio.create_task(t.pause(0.3, "code=80004"))
    await asyncio.sleep(0.05)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(t.before_request(), 0.1)

    await asyncio.wait_for(parker, 2.0)
    await asyncio.wait_for(t.before_request(), 0.1)
    await t.aclose()


async def test_a_longer_park_extends_an_active_one() -> None:
    """Two workers hitting the limit must not shorten the wait."""
    t = Throttle()
    short = asyncio.create_task(t.pause(0.1, "first"))
    await asyncio.sleep(0.02)
    long = asyncio.create_task(t.pause(0.5, "second"))

    await asyncio.wait_for(asyncio.gather(short, long), 3.0)
    # One gate, so one announcement -- the second call extends it.
    assert t.pauses == 1
    await t.aclose()


async def test_many_waiters_all_resume() -> None:
    t = Throttle()
    waiters = [asyncio.create_task(t.before_request()) for _ in range(8)]
    await asyncio.sleep(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(t.pause(0.2, "code=80004"), 0.02)

    await asyncio.wait_for(asyncio.gather(*waiters), 2.0)
    await t.aclose()
