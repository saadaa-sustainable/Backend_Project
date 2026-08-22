"""Campaign ingestion for the configured ad account."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import CAMPAIGN_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class CampaignSyncService(BaseMetaSyncService):
    endpoint_name = "campaigns"
    object_type = MetaObjectType.CAMPAIGN

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or CAMPAIGN_FIELDS)
        params: dict[str, Any] = {
            "fields": fields,
            # `effective_status` filter lets callers scope to e.g. only
            # ACTIVE campaigns. NOTE: "DELETED" is deliberately excluded —
            # Meta now rejects it outright ("Cannot Request for Deleted
            # Objects", error code 100 / subcode 1815001) rather than
            # silently ignoring it, so including it fails the whole request.
            "effective_status": request_params.get(
                "effective_status",
                [
                    "ACTIVE",
                    "PAUSED",
                    "ARCHIVED",
                    "IN_PROCESS",
                    "WITH_ISSUES",
                ],
            ),
        }
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/campaigns", params=params
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}
