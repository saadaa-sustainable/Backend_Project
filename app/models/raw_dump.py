"""The single consolidated Bronze table for all Meta Marketing API data.

Every Meta object type — accounts, campaigns, ad sets, ads, creatives,
insights, images, videos, audiences, pixels, custom conversions, activities,
business assets, catalogs, products, labels, offline events — lands in this
one table, tagged by :attr:`RawDumpMeta.object_type`. There is no per-entity
Bronze table: Bronze's only job is "get the exact bytes Meta returned into
Postgres," and a single wide table is enough for that. All structuring
(unnesting, typing, joins, dedup) happens in the Silver layer, which reads
this table filtered by ``object_type``.

This also accommodates *nested* dumps (see
:mod:`app.services.meta.nested_tree`): a single row's ``raw_payload`` can be
a whole ``campaign -> adsets -> ads -> insights`` JSON tree fetched via
Graph API field expansion in one request, not just a single flat object —
``is_nested`` flags which shape a row is so Silver knows whether to unnest
recursively or read it flat.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BronzeMixin


class MetaObjectType:
    """Allowed values for :attr:`RawDumpMeta.object_type`."""

    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    ADSET = "adset"
    AD = "ad"
    CREATIVE = "creative"
    INSIGHTS = "insights"
    IMAGE = "image"
    VIDEO = "video"
    ASSET_FEED_SPEC = "asset_feed_spec"
    AUDIENCE = "audience"
    PIXEL = "pixel"
    CUSTOM_CONVERSION = "custom_conversion"
    OFFLINE_EVENT = "offline_event"
    ACTIVITY = "activity"
    BUSINESS_ASSET = "business_asset"
    CATALOG = "catalog"
    PRODUCT = "product"
    LABEL = "label"
    # Nested-tree dumps (see app/services/meta/nested_tree.py) — one row per
    # top-level object, raw_payload holds its full expanded child tree.
    CAMPAIGN_TREE = "campaign_tree"


class RawDumpMeta(Base, BronzeMixin):
    """Raw, unmodified Meta Marketing API responses — the entire Bronze layer
    for Meta data. ``meta_id`` holds the top-level object's Meta-assigned id
    (a campaign id for a ``campaign_tree`` row, an ad id for an ``ad`` row,
    ``None`` for the id-less ``insights`` rows)."""

    __tablename__ = "raw_dump_meta"

    object_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: Convenience denormalization of the parent ids implied by raw_payload
    #: (e.g. {"account_id": ..., "campaign_id": ..., "adset_id": ...}) so
    #: Silver can filter/join without parsing the full JSON payload for the
    #: common case. Always derivable from raw_payload — never authoritative.
    parent_ids: Mapped[dict | None] = mapped_column(JSONB)
    #: True when raw_payload is a nested tree (object + expanded child
    #: edges) rather than a single flat Meta object.
    is_nested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_raw_dump_meta_batch_meta", "batch_id", "meta_id"),
        Index("ix_raw_dump_meta_object_type_meta_id", "object_type", "meta_id"),
        Index("ix_raw_dump_meta_raw_payload_gin", "raw_payload", postgresql_using="gin"),
    )
