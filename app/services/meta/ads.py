"""Ad ingestion for the configured ad account."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import AD_FIELDS, AD_URL_TRACKING_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class AdSyncService(BaseMetaSyncService):
    """Ad ingestion. Pass ``request_params={"include_creative_expansion":
    True}`` to fetch the nested creative/UTM tracking fields (Ads Insights
    reference §8 "Bulk pull") in the same call instead of the lean default
    field set — useful when this sync's only purpose is building a
    destination-URL / UTM mapping table downstream."""

    endpoint_name = "ads"
    object_type = MetaObjectType.AD

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        if request_params.get("include_creative_expansion"):
            fields = AD_URL_TRACKING_FIELDS
        else:
            fields = ",".join(request_params.get("fields") or AD_FIELDS)
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
                    "ADSET_PAUSED",
                ],
            ),
        }
        adset_id = request_params.get("adset_id")
        campaign_id = request_params.get("campaign_id")
        if adset_id:
            base = f"{adset_id}/ads"
        elif campaign_id:
            base = f"{campaign_id}/ads"
        else:
            base = f"{self.client.credentials.ad_account_id_prefixed}/ads"

        async for item in self.client.paginate(base, params=params):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "account_id": item.get("account_id", self.client.credentials.ad_account_id),
            "campaign_id": item.get("campaign_id"),
            "adset_id": item.get("adset_id"),
        }
