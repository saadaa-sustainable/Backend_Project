"""Generic repository for Bronze (raw) tables.

Bronze rows are immutable, append-only facts: every sync inserts new rows
(one per fetched object per run), never updates or deletes existing ones.
This keeps the full history of what Meta returned over time, which is what
makes the Bronze layer a trustworthy source of truth for reprocessing.

Inserts are batched via SQLAlchemy Core (``insert(...)`` executed with a
list of parameter dicts) rather than the ORM unit-of-work, avoiding
identity-map overhead when writing tens of thousands of rows per sync.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RepositoryError
from app.logging.setup import get_logger
from app.models.base import Base

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=Base)

DEFAULT_CHUNK_SIZE = 500


class BronzeRepository(Generic[ModelT]):
    """Persistence for a Bronze table.

    Parameterized by the SQLAlchemy model class — in practice this is
    always ``BronzeRepository(session, RawDumpMeta)``, since Meta ingestion
    writes into the single consolidated ``raw_dump_meta`` table, but the
    class stays generic so other sources (Shopify, Google Ads, ...) can
    reuse it with their own Bronze tables later.
    """

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def bulk_insert(
        self, records: Sequence[dict[str, Any]], *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> int:
        """Insert ``records`` (each a dict matching the model's columns) in
        chunks. Returns the number of rows inserted. Raises
        :class:`RepositoryError` on failure so callers can route the batch
        to the failed-jobs queue instead of losing the error.
        """
        if not records:
            return 0

        inserted = 0
        try:
            for start in range(0, len(records), chunk_size):
                chunk = records[start : start + chunk_size]
                await self.session.execute(insert(self.model), chunk)
                inserted += len(chunk)
            await self.session.flush()
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed error
            logger.error(
                "bronze_bulk_insert_failed",
                table=self.model.__tablename__,
                attempted=len(records),
                inserted_before_failure=inserted,
                error=str(exc),
            )
            raise RepositoryError(
                f"Bulk insert into {self.model.__tablename__} failed: {exc}"
            ) from exc

        logger.info("bronze_bulk_insert_complete", table=self.model.__tablename__, rows=inserted)
        return inserted

    async def count_for_batch(self, batch_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(self.model.id).where(self.model.batch_id == batch_id)
        )
        return len(result.scalars().all())

    async def latest_for_meta_id(self, meta_id: str) -> ModelT | None:
        """Return the most recently ingested row for a given Meta object id
        (useful for change-detection / debugging), or ``None``."""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.meta_id == meta_id)
            .order_by(self.model.ingested_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
