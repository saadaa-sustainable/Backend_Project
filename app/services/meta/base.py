"""Shared base class for Meta object ingestion services.

Every simple "fetch an edge, page through it, store the raw payload"
service (accounts, campaigns, ad sets, ads, creatives, images, videos,
audiences, pixels, custom conversions, activities, business assets,
catalogs, products, labels, ...) follows an identical shape:

1. open a :class:`~app.models.sync.SyncBatch`
2. stream items from the Meta client (:meth:`fetch_records`)
3. map each raw item to a :class:`~app.models.raw_dump.RawDumpMeta` row
   (:meth:`build_row`), tagged with this service's :attr:`object_type`
4. buffer + bulk-insert in chunks so memory stays bounded
5. record any per-chunk failures to the failed-jobs queue instead of
   aborting the whole run
6. close the batch with final counts

Every concrete service writes into the same single Bronze table
(``raw_dump_meta``) — there is no per-entity model to parameterize this
class over. Concrete services only need to set :attr:`endpoint_name` and
:attr:`object_type` and implement :meth:`fetch_records` (what to ask Meta
for); override :meth:`extract_parent_ids` to populate the convenience
``parent_ids`` column (e.g. ``{"campaign_id": ...}`` on an ad set row).
"""

from __future__ import annotations

import abc
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IngestionError
from app.logging.setup import get_logger
from app.models.raw_dump import RawDumpMeta
from app.models.sync import SyncBatch
from app.repositories.base import DEFAULT_CHUNK_SIZE, BronzeRepository
from app.repositories.batch_repository import BatchRepository
from app.repositories.failed_job_repository import FailedJobRepository
from app.services.meta.client import MetaAPIClient
from app.utils.hashing import hash_payload
from app.utils.time import utcnow

logger = get_logger(__name__)


class BaseMetaSyncService(abc.ABC):
    """Template-method base class for a single Meta endpoint's ingestion.
    Every subclass writes into :class:`RawDumpMeta` — the Bronze layer is
    one table."""

    #: Short, stable name used as the batch/log "endpoint" label (e.g. "campaigns").
    endpoint_name: str
    #: One of :class:`~app.models.raw_dump.MetaObjectType` — tags every row
    #: this service writes so Silver can filter ``raw_dump_meta`` by type.
    object_type: str
    #: Whether this service's rows hold a nested tree rather than a flat
    #: single Meta object (see ``app/services/meta/nested_tree.py``).
    is_nested: bool = False

    model = RawDumpMeta

    def __init__(self, session: AsyncSession, client: MetaAPIClient) -> None:
        self.session = session
        self.client = client
        self.repository = BronzeRepository(session, self.model)
        self.batch_repository = BatchRepository(session)
        self.failed_job_repository = FailedJobRepository(session)

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def fetch_records(self, request_params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield raw Meta API objects (already unwrapped from ``data``) for
        this endpoint. Implementations typically call
        ``self.client.paginate(path, params=...)``.
        """
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for typing

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Return the parent-object ids implied by ``item`` (e.g.
        ``{"account_id": ..., "campaign_id": ...}`` for an ad set), stored
        in the ``parent_ids`` convenience column. Default: none — override
        per service. Always derived from fields already present in
        ``item``; never an extra API call.
        """
        return None

    def extract_meta_id(self, item: dict[str, Any]) -> str | None:
        """Return this item's Meta-assigned id. Default: the ``id`` field —
        override for object types keyed differently (e.g. ad images are
        keyed by ``hash``, not ``id``)."""
        return item.get("id")

    def build_row(
        self,
        item: dict[str, Any],
        *,
        batch_id: uuid.UUID,
        api_endpoint: str,
        request_params: dict[str, Any],
        sync_type: str,
    ) -> dict[str, Any]:
        """Map one raw Meta object to a ``raw_dump_meta`` row dict. Every
        row is auto-tagged with which of the (possibly several) configured
        ad accounts it came from, on top of whatever ``extract_parent_ids``
        contributes — so multi-account rows are always attributable without
        Silver needing to parse ``raw_payload`` just to find out."""
        now = utcnow()
        parent_ids = {
            "account_key": self.client.credentials.account_key,
            "account_name": self.client.credentials.account_name,
            **(self.extract_parent_ids(item) or {}),
        }
        return {
            "id": uuid.uuid4(),
            "meta_id": self.extract_meta_id(item),
            "raw_payload": item,
            "api_endpoint": api_endpoint,
            "api_version": self.client.credentials.api_version,
            "batch_id": batch_id,
            "request_params": request_params,
            "extracted_at": now,
            "sync_type": sync_type,
            "payload_hash": hash_payload(item),
            "processing_status": "pending",
            "object_type": self.object_type,
            "parent_ids": parent_ids,
            "is_nested": self.is_nested,
        }

    # ------------------------------------------------------------------
    # Template method
    # ------------------------------------------------------------------

    async def sync(
        self,
        *,
        request_params: dict[str, Any] | None = None,
        sync_type: str = "manual",
        triggered_by: str = "api",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> SyncBatch:
        """Run a full ingestion pass for this endpoint and return the
        completed :class:`SyncBatch`."""
        request_params = request_params or {}
        batch = await self.batch_repository.create(
            endpoint=self.endpoint_name,
            sync_type=sync_type,
            request_params=request_params,
            triggered_by=triggered_by,
            account_key=self.client.credentials.account_key,
            account_name=self.client.credentials.account_name,
        )
        log = logger.bind(endpoint=self.endpoint_name, batch_id=str(batch.id))
        log.info("sync_started", request_params=request_params)

        fetched = 0
        failed = 0
        buffer: list[dict[str, Any]] = []

        try:
            async for item in self.fetch_records(request_params):
                row = self.build_row(
                    item,
                    batch_id=batch.id,
                    api_endpoint=self.endpoint_name,
                    request_params=request_params,
                    sync_type=sync_type,
                )
                buffer.append(row)
                if len(buffer) >= chunk_size:
                    fetched, failed = await self._flush(buffer, batch.id, fetched, failed, log)
                    buffer = []

            if buffer:
                fetched, failed = await self._flush(buffer, batch.id, fetched, failed, log)

            await self.batch_repository.complete(
                batch.id, records_fetched=fetched, records_failed=failed
            )
            log.info("sync_completed", records_fetched=fetched, records_failed=failed)
        except Exception as exc:  # noqa: BLE001 - convert to typed error, batch is preserved
            log.error("sync_failed", error=str(exc))
            await self.batch_repository.fail(batch.id, error_message=str(exc))
            await self.failed_job_repository.record_failure(
                batch_id=batch.id,
                endpoint=self.endpoint_name,
                error_message=str(exc),
                request_params=request_params,
                account_key=self.client.credentials.account_key,
                account_name=self.client.credentials.account_name,
            )
            raise IngestionError(
                f"Ingestion failed for endpoint '{self.endpoint_name}': {exc}"
            ) from exc

        refreshed = await self.batch_repository.get(batch.id)
        assert refreshed is not None
        return refreshed

    async def _flush(
        self,
        buffer: list[dict[str, Any]],
        batch_id: uuid.UUID,
        fetched: int,
        failed: int,
        log: Any,
    ) -> tuple[int, int]:
        try:
            inserted = await self.repository.bulk_insert(buffer)
            return fetched + inserted, failed
        except Exception as exc:  # noqa: BLE001
            log.error("sync_chunk_failed", chunk_size=len(buffer), error=str(exc))
            await self.failed_job_repository.record_failure(
                batch_id=batch_id,
                endpoint=self.endpoint_name,
                error_message=str(exc),
                request_params={"chunk_size": len(buffer)},
                account_key=self.client.credentials.account_key,
                account_name=self.client.credentials.account_name,
            )
            return fetched, failed + len(buffer)
