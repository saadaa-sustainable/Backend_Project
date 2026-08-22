"""Registry mapping endpoint name -> ingestion service class.

This is the extension point mentioned throughout the spec: adding a new
Meta endpoint means writing one small ``BaseMetaSyncService`` subclass and
adding one line here — no changes to the API layer, scheduler, or
orchestrator are required.
"""

from __future__ import annotations

from app.services.meta.accounts import AccountSyncService
from app.services.meta.activities import ActivitySyncService
from app.services.meta.adsets import AdSetSyncService
from app.services.meta.ads import AdSyncService
from app.services.meta.assets import AdImageSyncService, AdVideoSyncService, AssetFeedSpecSyncService
from app.services.meta.audiences import AudienceSyncService
from app.services.meta.base import BaseMetaSyncService
from app.services.meta.business import (
    BusinessAssetSyncService,
    CatalogSyncService,
    LabelSyncService,
)
from app.services.meta.campaigns import CampaignSyncService
from app.services.meta.creatives import CreativeSyncService
from app.services.meta.nested_tree import CampaignTreeSyncService
from app.services.meta.pixels import CustomConversionSyncService, PixelSyncService

#: Endpoints with a uniform "fetch an edge, store raw rows" shape. Keyed by
#: the name used in batch records, logs, and the `/sync/{endpoint}` route.
SIMPLE_SERVICE_REGISTRY: dict[str, type[BaseMetaSyncService]] = {
    "accounts": AccountSyncService,
    "campaigns": CampaignSyncService,
    "adsets": AdSetSyncService,
    "ads": AdSyncService,
    "creatives": CreativeSyncService,
    "images": AdImageSyncService,
    "videos": AdVideoSyncService,
    "asset_feed_specs": AssetFeedSpecSyncService,
    "audiences": AudienceSyncService,
    "pixels": PixelSyncService,
    "custom_conversions": CustomConversionSyncService,
    "activities": ActivitySyncService,
    "business_assets": BusinessAssetSyncService,
    "catalogs": CatalogSyncService,
    "labels": LabelSyncService,
}

#: Endpoints that need extra orchestration (discovering parent ids first,
#: or a fundamentally different fetch shape) — handled by
#: `app.services.meta.orchestrator.SyncOrchestrator` rather than generically.
SPECIAL_ENDPOINTS: frozenset[str] = frozenset({"products", "offline_events", "insights"})

#: Alternative, throttling-optimized fetch paths that duplicate what a
#: SIMPLE_SERVICE_REGISTRY entry already covers (e.g. "campaign_tree"
#: fetches the same data as campaigns+adsets+ads combined, just nested
#: into fewer calls). Deliberately excluded from SIMPLE_SERVICE_REGISTRY
#: and from `sync_all()`'s default loop — running both would double-fetch
#: the same data, not save quota. Opt in explicitly via their own route.
NESTED_SERVICE_REGISTRY: dict[str, type[BaseMetaSyncService]] = {
    "campaign_tree": CampaignTreeSyncService,
}

ALL_ENDPOINTS: frozenset[str] = (
    frozenset(SIMPLE_SERVICE_REGISTRY) | SPECIAL_ENDPOINTS | frozenset(NESTED_SERVICE_REGISTRY)
)

#: Endpoints scoped to the Business Manager (via META_BUSINESS_ID), not to
#: any individual ad account — the same data regardless of which
#: account's credentials make the request. When fanning a sync out across
#: every configured account (the multi-account default), these run once
#: instead of once per account, so we don't write N identical copies of the
#: same business-wide rows tagged with an arbitrary account.
BUSINESS_SCOPED_ENDPOINTS: frozenset[str] = frozenset({"business_assets", "catalogs", "products"})
