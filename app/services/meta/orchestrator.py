"""Coordinates a full "sync everything" run across every registered
ingestion service, respecting dependencies between them (e.g. catalogs must
be discovered before their products can be fetched) and bounding
concurrency so we do not overwhelm the Meta API or the DB pool.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfigurationError, IngestionError
from app.core.security import MetaCredentials, get_all_meta_credentials, get_meta_credentials
from app.database.session import session_scope
from app.logging.setup import get_logger
from app.models.sync import SyncBatch
from app.services.meta.business import ProductSyncService
from app.services.meta.client import MetaAPIClient
from app.services.meta.insights import InsightsSyncService
from app.services.meta.nested_tree import CampaignTreeSyncService
from app.services.meta.registry import BUSINESS_SCOPED_ENDPOINTS, SIMPLE_SERVICE_REGISTRY

logger = get_logger(__name__)

#: How many independent endpoint syncs to run concurrently. Bounded well
#: below the client's own per-request semaphore so a single `/sync/all`
#: call cannot starve other traffic sharing the same Meta app/token.
MAX_CONCURRENT_ENDPOINT_SYNCS = 4

#: How many accounts :class:`MultiAccountSyncCoordinator` processes
#: concurrently. Each account gets its own DB connection (via
#: `session_scope`) and its own Meta API rate-limit budget (via its own
#: `MetaAPIClient`), so this is really a cap on concurrent DB connections
#: opened by one multi-account sync call, not a Meta-side throttle.
MAX_CONCURRENT_ACCOUNT_SYNCS = 4


class SyncOrchestrator:
    def __init__(self, session: AsyncSession, client: MetaAPIClient) -> None:
        self.session = session
        self.client = client
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_ENDPOINT_SYNCS)

    async def sync_endpoint(
        self,
        endpoint: str,
        *,
        request_params: dict[str, Any] | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
    ) -> SyncBatch:
        """Run a single simple endpoint's ingestion service by name."""
        service_cls = SIMPLE_SERVICE_REGISTRY.get(endpoint)
        if service_cls is None:
            raise ConfigurationError(f"'{endpoint}' is not a simple registered endpoint.")
        service = service_cls(self.session, self.client)
        async with self._semaphore:
            return await service.sync(
                request_params=request_params, sync_type=sync_type, triggered_by=triggered_by
            )

    async def sync_insights(
        self,
        *,
        sync_type: str = "manual",
        triggered_by: str = "api",
        target_table: str | None = None,
        **insights_kwargs: Any,
    ) -> SyncBatch:
        # target_table is explicit, not folded into **insights_kwargs -- it
        # has to reach the service constructor (which resolves the write
        # target), not .sync() itself. None preserves the exact existing
        # raw_dump_meta behavior for every caller that doesn't pass it
        # (every scheduler job, every /sync/insights request).
        service = InsightsSyncService(self.session, self.client, target_table=target_table)
        async with self._semaphore:
            return await service.sync(
                sync_type=sync_type, triggered_by=triggered_by, **insights_kwargs
            )

    async def sync_products_for_all_catalogs(
        self, *, sync_type: str = "manual", triggered_by: str = "api"
    ) -> list[SyncBatch]:
        """Discover every catalog owned by the configured business, then
        sync products for each. Returns an empty list if no business id is
        configured or no catalogs exist."""
        if not self.client.credentials.business_id:
            logger.info("skip_products_sync_no_business_id")
            return []

        catalog_ids = await self._discover_catalog_ids()
        if not catalog_ids:
            return []

        batches: list[SyncBatch] = []
        for catalog_id in catalog_ids:
            batch = await self._sync_products_for_catalog(
                catalog_id, sync_type=sync_type, triggered_by=triggered_by
            )
            batches.append(batch)
        return batches

    async def _sync_products_for_catalog(
        self, catalog_id: str, *, sync_type: str, triggered_by: str
    ) -> SyncBatch:
        service = ProductSyncService(self.session, self.client)
        async with self._semaphore:
            return await service.sync(
                request_params={"catalog_id": catalog_id},
                sync_type=sync_type,
                triggered_by=triggered_by,
            )

    async def _discover_catalog_ids(self) -> list[str]:
        business_id = self.client.credentials.business_id
        ids: list[str] = []
        async for item in self.client.paginate(
            f"{business_id}/owned_product_catalogs", params={"fields": "id"}
        ):
            if item.get("id"):
                ids.append(item["id"])
        return ids

    async def sync_all(
        self,
        *,
        sync_type: str = "full",
        triggered_by: str = "scheduler",
        skip_business_scoped: bool = False,
    ) -> list[SyncBatch]:
        """Run every registered endpoint. Simple endpoints run concurrently
        (bounded); Insights and catalog-dependent products run after, since
        Insights benefits from campaigns/adsets/ads already being fresh and
        products depend on catalogs having just been discovered.
        Individual endpoint failures are logged and do not abort the rest
        of the run — each is already fault-isolated via its own SyncBatch
        and the failed-jobs queue.

        ``skip_business_scoped``: set by
        :class:`MultiAccountSyncCoordinator` on every account after the
        first when fanning a run out across multiple accounts —
        BUSINESS_SCOPED_ENDPOINTS (business assets, catalogs, products)
        return identical data regardless of which account's credentials
        make the request, so re-running them per account would just write
        duplicate rows.

        Note: an ``AsyncSession`` is not safe to use from multiple
        concurrent coroutines. ``self.session`` (this one account's session
        — see :class:`MultiAccountSyncCoordinator`, which gives each
        account its own) is only used for the sequential steps below; each
        concurrently-run simple endpoint sync opens its own short-lived
        session via :func:`session_scope` instead of sharing one.
        """
        results: list[SyncBatch] = []
        endpoints = [
            e
            for e in SIMPLE_SERVICE_REGISTRY
            if not (skip_business_scoped and e in BUSINESS_SCOPED_ENDPOINTS)
        ]

        async def _run(endpoint: str) -> SyncBatch | None:
            service_cls = SIMPLE_SERVICE_REGISTRY[endpoint]
            try:
                async with self._semaphore, session_scope() as session:
                    service = service_cls(session, self.client)
                    return await service.sync(sync_type=sync_type, triggered_by=triggered_by)
            except IngestionError as exc:
                logger.error("sync_all_endpoint_failed", endpoint=endpoint, error=str(exc))
                return None

        simple_results = await asyncio.gather(*(_run(endpoint) for endpoint in endpoints))
        results.extend(b for b in simple_results if b is not None)

        if not skip_business_scoped:
            try:
                results.extend(
                    await self.sync_products_for_all_catalogs(
                        sync_type=sync_type, triggered_by=triggered_by
                    )
                )
            except IngestionError as exc:
                logger.error("sync_all_products_failed", error=str(exc))

        try:
            results.append(
                await self.sync_insights(sync_type=sync_type, triggered_by=triggered_by)
            )
        except IngestionError as exc:
            logger.error("sync_all_insights_failed", error=str(exc))

        return results


@dataclass(frozen=True, slots=True)
class AccountSyncResult:
    """A :class:`~app.models.sync.SyncBatch` labeled with which configured
    account produced it — every :class:`MultiAccountSyncCoordinator` method
    returns these instead of bare batches, so a multi-account response
    never leaves the caller guessing whose data is whose."""

    account_key: str
    account_name: str
    batch: SyncBatch


class MultiAccountSyncCoordinator:
    """Fans a sync operation out across every configured Meta ad account
    (or a specific one) **concurrently**: each account gets its own
    short-lived DB session (via :func:`session_scope`) and its own
    ``MetaAPIClient``, so accounts are genuinely processed in parallel —
    not just structured as if they were.

    This is why the coordinator does not take (or reuse) a caller-supplied
    ``AsyncSession``: a single ``AsyncSession`` is not safe to use from
    multiple coroutines at once, so real concurrency requires one session
    per concurrently-running account, each committing its own transaction
    independently. That's also the right failure model for Bronze data —
    every account's writes are already fault-isolated per
    :class:`~app.models.sync.SyncBatch` and the failed-jobs queue, so there
    is no correctness reason for one account's commit to wait on another's.

    Concurrency is bounded by :data:`MAX_CONCURRENT_ACCOUNT_SYNCS` so a
    large account roster can't open unbounded concurrent DB connections;
    excess accounts queue for a slot rather than all firing at once.

    This is the entry point every API route and scheduler job should use —
    "sync across whichever accounts are configured, in parallel" is the
    default behavior a multi-account setup calls for, not an edge case.
    """

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNT_SYNCS)

    def _resolve_accounts(self, account_key: str | None) -> list[MetaCredentials]:
        if account_key is not None:
            return [get_meta_credentials(account_key)]
        return get_all_meta_credentials()

    async def _run_per_account(
        self,
        accounts: list[MetaCredentials],
        worker: Any,  # Callable[[MetaCredentials, AsyncSession], Awaitable[SyncBatch | list[SyncBatch]]]
    ) -> list[AccountSyncResult]:
        """Run ``worker(credentials, session)`` for every account in
        ``accounts`` concurrently (bounded), each in its own session/DB
        transaction. ``worker`` may return one batch or a list of batches
        (for account-level calls that themselves fan out, like
        ``sync_all``) — either shape is flattened into ``AccountSyncResult``
        entries, in the same order ``accounts`` was given regardless of
        which account's request actually finishes first.
        """

        async def _one(credentials: MetaCredentials) -> list[AccountSyncResult]:
            async with self._semaphore, session_scope() as session:
                outcome = await worker(credentials, session)
            batches = outcome if isinstance(outcome, list) else [outcome]
            return [
                AccountSyncResult(credentials.account_key, credentials.account_name, batch)
                for batch in batches
            ]

        grouped = await asyncio.gather(*(_one(c) for c in accounts))
        return [result for group in grouped for result in group]

    async def sync_endpoint(
        self,
        endpoint: str,
        *,
        account_key: str | None = None,
        request_params: dict[str, Any] | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
    ) -> list[AccountSyncResult]:
        accounts = self._resolve_accounts(account_key)
        # Business-scoped endpoints return identical data regardless of
        # which account's credentials make the request — run once, using
        # whichever account happens to be first, rather than once per
        # account (which would just write N duplicate copies).
        if endpoint in BUSINESS_SCOPED_ENDPOINTS and account_key is None:
            accounts = accounts[:1]

        async def worker(credentials: MetaCredentials, session: AsyncSession) -> SyncBatch:
            async with MetaAPIClient(credentials) as client:
                orchestrator = SyncOrchestrator(session, client)
                return await orchestrator.sync_endpoint(
                    endpoint,
                    request_params=request_params,
                    sync_type=sync_type,
                    triggered_by=triggered_by,
                )

        return await self._run_per_account(accounts, worker)

    async def sync_insights(
        self,
        *,
        account_key: str | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
        target_table: str | None = None,
        **insights_kwargs: Any,
    ) -> list[AccountSyncResult]:
        async def worker(credentials: MetaCredentials, session: AsyncSession) -> SyncBatch:
            async with MetaAPIClient(credentials) as client:
                orchestrator = SyncOrchestrator(session, client)
                return await orchestrator.sync_insights(
                    sync_type=sync_type, triggered_by=triggered_by,
                    target_table=target_table, **insights_kwargs
                )

        return await self._run_per_account(self._resolve_accounts(account_key), worker)

    async def sync_products(
        self,
        catalog_id: str,
        *,
        account_key: str | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
    ) -> list[AccountSyncResult]:
        # Business-scoped (products belong to a catalog, not an account) —
        # one account's credentials is enough regardless of account_key.
        accounts = self._resolve_accounts(account_key)[:1]

        async def worker(credentials: MetaCredentials, session: AsyncSession) -> SyncBatch:
            async with MetaAPIClient(credentials) as client:
                service = ProductSyncService(session, client)
                return await service.sync(
                    request_params={"catalog_id": catalog_id},
                    sync_type=sync_type,
                    triggered_by=triggered_by,
                )

        return await self._run_per_account(accounts, worker)

    async def sync_campaign_tree(
        self,
        *,
        account_key: str | None = None,
        request_params: dict[str, Any] | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
    ) -> list[AccountSyncResult]:
        async def worker(credentials: MetaCredentials, session: AsyncSession) -> SyncBatch:
            async with MetaAPIClient(credentials) as client:
                service = CampaignTreeSyncService(session, client)
                return await service.sync(
                    request_params=request_params,
                    sync_type=sync_type,
                    triggered_by=triggered_by,
                )

        return await self._run_per_account(self._resolve_accounts(account_key), worker)

    async def sync_all(
        self,
        *,
        account_key: str | None = None,
        sync_type: str = "full",
        triggered_by: str = "scheduler",
    ) -> list[AccountSyncResult]:
        accounts = self._resolve_accounts(account_key)
        # Which account fetches business-scoped data (business
        # assets/catalogs/products) is decided up front by position in
        # this list — independent of which account's sync actually
        # finishes first once they're running concurrently. See
        # sync_endpoint()'s docstring for why only one account fetches it.
        business_scoped_key = accounts[0].account_key if accounts else None

        async def worker(credentials: MetaCredentials, session: AsyncSession) -> list[SyncBatch]:
            async with MetaAPIClient(credentials) as client:
                orchestrator = SyncOrchestrator(session, client)
                return await orchestrator.sync_all(
                    sync_type=sync_type,
                    triggered_by=triggered_by,
                    skip_business_scoped=credentials.account_key != business_scoped_key,
                )

        return await self._run_per_account(accounts, worker)
