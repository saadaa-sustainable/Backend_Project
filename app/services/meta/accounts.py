"""Ad account ingestion.

Fetches the configured ad account itself, and — when a Business Manager id
is configured and ``include_business_accounts`` is requested — every ad
account owned by or shared as a client with that business, so multi-account
setups are captured without manual enumeration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import ACCOUNT_FIELDS
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService


class AccountSyncService(BaseMetaSyncService):
    endpoint_name = "accounts"
    object_type = MetaObjectType.ACCOUNT

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or ACCOUNT_FIELDS)

        account = await self.client.get(
            self.client.credentials.ad_account_id_prefixed, params={"fields": fields}
        )
        yield account

        business_id = self.client.credentials.business_id
        if request_params.get("include_business_accounts") and business_id:
            for edge in ("owned_ad_accounts", "client_ad_accounts"):
                async for item in self.client.paginate(
                    f"{business_id}/{edge}", params={"fields": fields}
                ):
                    yield item
