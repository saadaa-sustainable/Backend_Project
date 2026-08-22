"""``/sync/*`` endpoints.

One route per registered simple endpoint is generated from
:data:`SIMPLE_SERVICE_REGISTRY` (see :func:`_register_simple_routes`) so
adding a new Meta object type never requires touching this file — it only
requires adding the service to the registry. ``insights``, ``products``,
``campaign_tree``, and ``all`` have bespoke request shapes and are defined
explicitly.

Every route runs against every configured Meta ad account by default
(pass ``account`` in the request body to scope to just one) — see
:class:`~app.services.meta.orchestrator.MultiAccountSyncCoordinator`.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CoordinatorDep
from app.schemas.sync import (
    CampaignTreeSyncRequest,
    InsightsSyncRequest,
    MultiSyncResponse,
    SyncRequest,
    SyncResponse,
)
from app.services.meta.orchestrator import AccountSyncResult
from app.services.meta.registry import SIMPLE_SERVICE_REGISTRY

router = APIRouter(prefix="/sync", tags=["sync"])


def _to_response(result: AccountSyncResult) -> SyncResponse:
    batch = result.batch
    return SyncResponse(
        account_key=result.account_key,
        account_name=result.account_name,
        batch_id=batch.id,
        endpoint=batch.endpoint,
        status=batch.status,
        records_fetched=batch.records_fetched,
        records_failed=batch.records_failed,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
    )


def _to_multi_response(results: list[AccountSyncResult]) -> MultiSyncResponse:
    return MultiSyncResponse(batches=[_to_response(r) for r in results])


def _make_simple_handler(endpoint: str):
    """Build a route handler bound to ``endpoint`` via closure (not a
    function parameter), so FastAPI's signature introspection never sees —
    and can't expose as a query param — the endpoint name itself."""

    async def _handler(
        coordinator: CoordinatorDep, body: SyncRequest = SyncRequest()
    ) -> MultiSyncResponse:
        results = await coordinator.sync_endpoint(
            endpoint,
            account_key=body.account,
            sync_type=body.sync_type,
            triggered_by=body.triggered_by,
        )
        return _to_multi_response(results)

    return _handler


def _register_simple_routes() -> None:
    for endpoint in SIMPLE_SERVICE_REGISTRY:
        router.add_api_route(
            f"/{endpoint}",
            _make_simple_handler(endpoint),
            methods=["POST"],
            response_model=MultiSyncResponse,
            name=f"sync_{endpoint}",
            summary=f"Sync {endpoint.replace('_', ' ')} into the Bronze layer",
        )


_register_simple_routes()


@router.post("/insights", response_model=MultiSyncResponse)
async def sync_insights(
    coordinator: CoordinatorDep, body: InsightsSyncRequest
) -> MultiSyncResponse:
    date_range = (body.date_range.since, body.date_range.until) if body.date_range else None
    time_ranges = (
        [(r.since, r.until) for r in body.time_ranges] if body.time_ranges else None
    )
    results = await coordinator.sync_insights(
        account_key=body.account,
        levels=body.levels,
        date_preset=body.date_preset,
        date_range=date_range,
        time_ranges=time_ranges,
        time_increment=body.time_increment,
        breakdowns=body.breakdowns or None,
        action_breakdowns=body.action_breakdowns,
        attribution_windows=body.attribution_windows,
        use_unified_attribution_setting=body.use_unified_attribution_setting,
        use_account_attribution_setting=body.use_account_attribution_setting,
        action_report_time=body.action_report_time,
        field_groups=body.field_groups,
        extra_fields=body.extra_fields,
        filtering=(
            [f.model_dump(mode="json") for f in body.filtering] if body.filtering else None
        ),
        sort=body.sort,
        summary=body.summary,
        default_summary=body.default_summary,
        summary_action_breakdowns=body.summary_action_breakdowns,
        product_id_limit=body.product_id_limit,
        locale=body.locale,
        use_async=body.use_async,
        sync_type=body.sync_type,
        triggered_by=body.triggered_by,
    )
    return _to_multi_response(results)


@router.post("/products", response_model=MultiSyncResponse)
async def sync_products(
    coordinator: CoordinatorDep,
    catalog_id: str = Query(..., description="Product catalog id to sync products for."),
    body: SyncRequest = SyncRequest(),
) -> MultiSyncResponse:
    """Products belong to a catalog, not an ad account — this always runs
    once (using whichever account's credentials the request/default
    resolves to) regardless of how many accounts are configured."""
    results = await coordinator.sync_products(
        catalog_id,
        account_key=body.account,
        sync_type=body.sync_type,
        triggered_by=body.triggered_by,
    )
    return _to_multi_response(results)


@router.post("/campaign_tree", response_model=MultiSyncResponse)
async def sync_campaign_tree(
    coordinator: CoordinatorDep, body: CampaignTreeSyncRequest = CampaignTreeSyncRequest()
) -> MultiSyncResponse:
    """Throttling-optimized alternative to /sync/campaigns +
    /sync/adsets + /sync/ads: pulls the campaign->adset->ad hierarchy via
    Graph API nested field expansion in far fewer calls. Not run as part of
    /sync/all — see module docstring in nested_tree.py for why."""
    results = await coordinator.sync_campaign_tree(
        account_key=body.account,
        request_params={
            "nested_limit": body.nested_limit,
            "page_size": body.page_size,
            "include_insights": body.include_insights,
            "insights_date_preset": body.insights_date_preset,
        },
        sync_type=body.sync_type,
        triggered_by=body.triggered_by,
    )
    return _to_multi_response(results)


@router.post("/all", response_model=MultiSyncResponse)
async def sync_all(
    coordinator: CoordinatorDep, body: SyncRequest = SyncRequest()
) -> MultiSyncResponse:
    """Kick off a full ingestion pass across every registered endpoint for
    every configured account (or just ``account`` if given), including
    catalog-derived products and Insights. Long-running for accounts with
    substantial history — consider using the scheduler's daily job or
    ``/sync/*`` per-endpoint routes for tighter control."""
    results = await coordinator.sync_all(
        account_key=body.account, sync_type=body.sync_type, triggered_by=body.triggered_by
    )
    return _to_multi_response(results)
