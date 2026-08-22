"""Account activity (change-history audit log) ingestion.

Beyond general audit purposes, Silver relies on this feed to reconstruct
ad rename history (Meta bakes an ad's *original* name into UTM tags at
creation time, so a later rename would otherwise break UTM-based
attribution matching for older orders) — scan ``object_type == "ad"``
``NAME_CHANGE``-ish activities to build that history.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import ACTIVITY_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class ActivitySyncService(BaseMetaSyncService):
    """Ingests ``/act_<id>/activities`` — Meta's per-account change log
    (budget changes, status changes, targeting edits, renames, etc.).
    Activity records have no stable Meta-assigned id, so ``meta_id`` is left
    null and ``payload_hash`` is relied on for de-duplication downstream."""

    endpoint_name = "activities"
    object_type = MetaObjectType.ACTIVITY

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or ACTIVITY_FIELDS)
        params: dict[str, Any] = {"fields": fields}
        if since := request_params.get("since"):
            params["since"] = since
        if until := request_params.get("until"):
            params["until"] = until

        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/activities", params=params
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "account_id": item.get("account_id", self.client.credentials.ad_account_id),
            "object_id": item.get("object_id"),
        }
