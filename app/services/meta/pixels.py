"""Meta Pixel, custom conversion, and offline event ingestion."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.meta_registry import CUSTOM_CONVERSION_FIELDS, PIXEL_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class PixelSyncService(BaseMetaSyncService):
    """Ingests ``/act_<id>/adspixels`` (and, when a Business Manager id is
    configured, every pixel owned by the business)."""

    endpoint_name = "pixels"
    object_type = MetaObjectType.PIXEL

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or PIXEL_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/adspixels",
            params={"fields": fields},
        ):
            yield item

        business_id = self.client.credentials.business_id
        if business_id:
            async for item in self.client.paginate(
                f"{business_id}/adspixels", params={"fields": fields}
            ):
                yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"business_id": self.client.credentials.business_id}


class CustomConversionSyncService(BaseMetaSyncService):
    """Ingests ``/act_<id>/customconversions`` — this is how custom
    conversion display names (e.g. "NCP", "First-time EWV") resolve to the
    numeric custom-conversion ids that show up in Insights ``actions`` as
    ``offsite_conversion.custom.<id>``. Silver needs this table to join
    insights action arrays back to a human-readable conversion name."""

    endpoint_name = "custom_conversions"
    object_type = MetaObjectType.CUSTOM_CONVERSION

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or CUSTOM_CONVERSION_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/customconversions",
            params={"fields": fields},
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}


class OfflineEventSyncService(BaseMetaSyncService):
    """Ingests offline event *set* metadata (name, stats, matching config)
    for a given ``offline_event_set_id``.

    The Graph API's offline conversions product is upload-oriented — Meta
    does not expose bulk readback of previously uploaded individual events.
    The closest available "raw" object is the offline event set resource
    itself (``GET /{offline_event_set_id}``), which is what this service
    captures; per-event detail is not retrievable via the Marketing API.
    """

    endpoint_name = "offline_events"
    object_type = MetaObjectType.OFFLINE_EVENT

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        offline_event_set_id = request_params.get("offline_event_set_id")
        if not offline_event_set_id:
            raise ConfigurationError(
                "OfflineEventSyncService requires `offline_event_set_id` in request_params."
            )
        item = await self.client.get(
            str(offline_event_set_id),
            params={"fields": "id,name,description,creation_time,is_mta_use,is_restricted_use,usage"},
        )
        yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"offline_event_set_id": item.get("id")}
