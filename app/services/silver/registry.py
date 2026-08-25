"""Registry of known Bronze -> Silver flatten jobs.

Each entry names a *known* raw table this project actually builds a
flatten table from today — this is deliberately not "flatten any table
the user points at," since that requires column-mapping knowledge only a
human (or a lot more inference) has. Adding a new source (e.g. Shopify,
once it has a flatten target) means adding one entry here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.meta.entity_flatten import refresh_entity_tables
from app.services.silver.ad_lifecycle import refresh_ad_lifecycle
from app.services.silver.insights_flatten import refresh_insights_tables
from app.services.silver.instagram_flatten import refresh_insta_data


@dataclass(frozen=True)
class FlattenJob:
    key: str
    label: str
    source_table: str
    target_tables: tuple[str, ...]
    refresh: Callable[[AsyncSession], Awaitable[dict[str, int]]]


FLATTEN_REGISTRY: dict[str, FlattenJob] = {
    "meta_entities": FlattenJob(
        key="meta_entities",
        label="Meta campaigns / adsets / ads",
        source_table="raw_dump_meta",
        target_tables=("meta_campaigns", "meta_adsets", "meta_ads"),
        refresh=refresh_entity_tables,
    ),
    "insta_data": FlattenJob(
        key="insta_data",
        label="Instagram media / account",
        source_table="dump_instagram",
        target_tables=("insta_data",),
        refresh=refresh_insta_data,
    ),
    "meta_insights": FlattenJob(
        key="meta_insights",
        label="Meta campaign / adset / ad Insights",
        source_table="raw_dump_meta",
        target_tables=("campaign_insights", "adset_insights", "ad_insights"),
        refresh=refresh_insights_tables,
    ),
    "ad_lifecycle": FlattenJob(
        key="ad_lifecycle",
        label="Ad performance + Winner/Loser category (ae_raw_view/summary_table equivalent)",
        # ad_insights is the primary driver (performance metrics change far more
        # often than ad_status) -- staleness checking only watches this one source,
        # so a meta_ads-only change (e.g. an ad getting paused) won't mark this job
        # stale on its own. Known simplification: FlattenJob only supports one
        # source_table today.
        source_table="ad_insights",
        target_tables=("ad_lifecycle",),
        refresh=refresh_ad_lifecycle,
    ),
}


def jobs_for_table(table_name: str) -> list[FlattenJob]:
    """Every job where `table_name` is either the source or one of the targets --
    used by the Schema Browser to decide which Flatten panel(s) to show for whatever
    table is open. A source table (e.g. raw_dump_meta) can back more than one job."""
    return [job for job in FLATTEN_REGISTRY.values() if table_name == job.source_table or table_name in job.target_tables]
