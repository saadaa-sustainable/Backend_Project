"""Business examples and population invariants for daily revenue-share CPIS."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.gold.cpis_value_weighted import ProductLine, allocate_daily

DAY = date(2026, 10, 21)
NEXT = date(2026, 10, 22)


def line(sku, qty, revenue, *, order="o1", ad="a", adset="s", day=DAY):
    return ProductLine(day, order, ad, adset, sku, qty, D(str(revenue)))


def test_requested_ten_thousand_spend_example():
    rows = allocate_daily([line("X", 10, 10000), line("Y", 5, 3500)],
                          {(DAY, "ad:a"): D(10000)})
    x, y = rows
    assert x["ad_spend"].quantize(D(".01")) == D("7407.41")
    assert y["ad_spend"].quantize(D(".01")) == D("2592.59")
    assert (x["ad_spend"] / x["attributed_units"]).quantize(D(".01")) == D("740.74")
    assert (y["ad_spend"] / y["attributed_units"]).quantize(D(".01")) == D("518.52")
    assert abs(sum(r["ad_spend"] for r in rows) - D(10000)) < D("1e-20")


def test_weights_follow_revenue_across_orders_not_equal_order_counts():
    rows = allocate_daily([line("X", 10, 10000, order="large"),
                           line("Y", 5, 3500, order="small")],
                          {(DAY, "ad:a"): D(10000)})
    assert rows[0]["ad_spend"].quantize(D(".01")) == D("7407.41")
    assert rows[0]["ad_spend"] != D(5000)
    assert rows[0]["entity_orders"] == 2


def test_days_and_entities_never_share_denominators():
    rows = allocate_daily([
        line("X", 1, 100), line("Y", 1, 100, day=NEXT),
        line("Y", 1, 100, order="o2", ad="b", adset="t"),
    ], {(DAY, "ad:a"): D(100), (NEXT, "ad:a"): D(900), (DAY, "ad:b"): D(30)})
    assert sum(r["ad_spend"] for r in rows if r["master_sku"] == "X") == D(100)
    assert sum(r["ad_spend"] for r in rows if r["master_sku"] == "Y") == D(930)
    whole = rows
    split = allocate_daily([line("X", 1, 100), line("Y", 1, 100, order="o2", ad="b", adset="t")],
                           {(DAY, "ad:a"): D(100), (DAY, "ad:b"): D(30)})
    split += allocate_daily([line("Y", 1, 100, day=NEXT)], {(NEXT, "ad:a"): D(900)})
    assert whole == split


def test_adset_fallback_is_per_day_and_replaces_child_spend():
    rows = allocate_daily([
        line("X", 10, 10000), line("Y", 5, 3500, order="o2", ad=None),
        line("X", 1, 100, day=NEXT),
    ], {(DAY, "ad:a"): D(8000), (DAY, "adset:s"): D(10000),
        (NEXT, "ad:a"): D(200), (NEXT, "adset:s"): D(900)})
    today = [r for r in rows if r["day"] == DAY]
    assert {r["entity_id"] for r in today} == {"adset:s"}
    assert abs(sum(r["ad_spend"] for r in today) - D(10000)) < D("1e-20")
    assert rows[-1]["entity_id"] == "ad:a"
    assert rows[-1]["ad_spend"] == D(200)


def test_variants_collapse_to_one_sku_order_without_duplicating_baskets():
    rows = allocate_daily([line("X", 2, 200), line("X", 3, 300), line("Y", 1, 100)],
                          {(DAY, "ad:a"): D(120)})
    x, y = rows
    assert x["attributed_orders"] == x["entity_orders"] == 1
    assert x["attributed_units"] == 5
    assert x["attributed_revenue"] == 500
    assert x["order_revenue"] == y["order_revenue"] == 600
    assert x["ad_spend"] == 100
    assert x["halo_units"] == 1
    assert x["halo_orders"] == 1


def test_zero_revenue_spend_is_unallocated_and_free_items_get_no_share():
    rows = allocate_daily([line("X", 2, 0), line("Y", 1, 0)], {(DAY, "ad:a"): D(100)})
    assert sum(r["ad_spend"] for r in rows) == 0
    rows = allocate_daily([line("X", 2, 0), line("Y", 1, 100)], {(DAY, "ad:a"): D(100)})
    assert [r["ad_spend"] for r in rows] == [0, 100]


def test_unmapped_orders_and_non_selling_lines_do_not_dilute_weights():
    rows = allocate_daily([line("X", 1, 100), line("Y", 1, 900, ad=None, adset=None),
                           line("Y", 0, 1000), line("Y", -1, -100)],
                          {(DAY, "ad:a"): D(50)})
    assert len(rows) == 1
    assert rows[0]["ad_spend"] == 50


def test_no_spend_day_preserves_real_sales_without_borrowing_another_days_spend():
    rows = allocate_daily([line("X", 10, 1000)], {(NEXT, "ad:a"): D(500)})
    assert rows[0]["ad_spend"] == 0
    assert rows[0]["attributed_units"] == 10


@pytest.mark.parametrize("custom", [False, True])
async def test_api_uses_same_daily_source_for_preset_custom_sort_filters_and_totals(custom):
    from app.api.routers import analytics
    analytics.get_cpis_utm.analytics_cache.entries.clear()
    payload = {key: None for key in analytics.CpisUtmRow.model_fields}
    payload.update(master_sku="SDCP", window_key="30d", window_from=DAY, window_to=NEXT,
                   attributed_orders=1, attributed_units=10, attributed_revenue=10000,
                   ad_spend=7407.4074, ad_spend_vw=7407.4074,
                   cost_per_unit_sold=740.74074, cost_per_unit_sold_vw=740.74074,
                   contribution_margin=800)
    main = MagicMock()
    main.__iter__.return_value = iter([SimpleNamespace(_mapping=payload)])
    count = MagicMock()
    count.scalar_one.return_value = 1
    totals = MagicMock()
    totals.mappings.return_value.one.return_value = dict(
        attributed_spend=10000, attributed_orders_distinct=1,
        meta_total_spend=11000, spend_through=NEXT)
    bounds = MagicMock()
    bounds.first.return_value = (DAY, NEXT)
    results = ([bounds] if not custom else []) + [main, count, totals]
    session = SimpleNamespace(execute=AsyncMock(side_effect=results))
    response = await analytics.get_cpis_utm(
        session, attribution_mode="value_weighted", only_matched=True, search="SDCP",
        sort="cost_per_unit_sold", limit=1, offset=3,
        **({"from_date": DAY, "to_date": NEXT} if custom else {}),
    )
    assert response.attribution_mode == "value_weighted"
    assert response.rows[0].cost_per_unit_sold_vw == pytest.approx(740.74074)
    assert response.rows[0].acos_vw == pytest.approx(74.074074)
    assert response.rows[0].headroom_vw == pytest.approx(59.25926)
    assert response.attributed_spend == 10000
    assert response.untethered_spend == 1000
    calls = session.execute.call_args_list[-3:]
    for call in calls[:2]:
        sql, params = call.args
        assert "public.cpis_value_weighted_daily" in str(sql)
        assert params["from_date"] == DAY and params["to_date"] == NEXT
        assert params["search"] == "%SDCP%"
        assert "COALESCE(c.attributed_orders, 0) > 0" in str(sql)
    sql = str(calls[0].args[0])
    assert "ORDER BY c.cost_per_unit_sold DESC" in sql
    assert "LIMIT :limit OFFSET :offset" in sql
    assert "SUM(ad_spend) / NULLIF(SUM(attributed_units), 0)" in sql
    assert "AVG(" not in sql.split("page AS (")[0]
    assert "search" not in calls[-1].args[1]  # portfolio totals ignore pagination/search
    # Parse the composed Postgres query, including all existing enrichment joins.
    pglast = pytest.importorskip("pglast")
    from sqlalchemy.dialects.postgresql import asyncpg
    pglast.parse_sql(str(calls[0].args[0].compile(dialect=asyncpg.dialect())))

