"""The Google roster comes from Postgres, and never breaks the rebuild.

The point of `fetch_google_ads_entities.py` is that the silver rebuild
stops needing a live Google Ads credential. These lock that in: the
roster must be preferred, the API must be used only as a fallback, and
every failure mode must degrade instead of raising -- an enrichment that
can abort the Meta rebuild is worse than one that does nothing.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.silver import google_order_attribution as goog


def _session(*results):
    """An AsyncSession whose execute() returns each result in turn.

    A result is either rows to iterate or an Exception to raise, which
    is how a missing table is simulated.
    """
    session = AsyncMock()

    async def execute(*_args, **_kwargs):
        nxt = pending.pop(0) if pending else []
        if isinstance(nxt, Exception):
            raise nxt
        return iter(nxt)

    pending = list(results)
    session.execute = execute
    return session


# Order of reads in load_google_universe: roster campaigns, spend
# campaigns, roster ads.
ROSTER_CAMPAIGNS = [("19752547631", "Search - Branded")]
SPEND_CAMPAIGNS = [("19752547631", "Search - Branded (old name)"),
                   ("888", "Spend only campaign")]
ROSTER_ADS = [("649815036937", "Brand RSA", "19752547631", "Search - Branded")]


@pytest.mark.asyncio
async def test_roster_is_preferred_and_no_api_call_is_made():
    with patch.object(goog, "_fetch_ads_blocking",
                      side_effect=AssertionError("API must not be called")):
        u = await goog.load_google_universe(
            _session(ROSTER_CAMPAIGNS, SPEND_CAMPAIGNS, ROSTER_ADS))
    assert u.source == "roster"
    assert u.ads["649815036937"][0] == "Brand RSA"


@pytest.mark.asyncio
async def test_spend_table_fills_gaps_but_never_overrides_the_roster():
    u = await goog.load_google_universe(
        _session(ROSTER_CAMPAIGNS, SPEND_CAMPAIGNS, ROSTER_ADS))
    # The roster's current name wins over the spend table's stale one...
    assert u.campaigns["19752547631"] == "Search - Branded"
    # ...but a campaign only the spend table knows is still resolvable,
    # so an order naming an aged-out campaign does not go unmatched.
    assert u.campaigns["888"] == "Spend only campaign"


@pytest.mark.asyncio
async def test_empty_roster_falls_back_to_the_api():
    with patch.object(goog, "_fetch_ads_blocking",
                      return_value={"1": ("From API", "2", "Camp")}):
        u = await goog.load_google_universe(
            _session(ROSTER_CAMPAIGNS, SPEND_CAMPAIGNS, []))
    assert u.source == "api"
    assert u.ads == {"1": ("From API", "2", "Camp")}


@pytest.mark.asyncio
async def test_missing_roster_table_does_not_raise():
    """A fresh database has no google_ads table. That must not fail the rebuild."""
    with patch.object(goog, "_fetch_ads_blocking",
                      side_effect=RuntimeError("no credential")):
        u = await goog.load_google_universe(
            _session(RuntimeError("no such table: google_campaigns"),
                     SPEND_CAMPAIGNS,
                     RuntimeError("no such table: google_ads")))
    assert u.source == "none"
    assert u.ads == {}
    # Campaign-level matching still works off the spend table alone.
    assert u.campaigns["888"] == "Spend only campaign"
    assert goog.attribute_google("888", None, u) == (
        "campaign_only", None, None, "888", "Spend only campaign", "888")


@pytest.mark.asyncio
async def test_everything_unavailable_leaves_an_empty_falsy_universe():
    with patch.object(goog, "_fetch_ads_blocking",
                      side_effect=RuntimeError("no credential")):
        u = await goog.load_google_universe(
            _session(RuntimeError("x"), RuntimeError("x"), RuntimeError("x")))
    assert not u          # the caller skips Google entirely on a falsy universe
    assert u.source == "none"


@pytest.mark.asyncio
async def test_blank_ad_names_are_never_what_the_roster_returns():
    """google_ads.ad_label is NOT NULL, so a matched ad always has a label.

    11% of this account's ads have no ad_name, including every responsive
    search ad, so matching on the raw name would hand the UI a blank.
    """
    labelled = [("55", "Responsive Search Ad 55", "19752547631", "Search - Branded")]
    u = await goog.load_google_universe(
        _session(ROSTER_CAMPAIGNS, [], labelled))
    tier, ad_id, ad_name, _, _, _ = goog.attribute_google(None, "55", u)
    assert (tier, ad_id) == ("ad_direct", "55")
    assert ad_name and ad_name.strip()
