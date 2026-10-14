"""Read optional customer metrics without letting a timeout fail the ad page."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


CUSTOMER_MIX_TIMEOUT_MS = 3000
CustomerMix = dict[str, tuple[int, int, float, float]]

# Materialize the selected ads' order IDs before joining customer history.
# Classification, distinct-person counting, sales and IST dates stay unchanged.
CUSTOMER_MIX_DAILY = """
WITH matched_orders AS MATERIALIZED (
    SELECT order_id, matched_ad_id
    FROM public.shopify_order_attribution
    WHERE matched_ad_id = ANY(:ad_ids)
)
SELECT a.matched_ad_id,
       COUNT(*) FILTER (WHERE oct.is_new_customer),
       COUNT(DISTINCT oct.customer_id) FILTER (WHERE NOT oct.is_new_customer),
       COALESCE(SUM(oct.total_price) FILTER (WHERE oct.is_new_customer), 0),
       COALESCE(SUM(oct.total_price) FILTER (WHERE NOT oct.is_new_customer), 0)
FROM matched_orders a
JOIN public.order_customer_type oct ON oct.order_id = a.order_id
{date_where}
GROUP BY a.matched_ad_id
"""


async def query_ad_customer_mix(
    session: AsyncSession, ad_ids: list[str],
    from_date: date | None, to_date: date | None,
) -> CustomerMix:
    if not ad_ids:
        return {}
    params: dict[str, object] = {"ad_ids": ad_ids}
    date_where = ""
    if from_date and to_date:
        date_where = (
            "WHERE oct.order_day >= CAST(:from_str AS date) "
            "AND oct.order_day <= CAST(:to_str AS date)"
        )
        params.update(from_str=from_date, to_str=to_date)
    result = await session.execute(
        text(CUSTOMER_MIX_DAILY.format(date_where=date_where)), params,
    )
    return {
        aid: (int(nc or 0), int(rc or 0), float(ns or 0), float(rs or 0))
        for aid, nc, rc, ns, rs in result.all()
    }


async def read_ad_customer_mix(
    session: AsyncSession, ad_ids: list[str],
    from_date: date | None, to_date: date | None,
) -> CustomerMix | None:
    """None means unavailable; an empty dict means a successful zero-order read.

    PostgreSQL cancels just this optional query. Rolling back its savepoint
    restores the original timeout and lets the remaining page queries run in
    a healthy transaction. Other errors still propagate; there is no retry.
    """
    if not ad_ids:
        return {}
    try:
        async with session.begin_nested():
            previous_timeout = await session.scalar(text("SHOW statement_timeout"))
            await session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{CUSTOMER_MIX_TIMEOUT_MS}ms"},
            )
            result = await query_ad_customer_mix(session, ad_ids, from_date, to_date)
            await session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": previous_timeout},
            )
            return result
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if sqlstate != "57014":
            raise
        logging.getLogger(__name__).warning(
            "ads_customer_mix_timed_out", extra={"ad_count": len(ad_ids)},
        )
        return None
