"""Per-ad performance + category classification table -- this project's
equivalent of the legacy CTD's `ae_raw_view` / `summary_table`. One row
per unique ad_id, carrying EVERY raw metric from ad_insights (all ~169
Insights registry fields -- spend, impressions, ctr, cpm, video metrics,
quality rankings, the works) plus current ad_status/ad_effective_status
from meta_ads, plus a set of computed formula columns (ratios, F1-F4 pass
flags, Winner/Loser category) on top. Explicit user choice 2026-08-24:
this table should be the single wide "everything about this ad" table,
not a narrow curated subset -- ad_insights' full column set is carried
through via `ai.*` rather than re-selected field by field.

F1-F4 thresholds and the category logic below were an open ruling in this
project (5 disagreeing sources in the legacy repo -- see
docs/ctd_computation_logic_reference.md's "Open items" section) explicitly
settled by the user 2026-08-21:
    F1 = impressions >= 50,000
    F2 = conv_value / spend >= 3.0        (legacy code used 3.2; GUIDEBOOK.md's
                                            prose said 3 -- user picked 3.0)
    F3 = spend / ncp_count <= 525
    F4 = spend / ftewv_count <= 12        (legacy refresh_summary_table.py used
                                            25; refresh_ae_table.py + the
                                            dashboard's own toggle default used
                                            12 -- user picked 12)
    Incremental Winner = F1 AND (F2 OR F3) AND F4   (matches the live
                                            production CASE statement, not the
                                            user's own carry-forward doc's
                                            all-AND structure -- user picked
                                            the live-code version)

NCP/FTEWV resolution: exact custom-conversion name match ("NCP" /
"First-time EWV") -- also an explicit user ruling, with one correction
made after checking real data: custom-conversion ids are matched GLOBALLY
across every account, not scoped to the account_id the custom_conversion
entity happened to be fetched under. Confirmed live 2026-08-24 that the
same custom-conversion ids fire in OTHER accounts' ad-level actions (e.g.
id 1133449967928420, "First-time EWV", registered under Third Ad Account
- SD's account_id, appears 54 times in Fourth Ad Account - SD's own
insights actions) -- Meta custom conversions can be shared at the
Business Manager level across ad accounts, so account-scoping the match
would silently miss real conversions on any account that didn't happen to
have that custom_conversion entity fetched under its own account_id.
Real data also found MULTIPLE custom conversions literally named "NCP"
(ids 1109740267306786 and 1532250197416964) -- summed together per user's
tie-break choice, not picked arbitrarily.

Column-collision note: ad_insights already carries a raw `frequency` field
straight from Meta (Meta computes it itself) -- deliberately NOT
recomputed here as impressions/reach, to avoid a duplicate-column error
in `SELECT ai.*, ...` and because Meta's own value is authoritative.

IMPORTANT CAVEAT this table does NOT yet resolve: "lifetime" here means
whatever ad_insights currently holds -- which reflects each ad's MOST
RECENTLY FETCHED sync window (see app/services/silver/insights_flatten.py's
own caveat), not a true all-time cumulative total the way the legacy
ae_raw_view/summary_table aggregated across primary_table UNION
backfill_table's full history. Building genuine lifetime totals needs a
dedicated ad-level Insights fetch with date_preset=maximum -- deferred by
explicit user choice (2026-08-21) to build this logic first and swap in
real lifetime data later. Treat every metric here as "as of the last
sync," not "ever."

Extra formula columns added 2026-08-24 to match the legacy `primary_table`
schema (cost_per_purchase, thruplays, three_sec_video_plays,
video_play_time, outbound_clicks_count, post_engagements,
engagement_count) -- extraction logic copied verbatim from the legacy
repo's primary_sync.py (re-cloned fresh, not from memory):
  three_sec_video_plays = _action_val(actions, "video_view")
  thruplays             = video_thruplay_watched_actions[0].value
  video_play_time       = video_avg_time_watched_actions[0].value
  outbound_clicks_count = outbound_clicks[0].value  (renamed from primary_table's
                           bare "outbound_clicks" -- that name is already taken by
                           ad_insights' own raw jsonb column of the same name,
                           carried through via ai.*)
  post_engagements      = raw inline_post_engagement field, aliased to
                           primary_table's column name
  engagement_count       = thruplays + comments + reactions + saves + shares
                           + likes + link_clicks ("Simran Jadon formula" per
                           the legacy source's own comment), where:
    comments   = _action_val(actions, "comment")
    reactions  = _action_val(actions, "post_reaction")
    shares     = _action_val(actions, "post")   -- Meta names the share action "post"
    saves      = _action_val(actions, "onsite_conversion.post_save")
    likes      = _action_val(actions, "like")

Two primary_table fields deliberately NOT added -- they need data this
project hasn't fetched yet, not just a formula:
- `ltv_reach` / `ltv_frequency`: NOT derived from ad-level Insights at all
  in the legacy pipeline -- a separate lifetime-only reach/frequency fetch
  per ad (no date breakdown). Needs a dedicated fetch to build, same as
  the "lifetime totals" caveat below.
- `preview_link` / `ad_link` / `url_tags`: come from the ad's CREATIVE
  object (link_url/object_url/url_tags), not Insights. This project has
  never fetched `object_type='creative'` at all yet (checked live
  2026-08-24 -- zero creative rows in raw_dump_meta) -- needs a creative
  entity fetch + a matching Silver flatten before these can be built.

Also NOT built here (out of scope for this pass, revisit if needed):
- Shopify enrichment (shopify_orders/shopify_sales/shopify_roas) -- no
  Shopify Silver layer exists yet.
- F1-hit-date / days_to_result / date_of_result -- these need day-by-day
  historical grain (primary_table/backfill_table's daily rows); ad_insights
  is a single aggregated snapshot per entity, not a daily time series.
- Fleet-wide "anchor" efficiency scoring (x_cpr_eff, y_ftv_contrib_eff,
  etc.) -- a further analytical layer on top of this one, not requested.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger
from app.services.silver.insights_flatten import ENVELOPE_BY_LEVEL, FIELD_TYPES

logger = get_logger(__name__)

# Every column ad_insights has (envelope + date_start/date_stop + all Insights
# registry fields + extracted_at/updated_at), so ad_lifecycle's DDL always
# matches ad_insights' actual shape without hand-duplicating 169+ field names.
_AD_INSIGHTS_COLUMNS: list[tuple[str, str]] = (
    [(c, "text") for c in ENVELOPE_BY_LEVEL["ad"]]
    + [("date_start", "date"), ("date_stop", "date")]
    + [(f, t) for f, t in sorted(FIELD_TYPES.items()) if f not in ENVELOPE_BY_LEVEL["ad"] and f not in ("date_start", "date_stop")]
    + [("extracted_at", "timestamptz"), ("updated_at", "timestamptz")]
)

_COMPUTED_COLUMNS: list[tuple[str, str]] = [
    ("ad_status", "text"),
    ("ad_effective_status", "text"),
    ("ad_created_time", "timestamptz"),
    ("purchases", "numeric"),
    ("conv_value", "numeric"),
    ("checkout_initiate", "numeric"),
    ("add_to_cart", "numeric"),
    ("ncp_count", "numeric"),
    ("ftewv_count", "numeric"),
    ("cost_per_purchase", "numeric"),
    ("thruplays", "numeric"),
    ("three_sec_video_plays", "numeric"),
    ("video_play_time", "numeric"),
    ("outbound_clicks_count", "numeric"),
    ("post_engagements", "numeric"),
    ("engagement_count", "numeric"),
    ("ctr_pct", "numeric"),
    ("cpc_link", "numeric"),
    ("cpr_1000", "numeric"),
    ("checkout_compl_pct", "numeric"),
    ("cr_lc_pct", "numeric"),
    ("atc_lc_pct", "numeric"),
    ("ci_atc_pct", "numeric"),
    ("roas", "numeric"),
    ("cost_per_ncp", "numeric"),
    ("cost_per_ftewv", "numeric"),
    ("profit_efficiency", "numeric"),
    ("contrib_margin_pct", "numeric"),
    ("f1_pass", "boolean"),
    ("f2_pass", "boolean"),
    ("f3_pass", "boolean"),
    ("f4_pass", "boolean"),
    ("category", "text"),
    ("lifecycle_refreshed_at", "timestamptz"),
]


# Human-readable mirror of the SQL in `_INSERT` below, keyed by column name --
# exists purely so the Schema Browser (admin.py's `/admin/tables`) can show
# "how was this computed" next to a customised column instead of that only
# living in this file's SQL. Keep in sync by hand when `_INSERT` changes --
# no code generates one from the other, deliberately (the SQL is written for
# Postgres to execute; this is written for a human skimming the UI).
COLUMN_FORMULAS: dict[str, str] = {
    "ad_status": "meta_ads.ad_status (joined on ad_id)",
    "ad_effective_status": "meta_ads.ad_effective_status (joined on ad_id)",
    "ad_created_time": "meta_ads.created_time (joined on ad_id)",
    "purchases": "first match in actions[]: omni_purchase, else purchase",
    "conv_value": "first match in action_values[]: omni_purchase, else purchase",
    "checkout_initiate": "first match in actions[]: omni_initiated_checkout, else initiate_checkout",
    "add_to_cart": "first match in actions[]: omni_add_to_cart, else add_to_cart",
    "ncp_count": "SUM(actions[] where action_type = 'offsite_conversion.custom.<id>') for every custom-conversion id named \"NCP\" (matched globally across accounts, summed if more than one exists)",
    "ftewv_count": "SUM(actions[] where action_type = 'offsite_conversion.custom.<id>') for every custom-conversion id named \"First-time EWV\" (matched globally across accounts)",
    "cost_per_purchase": "spend / purchases",
    "thruplays": "video_thruplay_watched_actions[0].value",
    "three_sec_video_plays": "actions[] match action_type = video_view",
    "video_play_time": "video_avg_time_watched_actions[0].value",
    "outbound_clicks_count": "outbound_clicks[0].value",
    "post_engagements": "inline_post_engagement (raw Insights field, renamed)",
    "engagement_count": "thruplays + comments + reactions + saves + shares + likes + inline_link_clicks (\"Simran Jadon formula\")",
    "ctr_pct": "inline_link_clicks / impressions * 100",
    "cpc_link": "spend / inline_link_clicks",
    "cpr_1000": "spend / reach * 1000",
    "checkout_compl_pct": "purchases / checkout_initiate * 100",
    "cr_lc_pct": "purchases / inline_link_clicks * 100",
    "atc_lc_pct": "add_to_cart / inline_link_clicks * 100",
    "ci_atc_pct": "checkout_initiate / add_to_cart * 100",
    "roas": "conv_value / spend",
    "cost_per_ncp": "spend / ncp_count",
    "cost_per_ftewv": "spend / ftewv_count",
    "profit_efficiency": "conv_value - spend",
    "contrib_margin_pct": "(1 - spend / conv_value) * 100, else -100 if conv_value is 0",
    "f1_pass": "impressions >= 50,000",
    "f2_pass": "spend > 0 AND conv_value / spend >= 3.0",
    "f3_pass": "ncp_count > 0 AND spend / ncp_count <= 525",
    "f4_pass": "ftewv_count > 0 AND spend / ftewv_count <= 12",
    "category": (
        "F1 AND (F2 OR F3) AND F4 -> Incremental Winner; "
        "F1 AND (F2 OR F3) -> Winner; "
        "F1 AND F4 -> P0 analysis; "
        "F1 only -> P1 analysis; "
        "F2 only -> P2 analysis; "
        "ad created < 14 days ago -> Result Awaited; "
        "else -> Discarded"
    ),
    "lifecycle_refreshed_at": "now() at the time this row was last (re)computed",
}


def _ddl_statements() -> list[str]:
    cols = [f"{name} {sql_type}" for name, sql_type in _AD_INSIGHTS_COLUMNS]
    cols[0] = cols[0] + " PRIMARY KEY"  # ad_id, always first
    cols += [f"{name} {sql_type}" for name, sql_type in _COMPUTED_COLUMNS]
    return [
        "CREATE TABLE IF NOT EXISTS ad_lifecycle (\n  " + ",\n  ".join(cols) + "\n)",
        "CREATE INDEX IF NOT EXISTS ix_ad_lifecycle_account_name ON ad_lifecycle (account_name)",
        "CREATE INDEX IF NOT EXISTS ix_ad_lifecycle_campaign_id ON ad_lifecycle (campaign_id)",
        "CREATE INDEX IF NOT EXISTS ix_ad_lifecycle_category ON ad_lifecycle (category)",
    ]


# `INSERT INTO table SELECT ...` (no target column list) maps SELECT's output
# columns to the target table POSITIONALLY -- if the DDL's column order and the
# SELECT's column order ever drifted apart (e.g. ad_insights' real column order
# not exactly matching this module's Python-side reconstruction of it), values
# would land in the WRONG columns silently. Both the INSERT's target list and
# the raw-column half of its SELECT list are generated from the SAME
# _AD_INSIGHTS_COLUMNS names below specifically to rule that out -- a genuine
# name mismatch fails loudly ("column ai.x does not exist") instead of
# silently misaligning.
_INSERT_TARGET_COLUMNS = ", ".join(name for name, _ in _AD_INSIGHTS_COLUMNS + _COMPUTED_COLUMNS)
_AI_COLUMN_LIST = ",\n    ".join(f"ai.{name}" for name, _ in _AD_INSIGHTS_COLUMNS)


_TRUNCATE = "TRUNCATE ad_lifecycle"

# _action_val(actions_or_values, *types): first matching action_type wins,
# NOT summed -- matches the legacy primary_sync.py helper exactly (omni_*
# names are Meta's newer naming, the bare name is the fallback for older
# accounts/objectives that don't emit the omni_ variant).
def _first_match(column: str, *action_types: str) -> str:
    parts = "\n            ".join(
        f"(SELECT (elem ->> 'value')::numeric FROM jsonb_array_elements(COALESCE(ai.{column}, '[]'::jsonb)) elem "
        f"WHERE elem ->> 'action_type' = '{t}' LIMIT 1),"
        for t in action_types
    )
    return f"COALESCE(\n            {parts}\n            0\n        )"


_INSERT = f"""
INSERT INTO ad_lifecycle ({_INSERT_TARGET_COLUMNS})
WITH ncp_ids AS (
    -- Global, not account-scoped -- custom-conversion ids are shared across ad
    -- accounts at the Business Manager level (confirmed live, see module docstring).
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'NCP'
),
ftewv_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'First-time EWV'
),
calc AS (
    SELECT
        ai.ad_id,
        {_first_match("actions", "omni_purchase", "purchase")} AS purchases,
        {_first_match("action_values", "omni_purchase", "purchase")} AS conv_value,
        {_first_match("actions", "omni_initiated_checkout", "initiate_checkout")} AS checkout_initiate,
        {_first_match("actions", "omni_add_to_cart", "add_to_cart")} AS add_to_cart,
        {_first_match("actions", "video_view")} AS three_sec_video_plays,
        {_first_match("actions", "comment")} AS post_comments,
        {_first_match("actions", "post_reaction")} AS post_reactions,
        {_first_match("actions", "onsite_conversion.post_save")} AS post_saves,
        {_first_match("actions", "post")} AS post_shares,
        {_first_match("actions", "like")} AS page_likes,
        COALESCE((ai.video_thruplay_watched_actions -> 0 ->> 'value')::numeric, 0) AS thruplays,
        COALESCE((ai.video_avg_time_watched_actions -> 0 ->> 'value')::numeric, 0) AS video_play_time,
        COALESCE((ai.outbound_clicks -> 0 ->> 'value')::numeric, 0) AS outbound_clicks_count,
        COALESCE((
            SELECT SUM((elem ->> 'value')::numeric)
            FROM jsonb_array_elements(COALESCE(ai.actions, '[]'::jsonb)) elem
            WHERE elem ->> 'action_type' = ANY (SELECT 'offsite_conversion.custom.' || id FROM ncp_ids)
        ), 0) AS ncp_count,
        COALESCE((
            SELECT SUM((elem ->> 'value')::numeric)
            FROM jsonb_array_elements(COALESCE(ai.actions, '[]'::jsonb)) elem
            WHERE elem ->> 'action_type' = ANY (SELECT 'offsite_conversion.custom.' || id FROM ftewv_ids)
        ), 0) AS ftewv_count
    FROM ad_insights ai
)
SELECT
    {_AI_COLUMN_LIST},
    ma.ad_status, ma.ad_effective_status, ma.created_time AS ad_created_time,
    c.purchases, c.conv_value, c.checkout_initiate, c.add_to_cart, c.ncp_count, c.ftewv_count,
    CASE WHEN c.purchases > 0 THEN COALESCE(ai.spend, 0) / c.purchases ELSE NULL END AS cost_per_purchase,
    c.thruplays, c.three_sec_video_plays, c.video_play_time, c.outbound_clicks_count,
    COALESCE(ai.inline_post_engagement, 0) AS post_engagements,
    (c.thruplays + c.post_comments + c.post_reactions + c.post_saves + c.post_shares + c.page_likes
        + COALESCE(ai.inline_link_clicks, 0)) AS engagement_count,
    CASE WHEN COALESCE(ai.impressions, 0) > 0
        THEN COALESCE(ai.inline_link_clicks, 0) / ai.impressions * 100 ELSE NULL END AS ctr_pct,
    CASE WHEN COALESCE(ai.inline_link_clicks, 0) > 0
        THEN COALESCE(ai.spend, 0) / ai.inline_link_clicks ELSE NULL END AS cpc_link,
    CASE WHEN COALESCE(ai.reach, 0) > 0
        THEN COALESCE(ai.spend, 0) / ai.reach * 1000 ELSE NULL END AS cpr_1000,
    CASE WHEN c.checkout_initiate > 0 THEN c.purchases / c.checkout_initiate * 100 ELSE NULL END AS checkout_compl_pct,
    CASE WHEN COALESCE(ai.inline_link_clicks, 0) > 0
        THEN c.purchases / ai.inline_link_clicks * 100 ELSE NULL END AS cr_lc_pct,
    CASE WHEN COALESCE(ai.inline_link_clicks, 0) > 0
        THEN c.add_to_cart / ai.inline_link_clicks * 100 ELSE NULL END AS atc_lc_pct,
    CASE WHEN c.add_to_cart > 0 THEN c.checkout_initiate / c.add_to_cart * 100 ELSE NULL END AS ci_atc_pct,
    CASE WHEN COALESCE(ai.spend, 0) > 0 THEN c.conv_value / ai.spend ELSE 0 END AS roas,
    CASE WHEN c.ncp_count > 0 THEN COALESCE(ai.spend, 0) / c.ncp_count ELSE NULL END AS cost_per_ncp,
    CASE WHEN c.ftewv_count > 0 THEN COALESCE(ai.spend, 0) / c.ftewv_count ELSE NULL END AS cost_per_ftewv,
    c.conv_value - COALESCE(ai.spend, 0) AS profit_efficiency,
    CASE WHEN COALESCE(ai.spend, 0) > 0 AND c.conv_value > 0
        THEN (1 - ai.spend / c.conv_value) * 100 ELSE -100 END AS contrib_margin_pct,
    (COALESCE(ai.impressions, 0) >= 50000) AS f1_pass,
    (COALESCE(ai.spend, 0) > 0 AND c.conv_value / ai.spend >= 3.0) AS f2_pass,
    (c.ncp_count > 0 AND COALESCE(ai.spend, 0) / c.ncp_count <= 525) AS f3_pass,
    (c.ftewv_count > 0 AND COALESCE(ai.spend, 0) / c.ftewv_count <= 12) AS f4_pass,
    CASE
        WHEN COALESCE(ai.impressions, 0) >= 50000
         AND ((COALESCE(ai.spend, 0) > 0 AND c.conv_value / ai.spend >= 3.0)
              OR (c.ncp_count > 0 AND ai.spend / c.ncp_count <= 525))
         AND c.ftewv_count > 0 AND ai.spend / c.ftewv_count <= 12
            THEN 'Incremental Winner'
        WHEN COALESCE(ai.impressions, 0) >= 50000
         AND ((COALESCE(ai.spend, 0) > 0 AND c.conv_value / ai.spend >= 3.0)
              OR (c.ncp_count > 0 AND ai.spend / c.ncp_count <= 525))
            THEN 'Winner'
        WHEN COALESCE(ai.impressions, 0) >= 50000 AND c.ftewv_count > 0 AND ai.spend / c.ftewv_count <= 12
            THEN 'P0 analysis'
        WHEN COALESCE(ai.impressions, 0) >= 50000
            THEN 'P1 analysis'
        WHEN COALESCE(ai.spend, 0) > 0 AND c.conv_value / ai.spend >= 3.0
            THEN 'P2 analysis'
        WHEN ma.created_time > now() - INTERVAL '14 days'
            THEN 'Result Awaited'
        ELSE 'Discarded'
    END AS category,
    now() AS lifecycle_refreshed_at
FROM ad_insights ai
LEFT JOIN meta_ads ma ON ma.ad_id = ai.ad_id
LEFT JOIN calc c ON c.ad_id = ai.ad_id
"""


async def ensure_ad_lifecycle_table(session: AsyncSession) -> None:
    for statement in _ddl_statements():
        await session.execute(text(statement))
    await session.commit()


async def refresh_ad_lifecycle(session: AsyncSession) -> dict[str, int]:
    await ensure_ad_lifecycle_table(session)
    await session.execute(text(_TRUNCATE))
    await session.execute(text(_INSERT))
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM ad_lifecycle"))
    count = result.scalar_one()
    logger.info("ad_lifecycle_refreshed", ad_lifecycle=count)
    return {"ad_lifecycle": count}
