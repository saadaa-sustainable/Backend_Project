"""Silver-layer flatten for Google Ads campaign / ad group / ad entities.

The counterpart of app/services/meta/entity_flatten.py, and deliberately
the same shape: Bronze (``raw_dump_google_ads``) accumulates one row per
object per fetch, and this collapses it to three current-state Silver
tables -- ``google_campaigns``, ``google_ad_groups``, ``google_ads`` --
one row per entity, newest snapshot wins.

Column names mirror ``meta_campaigns`` / ``meta_adsets`` / ``meta_ads``
where the concepts line up (``campaign_id``, ``campaign_name``,
``campaign_status``, ``ad_id``, ``ad_name``, ``ad_status``) so a reader
does not have to learn two vocabularies, and parent names are joined in
here rather than left to callers.

WHY SILVER OUTLIVES THE API
---------------------------
Google ages removed campaigns and ads out of GAQL. Because Bronze is
append-only, an entity fetched once is still in Bronze after Google
stops returning it, so this flatten keeps deriving its name forever and
attribution for a closed month does not silently change. ``first_seen``
is therefore ``min(extracted_at)`` across every Bronze snapshot, not a
value this table has to defend against being overwritten.

AD NAMES ARE OFTEN BLANK, HENCE ad_label
----------------------------------------
Google does not require an ad name. Measured 2026-10-21, 50 of 440 ads
have none -- including ALL 32 responsive search ads, the type most
likely to produce an ad-level order match. ``ad_name`` keeps the raw
truth, blanks included, so nobody has to guess later which blanks were
real; ``ad_label`` is NOT NULL and falls back to the ad type and id.
Reporting and attribution join to ``ad_label``.

Each statement is executed individually (never semicolon-joined into one
call) -- asyncpg's extended query protocol rejects multiple commands in a
single prepared statement.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS google_campaigns (
        campaign_id      text PRIMARY KEY,
        campaign_name    text,
        campaign_status  text,
        serving_status   text,
        channel_type     text,
        bid_strategy     text,
        start_at         timestamp,
        end_at           timestamp,
        first_seen       timestamptz,
        snapshot_at      timestamptz,
        updated_at       timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS google_ad_groups (
        ad_group_id      text PRIMARY KEY,
        ad_group_name    text,
        ad_group_status  text,
        ad_group_type    text,
        campaign_id      text,
        campaign_name    text,
        first_seen       timestamptz,
        snapshot_at      timestamptz,
        updated_at       timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS google_ads (
        ad_id            text PRIMARY KEY,
        ad_name          text,
        ad_label         text NOT NULL,
        ad_status        text,
        ad_type          text,
        ad_group_id      text,
        ad_group_name    text,
        campaign_id      text,
        campaign_name    text,
        first_seen       timestamptz,
        snapshot_at      timestamptz,
        updated_at       timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_google_ads_campaign ON google_ads(campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_google_ads_ad_group ON google_ads(ad_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_google_ad_groups_campaign "
    "    ON google_ad_groups(campaign_id)",
]

#: `start_date_time` arrives as "2020-12-05 02:05:05" -- account-local,
#: with no offset. Cast to `timestamp`, never `timestamptz`, or Postgres
#: stamps it UTC and the value silently moves.
#:
#: DISTINCT ON picks the newest snapshot per entity; the window function
#: beside it carries the oldest `extracted_at` through as `first_seen`,
#: so one pass over Bronze yields both.
_LATEST = """
SELECT DISTINCT ON (google_id)
       google_id,
       raw_payload,
       extracted_at,
       min(extracted_at) OVER (PARTITION BY google_id) AS first_seen
  FROM raw_dump_google_ads
 WHERE object_type = :object_type
 ORDER BY google_id, extracted_at DESC, ingested_at DESC
"""

_CAMPAIGNS_SQL = f"""
WITH latest AS ({_LATEST})
INSERT INTO google_campaigns
    (campaign_id, campaign_name, campaign_status, serving_status,
     channel_type, bid_strategy, start_at, end_at,
     first_seen, snapshot_at, updated_at)
SELECT google_id,
       raw_payload -> 'campaign' ->> 'name',
       raw_payload -> 'campaign' ->> 'status',
       raw_payload -> 'campaign' ->> 'servingStatus',
       raw_payload -> 'campaign' ->> 'advertisingChannelType',
       raw_payload -> 'campaign' ->> 'biddingStrategyType',
       (raw_payload -> 'campaign' ->> 'startDateTime')::timestamp,
       (raw_payload -> 'campaign' ->> 'endDateTime')::timestamp,
       first_seen, extracted_at, now()
  FROM latest
ON CONFLICT (campaign_id) DO UPDATE SET
    campaign_name   = EXCLUDED.campaign_name,
    campaign_status = EXCLUDED.campaign_status,
    serving_status  = EXCLUDED.serving_status,
    channel_type    = EXCLUDED.channel_type,
    bid_strategy    = EXCLUDED.bid_strategy,
    start_at        = EXCLUDED.start_at,
    end_at          = EXCLUDED.end_at,
    first_seen      = EXCLUDED.first_seen,
    snapshot_at     = EXCLUDED.snapshot_at,
    updated_at      = EXCLUDED.updated_at
"""

_AD_GROUPS_SQL = f"""
WITH latest AS ({_LATEST})
INSERT INTO google_ad_groups
    (ad_group_id, ad_group_name, ad_group_status, ad_group_type,
     campaign_id, campaign_name, first_seen, snapshot_at, updated_at)
SELECT google_id,
       raw_payload -> 'adGroup' ->> 'name',
       raw_payload -> 'adGroup' ->> 'status',
       raw_payload -> 'adGroup' ->> 'type',
       raw_payload -> 'campaign' ->> 'id',
       raw_payload -> 'campaign' ->> 'name',
       first_seen, extracted_at, now()
  FROM latest
ON CONFLICT (ad_group_id) DO UPDATE SET
    ad_group_name   = EXCLUDED.ad_group_name,
    ad_group_status = EXCLUDED.ad_group_status,
    ad_group_type   = EXCLUDED.ad_group_type,
    campaign_id     = EXCLUDED.campaign_id,
    campaign_name   = EXCLUDED.campaign_name,
    first_seen      = EXCLUDED.first_seen,
    snapshot_at     = EXCLUDED.snapshot_at,
    updated_at      = EXCLUDED.updated_at
"""

#: initcap(replace(type,'_',' ')) turns SHOPPING_SMART_AD into
#: "Shopping Smart Ad", so a nameless ad reads as something a human can
#: place rather than a bare id.
_ADS_SQL = f"""
WITH latest AS ({_LATEST})
INSERT INTO google_ads
    (ad_id, ad_name, ad_label, ad_status, ad_type, ad_group_id,
     ad_group_name, campaign_id, campaign_name,
     first_seen, snapshot_at, updated_at)
SELECT google_id,
       raw_payload -> 'adGroupAd' -> 'ad' ->> 'name',
       COALESCE(
           NULLIF(BTRIM(raw_payload -> 'adGroupAd' -> 'ad' ->> 'name'), ''),
           INITCAP(REPLACE(COALESCE(
               raw_payload -> 'adGroupAd' -> 'ad' ->> 'type', 'AD'), '_', ' '))
           || ' ' || google_id),
       raw_payload -> 'adGroupAd' ->> 'status',
       raw_payload -> 'adGroupAd' -> 'ad' ->> 'type',
       raw_payload -> 'adGroup' ->> 'id',
       raw_payload -> 'adGroup' ->> 'name',
       raw_payload -> 'campaign' ->> 'id',
       raw_payload -> 'campaign' ->> 'name',
       first_seen, extracted_at, now()
  FROM latest
ON CONFLICT (ad_id) DO UPDATE SET
    ad_name       = EXCLUDED.ad_name,
    ad_label      = EXCLUDED.ad_label,
    ad_status     = EXCLUDED.ad_status,
    ad_type       = EXCLUDED.ad_type,
    ad_group_id   = EXCLUDED.ad_group_id,
    ad_group_name = EXCLUDED.ad_group_name,
    campaign_id   = EXCLUDED.campaign_id,
    campaign_name = EXCLUDED.campaign_name,
    first_seen    = EXCLUDED.first_seen,
    snapshot_at   = EXCLUDED.snapshot_at,
    updated_at    = EXCLUDED.updated_at
"""

_STEPS = (
    ("google_campaigns", "campaign", _CAMPAIGNS_SQL),
    ("google_ad_groups", "ad_group", _AD_GROUPS_SQL),
    ("google_ads", "ad", _ADS_SQL),
)


async def refresh_google_entity_tables(session: AsyncSession) -> dict[str, int]:
    """Rebuild the three Google Silver tables from Bronze.

    Upsert rather than TRUNCATE-and-insert: Bronze is the only source, so
    a rebuild is idempotent either way, but upserting leaves the tables
    readable throughout -- the order-attribution rebuild reads
    ``google_ads`` and must never find it momentarily empty.
    """
    for statement in _DDL_STATEMENTS:
        await session.execute(text(statement))

    counts: dict[str, int] = {}
    for table, object_type, sql in _STEPS:
        await session.execute(text(sql), {"object_type": object_type})
        counts[table] = (
            await session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar_one()

    await session.commit()
    logger.info("google_entities_flattened", **counts)
    return counts
