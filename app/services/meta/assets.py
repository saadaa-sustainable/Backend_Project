"""Creative asset ingestion: images, videos, and asset feed specs.

Images and videos are top-level ad account edges. Asset feed specs (used by
Dynamic Creative ads) are not a standalone edge — they are embedded inside
an ad creative — so :class:`AssetFeedSpecSyncService` derives its rows by
requesting the ``asset_feed_spec`` field from ``/adcreatives`` and emitting
one Bronze row per creative that has one, preserving that sub-object
exactly as returned.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import AD_IMAGE_FIELDS, AD_VIDEO_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService
from app.utils.hashing import hash_payload
from app.utils.time import utcnow


class AdImageSyncService(BaseMetaSyncService):
    endpoint_name = "images"
    object_type = MetaObjectType.IMAGE

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or AD_IMAGE_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/adimages",
            params={"fields": fields},
        ):
            yield item

    def extract_meta_id(self, item: dict[str, Any]) -> str | None:
        return item.get("hash")

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}


class AdVideoSyncService(BaseMetaSyncService):
    endpoint_name = "videos"
    object_type = MetaObjectType.VIDEO

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or AD_VIDEO_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/advideos",
            params={"fields": fields},
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}


class AssetFeedSpecSyncService(BaseMetaSyncService):
    endpoint_name = "asset_feed_specs"
    object_type = MetaObjectType.ASSET_FEED_SPEC

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        params = {"fields": "id,account_id,asset_feed_spec"}
        async for creative in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/adcreatives", params=params
        ):
            spec = creative.get("asset_feed_spec")
            if not spec:
                continue
            yield {
                "creative_id": creative.get("id"),
                "account_id": creative.get("account_id"),
                "asset_feed_spec": spec,
            }

    def build_row(
        self,
        item: dict[str, Any],
        *,
        batch_id: uuid.UUID,
        api_endpoint: str,
        request_params: dict[str, Any],
        sync_type: str,
    ) -> dict[str, Any]:
        now = utcnow()
        return {
            "id": uuid.uuid4(),
            "meta_id": item["creative_id"],
            "raw_payload": item["asset_feed_spec"],
            "api_endpoint": api_endpoint,
            "api_version": self.client.credentials.api_version,
            "batch_id": batch_id,
            "request_params": request_params,
            "extracted_at": now,
            "sync_type": sync_type,
            "payload_hash": hash_payload(item["asset_feed_spec"]),
            "processing_status": "pending",
            "object_type": self.object_type,
            "parent_ids": {
                "account_key": self.client.credentials.account_key,
                "account_name": self.client.credentials.account_name,
                "account_id": item.get("account_id", self.client.credentials.ad_account_id),
                "creative_id": item["creative_id"],
            },
            "is_nested": self.is_nested,
        }
