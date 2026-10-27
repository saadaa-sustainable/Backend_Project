"""Ad set ingestion for the configured ad account."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import ADSET_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class AdSetSyncService(BaseMetaSyncService):
    endpoint_name = "adsets"
    object_type = MetaObjectType.ADSET

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or ADSET_FIELDS)

        # Near-real-time paths pass the exact ids that changed; walking
        # the account edge to rediscover them would be pointless.
        object_ids = request_params.get("object_ids")
        if object_ids:
            async for item in self.fetch_objects_by_id(object_ids, fields):
                yield item
            return

        params: dict[str, Any] = {
            "fields": fields,
            # NOTE: "DELETED" deliberately excluded — Meta rejects it
            # outright now (error code 100 / subcode 1815001, "Cannot
            # Request for Deleted Objects") rather than silently ignoring
            # it, so including it fails the whole request.
            "effective_status": request_params.get(
                "effective_status",
                [
                    "ACTIVE",
                    "PAUSED",
                    "ARCHIVED",
                    "IN_PROCESS",
                    "WITH_ISSUES",
                    "CAMPAIGN_PAUSED",
                ],
            ),
            # A Graph `filtering` spec, e.g. adset.updated_time
            # GREATER_THAN <unix ts> for a delta pull.
            "filtering": request_params.get("filtering"),
        }
        campaign_id = request_params.get("campaign_id")
        base = (
            f"{campaign_id}/adsets"
            if campaign_id
            else f"{self.client.credentials.ad_account_id_prefixed}/adsets"
        )
        async for item in self.client.paginate(base, params=params):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "account_id": item.get("account_id", self.client.credentials.ad_account_id),
            "campaign_id": item.get("campaign_id"),
        }
