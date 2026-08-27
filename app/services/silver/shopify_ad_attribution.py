"""Maps Shopify data to Meta ads data -- order attribution and landing-page
analysis.

The order-attribution matching engine is a faithful PORT (not a from-scratch
reimplementation) of the legacy Creative Testing Dashboard's
`rebuild_attribution_orders.py::attribute_order()` -- re-cloned and read in
full (2026-08-26) rather than working from summary/memory. The name
normalization (`_norm_name`/`_sep_key`), the token-subset + ratio-tiebreak
scoped-match algorithm, the substring length guard (10 chars), and the
spend/name-length-gap tiebreak are all copied verbatim from that file's
real logic, not approximated.

What's DELIBERATELY not ported, because there's no equivalent data source
in this project (confirmed live before starting, not assumed):
- **T0 override ledger** (`ad_attribution_overrides`) -- no such table here.
- **Asset-id tier** (`ad_asset_ids`, from an external Google Sheet) -- no
  such data here.
- **`ad_name_history`** (rename tracking, so an ad's old names still match
  its current utm tags) -- this project's `meta_ads` only carries each
  ad's CURRENT name, no history.
- **Two independent candidates for name/adset/campaign** -- the legacy
  cascade tries `(attr_ad_name, utm_content)`, `(attr_adset_id, utm_term)`,
  etc., because their checkout template captured separate custom
  attributes (`Ad`, `Campaign`, `AdSetID`) IN ADDITION TO standard UTM
  params. This project's `shopify_orders.customer_journey` (Shopify's
  modern `customerJourneySummary` field) only has the standard UTM
  params -- one candidate each (`utm_content` for name, `utm_term` for
  adset, `utm_campaign` for campaign), not two. This is why order-level
  match coverage here is much lower than the legacy dashboard's (~5% of
  orders carry any UTM data at all here, confirmed live) -- a real data
  gap, not a matching-logic gap.

Two tables:
- `shopify_order_attribution` -- one row per Shopify order, ALWAYS (no
  silent drops -- unmatched orders get tier='unmatched', not omitted).
- `shopify_landing_page_analysis` -- shopify_sessions (already has
  landing_page_path + UTM + full conversion-funnel metrics, see
  shopify_flatten.py) rolled up and joined to meta_campaigns on
  utm_campaign. Unchanged from the prior pass -- the legacy repo has no
  equivalent script for this (it's this project's own construction from
  ShopifyQL session aggregates, not a port).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

# ----------------------------------------------------------------------
# Matching engine -- ported from rebuild_attribution_orders.py
# ----------------------------------------------------------------------

# Strips trailing "_copy"/"_copy 2"/"-h0"/"_c1" etc (repeatedly -- names can
# carry more than one suffix), collapses whitespace, lowercases. Verbatim
# from the legacy `norm_name()`.
_SUFFIX_RE = re.compile(r"(?:[\s_\-]+(?:copy(?:\s*\d+)?|[hc]\d+))+\s*$", re.IGNORECASE)
# Collapses +/-/_/. / space , into a single space -- the legacy `_sep_key()`,
# used for separator-tolerant substring/token matching (Meta ad names mix
# separators inconsistently across templates/accounts).
_SEP_RE = re.compile(r"[+\-_/.\s,]+")

SUBSTRING_MIN_LEN = 10
TOKEN_SUBSET_MIN_TOKENS = 3
TOKEN_SUBSET_MIN_DISTINCTIVE_LEN = 5
TOKEN_SUBSET_RATIO_THRESHOLD = 0.6
TOKEN_SUBSET_MARGIN = 0.15


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


def _sep_key(s: str | None) -> str:
    if not s:
        return ""
    return _SEP_RE.sub(" ", s).strip().lower()


@dataclass(frozen=True)
class AdMeta:
    ad_id: str
    ad_name: str
    adset_id: str | None
    campaign_id: str | None
    campaign_name: str | None
    spend: float


@dataclass
class AdUniverse:
    by_id: dict[str, AdMeta] = field(default_factory=dict)
    by_name: dict[str, list[AdMeta]] = field(default_factory=dict)      # exact lowercase ad_name
    by_fuzzy: dict[str, list[AdMeta]] = field(default_factory=dict)     # norm_name, indexed at build time
    name_index: list[tuple[str, str, int, AdMeta]] = field(default_factory=list)  # (lower, sep_key, len, ad)
    adset_ads: dict[str, list[AdMeta]] = field(default_factory=dict)
    campaign_id_ads: dict[str, list[AdMeta]] = field(default_factory=dict)


async def _load_ad_universe(session: AsyncSession) -> AdUniverse:
    result = await session.execute(
        text(
            "SELECT a.ad_id, a.ad_name, a.adset_id, a.campaign_id, a.campaign_name, COALESCE(al.spend, 0) AS spend "
            "FROM meta_ads a LEFT JOIN ad_lifecycle al ON al.ad_id = a.ad_id "
            "WHERE a.ad_name IS NOT NULL"
        )
    )
    universe = AdUniverse()
    for row in result:
        ad = AdMeta(
            ad_id=row.ad_id, ad_name=row.ad_name, adset_id=row.adset_id,
            campaign_id=row.campaign_id, campaign_name=row.campaign_name, spend=float(row.spend or 0),
        )
        universe.by_id[ad.ad_id] = ad
        universe.by_name.setdefault(ad.ad_name.lower(), []).append(ad)
        universe.by_fuzzy.setdefault(_norm_name(ad.ad_name), []).append(ad)
        universe.name_index.append((ad.ad_name.lower(), _sep_key(ad.ad_name), len(ad.ad_name), ad))
        if ad.adset_id:
            universe.adset_ads.setdefault(ad.adset_id, []).append(ad)
        if ad.campaign_id:
            universe.campaign_id_ads.setdefault(ad.campaign_id, []).append(ad)
    return universe


def _scoped_match(ads: list[AdMeta], name_cand: str) -> AdMeta | None:
    """Narrows a small ad set (one adset or one campaign) down to a single
    ad by name -- ported from `_scoped_match()`. Exact -> fuzzy -> raw
    substring -> separator-tolerant substring (no length guard here,
    unlike the global Step 2 match -- safe because the candidate set is
    already small, same as the legacy version) -> token-subset +
    ratio-tiebreak for the remaining ambiguous cases."""
    if not name_cand or not ads:
        return None
    nc_l = name_cand.lower()
    nc_norm = _norm_name(name_cand)
    nc_sep = _sep_key(name_cand)

    exact = [a for a in ads if a.ad_name.lower() == nc_l]
    if len(exact) == 1:
        return exact[0]
    fuzzy = [a for a in ads if _norm_name(a.ad_name) == nc_norm]
    if len(fuzzy) == 1:
        return fuzzy[0]
    sub_hits = [a for a in ads if a.ad_name.lower() in nc_l or nc_l in a.ad_name.lower()]
    if len(sub_hits) == 1:
        return sub_hits[0]
    sep_hits = [a for a in ads if _sep_key(a.ad_name) and (_sep_key(a.ad_name) in nc_sep or nc_sep in _sep_key(a.ad_name))]
    if len(sep_hits) == 1:
        return sep_hits[0]

    utm_tokens = [t for t in nc_sep.split() if t]
    if len(utm_tokens) >= TOKEN_SUBSET_MIN_TOKENS:
        distinctive = [t for t in utm_tokens if len(t) >= TOKEN_SUBSET_MIN_DISTINCTIVE_LEN and not t.isdigit()]
        if distinctive:
            utm_tok_set = set(utm_tokens)
            scored: list[tuple[float, AdMeta]] = []
            for a in ads:
                ad_tok_set = set(_sep_key(a.ad_name).split())
                if ad_tok_set and utm_tok_set.issubset(ad_tok_set):
                    scored.append((len(utm_tok_set) / len(ad_tok_set), a))
            if len(scored) == 1:
                return scored[0][1]
            if len(scored) >= 2:
                scored.sort(key=lambda t: -t[0])
                top_r, runner_r = scored[0][0], scored[1][0]
                if top_r >= TOKEN_SUBSET_RATIO_THRESHOLD and (top_r - runner_r) >= TOKEN_SUBSET_MARGIN:
                    return scored[0][1]
    return None


@dataclass
class AttributionResult:
    tier: str
    matched_ad_id: str | None
    matched_ad_name: str | None
    matched_campaign_id: str | None
    matched_campaign_name: str | None


_UNMATCHED = AttributionResult("unmatched", None, None, None, None)


def _attribute_order(utm_content: str, utm_term: str, utm_campaign: str, universe: AdUniverse) -> AttributionResult:
    """Port of `attribute_order()`'s Meta cascade, single-candidate version
    (see module docstring for why). Order matters -- first hit wins:
    Step 1 (direct id) -> Step 3-early (adset, only if it narrows -- takes
    priority over Step 2, same as the legacy cascade, so a user-tagged
    adset beats a same-named archived clone elsewhere in the account) ->
    Step 2 (global name match) -> Step 3-retry (adset known but never
    narrowed -> adset_only) -> Step 4 (campaign-scoped, narrowed or
    campaign_only) -> unmatched."""
    utm_content = (utm_content or "").strip()
    utm_term = (utm_term or "").strip()
    utm_campaign = (utm_campaign or "").strip()

    if utm_content.isdigit() and utm_content in universe.by_id:
        ad = universe.by_id[utm_content]
        return AttributionResult("ad_direct", ad.ad_id, ad.ad_name, ad.campaign_id, ad.campaign_name)

    adset_ads = universe.adset_ads.get(utm_term) if utm_term else None
    if adset_ads:
        matched = _scoped_match(adset_ads, utm_content)
        if matched:
            return AttributionResult("adset_scoped", matched.ad_id, matched.ad_name, matched.campaign_id, matched.campaign_name)

    if utm_content:
        nc_l = utm_content.lower()
        candidates = universe.by_name.get(nc_l)
        if candidates:
            ad = max(candidates, key=lambda a: a.spend)
            return AttributionResult("ad_name_match", ad.ad_id, ad.ad_name, ad.campaign_id, ad.campaign_name)
        nc_norm = _norm_name(utm_content)
        candidates = universe.by_fuzzy.get(nc_norm) if nc_norm else None
        if candidates:
            ad = max(candidates, key=lambda a: a.spend)
            return AttributionResult("ad_name_match", ad.ad_id, ad.ad_name, ad.campaign_id, ad.campaign_name)
        if len(nc_l) >= SUBSTRING_MIN_LEN:
            nc_sep = _sep_key(utm_content)
            best: AdMeta | None = None
            best_spend = -1.0
            best_gap = 10**9
            for name_lower, name_sep, name_len, ad in universe.name_index:
                hit = (
                    min(len(name_lower), len(nc_l)) >= SUBSTRING_MIN_LEN
                    and (name_lower in nc_l or nc_l in name_lower)
                ) or (
                    min(len(name_sep), len(nc_sep)) >= SUBSTRING_MIN_LEN
                    and (name_sep in nc_sep or nc_sep in name_sep)
                )
                if hit:
                    gap = abs(name_len - len(utm_content))
                    if (ad.spend > best_spend) or (ad.spend == best_spend and gap < best_gap):
                        best, best_spend, best_gap = ad, ad.spend, gap
            if best is not None:
                return AttributionResult("ad_name_match", best.ad_id, best.ad_name, best.campaign_id, best.campaign_name)

    if adset_ads:
        first = adset_ads[0]
        return AttributionResult("adset_only", None, None, first.campaign_id, first.campaign_name)

    campaign_ads = universe.campaign_id_ads.get(utm_campaign) if utm_campaign else None
    if campaign_ads:
        matched = _scoped_match(campaign_ads, utm_content)
        if matched:
            return AttributionResult("campaign_scoped", matched.ad_id, matched.ad_name, matched.campaign_id, matched.campaign_name)
        first = campaign_ads[0]
        return AttributionResult("campaign_only", None, None, first.campaign_id, first.campaign_name)

    return _UNMATCHED


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
]

_ATTRIBUTION_INSERT_COLUMNS = [
    "order_id", "name", "total_price", "created_at", "customer_id",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "tier", "matched_ad_id", "matched_ad_name", "matched_campaign_id", "matched_campaign_name",
    "flattened_at",
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
"""

_ATTRIBUTION_INSERT = (
    f"INSERT INTO shopify_order_attribution ({', '.join(_ATTRIBUTION_INSERT_COLUMNS)}) "
    "VALUES (:order_id, :name, :total_price, :created_at, :customer_id, "
    ":utm_source, :utm_medium, :utm_campaign, :utm_content, :utm_term, "
    ":tier, :matched_ad_id, :matched_ad_name, :matched_campaign_id, :matched_campaign_name, "
    "now())"
)


async def _refresh_order_attribution(session: AsyncSession) -> int:
    universe = await _load_ad_universe(session)
    orders = (await session.execute(text(_ORDER_UTM_QUERY))).fetchall()

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

    attribution_count = await _refresh_order_attribution(session)

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
