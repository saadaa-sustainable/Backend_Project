"""Gold layer: CPIS (Cost Per Item Sold) by master SKU -- ported from the
legacy Creative Testing Dashboard's `cpis_by_sku` / `fetch_cpis_by_sku.py`.

Researched from the legacy source directly (2026-08-27, both the git repo
script and the live `Meta_ads_data` Postgres functions -- no drift found
between them for this feature): legacy's own `cpis` column was NEVER
actually computed -- every write sets it to `None` with the code comment
"Cost Per Item Sold placeholder (formula pending)". What legacy actually
shipped instead was **cost_per_ncp** (ad spend / NCP count) and **ROAS**
per master SKU. This module computes both of those AND the literal CPIS
formula legacy left unfinished (spend / units sold) -- we can, because
this project's `shopify_inventory` already carries real per-SKU daily
`inventory_units_sold`, which legacy's title-level-only sales source
didn't have.

SKU hierarchy (from legacy, confirmed against real SKUs in this project's
own `shopify_inventory` data): variant SKU (`SDCPBL_L`) -> strip a
trailing `_<size>` suffix -> color SKU (`SDCPBL`) -> strip the last 2
chars (the color code) -> master SKU (`SDCP`), required to match
`^(SD|SM|SU)[A-Z]{1,4}$` (SD=women, SM=men, SU=unisex) and be >= 4 chars.
Ad -> master-SKU matching is a plain lowercase substring check of the
master SKU against the ad's name (legacy's own approach, confirmed live:
21 of 25 real ad names in this project match the master-SKU-prefix
pattern) -- guarded the same way legacy guards it, skipping any master
SKU shorter than 4 chars to avoid coincidental short-string matches.

Real gap this port can't paper over: legacy's spend came from
`primary_table`, which has one row per (ad, DAY) -- true daily grain, so
its 1d/7d/30d windows applied to spend too. This project's `ad_lifecycle`
is a single "as of last sync" snapshot per ad (see ad_lifecycle.py's own
caveat) -- there is no per-ad-per-day Insights time series here yet.
So: **units_sold is genuinely windowed** (1d/7d/30d, from
`shopify_inventory`'s real daily grain); **ad_spend/ncp_count are
lifetime totals** for whichever ads match a SKU, not window-scoped. Both
are labeled accordingly in the output rather than presented as
apples-to-apples. Color-level rollups (legacy's other `level` value)
aren't built this pass -- ad targeting is realistically at the master-SKU
grain, not full color+size, so a color-level ad-spend split would be
mostly guesswork; flagged as a known follow-up, not silently done.

Per user preference (2026-08-27): SKU parsing and ad-matching are real
branching logic -> done in Python, not a SQL regex chain.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

_SIZE_SUFFIX_RE = re.compile(r"_[A-Za-z0-9]+$")
_MASTER_SKU_RE = re.compile(r"^(SD|SM|SU)[A-Z]{1,4}$")

_WINDOWS: dict[str, int] = {"1d": 1, "7d": 7, "30d": 30}


def parse_master_sku(variant_sku: str | None) -> str | None:
    """variant SKU -> color SKU (strip trailing _<size>) -> master SKU
    (strip the 2-char color code), validated against the master-SKU
    pattern. Returns None for anything that doesn't parse cleanly."""
    if not variant_sku:
        return None
    color_sku = _SIZE_SUFFIX_RE.sub("", variant_sku)
    if len(color_sku) < 4:
        return None
    master_sku = color_sku[:-2]
    if len(master_sku) < 4 or not _MASTER_SKU_RE.match(master_sku):
        return None
    return master_sku


def match_ads_to_sku(master_sku: str, ad_names: dict[str, str]) -> list[str]:
    """Every ad_id whose ad_name contains `master_sku` (case-insensitive
    substring, legacy's own approach) -- guarded against short SKUs that
    would false-positive-match almost anything."""
    if len(master_sku) < 4:
        return []
    needle = master_sku.lower()
    return [ad_id for ad_id, name in ad_names.items() if name and needle in name.lower()]


@dataclass
class _SkuUnits:
    units_sold: int = 0
    ending_inventory_units: int = 0
    sell_through_samples: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sell_through_samples is None:
            self.sell_through_samples = []


_DDL = """
CREATE TABLE IF NOT EXISTS cpis_by_sku (
    master_sku text NOT NULL,
    window_key text NOT NULL,
    window_from date,
    window_to date,
    units_sold numeric,
    ending_inventory_units numeric,
    avg_sell_through_rate numeric,
    matched_ad_count integer,
    ad_spend numeric,
    ncp_count numeric,
    cost_per_ncp numeric,
    cost_per_unit_sold numeric,
    computed_at timestamptz,
    PRIMARY KEY (master_sku, window_key)
)
"""

_TRUNCATE = "TRUNCATE cpis_by_sku"

_INSERT = """
INSERT INTO cpis_by_sku (
    master_sku, window_key, window_from, window_to, units_sold, ending_inventory_units,
    avg_sell_through_rate, matched_ad_count, ad_spend, ncp_count, cost_per_ncp, cost_per_unit_sold, computed_at
) VALUES (
    :master_sku, :window_key, :window_from, :window_to, :units_sold, :ending_inventory_units,
    :avg_sell_through_rate, :matched_ad_count, :ad_spend, :ncp_count, :cost_per_ncp, :cost_per_unit_sold, now()
)
"""

COLUMN_FORMULAS: dict[str, str] = {
    "master_sku": "parsed from shopify_inventory.product_variant_sku: strip trailing _<size>, then strip the 2-char color code, validated against ^(SD|SM|SU)[A-Z]{1,4}$",
    "units_sold": "SUM(shopify_inventory.inventory_units_sold) for every variant SKU under this master, within window_from..window_to (genuinely windowed -- real daily grain)",
    "matched_ad_count": "COUNT of ad_lifecycle ads whose ad_name contains this master_sku (case-insensitive substring)",
    "ad_spend": "SUM(ad_lifecycle.spend) for matched ads -- LIFETIME total (as-of-last-sync), NOT windowed -- ad_lifecycle has no per-day grain yet",
    "ncp_count": "SUM(ad_lifecycle.ncp_count) for matched ads -- lifetime total, same caveat as ad_spend",
    "cost_per_ncp": "ad_spend / ncp_count -- the metric legacy actually shipped as CPIS's companion, per master SKU",
    "cost_per_unit_sold": "ad_spend / units_sold -- the literal 'Cost Per Item Sold' formula legacy's own cpis_by_sku.cpis column left unfinished (always written as None there); mixes a lifetime numerator with a windowed denominator, by necessity -- see module docstring",
}


async def ensure_cpis_table(session: AsyncSession) -> None:
    await session.execute(text(_DDL))
    await session.commit()


async def refresh_cpis_by_sku(session: AsyncSession) -> dict[str, int]:
    await ensure_cpis_table(session)

    ad_rows = (
        await session.execute(text("SELECT ad_id, ad_name, spend, ncp_count FROM ad_lifecycle WHERE ad_name IS NOT NULL"))
    ).mappings().all()
    ad_names = {r["ad_id"]: r["ad_name"] for r in ad_rows}
    ad_spend = {r["ad_id"]: float(r["spend"] or 0) for r in ad_rows}
    ad_ncp = {r["ad_id"]: float(r["ncp_count"] or 0) for r in ad_rows}

    inventory_rows = (
        await session.execute(
            text("SELECT day, product_variant_sku, inventory_units_sold, ending_inventory_units, sell_through_rate FROM shopify_inventory")
        )
    ).mappings().all()

    # Bucket raw inventory rows by master_sku once, keyed by day, so each
    # window (1d/7d/30d) below just filters this pre-parsed structure
    # instead of re-parsing every SKU per window.
    by_master_by_day: dict[str, dict[date, _SkuUnits]] = defaultdict(dict)
    master_skus: set[str] = set()
    for row in inventory_rows:
        master = parse_master_sku(row["product_variant_sku"])
        if master is None:
            continue
        master_skus.add(master)
        bucket = by_master_by_day[master].setdefault(row["day"], _SkuUnits())
        bucket.units_sold += int(row["inventory_units_sold"] or 0)
        bucket.ending_inventory_units += int(row["ending_inventory_units"] or 0)
        if row["sell_through_rate"] is not None:
            bucket.sell_through_samples.append(float(row["sell_through_rate"]))

    if not master_skus:
        logger.info("cpis_by_sku_refreshed", cpis_by_sku=0)
        await session.execute(text(_TRUNCATE))
        await session.commit()
        return {"cpis_by_sku": 0}

    today = max(d for days in by_master_by_day.values() for d in days) if by_master_by_day else date.today()

    ad_matches_by_master: dict[str, list[str]] = {
        master: match_ads_to_sku(master, ad_names) for master in master_skus
    }

    params: list[dict[str, object]] = []
    for master in sorted(master_skus):
        matched_ads = ad_matches_by_master[master]
        total_spend = sum(ad_spend.get(a, 0.0) for a in matched_ads)
        total_ncp = sum(ad_ncp.get(a, 0.0) for a in matched_ads)

        for window_key, n_days in _WINDOWS.items():
            window_from = today - timedelta(days=n_days - 1)
            days_in_window = [d for d in by_master_by_day[master] if window_from <= d <= today]
            units_sold = sum(by_master_by_day[master][d].units_sold for d in days_in_window)
            ending_units = by_master_by_day[master][max(days_in_window)].ending_inventory_units if days_in_window else 0
            samples = [s for d in days_in_window for s in by_master_by_day[master][d].sell_through_samples]
            avg_sell_through = sum(samples) / len(samples) if samples else None

            params.append({
                "master_sku": master,
                "window_key": window_key,
                "window_from": window_from,
                "window_to": today,
                "units_sold": units_sold,
                "ending_inventory_units": ending_units,
                "avg_sell_through_rate": avg_sell_through,
                "matched_ad_count": len(matched_ads),
                "ad_spend": round(total_spend, 2),
                "ncp_count": total_ncp,
                "cost_per_ncp": round(total_spend / total_ncp, 2) if total_ncp > 0 else None,
                "cost_per_unit_sold": round(total_spend / units_sold, 2) if units_sold > 0 else None,
            })

    await session.execute(text(_TRUNCATE))
    if params:
        await session.execute(text(_INSERT), params)
    await session.commit()

    logger.info("cpis_by_sku_refreshed", cpis_by_sku=len(params), distinct_master_skus=len(master_skus))
    return {"cpis_by_sku": len(params)}
