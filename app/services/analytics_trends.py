"""Read CPIS spend trends for a page of SKUs in one aggregation.

These are name-matched ad spend series, like the original single-SKU
endpoint. An ad matching two requested SKUs contributes its full spend to
both. Missing delivery dates stay absent from the series for compatibility.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_TREND_SKUS = 100
_SKU_PATTERN = re.compile(r"[A-Za-z0-9_\-./]+")
_WINDOWS = {"7d", "30d", "90d"}


class SpendTrendWindowNotFound(LookupError):
    """The requested preset has no published CPIS window yet."""


_BOUNDS_SQL = text("""
SELECT window_from AS lo, window_to AS hi
FROM cpis_by_sku_utm
WHERE window_key = :window
LIMIT 1
""")

_TRENDS_SQL = text("""
WITH requested AS (
    SELECT master_sku, pattern, ordinal
    FROM unnest(CAST(:master_skus AS text[]), CAST(:patterns AS text[]))
         WITH ORDINALITY AS r(master_sku, pattern, ordinal)
),
matched_ads AS (
    SELECT r.master_sku, al.ad_id
    FROM requested r
    JOIN ad_lifecycle al ON al.ad_name ~* r.pattern
),
daily AS (
    SELECT m.master_sku, d.day, SUM(d.spend) AS spend
    FROM public.insights_daily_by_ad d
    JOIN matched_ads m ON m.ad_id = d.ad_id
    WHERE d.day BETWEEN :prev_lo AND :hi
    GROUP BY m.master_sku, d.day
)
SELECT r.master_sku,
       COALESCE(
           jsonb_agg(d.spend::float8 ORDER BY d.day)
               FILTER (WHERE d.day BETWEEN :lo AND :hi),
           '[]'::jsonb
       ) AS current_series,
       COALESCE(SUM(d.spend) FILTER (WHERE d.day < :lo), 0)::float8 AS prev_total
FROM requested r
LEFT JOIN daily d ON d.master_sku = r.master_sku
GROUP BY r.master_sku, r.ordinal
ORDER BY r.ordinal
""")


async def get_cpis_spend_trends(
    session: AsyncSession,
    master_skus: Sequence[str],
    *,
    window: str = "30d",
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, object]]:
    """Return existing trend response rows with one daily-data query.

    Presets use the published CPIS bounds; explicit dates use exactly that
    inclusive range. Invalid inputs raise ValueError before any query.
    Missing preset bounds raise SpendTrendWindowNotFound.
    """
    if isinstance(master_skus, (str, bytes)) or not 1 <= len(master_skus) <= MAX_TREND_SKUS:
        raise ValueError(f"Provide between 1 and {MAX_TREND_SKUS} master_skus")
    if any(not isinstance(sku, str) or not _SKU_PATTERN.fullmatch(sku) for sku in master_skus):
        raise ValueError("Invalid master_sku")
    if window not in _WINDOWS:
        raise ValueError("window must be one of 7d, 30d, 90d")
    if (from_date is None) != (to_date is None):
        raise ValueError("from_date and to_date must be provided together")
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must not be after to_date")

    skus = list(dict.fromkeys(master_skus))
    if from_date is not None and to_date is not None:
        lo, hi = from_date, to_date
    else:
        bounds = (await session.execute(_BOUNDS_SQL, {"window": window})).mappings().first()
        if bounds is None or bounds["lo"] is None or bounds["hi"] is None:
            raise SpendTrendWindowNotFound(
                "Window not found in cpis_by_sku_utm; run refresh_cpis_utm.py first."
            )
        lo, hi = bounds["lo"], bounds["hi"]
    if lo > hi:
        raise ValueError("Window start must not be after window end")
    try:
        prev_lo = lo - timedelta(days=(hi - lo).days + 1)
    except OverflowError as exc:
        raise ValueError("Window starts too early to calculate the previous period") from exc

    result = await session.execute(
        _TRENDS_SQL,
        {
            "master_skus": skus,
            "patterns": [r"\y" + re.escape(sku) + r"\y" for sku in skus],
            "lo": lo,
            "hi": hi,
            "prev_lo": prev_lo,
        },
    )
    rows = []
    for row in result.mappings():
        raw = row["current_series"]
        series = json.loads(raw) if isinstance(raw, str) else (raw or [])
        rows.append({
            "master_sku": row["master_sku"],
            "window_key": window,
            "window_from": lo,
            "window_to": hi,
            "spend_trend_current": [float(value or 0) for value in series],
            "spend_trend_prev_total": float(row["prev_total"] or 0),
        })
    return rows
