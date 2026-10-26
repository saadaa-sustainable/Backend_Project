"""Last-click Google, folded into shopify_order_attribution.

WHY THIS SITS BESIDE THE META MATCHER
-------------------------------------
Google orders were landing in `unmatched` and the Last Click view showed
them as unattributable: 1,913 orders and Rs 3,144,101 over the 30 days
to 2026-10-21, a third of everything that tier contained. The Meta
matcher cannot resolve them -- it searches a roster of Meta ads -- so
they need their own pass over the same rows.

It runs only on orders the Meta matcher left `unmatched`, so it can
never take an order away from a Meta match.

WHAT THE UTM FIELDS ACTUALLY HOLD
---------------------------------
Google auto-tagging writes ValueTrack ids, and this account's template
puts them in an order that does NOT match the parameter names --
verified against the Google Ads API on 2026-10-21:

    utm_campaign  = campaign id   19752547631  -> Search - Branded
    utm_term      = AD GROUP id   148136693402 -> सादा / SAADAA
    utm_content   = AD id         649815036937

`utm_term` is the ad group and `utm_content` is the ad. Meta's matcher
reads `utm_content` as an ad and `utm_term` as an ad SET, so the two
agree by accident on content and disagree on term. Do not share code
between them on that assumption.

ONLY TWO TIERS ARE REACHABLE, AND THAT IS CORRECT
-------------------------------------------------
`shopify_order_attribution` has no ad-set columns -- Meta's own
`adset_scoped` still resolves to an ad inside the ad set. Google has no
equivalent to offer, so this emits only:

    ad_direct      utm_content resolved to a real ad
    campaign_only  it did not, but utm_campaign resolved

That loses nothing in practice. Measured over the same 30 days,
campaign_only is 677/688 PERFORMANCE MAX, which has asset groups rather
than ad groups or ads and so cannot emit {adgroupid} or {creative} at
all. For PMax the campaign IS the deepest honest level.

WHAT IS DELIBERATELY NOT MATCHED
--------------------------------
`sag_organic` in utm_campaign/utm_content marks Google's FREE product
listings -- surfaces across Google, a click nobody paid for. It stays
`unmatched`, which is the truthful answer for an AD attribution table.
Crediting it would have added 870 orders and Rs 1,255,300 to paid
Google, overstating it by about 41% of what the paid orders are worth.

WHERE THE ROSTER COMES FROM
---------------------------
Postgres, exactly like Meta's. `scripts/fetch_google_ads_entities.py`
lands `google_ads` / `google_ad_groups` / `google_campaigns` in the
nightly, and this reads them -- so the rebuild needs no Google
credential at run time, which matters because the nightly runs in CI
where no refresh token exists.

The Google Ads API stays as a fallback for the case where the roster
table has not been filled yet, and the whole load is wrapped so that a
missing table, an empty one or an unreachable API leaves Google orders
`unmatched` rather than failing the silver rebuild.

AD NAMES ARE OFTEN BLANK, SO JOIN TO ad_label
---------------------------------------------
Google does not require an ad name and 50 of 440 ads have none --
including ALL 32 responsive search ads, the type most likely to produce
an `ad_direct` match. `google_ads.ad_label` is NOT NULL and falls back
to the ad type and id, so this reads that column, never `ad_name`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: Google's marker for free product listings. Never a paid click.
ORGANIC_MARKER = "sag_organic"

#: The roster: every campaign in the account, spending or not.
_ROSTER_CAMPAIGNS_SQL = """
SELECT campaign_id, campaign_name
  FROM public.google_campaigns
 WHERE campaign_name IS NOT NULL
"""

#: Read second, and only to fill gaps the roster left. A campaign can be
#: in the spend table and not the roster -- it spent before the roster
#: existed, or the API aged it out -- and an order naming it should still
#: resolve. `setdefault` in the loader makes the roster win on conflict,
#: because its names are current and this one's are as of the last day
#: the campaign spent.
_SPEND_CAMPAIGNS_SQL = """
SELECT DISTINCT ON (campaign_id) campaign_id, campaign_name
  FROM public.google_ads_spend_daily
 WHERE campaign_name IS NOT NULL
 ORDER BY campaign_id, day DESC
"""

#: ad_label, not ad_name: see the module docstring.
_ROSTER_ADS_SQL = """
SELECT ad_id, ad_label, campaign_id, campaign_name
  FROM public.google_ads
"""

#: Removed ads included on purpose: an order from three months ago can
#: name an ad since deleted, and skipping it would file a matchable
#: order as unmatched.
_ADS_GAQL = ("SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, "
             "campaign.id, campaign.name FROM ad_group_ad")


@dataclass
class GoogleUniverse:
    campaigns: dict[str, str] = field(default_factory=dict)
    #: ad_id -> (ad_label, campaign_id, campaign_name)
    ads: dict[str, tuple[str | None, str, str | None]] = field(default_factory=dict)
    #: "roster" (Postgres), "api" (live fallback) or "none". Logged, so a
    #: run that quietly lost ad-level matching is visible afterwards
    #: rather than looking like an account with no ads.
    source: str = "none"

    def __bool__(self) -> bool:
        return bool(self.campaigns or self.ads)


def _fetch_ads_blocking() -> dict[str, tuple[str | None, str, str | None]]:
    """Google Ads API, in a worker thread -- the client is synchronous."""
    from scripts.google_ads_auth import connect

    out: dict[str, tuple[str | None, str, str | None]] = {}
    for row in connect().search_stream(_ADS_GAQL):
        ad = row["adGroupAd"]["ad"]
        camp = row.get("campaign", {})
        out[str(ad["id"])] = (ad.get("name"), str(camp.get("id") or ""),
                              camp.get("name"))
    return out


async def load_google_universe(session: AsyncSession) -> GoogleUniverse:
    """The roster from Postgres, with the live API as a fallback.

    Every read is guarded, and for one reason: this is an ENRICHMENT of
    the Meta rebuild. A missing table, an empty one or an unreachable
    API leaves Google orders `unmatched` -- exactly where they were
    before this existed. An enrichment that can abort the whole silver
    refresh is a worse trade than one that quietly does nothing.
    """
    universe = GoogleUniverse()

    for sql, table in ((_ROSTER_CAMPAIGNS_SQL, "google_campaigns"),
                       (_SPEND_CAMPAIGNS_SQL, "google_ads_spend_daily")):
        try:
            result = await session.execute(text(sql))
            for campaign_id, campaign_name in result:
                universe.campaigns.setdefault(str(campaign_id), campaign_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("google_attribution_campaigns_unavailable",
                           table=table, error=str(exc)[:200])

    try:
        result = await session.execute(text(_ROSTER_ADS_SQL))
        universe.ads = {str(r[0]): (r[1], str(r[2] or ""), r[3]) for r in result}
        if universe.ads:
            universe.source = "roster"
    except Exception as exc:  # noqa: BLE001
        logger.warning("google_attribution_roster_unavailable",
                       error=str(exc)[:200])

    # Only when the roster gave nothing. Once
    # scripts/fetch_google_ads_entities.py has run this never fires, and
    # on a fresh database it keeps ad-level matching working anyway.
    if not universe.ads:
        try:
            universe.ads = await asyncio.to_thread(_fetch_ads_blocking)
            universe.source = "api"
        except Exception as exc:  # noqa: BLE001 -- degrade, never fail
            logger.warning("google_attribution_api_unavailable",
                           error=str(exc)[:200],
                           note="falling back to campaign-level matching")

    logger.info("google_universe_loaded",
                campaigns=len(universe.campaigns), ads=len(universe.ads),
                source=universe.source)
    return universe


def is_google_order(utm_source: str | None) -> bool:
    return "google" in (utm_source or "").strip().lower()


def attribute_google(
    utm_campaign: str | None, utm_content: str | None,
    universe: GoogleUniverse,
) -> tuple[str, str | None, str | None, str | None, str | None, str | None] | None:
    """-> (tier, ad_id, ad_name, campaign_id, campaign_name, matched_value).

    None when nothing resolves, so the caller keeps the Meta result it
    already has rather than overwriting a considered `unmatched` with a
    differently-worded one.

    `utm_term` is NOT read. It carries the ad group id, and this table
    has nowhere to put an ad group that is not also an ad -- see the
    module docstring.
    """
    campaign = (utm_campaign or "").strip()
    content = (utm_content or "").strip()

    # A free listing is not an ad. Decided before any lookup so the
    # marker can never collide with a real id.
    if ORGANIC_MARKER in (campaign, content):
        return None

    if content and content in universe.ads:
        ad_name, camp_id, camp_name = universe.ads[content]
        return ("ad_direct", content, ad_name,
                camp_id or campaign or None,
                camp_name or universe.campaigns.get(campaign), content)

    if campaign and campaign in universe.campaigns:
        return ("campaign_only", None, None, campaign,
                universe.campaigns[campaign], campaign)
    return None
