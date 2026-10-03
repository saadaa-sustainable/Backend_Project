"""Refreshing faster must not change the existing matching rules or publication."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.silver import shopify_ad_attribution as attribution
from scripts.refresh_shopify_silver import verify_attribution_freshness


def ad(ad_id, name, adset="set-1", campaign="campaign-1"):
    return attribution.AdMeta(ad_id, name, adset, campaign, "Test campaign", 10)


@pytest.fixture
def universe():
    return attribution._build_ad_universe(
        [ad("111", "Linen summer creative"), ad("222", "Shared creative"),
         ad("333", "Shared creative"), ad("444", "Different creative", "set-2")],
        adsets=[("set-1", "campaign-1", "Test campaign")],
        campaigns=[("campaign-1", "Test campaign")],
        name_history=[("set-1", "111", "Historical creative")],
        overrides=[("weighted creative", "*", "222", 1),
                   ("weighted creative", "*", "333", 2)],
    )


@pytest.mark.parametrize("signals", [
    ("111", "set-2", "Other campaign"),
    ("%31%31%31", "", ""),
    (" Linen summer creative ", "set-1", ""),
    ("Linen_summer_creative", "", "campaign-1"),
    ("Historical creative", "set-1", ""),
    ("Shared creative", "set-1", ""),
    ("Different creative", "set-1", ""),
    ("No matching creative", "", "campaign-1"),
    ("Prefix Linen summer creative suffix", "", ""),
    ("weighted creative", "", ""),
    (None, None, None),
])
def test_cached_matching_preserves_every_tier_and_order_identity(universe, signals):
    match = attribution._build_order_matcher(universe)
    for index in range(40):
        order_id = f"order-{index}"
        expected = attribution._attribute_order(*signals, universe, order_id=order_id)
        assert match(*signals, order_id=order_id) == expected


def test_weighted_override_still_splits_identical_signals_per_order(universe):
    match = attribution._build_order_matcher(universe)
    results = {match("weighted creative", "", "", order_id=f"order-{i}").matched_ad_id
               for i in range(100)}
    assert results == {"222", "333"}


def test_identical_signals_are_computed_once_and_cache_is_per_rebuild(universe, monkeypatch):
    original = attribution._attribute_order
    spy = MagicMock(wraps=original)
    monkeypatch.setattr(attribution, "_attribute_order", spy)
    match = attribution._build_order_matcher(universe)
    for i in range(100):
        assert match("Linen summer creative", "set-1", "", order_id=str(i)).matched_ad_id == "111"
    assert spy.call_count == 1
    rebuilt = attribution._build_order_matcher(attribution._build_ad_universe([]))
    assert rebuilt("Linen summer creative", "set-1", "").matched_ad_id is None
    assert spy.call_count == 2


@pytest.mark.parametrize("fail_second_batch", [False, True])
async def test_attribution_publishes_all_batches_in_one_commit(monkeypatch, fail_second_batch):
    orders = [SimpleNamespace(order_id=str(i), name=None, total_price=0, created_at=None,
                              customer_id=None, utm_source=None, utm_medium=None,
                              utm_content=None, utm_term=None, utm_campaign=None)
              for i in range(10_001)]
    monkeypatch.setattr(attribution, "_load_ad_universe", AsyncMock(
        return_value=attribution._build_ad_universe([]),
    ))
    monkeypatch.setattr(attribution, "_load_orders", AsyncMock(return_value=orders))
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    writes = []

    async def execute(statement, rows=None):
        session.commit.assert_not_awaited()
        if rows is not None:
            writes.append(rows)
            if fail_second_batch and len(writes) == 2:
                raise RuntimeError("Synthetic write failure")

    session.execute.side_effect = execute
    if fail_second_batch:
        with pytest.raises(RuntimeError, match="Synthetic write failure"):
            await attribution._refresh_order_attribution(session)
        session.commit.assert_not_awaited()
    else:
        assert await attribution._refresh_order_attribution(session) == len(orders)
        session.commit.assert_awaited_once()
    assert [len(rows) for rows in writes] == [10_000, 1]
    assert [row["order_id"] for rows in writes for row in rows] == [o.order_id for o in orders]
    assert str(session.execute.call_args_list[0].args[0]) == "TRUNCATE shopify_order_attribution"


@pytest.mark.parametrize("attributed_day,ok", [(3, True), (2, False), (None, False)])
async def test_refresh_cannot_report_success_when_attribution_is_behind(attributed_day, ok):
    source = datetime(2026, 10, 3, tzinfo=timezone.utc)
    attributed = datetime(2026, 10, attributed_day, tzinfo=timezone.utc) if attributed_day else None
    result = MagicMock()
    result.one.return_value = (source, attributed, source)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    if ok:
        await verify_attribution_freshness(session)
    else:
        with pytest.raises(RuntimeError, match="still behind"):
            await verify_attribution_freshness(session)
