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
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import unquote

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
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
    #: Historical ad names -> the ad that used to carry them. Meta writes
    #: the ad name into the UTM at CLICK time, so an ad renamed afterwards
    #: leaves every older order naming something that no longer exists.
    #: Populated from `ad_name_alias` (see refresh_ad_name_aliases.py);
    #: only unambiguous aliases are loaded, so resolving one identifies a
    #: single ad by id rather than guessing between two.
    alias_ads: dict[str, AdMeta] = field(default_factory=dict)
    alias_fuzzy: dict[str, AdMeta] = field(default_factory=dict)
    #: (utm_content lowered, adset_id or '*') -> the ad a PERSON says it
    #: is. From `ad_name_override`; see scripts/load_ad_name_overrides.py
    #: for why hand-supplied evidence gets its own table rather than
    #: being approximated by loosening a rule.
    overrides: dict[tuple[str, str], AdMeta] = field(default_factory=dict)


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
_CAMPAIGN_ROSTER_SQL = (
    "SELECT campaign_id, campaign_name FROM meta_campaigns WHERE campaign_id IS NOT NULL"
)


def _ad_names(ad: AdMeta) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n.strip() for n in (ad.ad_name, *ad.aliases) if n and n.strip()))


def _build_ad_universe(
    ads: Iterable[AdMeta], *,
    adsets: Iterable[tuple[str, str | None, str | None]] = (),
    campaigns: Iterable[tuple[str, str | None]] = (),
    aliases: Iterable[tuple[str, str]] = (),
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

    # Historical names last, and never over a live one: a name that some
    # ad answers to TODAY must resolve to that ad, not to whoever used to
    # be called it.
    for name, ad_id in aliases:
        ad = universe.by_id.get(ad_id)
        if ad is None or not name:
            continue
        if name not in universe.by_name:
            universe.alias_ads.setdefault(name, ad)
        norm = _norm_name(name)
        if norm and norm not in universe.by_fuzzy:
            universe.alias_fuzzy.setdefault(norm, ad)

    # A mapping naming an ad the universe does not hold is dropped here
    # rather than at load time: the override table outlives any single
    # roster refresh, and an ad missing today may be back tomorrow.
    for utm_content, adset_id, ad_id in overrides:
        ad = universe.by_id.get(ad_id)
        if ad is not None and utm_content:
            universe.overrides[(utm_content.lower(), adset_id or "*")] = ad
    return universe


#: Only unambiguous aliases: a name that has belonged to two ads cannot
#: identify one. The table keeps those rows so the refusal is auditable,
#: and this is where they are refused.
_AD_ALIAS_SQL = """
SELECT ad_name_lower, ad_id
  FROM public.ad_name_alias
 WHERE NOT ambiguous
"""


#: Hand-supplied mappings. Loaded whole -- there are tens of these, not
#: thousands, and each one is a deliberate human statement.
_AD_OVERRIDE_SQL = """
SELECT utm_content_lower, adset_id, ad_id
  FROM public.ad_name_override
"""


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
    try:
        aliases = [
            (row[0], row[1])
            for row in await session.execute(text(_AD_ALIAS_SQL))
        ]
    except (ProgrammingError, OperationalError):
        # The table is built by a separate script; attribution must still
        # run on an installation that has never run it.
        await session.rollback()
        logger.warning("ad_name_alias_unavailable")
        aliases = []
    try:
        overrides = [
            (row[0], row[1], row[2])
            for row in await session.execute(text(_AD_OVERRIDE_SQL))
        ]
    except (ProgrammingError, OperationalError):
        await session.rollback()
        logger.warning("ad_name_override_unavailable")
        overrides = []
    return _build_ad_universe(
        ads, adsets=adsets, campaigns=campaigns, aliases=aliases, overrides=overrides,
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


def _override_match(
    utm_content: str, utm_term: str, universe: AdUniverse,
) -> AdMeta | None:
    """A hand-supplied mapping for this utm_content, if one applies.

    An ad-set-scoped mapping is tried before an account-wide one: it was
    written precisely because the name means different things in
    different ad sets, so it must win where both could apply.
    """
    if not universe.overrides or not utm_content:
        return None
    adset_ids = [
        value for value in _value_candidates(utm_term)
        if value in universe.adset_ads or value in universe.roster_adsets
    ]
    for candidate in _value_candidates(utm_content):
        key = candidate.lower()
        for adset_id in adset_ids:
            ad = universe.overrides.get((key, adset_id))
            if ad is not None:
                return ad
        ad = universe.overrides.get((key, "*"))
        if ad is not None:
            return ad
    return None


def _alias_match(value: str, universe: AdUniverse) -> AdMeta | None:
    """Resolve a name the ad universe no longer knows, via rename history.

    Exact spelling first, then the same normalisation live matching uses
    (so a " - Copy" / " – Copy" difference does not defeat it). Only
    unambiguous aliases are in the index, so a hit is one ad.
    """
    for candidate in _value_candidates(value):
        ad = universe.alias_ads.get(candidate.lower())
        if ad is not None:
            return ad
    for candidate in _value_candidates(value):
        norm = _norm_name(candidate)
        if norm:
            ad = universe.alias_fuzzy.get(norm)
            if ad is not None:
                return ad
    return None


def _attribute_order(
    utm_content: str, utm_term: str, utm_campaign: str, universe: AdUniverse,
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

    # A person's mapping outranks every inference below it, but not an
    # explicit ad id above it: the id is already unambiguous, so there is
    # nothing for a human to correct there.
    override = _override_match(utm_content, utm_term, universe)
    if override is not None:
        return matched("manual_map", override)

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
        # Nothing in the ad set answers to that name TODAY. Before
        # giving up, ask whether anything in it used to: Meta stamps the
        # name into the UTM at click time, so a rename since the click
        # leaves the order naming an ad that no longer exists under that
        # name. An alias names one ad id outright, so confirming it sits
        # in this very ad set is corroboration, not a guess.
        renamed = _alias_match(utm_content, universe)
        if renamed is not None and renamed.adset_id == adset_id:
            return matched("adset_renamed", renamed)
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
    if ad:
        return matched("ad_name_match", ad)
    # No parent evidence at all and no live name. A historical name is
    # still an identification rather than a guess -- it came from a
    # recorded rename of a specific ad id -- so it is taken, under its
    # own tier so it stays countable separately.
    renamed = _alias_match(utm_content, universe) if utm_content else None
    return matched("ad_renamed", renamed) if renamed else _UNMATCHED


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
        result = _attribute_order(o.utm_content, o.utm_term, o.utm_campaign, universe)
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
