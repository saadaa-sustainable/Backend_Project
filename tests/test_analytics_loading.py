"""Exercise composed analytics queries and response decoding with fake sessions."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects.postgresql import asyncpg

from app.api.routers import analytics


@pytest.fixture(autouse=True)
def clear_analytics_caches():
    caches = [
        getattr(analytics, name).analytics_cache
        for name in ("get_creative_testing", "get_ads_analyse", "_daily_mirror_ready",
                     "_get_cpis_reconciliation")
    ]
    for cache in caches:
        cache.entries.clear()
    yield
    for cache in caches:
        cache.entries.clear()


def _mapped_result(value: dict) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.one.return_value = value
    return result


def _creative_payload(*, empty_page: bool = False) -> dict:
    row = {name: None for name in analytics.CreativeTestingRow.model_fields}
    row.update(
        asset_id="CPL001-0123", kind="new", iteration_count=2, ads=3,
        copy_ads=1, ads_in_window=2, asset_created="2026-09-01", spend=100,
    )
    totals = {name: 0 for name in analytics.CreativeTestingTotals.model_fields}
    totals.update(assets=42, new_creatives=30, iterations=12, spend=10000,
                  roas=2.5, cost_per_ncp=None, cost_per_ftewv=None)
    return {
        "rows": [] if empty_page else [row], "totals": totals,
        "category_counts": {"Winner": 20, "Discarded": 22},
        "kind_counts": {"new": 30},
    }


def _parsed_statement(query):
    pglast = pytest.importorskip("pglast")
    compiled = query.compile(dialect=asyncpg.dialect())
    statements = pglast.parse_sql(str(compiled))
    assert len(statements) == 1
    return statements[0].stmt, compiled


def _panel_queries(statement):
    from pglast import ast

    panels = {}
    for target in statement.targetList:
        expression = target.val
        if isinstance(expression, ast.CoalesceExpr):
            expression = expression.args[0]
        source = expression.subselect.fromClause[0]
        # Outbound ad links are joined after the asset page is selected.
        while isinstance(source, ast.JoinExpr):
            source = source.larg
        panels[target.name] = source.subquery
    return panels


def _where_parameters(query, compiled) -> set[str]:
    from pglast.visitors import Visitor

    names = set()

    class Parameters(Visitor):
        def visit_ParamRef(self, ancestors, node):
            names.add(compiled.positiontup[node.number - 1])

    Parameters()(query.whereClause)
    return names


@pytest.mark.parametrize("sort", list(analytics._CT_SORT_COLUMNS))
@pytest.mark.parametrize(("kind", "category", "extra_filters"), [
    (None, None, False),
    ("new", "Winner", True),
    ("iteration", "Discarded", True),
    (None, "P0 analysis", True),
])
async def test_creative_testing_uses_one_materialized_rollup_with_distinct_panel_scopes(
    sort: str, kind: str | None, category: str | None, extra_filters: bool,
) -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_mapped_result(_creative_payload())))
    kwargs = {"media": "video", "account_name": "Main", "search": "CPL"} if extra_filters else {}
    response = await analytics.get_creative_testing(
        session, from_date=date(2026, 9, 1), to_date=date(2026, 9, 15),
        kind=kind, category=category, sort=sort, limit=1, offset=10, **kwargs,
    )

    session.execute.assert_awaited_once()
    query, params = session.execute.call_args.args
    statement, compiled = _parsed_statement(query)
    from pglast.enums import CTEMaterialize

    aggregate = next(cte for cte in statement.withClause.ctes if cte.ctename == "agg")
    assert aggregate.ctematerialized == CTEMaterialize.CTEMaterializeAlways
    assert str(query).count("FROM public.ad_asset_map m") == 1
    panels = _panel_queries(statement)
    base = {"media", "account_name", "search"} if extra_filters else set()
    kind_parameters = {"from_date", "to_date"} if kind else set()
    category_parameters = {"category"} if category else set()
    assert _where_parameters(panels["rows"], compiled) == base | kind_parameters | category_parameters
    assert _where_parameters(panels["totals"], compiled) == base | kind_parameters | category_parameters
    assert _where_parameters(panels["category_counts"], compiled) == base | kind_parameters
    # The existing kind tabs ignore both the selected kind and category.
    assert _where_parameters(panels["kind_counts"], compiled) == base
    assert panels["rows"].limitCount is not None
    assert panels["rows"].limitOffset is not None
    assert panels["totals"].limitCount is None
    assert len(panels["rows"].sortClause) == 2  # Metric plus stable asset_id tie-break.
    assert params["limit"] == 1 and params["offset"] == 10
    assert response.total == response.totals.assets == 42
    assert len(response.rows) == 1
    assert response.totals.spend == 10000


@pytest.mark.parametrize("as_text", [False, True])
@pytest.mark.parametrize("empty_page", [False, True])
async def test_creative_testing_decodes_json_and_defaults_without_losing_empty_page_totals(
    as_text: bool, empty_page: bool,
) -> None:
    payload = _creative_payload(empty_page=empty_page)
    if as_text:
        payload = {name: json.dumps(value) for name, value in payload.items()}
    session = SimpleNamespace(execute=AsyncMock(return_value=_mapped_result(payload)))

    # Call the decorated endpoint directly: omitted Query defaults must
    # become plain Python values before query construction and cache keys.
    response = await analytics.get_creative_testing(
        session, from_date=date(2026, 9, 1), to_date=date(2026, 9, 15),
    )

    session.execute.assert_awaited_once()
    params = session.execute.call_args.args[1]
    assert params == {"from_date": date(2026, 9, 1), "to_date": date(2026, 9, 15),
                      "limit": 2000, "offset": 0}
    assert response.total == 42
    assert response.kind_counts == {"new": 30, "iteration": 0}
    assert response.category_counts == {"Winner": 20, "Discarded": 22}
    assert response.totals.cost_per_ncp is None
    if empty_page:
        assert response.rows == []
    else:
        assert response.rows[0].asset_created == date(2026, 9, 1)


@pytest.mark.parametrize("preview_fields", [
    {},
    {"preview_url": None, "thumbnail_url": None},
    {"preview_url": "https://drive.google.com/file/d/asset-123/view?resourcekey=key",
     "thumbnail_url": "https://example.com/thumbnail.jpg"},
])
async def test_creative_testing_returns_preview_links_without_additional_requests(
    preview_fields: dict[str, str | None],
) -> None:
    payload = _creative_payload()
    row = payload["rows"][0]
    row.pop("preview_url")
    row.pop("thumbnail_url")
    row.update(preview_fields)
    session = SimpleNamespace(execute=AsyncMock(return_value=_mapped_result(payload)))

    response = await analytics.get_creative_testing(
        session, from_date=date(2026, 9, 1), to_date=date(2026, 9, 15),
    )

    session.execute.assert_awaited_once()
    assert response.rows[0].preview_url == preview_fields.get("preview_url")
    assert response.rows[0].thumbnail_url == preview_fields.get("thumbnail_url")
    assert response.rows[0].spend == 100
    assert response.total == 42


@pytest.mark.parametrize("ad_fields", [
    {},
    {"ad_preview_url": None, "destination_url": None, "preview_ad_id": None},
    {"ad_preview_url": "https://www.instagram.com/p/ad-preview/",
     "destination_url": "https://saadaa.in/products/cotton-pants?utm_content=ad-123",
     "preview_ad_id": "123"},
])
async def test_creative_testing_ad_links_keep_asset_preview_and_metrics(ad_fields: dict) -> None:
    payload = _creative_payload()
    row = payload["rows"][0]
    for field in ("ad_preview_url", "destination_url", "preview_ad_id"):
        row.pop(field)
    row.update(ad_fields, preview_url="https://drive.google.com/file/d/source/view")
    session = SimpleNamespace(execute=AsyncMock(return_value=_mapped_result(payload)))

    response = await analytics.get_creative_testing(
        session, from_date=date(2026, 9, 1), to_date=date(2026, 9, 15), limit=50,
    )

    session.execute.assert_awaited_once()
    actual = response.rows[0]
    for field in ("ad_preview_url", "destination_url", "preview_ad_id"):
        assert getattr(actual, field) == ad_fields.get(field)
    assert actual.preview_url == "https://drive.google.com/file/d/source/view"
    assert actual.spend == 100
    assert actual.ads == 3
    assert response.totals.spend == 10000
    assert response.total == 42

    query, _ = session.execute.call_args.args
    statement, _ = _parsed_statement(query)
    panels = _panel_queries(statement)
    from pglast import ast
    from pglast.stream import RawStream

    # Unique ad_id joins only enrich the selected asset page, so neither
    # aggregate metrics nor filter-specific category/totals populations change.
    rows_expression = statement.targetList[0].val.args[0].subselect
    media_join = rows_expression.fromClause[0]
    assert isinstance(media_join, ast.JoinExpr)
    assert media_join.rarg.relname == "ad_media"
    assert media_join.larg.rarg.relname == "ad_thumbnails"
    assert panels["rows"].limitCount is not None
    assert panels["rows"].limitOffset is not None
    for panel in ("totals", "kind_counts", "category_counts"):
        assert "ad_thumbnails" not in RawStream()(panels[panel])
        assert "ad_media" not in RawStream()(panels[panel])
    aggregate = next(cte for cte in statement.withClause.ctes if cte.ctename == "agg")
    representative = next(target for target in aggregate.ctequery.targetList
                          if target.name == "preview_ad_id")
    assert "array_agg(m.ad_id ORDER BY m.spend DESC NULLS LAST, m.ad_id)" in RawStream()(representative)


@pytest.mark.parametrize("ad_fields", [
    {},
    {"ad_preview_url": None, "destination_url": None},
    {"ad_preview_url": "https://www.facebook.com/123/posts/456",
     "destination_url": "https://saadaa.in/products/test?utm_content=456"},
])
async def test_creative_testing_drilldown_exposes_links_for_each_ad(ad_fields: dict) -> None:
    row = {name: None for name in analytics.CreativeTestingAdRow.model_fields}
    row.update(ad_id="456", ad_name="test - Copy", is_copy=True,
               iteration_index=1, spend=42, ad_created_date=date(2026, 9, 1))
    row.pop("ad_preview_url")
    row.pop("destination_url")
    row.update(ad_fields)
    rows_result = MagicMock()
    rows_result.__iter__.return_value = iter([SimpleNamespace(_mapping=row)])
    media_result = MagicMock()
    media_result.scalar.return_value = "video"
    session = SimpleNamespace(execute=AsyncMock(side_effect=[rows_result, media_result]))

    response = await analytics.get_creative_testing_ads(session, "asset-123")

    assert session.execute.await_count == 2
    assert response.media == "video"
    assert len(response.ads) == 1
    assert response.ads[0].ad_preview_url == ad_fields.get("ad_preview_url")
    assert response.ads[0].destination_url == ad_fields.get("destination_url")
    assert response.ads[0].spend == 42
    assert response.ads[0].iteration_index == 1
    query, params = session.execute.call_args_list[0].args
    assert str(query) == analytics._CT_ADS_SQL
    assert params == {"asset_id": "asset-123"}
    _parsed_statement(query)


@pytest.mark.parametrize("custom", [False, True])
async def test_cpis_reconciliation_executes_exact_combined_sql_with_indexable_dates(custom: bool) -> None:
    data = {"ad_unknown": 10, "no_conversion": 20, "meta_total_spend": 100, "attributed_spend": 50}
    session = SimpleNamespace(execute=AsyncMock(return_value=_mapped_result(data)))
    result = await analytics._get_cpis_reconciliation(
        session, date(2026, 9, 1), date(2026, 9, 15), "30d", custom,
    )
    session.execute.assert_awaited_once()
    query, params = session.execute.call_args.args
    assert str(query) == analytics._cpis_reconciliation_sql(custom)
    statement, _ = _parsed_statement(query)
    assert statement.withClause.ctes[0].ctename == "breakdown"
    sql = " ".join(str(query).split())
    assert sql.count("FROM shopify_orders so") == 1
    assert "orders_in_window AS MATERIALIZED" in sql
    assert "WHERE so.processed_at >= CAST(:wf AS date)" in sql
    assert "AND so.processed_at < CAST(:wt AS date) + integer '1'" in sql
    assert "WHERE so.processed_at::date" not in sql
    assert "WHERE day BETWEEN :wf AND :wt" in sql
    if custom:
        assert "FROM cpis_by_sku_daily WHERE day BETWEEN :wf AND :wt" in sql
        assert "FROM cpis_by_sku_utm" not in sql
    else:
        assert "FROM cpis_by_sku_utm WHERE window_key = :window" in sql
        assert "FROM cpis_by_sku_daily" not in sql
    assert params == {"wf": date(2026, 9, 1), "wt": date(2026, 9, 15), "window": "30d"}
    assert result == data


@pytest.mark.parametrize(("shopify_orders", "shopify_revenue"), [(None, None), (0, 0), (2, 200)])
async def test_delivery_overlay_awaits_daily_query_and_preserves_unknown_shopify_metrics(
    shopify_orders: int | None, shopify_revenue: int | None,
) -> None:
    lifetime = {name: None for name in analytics.AdsAnalyseRow.model_fields}
    lifetime.update(ad_id="123", spend=99999, impressions=88888, shopify_orders=999,
                    shopify_revenue=99999, shopify_roas=999, atc_count=555, ci_count=333)
    rows_result = MagicMock()
    rows_result.__iter__.return_value = iter([SimpleNamespace(_mapping=lifetime)])
    daily_result = MagicMock()
    daily_result.all.return_value = [
        ("123", 100, 1000, 500, 300, 5, 20, 2, 10, shopify_orders, shopify_revenue),
    ]
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    categories_result = MagicMock()
    categories_result.__iter__.return_value = iter([("Winner", 1)])
    totals_data = {name: 0 for name in analytics.AdsAnalyseTotals.model_fields}
    totals_data.update(ad_count=1, spend=100, impressions=1000, reach=500, conv_value=300,
                       shopify_orders=shopify_orders, shopify_revenue=shopify_revenue)
    totals_result = MagicMock()
    totals_result.one.return_value = SimpleNamespace(**totals_data)
    exists_result = MagicMock()
    exists_result.first.return_value = (1,)
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        exists_result, exists_result, rows_result, daily_result, count_result,
        categories_result, totals_result,
    ]))

    response = await analytics.get_ads_analyse(
        session, from_date=date(2026, 9, 1), to_date=date(2026, 9, 15), date_field="delivery",
    )

    assert session.execute.await_count == 7
    daily_query, daily_params = session.execute.call_args_list[3].args
    assert str(daily_query) == analytics._EXTERNAL_DAILY
    _parsed_statement(daily_query)
    assert daily_params == {"ad_ids": ["123"], "from_str": date(2026, 9, 1),
                            "to_str": date(2026, 9, 15)}
    row = response.rows[0]
    assert row.spend == 100
    assert row.impressions == 1000
    assert row.meta_roas == row.roas == 3
    assert row.ctr_pct == 2
    assert row.cost_per_ncp == 50
    assert row.cost_per_ftewv == 10
    assert row.atc_count is row.ci_count is row.engagement_count is None
    assert row.shopify_orders == response.totals.shopify_orders == shopify_orders
    assert row.shopify_revenue == response.totals.shopify_revenue == shopify_revenue
    if shopify_revenue is None:
        assert row.shopify_aov is row.shopify_roas is row.cost_per_shopify_order is None
        assert row.meta_shop_diff_pct is None
    elif shopify_orders == 0:
        assert row.shopify_roas == 0
        assert row.shopify_aov is row.cost_per_shopify_order is None
    else:
        assert row.shopify_aov == 100
        assert row.shopify_roas == 2
        assert row.cost_per_shopify_order == 50
        assert row.meta_shop_diff_pct == pytest.approx(-100 / 3)
