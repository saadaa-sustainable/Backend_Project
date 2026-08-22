"""Nested-tree Meta ingestion — fewer API calls via Graph API field expansion.

The flat services (:class:`~app.services.meta.campaigns.CampaignSyncService`,
:class:`~app.services.meta.adsets.AdSetSyncService`,
:class:`~app.services.meta.ads.AdSyncService`) each paginate their own edge
independently: fetching every campaign, then every ad set per campaign,
then every ad per ad set is 1 + N + M separate paginated request chains.
Graph API supports embedding child edges directly in a parent object's
response via field expansion (``adsets.limit(50){id,name,ads.limit(50)
{id,name,...}}}``), collapsing that into roughly one paginated request
chain at the campaign level — far fewer HTTP calls, which is the whole
point when the goal is reducing rate-limit pressure on large accounts.

:class:`CampaignTreeSyncService` dumps the **entire nested JSON tree**
returned for each campaign into one ``raw_dump_meta`` row
(``object_type="campaign_tree"``, ``is_nested=True``) — Bronze does not
unnest it; that is Silver's job, reading rows where ``is_nested`` is true
and walking ``raw_payload['adsets']['data'][*]['ads']['data'][*]``.

**Real limitation — read before relying on this for completeness.** Each
nested edge has its own internal pagination, capped by its ``.limit()``
argument (default here: 100). A campaign with more ad sets than the
configured limit only returns the first page of them, embedded inline —
this service does **not** auto-follow a nested connection's own
``paging.next`` cursor (Graph API does not surface that as a top-level
cursor you can pass back in, it's nested inside each parent's own field
data, which means following it requires a separate, per-parent follow-up
call — defeating the "fewer calls" point for accounts where that actually
matters). This mode is a throttling optimization for typical-sized
accounts (up to a few hundred ad sets/ads per campaign, well within the
default limits below); for accounts large enough to blow past that,
either raise ``nested_limit`` accordingly or fall back to the flat,
exhaustively-paginating services.

**Nested Insights — off by default, verify before turning on.** Graph
API's nested-edge syntax for embedding an ``insights`` connection under a
nested ``ads`` edge has had version-to-version quirks and is not exercised
by this codebase's test suite (no live Meta API access at build time).
Pass ``include_insights=True`` only after confirming the exact modifier
syntax (``insights.date_preset(...).limit(...)``) behaves as expected
against your actual ad account and API version — the standalone, flat
:class:`~app.services.meta.insights.InsightsSyncService` is the
well-exercised path for insights and should remain the default choice.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.meta_registry import (
    AD_FIELDS,
    ADSET_FIELDS,
    CAMPAIGN_FIELDS,
    get_insights_fields,
)
from app.models.raw_dump import MetaObjectType
from app.services.meta.base import BaseMetaSyncService

#: Max children embedded per nested edge (ad sets per campaign, ads per ad
#: set). Raise for accounts with denser hierarchies; each unit costs
#: response size/complexity, not extra API calls.
DEFAULT_NESTED_LIMIT = 100

#: Max campaigns fetched per top-level page (this level paginates normally).
DEFAULT_PAGE_SIZE = 25


class CampaignTreeSyncService(BaseMetaSyncService):
    endpoint_name = "campaign_tree"
    object_type = MetaObjectType.CAMPAIGN_TREE
    is_nested = True

    async def fetch_records(
        self, request_params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        campaign_fields = request_params.get("campaign_fields") or CAMPAIGN_FIELDS
        adset_fields = request_params.get("adset_fields") or ADSET_FIELDS
        ad_fields = list(request_params.get("ad_fields") or AD_FIELDS)
        nested_limit = int(request_params.get("nested_limit", DEFAULT_NESTED_LIMIT))
        page_size = int(request_params.get("page_size", DEFAULT_PAGE_SIZE))

        ad_fields_expr = ",".join(ad_fields)
        if request_params.get("include_insights"):
            insights_fields = request_params.get("insights_fields") or get_insights_fields(
                include_groups=["identity", "spend", "delivery", "rate_and_cost"]
            )
            date_preset = request_params.get("insights_date_preset", "last_30d")
            insights_limit = int(request_params.get("insights_limit", 31))
            ad_fields_expr += (
                f",insights.date_preset({date_preset}).limit({insights_limit})"
                f"{{{','.join(insights_fields)}}}"
            )

        nested_fields = (
            ",".join(campaign_fields)
            + f",adsets.limit({nested_limit})"
            + "{"
            + ",".join(adset_fields)
            + f",ads.limit({nested_limit})"
            + "{"
            + ad_fields_expr
            + "}}"
        )

        params: dict[str, Any] = {"fields": nested_fields}
        async for campaign in self.client.paginate(
            f"{self.client.credentials.ad_account_id_prefixed}/campaigns",
            params=params,
            page_size=page_size,
        ):
            yield campaign

    def extract_parent_ids(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {"account_id": item.get("account_id", self.client.credentials.ad_account_id)}
