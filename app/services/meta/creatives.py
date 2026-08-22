"""Ad creative ingestion for the configured ad account."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import CREATIVE_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class CreativeSyncService(BaseMetaSyncService):
    endpoint_name = "creatives"
    object_type = MetaObjectType.CREATIVE

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or CREATIVE_FIELDS)
        params: dict[str, Any] = {"fields": fields}
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/adcreatives", params=params
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}
