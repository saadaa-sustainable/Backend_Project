"""Custom / lookalike / saved audience ingestion.

Meta distinguishes audience types via the ``subtype`` field within the
object itself (``CUSTOM``, ``LOOKALIKE``, ``SAVED``, ``WEBSITE``, ...) —
all are served from the same ``customaudiences`` edge and stored verbatim.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import AUDIENCE_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class AudienceSyncService(BaseMetaSyncService):
    endpoint_name = "audiences"
    object_type = MetaObjectType.AUDIENCE

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or AUDIENCE_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/customaudiences",
            params={"fields": fields},
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "account_id": item.get("account_id", self.client.credentials.ad_account_id),
            "business_id": self.client.credentials.business_id,
        }
