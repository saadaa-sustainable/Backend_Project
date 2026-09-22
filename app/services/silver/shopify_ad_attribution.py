"""Match Shopify last-click signals to known Meta ads and parent entities.

The hierarchy preserves direct ad IDs, then strict terminal adset evidence,
then terminal campaign evidence, then global name matching. A name identifies
an ad only when its strongest matching layer yields one distinct ad ID.
Spend never resolves ambiguity. Current names from both maintained Meta
rosters are indexed as aliases; no guessed name or historical bronze scan is
introduced here. Order-source selection is kept separate below.

Every Shopify order remains in shopify_order_attribution, including orders
whose ad cannot be identified. Parent-only attribution does not credit an ad.
shopify_landing_page_analysis separately aggregates Shopify session metrics.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from urllib.parse import unquote

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

# Name equality may ignore Meta duplicate suffixes and separator differences,
# but it must still identify one ad. Two copies are two ads, even with one name.
#
# DASHES: Meta's own "Duplicate" writes an EN DASH -- "Name – Copy" -- while a
# hand-typed duplicate uses a hyphen. Both spellings exist side by side in
# this account, sometimes for the same ad. A separator class of [\s_\-]
# stripped "Copy" off the en-dash form but left the dash stranded, so
# "TW_onseventhsky_IFAD_230425" and "TW_onseventhsky_IFAD_230425 – Copy"
# normalised to different strings and failed to match each other.
_DASHES = r"\-‐‑‒–—―−"
_SUFFIX_RE = re.compile(
    rf"(?:[\s_{_DASHES}]+(?:copy(?:\s*\d+)?|[hc]\d+))+[\s_{_DASHES}]*$", re.IGNORECASE
)
_SEP_RE = re.compile(rf"[+_/\.\s,{_DASHES}]+")
_CAMPAIGN_SUFFIX_RE = re.compile(rf"[\s_{_DASHES}]*campaign\s*$", re.IGNORECASE)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9a-fA-F]{2}")
SUBSTRING_MIN_LEN = 10
TOKEN_SUBSET_MIN_TOKENS = 3
TOKEN_SUBSET_MIN_DISTINCTIVE_LEN = 5


def _norm_name(n: str | None) -> str:
    if not n:
        return ""
    n = n.strip()
    while True:
        new = _SUFFIX_RE.sub("", n).strip()
        if new == n:
            break
        n = new
    return re.sub(r"\s+", " ", n).strip().lower()


def _norm_campaign_name(n: str | None) -> str:
    if not n:
        return ""
    return _SEP_RE.sub(" ", _CAMPAIGN_SUFFIX_RE.sub("", n.strip())).strip().lower()


def _sep_key(s: str | None) -> str:
    return _SEP_RE.sub(" ", s).strip().lower() if s else ""


def _value_candidates(value: str | None) -> tuple[str, ...]:
    """Preserve the raw signal and at most two valid percent-decoding layers.

    A literal '+' stays '+': these fields are already parameter values, and
    plus signs are part of this account's ad names -- 40% of them carry one.

    But some capture path DID decode it the query-string way, turning the
    '+' into a space, and those values arrive unmatchable:

        utm_content   SDPL_AD FLATLAY
        ad_name       SDPL_AD+FLATLAY - Copy

    So a space-to-'+' form is offered as an EXTRA candidate, never as a
    replacement -- undoing a known decoding, exactly as the percent layers
    above do. It can only widen what a strict, uniqueness-checked match
    considers; it cannot change what the raw value already resolved to.
    """
    current = (value or "").strip()
    if not current:
        return ()
    candidates = [current]
    for _ in range(2):
        if not _PERCENT_ESCAPE_RE.search(current):
            break
        try:
            decoded = unquote(current, errors="strict").strip()
        except UnicodeDecodeError:
            break
        if not decoded or decoded in candidates:
            break
        candidates.append(decoded)
        current = decoded
    for candidate in list(candidates):
        if " " in candidate:
            restored = candidate.replace(" ", "+")
            if restored not in candidates:
                candidates.append(restored)
    return tuple(candidates)


@dataclass(frozen=True)
class AdMeta:
    ad_id: str
    ad_name: str
    adset_id: str | None
    campaign_id: str | None
    campaign_name: str | None
    spend: float
    aliases: tuple[str, ...] = ()


@dataclass
class AdUniverse:
    by_id: dict[str, AdMeta] = field(default_factory=dict)
    by_name: dict[str, list[AdMeta]] = field(default_factory=dict)
    by_fuzzy: dict[str, list[AdMeta]] = field(default_factory=dict)
    name_index: list[tuple[str, str, int, AdMeta]] = field(default_factory=list)
    adset_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    campaign_id_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    campaign_name_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    campaign_fuzzy_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    roster_adsets: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    roster_campaigns: dict[str, str | None] = field(default_factory=dict)
    roster_campaign_names: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    # These include campaigns with zero loaded ads, so such a campaign can
    # both constrain matching and make a duplicated campaign name ambiguous.
    campaign_name_ids: dict[str, set[str]] = field(default_factory=dict)
    campaign_fuzzy_ids: dict[str, set[str]] = field(default_factory=dict)
    #: Per ad set, the ads of that ad set carrying every name they have
    #: EVER answered to (from public.ad_edit_log), not just their current
    #: one. Deliberately a separate index rather than extra aliases on the
    #: main ads: a historical name must never be able to win against a
    #: live one, so this is only consulted after the current-name match
    #: has already failed. See _attribute_order's `edit_name_match`.
    adset_hist_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    #: (utm_content_lower, adset_id | '*') -> ad_id, from
    #: public.ad_name_override. Reported as `edit_name_match`: these are
    #: not a rule of their own, they are the rename the edit log failed
    #: to record, supplied by someone who checked. When the log is fixed
    #: the rule finds them unaided and the row becomes redundant.
    overrides: dict[tuple[str, str], list[tuple[str, float | None]]] = field(
        default_factory=dict)


# Use both entity rosters, including direct IDs for ads without a usable name.
# Display names retain the existing lifecycle-first preference; alternate
# current names are matching aliases for the SAME ad, not extra candidates.
_AD_UNIVERSE_SQL = """
SELECT COALESCE(al.ad_id, a.ad_id) AS ad_id,
       COALESCE(NULLIF(BTRIM(al.ad_name), ''), NULLIF(BTRIM(a.ad_name), ''), '') AS ad_name,
       a.ad_name AS meta_ad_name,
       al.ad_name AS lifecycle_ad_name,
       COALESCE(al.adset_id, a.adset_id) AS adset_id,
       COALESCE(al.campaign_id, a.campaign_id) AS campaign_id,
       COALESCE(al.campaign_name, a.campaign_name) AS campaign_name,
       COALESCE(al.spend, 0) AS spend
FROM ad_lifecycle al
FULL OUTER JOIN meta_ads a ON a.ad_id = al.ad_id
WHERE COALESCE(al.ad_id, a.ad_id) IS NOT NULL
"""
_ADSET_ROSTER_SQL = (
    "SELECT adset_id, campaign_id, campaign_name FROM meta_adsets WHERE adset_id IS NOT NULL"
)

# Every name an ad has ever carried, scoped to the ad set it was in when
# the rename happened.
#
# `utm_content` is frozen at click time -- it holds the ad's name AS IT
# WAS THEN. `ad_lifecycle` and `meta_ads` hold only the name now, so a
# rename between the click and today silently breaks name matching. That
# is the entire `adset_name_miss` tier: 54,055 orders where the ad set
# resolved and the name did not.
#
# Both sides of the rename are taken. `new_value` matters as much as
# `old_value`: a second rename makes today's name yesterday's alias.
# `object_name` is the name as of the event, which covers an ad renamed
# before our first fetch.
#
# adset_id comes from the log itself, so it is the ad set the ad was in
# AT EDIT TIME rather than the one it sits in now, and the key is exactly
# the pair an order hands us -- utm_term is the ad set, utm_content the
# name. Measured on this data, scoping the lookup to the ad set cuts
# ambiguous keys from 13.3% (name alone) to 1.9%.
_ADSET_NAME_HISTORY_SQL = """
SELECT DISTINCT e.adset_id, e.ad_id, BTRIM(nm) AS historical_name
  FROM public.ad_edit_log e,
       LATERAL (VALUES (e.extra_data ->> 'old_value'),
                       (e.extra_data ->> 'new_value'),
                       (e.object_name)) v(nm)
 WHERE e.event_type = 'update_ad_friendly_name'
   AND e.ad_id IS NOT NULL AND e.adset_id IS NOT NULL
   AND nm IS NOT NULL AND BTRIM(nm) <> ''
"""

_AD_EDIT_LOG_EXISTS = (
    "SELECT 1 FROM information_schema.tables "
    "WHERE table_schema='public' AND table_name='ad_edit_log'"
)

# Hand-supplied mappings (scripts/load_ad_name_overrides.py).
#
# This is the one input the cascade does not derive. Someone who knows
# which ad actually ran said so, and that is evidence the data does not
# carry -- an ad renamed before our earliest log, or a UTM that never
# equalled any recorded name. It therefore outranks every automatic
# rule, including a direct ad id: if a human says this utm_content means
# that ad, an inference has nothing to add.
#
# adset_id '*' applies account-wide; a real id scopes the mapping to
# orders from that ad set, which is what makes an ambiguous name usable.
_OVERRIDE_SQL = (
    "SELECT utm_content_lower, adset_id, ad_id, weight "
    "FROM public.ad_name_override ORDER BY utm_content_lower, adset_id, ad_id"
)

_OVERRIDE_EXISTS = (
    "SELECT 1 FROM information_schema.tables "
    "WHERE table_schema='public' AND table_name='ad_name_override'"
)
_CAMPAIGN_ROSTER_SQL = (
    "SELECT campaign_id, campaign_name FROM meta_campaigns WHERE campaign_id IS NOT NULL"
)


def _ad_names(ad: AdMeta) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n.strip() for n in (ad.ad_name, *ad.aliases) if n and n.strip()))


def _build_ad_universe(
    ads: Iterable[AdMeta], *,
    adsets: Iterable[tuple[str, str | None, str | None]] = (),
    campaigns: Iterable[tuple[str, str | None]] = (),
    name_history: Iterable[tuple[str, str, str]] = (),
    overrides: Iterable[tuple[str, str, str]] = (),
) -> AdUniverse:
    """Build the same pure matching indexes for database loads and audit replays."""
    universe = AdUniverse()
    universe.roster_adsets = {aid: (cid, name) for aid, cid, name in adsets}
    universe.roster_campaigns = dict(campaigns)

    def index_campaign(cid: str | None, name: str | None) -> None:
        if not cid or not name or not name.strip():
            return
        universe.campaign_name_ids.setdefault(name.strip().lower(), set()).add(cid)
        norm = _norm_campaign_name(name)
        if norm:
            universe.campaign_fuzzy_ids.setdefault(norm, set()).add(cid)

    # An alias can appear several times in source data. Index one canonical
    # object per ad ID so duplicates can never manufacture ambiguity.
    universe.by_id = {ad.ad_id: ad for ad in ads}
    for ad in universe.by_id.values():
        for name in _ad_names(ad):
            universe.by_name.setdefault(name.lower(), []).append(ad)
            norm = _norm_name(name)
            if norm:
                universe.by_fuzzy.setdefault(norm, []).append(ad)
            universe.name_index.append((name.lower(), _sep_key(name), len(name), ad))
        if ad.adset_id:
            universe.adset_ads.setdefault(ad.adset_id, []).append(ad)
        if ad.campaign_id:
            universe.campaign_id_ads.setdefault(ad.campaign_id, []).append(ad)
        if ad.campaign_name:
            universe.campaign_name_ads.setdefault(ad.campaign_name.strip().lower(), []).append(ad)
            universe.campaign_fuzzy_ads.setdefault(
                _norm_campaign_name(ad.campaign_name), [],
            ).append(ad)
        index_campaign(ad.campaign_id, ad.campaign_name)
    for cid, name in universe.roster_campaigns.items():
        index_campaign(cid, name)
    for cid, name in universe.roster_adsets.values():
        index_campaign(cid, name)
    for norm, ids in universe.campaign_fuzzy_ids.items():
        if len(ids) == 1:
            cid = next(iter(ids))
            universe.roster_campaign_names[norm] = (cid, universe.roster_campaigns.get(cid))

    # Historical names, indexed per ad set. Each entry is the REAL ad
    # object with its past names attached as aliases, so `_ad_names`
    # yields them and `_scoped_match` can run its ordinary strict layers
    # over them unchanged -- the matching rule is identical, only the
    # names it sees are wider. `_unique_ad` still collapses by ad_id, so
    # an ad reachable by two of its own old names is one candidate, not
    # two, while two different ads sharing an old name stay ambiguous and
    # therefore terminal.
    hist_by_ad: dict[tuple[str, str], set[str]] = {}
    for adset_id, ad_id, historical_name in name_history:
        if not adset_id or not ad_id or not historical_name:
            continue
        hist_by_ad.setdefault((adset_id, ad_id), set()).add(historical_name.strip())
    for (adset_id, ad_id), names in hist_by_ad.items():
        ad = universe.by_id.get(ad_id)
        if ad is None:
            # An ad the cascade cannot resolve anyway. An alias for it
            # could only produce a match pointing at nothing.
            continue
        universe.adset_hist_ads.setdefault(adset_id, []).append(
            replace(ad, aliases=tuple(dict.fromkeys((*ad.aliases, *sorted(names))))),
        )

    for utm_lower, adset_id, ad_id, weight in overrides:
        if not utm_lower or ad_id not in universe.by_id:
            # A mapping naming an ad the cascade cannot resolve would
            # produce a match pointing at nothing.
            continue
        universe.overrides.setdefault(
            (utm_lower.strip().lower(), adset_id or "*"), [],
        ).append((ad_id, None if weight is None else float(weight)))
    return universe


def _pick_weighted(
    choices: list[tuple[str, float | None]], order_id: str,
) -> str:
    """Choose one ad from a weighted key, deterministically per order.

    Two ads in one ad set can carry the SAME name -- two Sep-682 ads are
    both `SMCP_VRP_UB_US_916_Sep-682_03/10/2025_H0`. No rule can separate
    them, because nothing in the data distinguishes them. The orders are
    real and each belongs to exactly one of the two; which one is
    genuinely unknown.

    So the split is modelled, by spend share. The choice is a hash of the
    ORDER ID rather than a random draw or a round-robin: it is stable
    across rebuilds (the same order lands on the same ad every time),
    needs no stored state, and converges on the requested proportions
    over any reasonable number of orders. A random draw would reshuffle
    every ad's revenue on every refresh.

    This is an ESTIMATE and the only place in the cascade that produces
    one. Everything else either identifies an ad or declines to.
    """
    weighted = [(ad, w) for ad, w in choices if w and w > 0]
    if not weighted:
        return choices[0][0]
    if len(weighted) == 1:
        return weighted[0][0]
    total = sum(w for _a, w in weighted)
    # 1e6 buckets: fine enough that a 0.01% weight still lands.
    bucket = int(hashlib.md5(order_id.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000
    cutoff = bucket / 1_000_000 * total
    running = 0.0
    for ad, w in weighted:
        running += w
        if cutoff < running:
            return ad
    return weighted[-1][0]


async def _load_ad_universe(session: AsyncSession) -> AdUniverse:
    rows = await session.execute(text(_AD_UNIVERSE_SQL))
    ads = [
        AdMeta(
            ad_id=row.ad_id, ad_name=row.ad_name, adset_id=row.adset_id,
            campaign_id=row.campaign_id, campaign_name=row.campaign_name,
            spend=float(row.spend or 0),
            aliases=tuple(n for n in (row.meta_ad_name, row.lifecycle_ad_name) if n),
        )
        for row in rows
    ]
    adsets = [tuple(row) for row in await session.execute(text(_ADSET_ROSTER_SQL))]
    campaigns = [tuple(row) for row in await session.execute(text(_CAMPAIGN_ROSTER_SQL))]
    # Optional: an install that has not run scripts/ingest_ad_edit_log.py
    # simply has no rename history, and the cascade behaves exactly as it
    # did before rather than failing to load.
    name_history: list[tuple[str, str, str]] = []
    if (await session.execute(text(_AD_EDIT_LOG_EXISTS))).first() is not None:
        name_history = [
            tuple(row) for row in await session.execute(text(_ADSET_NAME_HISTORY_SQL))
        ]
        logger.info("ad_edit_log name history loaded", extra={"rows": len(name_history)})
    overrides: list[tuple[str, str, str]] = []
    if (await session.execute(text(_OVERRIDE_EXISTS))).first() is not None:
        overrides = [tuple(row) for row in await session.execute(text(_OVERRIDE_SQL))]
        logger.info("ad_name_override loaded", extra={"rows": len(overrides)})
    return _build_ad_universe(
        ads, adsets=adsets, campaigns=campaigns, name_history=name_history,
        overrides=overrides,
    )


def _unique_ad(candidates: Iterable[AdMeta]) -> AdMeta | None:
    by_id = {ad.ad_id: ad for ad in candidates}
    return next(iter(by_id.values())) if len(by_id) == 1 else None


def _scoped_match(ads: list[AdMeta], name_cand: str, *, strict: bool = False) -> AdMeta | None:
    """Resolve only a unique ad at the first matching name layer.

    Strict adset matching permits exact, duplicate-suffix-normalized, and
    separator-equivalent equality. It never uses containment or tokens.
    Ambiguity at any layer is terminal; a weaker rule cannot pick a winner.
    Campaign containment/token matching also requires one distinct ad ID.
    """
    values = _value_candidates(name_cand)
    if not values or not ads:
        return None
    names = [(name, ad) for ad in ads for name in _ad_names(ad)]
    for normalize in (str.lower, _norm_name, _sep_key):
        keys = {normalize(value) for value in values} - {""}
        hits = [ad for name, ad in names if normalize(name) in keys]
        if hits:
            return _unique_ad(hits)
    if strict:
        return None
    # A short fragment such as "ad" is not identifying evidence, even if
    # a campaign currently contains only one ad in the local roster.
    for normalize in (str.lower, _sep_key):
        keys = [normalize(value) for value in values]
        hits = [
            ad for name, ad in names
            if any(
                min(len(normalize(name)), len(key)) >= SUBSTRING_MIN_LEN
                and (normalize(name) in key or key in normalize(name))
                for key in keys
            )
        ]
        if hits:
            return _unique_ad(hits)
    token_sets = [
        set(_sep_key(value).split()) for value in values
        if len(_sep_key(value).split()) >= TOKEN_SUBSET_MIN_TOKENS
        and any(
            len(token) >= TOKEN_SUBSET_MIN_DISTINCTIVE_LEN and not token.isdigit()
            for token in _sep_key(value).split()
        )
    ]
    return _unique_ad(
        ad for name, ad in names
        if any(tokens.issubset(set(_sep_key(name).split())) for tokens in token_sets)
    )


@dataclass
class AttributionResult:
    tier: str
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_campaign_id: str | None
    matched_campaign_name: str | None
    matched_value: str | None = None


_UNMATCHED = AttributionResult("unmatched", None, None, None, None, None)


def _campaign_ids(utm_campaign: str, universe: AdUniverse) -> set[str]:
    """Return IDs from the strongest campaign layer, retaining ambiguity."""
    values = _value_candidates(utm_campaign)
    known_ids = set(universe.campaign_id_ads) | set(universe.roster_campaigns)
    known_ids.update(cid for cid, _ in universe.roster_adsets.values() if cid)
    direct = {value for value in values if value in known_ids}
    if direct:
        return direct
    for normalize, index in (
        (str.lower, universe.campaign_name_ids),
        (_norm_campaign_name, universe.campaign_fuzzy_ids),
    ):
        ids = set().union(*(index.get(normalize(value), set()) for value in values))
        if ids:
            return ids
    return set()


def _resolve_campaign(utm_campaign: str, universe: AdUniverse) -> list[AdMeta] | None:
    """Compatibility helper: duplicate campaign names never resolve a scope."""
    ids = _campaign_ids(utm_campaign, universe)
    if len(ids) != 1:
        return None
    return universe.campaign_id_ads.get(next(iter(ids)), [])


def _global_name_match(utm_content: str, universe: AdUniverse) -> AdMeta | None:
    values = _value_candidates(utm_content)
    for normalize, index in ((str.lower, universe.by_name), (_norm_name, universe.by_fuzzy)):
        hits = [ad for value in values for ad in index.get(normalize(value), [])]
        if hits:
            return _unique_ad(hits)
    # A raw/normalized substring is one evidence layer; do not pick a
    # higher-spend candidate, or retry a weaker layer after an ambiguous hit.
    hits = []
    for name_lower, name_sep, _, ad in universe.name_index:
        for value in values:
            raw, sep = value.lower(), _sep_key(value)
            if (
                min(len(name_lower), len(raw)) >= SUBSTRING_MIN_LEN
                and (name_lower in raw or raw in name_lower)
            ) or (
                min(len(name_sep), len(sep)) >= SUBSTRING_MIN_LEN
                and (name_sep in sep or sep in name_sep)
            ):
                hits.append(ad)
                break
    return _unique_ad(hits)


def _attribute_order(
    utm_content: str, utm_term: str, utm_campaign: str, universe: AdUniverse,
    order_id: str = "",
) -> AttributionResult:
    """Direct ID -> terminal strict adset -> terminal campaign -> global name.

    All returned ad matches identify one distinct ad ID. Known parent
    evidence cannot be overridden by a same-named ad outside that parent.
    Original UTM values remain available as the audit token.
    """
    utm_content = (utm_content or "").strip()
    utm_term = (utm_term or "").strip()
    utm_campaign = (utm_campaign or "").strip()

    def matched(tier: str, ad: AdMeta) -> AttributionResult:
        return AttributionResult(
            tier, ad.ad_id, ad.ad_name, ad.campaign_id, ad.campaign_name, utm_content,
        )

    direct = [
        universe.by_id[value] for value in _value_candidates(utm_content)
        if value.isdigit() and value in universe.by_id
    ]
    if direct:
        ad = _unique_ad(direct)
        return matched("ad_direct", ad) if ad else _UNMATCHED

    # Hand-supplied mappings, reported as `edit_name_match` because that
    # is what they stand in for: a rename the edit log did not record.
    #
    # Placed after the direct ad-id check so an explicit id in the URL
    # still wins -- that is stronger evidence than a name mapping, and
    # these rows exist for names, not ids. Placed BEFORE the adset
    # branch because an account-wide mapping must apply whatever ad set
    # the order came through: the case it exists for is an order from ad
    # set A naming an ad that sits in ad set B, which is unreachable
    # from inside a branch scoped to A.
    if universe.overrides:
        for value in _value_candidates(utm_content):
            key = value.strip().lower()
            for scope in (utm_term.strip(), "*"):
                choices = universe.overrides.get((key, scope)) if scope else None
                if choices:
                    ad_id = _pick_weighted(choices, order_id or utm_content)
                    return matched("edit_name_match", universe.by_id[ad_id])

    adset_ids = {
        value for value in _value_candidates(utm_term)
        if value in universe.adset_ads or value in universe.roster_adsets
    }
    if adset_ids:
        if len(adset_ids) != 1:
            return _UNMATCHED
        adset_id = next(iter(adset_ids))
        ads = universe.adset_ads.get(adset_id, [])
        ad = _scoped_match(ads, utm_content, strict=True)
        if ad:
            return matched("adset_scoped", ad)

        # The ad's CURRENT name did not match. Before giving up, try the
        # names it used to have: `utm_content` was written at click time,
        # so an ad renamed since then still carries its old name in the
        # order while ad_lifecycle carries only the new one.
        #
        # Strictly after the live-name attempt above, never instead of
        # it. 5,843 orders that already resolve on a current name ALSO
        # match some ad's historical name, so consulting history first
        # would let a stale name shadow a correct match.
        #
        # Same rule, same strictness -- only the set of names is wider,
        # so ambiguity stays terminal here exactly as it does above.
        hist = universe.adset_hist_ads.get(adset_id)
        if hist:
            ad = _scoped_match(hist, utm_content, strict=True)
            if ad:
                return matched("edit_name_match", ad)

        parent = universe.roster_adsets.get(adset_id)
        if parent is None:
            ids = {ad.campaign_id for ad in ads}
            parent = (ads[0].campaign_id, ads[0].campaign_name) if len(ids) == 1 else (None, None)
        return AttributionResult("adset_name_miss", None, None, *parent, utm_term)

    campaign_ids = _campaign_ids(utm_campaign, universe)
    if campaign_ids:
        if len(campaign_ids) != 1:
            return _UNMATCHED
        campaign_id = next(iter(campaign_ids))
        ads = universe.campaign_id_ads.get(campaign_id, [])
        ad = _scoped_match(ads, utm_content)
        if ad:
            return matched("campaign_scoped", ad)
        campaign_name = universe.roster_campaigns.get(campaign_id)
        if campaign_name is None and ads:
            campaign_name = ads[0].campaign_name
        if campaign_name is None:
            campaign_name = next(
                (name for cid, name in universe.roster_adsets.values() if cid == campaign_id), None,
            )
        return AttributionResult(
            "campaign_only", None, None, campaign_id, campaign_name, utm_campaign,
        )

    ad = _global_name_match(utm_content, universe) if utm_content else None
    return matched("ad_name_match", ad) if ad else _UNMATCHED


# ----------------------------------------------------------------------
# shopify_order_attribution
# ----------------------------------------------------------------------

_ATTRIBUTION_DDL = """
CREATE TABLE IF NOT EXISTS shopify_order_attribution (
    order_id text PRIMARY KEY,
    name text,
    total_price numeric,
    created_at timestamptz,
    customer_id text,
    utm_source text,
    utm_medium text,
    utm_campaign text,
    utm_content text,
    utm_term text,
    tier text,
    matched_ad_id text,
    matched_ad_name text,
    matched_campaign_id text,
    matched_campaign_name text,
    matched_value text,
    flattened_at timestamptz
)
"""

_ATTRIBUTION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_shopify_order_attribution_tier ON shopify_order_attribution (tier)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_order_attribution_matched_ad_id ON shopify_order_attribution (matched_ad_id)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_order_attribution_matched_campaign_id ON shopify_order_attribution (matched_campaign_id)",
]

# shopify_order_attribution predates the utm_term column -- ALTER, not just
# CREATE IF NOT EXISTS, same migration idiom used for shopify_sessions'
# column growth (see shopify_flatten.py).
_ATTRIBUTION_COLUMN_MIGRATIONS = [
    "ALTER TABLE IF EXISTS shopify_order_attribution ADD COLUMN IF NOT EXISTS utm_term text",
    # The token each match fired on -- see AttributionResult.matched_value.
    "ALTER TABLE IF EXISTS shopify_order_attribution ADD COLUMN IF NOT EXISTS matched_value text",
]

_ATTRIBUTION_INSERT_COLUMNS = [
    "order_id", "name", "total_price", "created_at", "customer_id",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "tier", "matched_ad_id", "matched_ad_name", "matched_campaign_id", "matched_campaign_name",
    "matched_value", "flattened_at",
]

#: shopify_orders.utm_* (extracted from customAttributes -- the checkout-
#: captured UTM data, confirmed live 2026-08-26 to have 64% coverage) is
#: now the primary source, with customer_journey (customerJourneySummary,
#: ~5% coverage) as a per-field COALESCE fallback for the minority of
#: orders where customAttributes didn't carry a given value but
#: customerJourneySummary happened to. See shopify_flatten.py's
#: `_custom_attr` and scripts/ingest_shopify.py's module docstring "REAL
#: BUG FOUND AND FIXED" note for the full story -- this replaces a version
#: that read customer_journey exclusively, which is why order-level match
#: coverage was far lower than it should have been.
_ORDER_UTM_QUERY = """
SELECT
    order_id, name, total_price, created_at, customer_id,
    COALESCE(utm_source, customer_journey -> 'lastVisit' -> 'utmParameters' ->> 'source') AS utm_source,
    COALESCE(utm_medium, customer_journey -> 'lastVisit' -> 'utmParameters' ->> 'medium') AS utm_medium,
    COALESCE(utm_campaign, customer_journey -> 'lastVisit' -> 'utmParameters' ->> 'campaign') AS utm_campaign,
    COALESCE(utm_content, customer_journey -> 'lastVisit' -> 'utmParameters' ->> 'content') AS utm_content,
    COALESCE(utm_term, customer_journey -> 'lastVisit' -> 'utmParameters' ->> 'term') AS utm_term
FROM shopify_orders
WHERE order_id > :after
ORDER BY order_id
LIMIT :batch
"""

#: Rows per round trip. The unpaged version of this read -- one statement
#: for all 368,924 orders -- failed with asyncpg's
#: `ConnectionDoesNotExistError: connection was closed in the middle of
#: operation` on two of three runs on 2026-09-16, each time after
#: several minutes of streaming. It is the same shape of failure that
#: cost two whole Meta fetches in scripts/ingest_last_15_days.py: the
#: work succeeds and the transport dies under it. A single long-lived
#: read through the Supabase pooler is the fragile part, so this takes
#: many short ones instead.
_ORDER_BATCH = 25_000

#: A dropped connection leaves the session unusable until it is rolled
#: back; after that, the next execute checks out a fresh connection from
#: the pool. So a retry has to rollback first -- retrying on the dead
#: session just re-raises.
_ORDER_READ_ATTEMPTS = 5


async def _load_orders(session: AsyncSession) -> list:
    """Page through shopify_orders by keyset, retrying a dropped batch.

    Keyset (`order_id > :after`) rather than LIMIT/OFFSET: OFFSET makes
    Postgres walk and discard the skipped rows, so the last page of a
    368k-row table costs a full scan, and the cost grows with each page.

    Paging does mean the read is no longer one consistent snapshot -- an
    order written mid-run can land in a later page. That is acceptable
    here and nowhere near as bad as it sounds: this job TRUNCATEs and
    re-derives every order from scratch on every run, so a row that
    slips through one night is picked up whole the next.
    """
    orders: list = []
    after = ""
    while True:
        for attempt in range(1, _ORDER_READ_ATTEMPTS + 1):
            try:
                chunk = (
                    await session.execute(
                        text(_ORDER_UTM_QUERY), {"after": after, "batch": _ORDER_BATCH}
                    )
                ).fetchall()
                break
            except DBAPIError as exc:
                if attempt == _ORDER_READ_ATTEMPTS:
                    raise
                logger.warning(
                    "order_read_batch_failed",
                    after=after, attempt=attempt, error=str(exc)[:200],
                )
                await session.rollback()
                await asyncio.sleep(2 ** attempt)
        if not chunk:
            break
        orders.extend(chunk)
        after = chunk[-1].order_id
        logger.info("order_read_progress", loaded=len(orders))
    return orders

_ATTRIBUTION_INSERT = (
    f"INSERT INTO shopify_order_attribution ({', '.join(_ATTRIBUTION_INSERT_COLUMNS)}) "
    "VALUES (:order_id, :name, :total_price, :created_at, :customer_id, "
    ":utm_source, :utm_medium, :utm_campaign, :utm_content, :utm_term, "
    ":tier, :matched_ad_id, :matched_ad_name, :matched_campaign_id, :matched_campaign_name, "
    ":matched_value, now())"
)


async def _refresh_order_attribution(session: AsyncSession) -> int:
    universe = await _load_ad_universe(session)
    orders = await _load_orders(session)

    rows = []
    for o in orders:
        result = _attribute_order(o.utm_content, o.utm_term, o.utm_campaign, universe,
                                  order_id=o.order_id or "")
        rows.append({
            "order_id": o.order_id, "name": o.name, "total_price": o.total_price,
            "created_at": o.created_at, "customer_id": o.customer_id,
            "utm_source": o.utm_source, "utm_medium": o.utm_medium,
            "utm_campaign": o.utm_campaign, "utm_content": o.utm_content, "utm_term": o.utm_term,
            "tier": result.tier, "matched_ad_id": result.matched_ad_id,
            "matched_ad_name": result.matched_ad_name,
            "matched_value": result.matched_value,
            "matched_campaign_id": result.matched_campaign_id,
            "matched_campaign_name": result.matched_campaign_name,
        })

    await session.execute(text("TRUNCATE shopify_order_attribution"))
    if rows:
        await session.execute(text(_ATTRIBUTION_INSERT), rows)
    await session.commit()
    return len(rows)


# ----------------------------------------------------------------------
# shopify_landing_page_analysis -- unchanged from the prior pass, this
# project's own construction (no legacy script for it, see module docstring)
# ----------------------------------------------------------------------

_LANDING_PAGE_DDL = """
CREATE TABLE IF NOT EXISTS shopify_landing_page_analysis (
    day date,
    landing_page_path text,
    landing_page_type text,
    referrer_source text,
    matched_campaign_id text,
    matched_campaign_name text,
    sessions numeric,
    pageviews numeric,
    sessions_with_cart_additions numeric,
    sessions_that_reached_checkout numeric,
    sessions_that_completed_checkout numeric,
    added_to_cart_rate numeric,
    conversion_rate numeric,
    flattened_at timestamptz
)
"""

_LANDING_PAGE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_shopify_landing_page_analysis_day ON shopify_landing_page_analysis (day)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_landing_page_analysis_path ON shopify_landing_page_analysis (landing_page_path)",
    "CREATE INDEX IF NOT EXISTS ix_shopify_landing_page_analysis_campaign ON shopify_landing_page_analysis (matched_campaign_id)",
]

_LANDING_PAGE_INSERT_COLUMNS = [
    "day", "landing_page_path", "landing_page_type", "referrer_source",
    "matched_campaign_id", "matched_campaign_name",
    "sessions", "pageviews", "sessions_with_cart_additions",
    "sessions_that_reached_checkout", "sessions_that_completed_checkout",
    "added_to_cart_rate", "conversion_rate", "flattened_at",
]

# Rate columns (conversion_rate, added_to_cart_rate) are NOT summed or
# averaged from shopify_sessions' pre-computed per-row rates -- that would
# be mathematically wrong once multiple session rows (different
# utm_source/utm_medium) roll up into one output row. Recomputed from the
# SUMmed counts instead, which weights correctly by construction.
_LANDING_PAGE_INSERT = f"""
INSERT INTO shopify_landing_page_analysis ({", ".join(_LANDING_PAGE_INSERT_COLUMNS)})
SELECT
    s.day,
    s.landing_page_path,
    s.landing_page_type,
    s.referrer_source,
    c.campaign_id AS matched_campaign_id,
    c.campaign_name AS matched_campaign_name,
    SUM(s.sessions) AS sessions,
    SUM(s.pageviews) AS pageviews,
    SUM(s.sessions_with_cart_additions) AS sessions_with_cart_additions,
    SUM(s.sessions_that_reached_checkout) AS sessions_that_reached_checkout,
    SUM(s.sessions_that_completed_checkout) AS sessions_that_completed_checkout,
    CASE WHEN SUM(s.sessions) > 0 THEN SUM(s.sessions_with_cart_additions) / SUM(s.sessions) ELSE NULL END AS added_to_cart_rate,
    CASE WHEN SUM(s.sessions) > 0 THEN SUM(s.sessions_that_completed_checkout) / SUM(s.sessions) ELSE NULL END AS conversion_rate,
    now() AS flattened_at
FROM shopify_sessions s
LEFT JOIN meta_campaigns c ON c.campaign_id = s.utm_campaign
GROUP BY s.day, s.landing_page_path, s.landing_page_type, s.referrer_source, c.campaign_id, c.campaign_name
"""


#: Identical per-transaction tuning to app/services/silver/
#: shopify_flatten.py's _FLATTEN_SESSION_TUNING, and needed for the same
#: reason -- this module runs as the SECOND half of the same
#: silver_shopify step and never got it.
#:
#: What that cost, on run #9 (2026-09-04): the flatten finished, then
#: _LANDING_PAGE_INSERT died with "canceling statement due to statement
#: timeout" on the database's 120s default, failing the whole step after
#: 2019s of successful work. That INSERT groups ~1.37M shopify_sessions
#: rows on six keys into ~493k output rows -- 120s was never going to be
#: enough, and the 3.5MB default work_mem sends that aggregate to an
#: on-disk sort as well.
#:
#: SET LOCAL, not SET: Supabase's Supavisor pools in transaction mode, so
#: a session-level SET can land on a backend a later statement never
#: sees. Applied inside refresh_attribution_tables' own transactions.
_ATTRIBUTION_SESSION_TUNING = (
    "SET LOCAL statement_timeout = '1800s'",
    "SET LOCAL work_mem = '64MB'",
)


async def ensure_attribution_tables(session: AsyncSession) -> None:
    await session.execute(text(_ATTRIBUTION_DDL))
    await session.execute(text(_LANDING_PAGE_DDL))
    for statement in _ATTRIBUTION_COLUMN_MIGRATIONS:
        await session.execute(text(statement))
    for statement in _ATTRIBUTION_INDEXES + _LANDING_PAGE_INDEXES:
        await session.execute(text(statement))
    await session.commit()


async def refresh_attribution_tables(session: AsyncSession) -> dict[str, int]:
    """Rebuilds shopify_order_attribution (Python-side matching engine --
    see _attribute_order above, the token-subset/ratio-tiebreak logic it
    ports can't be expressed cleanly in SQL, same reason the legacy script
    itself is pure Python over in-memory indexes, not a SQL query) and
    shopify_landing_page_analysis (plain SQL rollup, unchanged)."""
    await ensure_attribution_tables(session)

    for statement in _ATTRIBUTION_SESSION_TUNING:
        await session.execute(text(statement))
    attribution_count = await _refresh_order_attribution(session)

    # TRUNCATE and INSERT stay in ONE transaction, so the run-#9 timeout
    # rolled both back and left the previous 493k rows intact rather than
    # an empty table. Keep them together; the tuning below just stops the
    # INSERT being cancelled in the first place.
    for statement in _ATTRIBUTION_SESSION_TUNING:
        await session.execute(text(statement))
    await session.execute(text("TRUNCATE shopify_landing_page_analysis"))
    await session.execute(text(_LANDING_PAGE_INSERT))
    await session.commit()
    landing_page_count = (
        await session.execute(text("SELECT COUNT(*) FROM shopify_landing_page_analysis"))
    ).scalar_one()

    counts = {
        "shopify_order_attribution": attribution_count,
        "shopify_landing_page_analysis": landing_page_count,
    }
    logger.info("shopify_ad_attribution_refreshed", **counts)
    return counts
