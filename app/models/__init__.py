"""SQLAlchemy ORM models.

Importing this package registers every mapped class on :data:`Base.metadata`,
which Alembic's ``env.py`` relies on for autogenerate. The Bronze layer is a
single consolidated table (:class:`RawDumpMeta`) — see
``app/models/raw_dump.py`` for why.
"""

from app.models.base import Base, BronzeMixin, ProcessingStatus, SyncType
from app.models.raw_dump import MetaObjectType, RawDumpMeta
from app.models.sync import BatchStatus, FailedJob, SyncBatch

__all__ = [
    "Base",
    "BronzeMixin",
    "ProcessingStatus",
    "SyncType",
    "BatchStatus",
    "SyncBatch",
    "FailedJob",
    "MetaObjectType",
    "RawDumpMeta",
]
