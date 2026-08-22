"""Business Manager scoped ingestion: business assets, catalogs, products,
and account labels."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.meta_registry import (
    BUSINESS_ASSET_FIELDS,
    CATALOG_FIELDS,
    LABEL_FIELDS,
    PRODUCT_FIELDS,
)
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService

#: (edge name on the business node, friendly asset-type label)
BUSINESS_ASSET_EDGES: list[tuple[str, str]] = [
    ("owned_pages", "page"),
    ("client_pages", "page"),
    ("owned_apps", "app"),
    ("client_apps", "app"),
    ("owned_instagram_accounts", "instagram_account"),
]


class BusinessAssetSyncService(BaseMetaSyncService):
    """Ingests every asset type owned by / shared with the configured
    Business Manager (pages, apps, Instagram accounts, ...)."""

    endpoint_name = "business_assets"
    object_type = MetaObjectType.BUSINESS_ASSET

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        business_id = self.client.credentials.business_id
        if not business_id:
            raise ConfigurationError(
                "BusinessAssetSyncService requires META_BUSINESS_ID to be configured."
            )
        fields = ",".join(request_params.get("fields") or BUSINESS_ASSET_FIELDS)
        for edge, asset_type in BUSINESS_ASSET_EDGES:
            async for item in self.client.paginate(
                f"{business_id}/{edge}", params={"fields": fields}
            ):
                item["_asset_type"] = asset_type
                yield item

    def build_row(
        self,
        item: dict[str, Any],
        *,
        batch_id: uuid.UUID,
        api_endpoint: str,
        request_params: dict[str, Any],
        sync_type: str,
    ) -> dict[str, Any]:
        # `_asset_type` is a tag we injected in fetch_records, not part of
        # Meta's response — pop it before it lands in raw_payload.
        asset_type = item.pop("_asset_type", None)
        row = super().build_row(
            item,
            batch_id=batch_id,
            api_endpoint=api_endpoint,
            request_params=request_params,
            sync_type=sync_type,
        )
        row["parent_ids"] = {
            **row["parent_ids"],
            "business_id": self.client.credentials.business_id,
            "asset_type": asset_type,
        }
        return row


class CatalogSyncService(BaseMetaSyncService):
    endpoint_name = "catalogs"
    object_type = MetaObjectType.CATALOG

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        business_id = self.client.credentials.business_id
        if not business_id:
            raise ConfigurationError(
                "CatalogSyncService requires META_BUSINESS_ID to be configured."
            )
        fields = ",".join(request_params.get("fields") or CATALOG_FIELDS)
        async for item in self.client.paginate(
            f"{business_id}/owned_product_catalogs", params={"fields": fields}
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"business_id": self.client.credentials.business_id}


class ProductSyncService(BaseMetaSyncService):
    """Ingests ``/{catalog_id}/products``. Requires ``catalog_id`` in
    ``request_params`` — orchestrate via :class:`CatalogSyncService` first
    to discover catalog ids, e.g. through the ``/sync/all`` endpoint."""

    endpoint_name = "products"
    object_type = MetaObjectType.PRODUCT

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        catalog_id = request_params.get("catalog_id")
        if not catalog_id:
            raise ConfigurationError("ProductSyncService requires `catalog_id` in request_params.")
        fields = ",".join(request_params.get("fields") or PRODUCT_FIELDS)
        async for item in self.client.paginate(
            f"{catalog_id}/products", params={"fields": fields}
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        # catalog_id isn't on the product item itself — it's the request
        # scope, so pull it from request_params via build_row instead.
        return None

    def build_row(
        self,
        item: dict[str, Any],
        *,
        batch_id: uuid.UUID,
        api_endpoint: str,
        request_params: dict[str, Any],
        sync_type: str,
    ) -> dict[str, Any]:
        row = super().build_row(
            item,
            batch_id=batch_id,
            api_endpoint=api_endpoint,
            request_params=request_params,
            sync_type=sync_type,
        )
        row["parent_ids"] = {
            **row["parent_ids"],
            "catalog_id": request_params.get("catalog_id"),
        }
        return row


class LabelSyncService(BaseMetaSyncService):
    endpoint_name = "labels"
    object_type = MetaObjectType.LABEL

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        fields = ",".join(request_params.get("fields") or LABEL_FIELDS)
        async for item in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/adlabels",
            params={"fields": fields},
        ):
            yield item

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}
