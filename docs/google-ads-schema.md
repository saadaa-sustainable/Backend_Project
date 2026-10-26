# Google Ads: what we fetch, and what could be fetched

Measured against the live account on 2026-10-21, API **v24**, customer
`6770669478` (SAADAA) under manager `6989532543` (Saadaa MCC).

Everything below is schema — field names and types only, no campaign
names, spend or order data. This repo is public; keep it that way.

---

## 1. Bronze: `raw_dump_google_ads`

The counterpart of `raw_dump_meta`. Append-only, one row per object per
fetch, written by `scripts/fetch_google_ads_entities.py`. Column
vocabulary is lifted from `raw_dump_meta` on purpose so the two bronze
tables read the same way.

| column | type | notes |
|---|---|---|
| `id` | `uuid` | PK, generated per row |
| `object_type` | `varchar` | `campaign` \| `ad_group` \| `ad` |
| `google_id` | `varchar` | the object's own id |
| `parent_ids` | `jsonb` | `{"campaign_id":…, "ad_group_id":…}` where GAQL gave them |
| `raw_payload` | `jsonb` | **one whole GAQL result row**, unmodified |
| `api_endpoint` | `varchar` | `customers/{cid}/googleAds:searchStream` |
| `api_version` | `varchar` | e.g. `v24` |
| `batch_id` | `uuid` | one per run, all three object types share it |
| `request_params` | `jsonb` | `{"query": "<the GAQL>"}` |
| `extracted_at` | `timestamptz` | when the API was called |
| `ingested_at` | `timestamptz` | defaults `now()` |
| `sync_type` | `varchar` | `full_roster` |
| `payload_hash` | `varchar` | sha256 of the canonical payload |
| `processing_status` | `varchar` | defaults `pending` |

Indexes: `(object_type, google_id, extracted_at DESC)` and `(batch_id)`.

Volume: ~806 rows a run, ~294k a year. `raw_dump_meta` already holds
4.45M, so the honest append-only version costs nothing worth saving.

### What `raw_payload` holds

GAQL returns parents inline, so the shape differs per `object_type`:

```
campaign   {"campaign": {…}}
ad_group   {"adGroup": {…}, "campaign": {…}}
ad         {"adGroupAd": {"ad": {…}, …}, "adGroup": {…}, "campaign": {…}}
```

### Fields actually fetched today, with observed fill rates

**`object_type = 'campaign'`** — 192 rows
| JSON path | present |
|---|---|
| `campaign.resourceName` | 192 |
| `campaign.id` | 192 |
| `campaign.name` | 192 |
| `campaign.status` | 192 |
| `campaign.servingStatus` | 192 |
| `campaign.advertisingChannelType` | 192 |
| `campaign.biddingStrategyType` | 192 |
| `campaign.startDateTime` | 192 |
| `campaign.endDateTime` | **0** — every campaign is open-ended |

**`object_type = 'ad_group'`** — 174 rows
| JSON path | present |
|---|---|
| `adGroup.resourceName` / `.id` / `.name` / `.status` | 174 |
| `adGroup.type` | **97 of 174** |
| `campaign.resourceName` / `.id` / `.name` | 174 |

**`object_type = 'ad'`** — 440 rows
| JSON path | present |
|---|---|
| `adGroupAd.resourceName` / `.status` | 440 |
| `adGroupAd.ad.resourceName` / `.id` / `.type` | 440 |
| `adGroupAd.ad.name` | **390 of 440 (88.6%)** |
| `adGroup.resourceName` / `.id` / `.name` | 440 |
| `campaign.resourceName` / `.id` / `.name` | 440 |

### The three GAQL queries

```sql
-- campaign
SELECT campaign.id, campaign.name, campaign.status,
       campaign.serving_status, campaign.advertising_channel_type,
       campaign.bidding_strategy_type, campaign.start_date_time,
       campaign.end_date_time
FROM campaign

-- ad_group
SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.type,
       campaign.id, campaign.name
FROM ad_group

-- ad
SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.ad.type,
       ad_group_ad.status, ad_group.id, ad_group.name,
       campaign.id, campaign.name
FROM ad_group_ad
```

No date filter and no status filter: removed entities are fetched on
purpose, because an order from three months ago can name an ad since
deleted and skipping it would file a matchable order as unmatched.

---

## 2. Silver: current state, one row per entity

Built by `app/services/google/entity_flatten.py`
(`scripts/refresh_google_entities.py`), newest snapshot per entity wins.

### `google_campaigns` — 192 rows
| column | type |
|---|---|
| `campaign_id` | `text` PK |
| `campaign_name` | `text` |
| `campaign_status` | `text` |
| `serving_status` | `text` |
| `channel_type` | `text` |
| `bid_strategy` | `text` |
| `start_at` | `timestamp` |
| `end_at` | `timestamp` |
| `first_seen` | `timestamptz` |
| `snapshot_at` | `timestamptz` |
| `updated_at` | `timestamptz` |

### `google_ad_groups` — 174 rows
`ad_group_id` PK, `ad_group_name`, `ad_group_status`, `ad_group_type`,
`campaign_id`, `campaign_name`, `first_seen`, `snapshot_at`, `updated_at`

### `google_ads` — 440 rows
`ad_id` PK, `ad_name`, **`ad_label` NOT NULL**, `ad_status`, `ad_type`,
`ad_group_id`, `ad_group_name`, `campaign_id`, `campaign_name`,
`first_seen`, `snapshot_at`, `updated_at`

### `google_ads_spend_daily` — campaign × day metrics

Pre-existing, filled by `fetch_google_ads_spend.py` (MapleMonk BigQuery)
then overwritten by `fetch_google_ads_api.py` (the API, authoritative).
PK `(day, campaign_id)`; columns `campaign_name`, `campaign_status`,
`channel_type`, `spend`, `clicks`, `impressions`, `conversions`,
`conv_value`, `fetched_at`, `source`.

This one does **not** have a bronze layer — it writes a final table
directly. A known inconsistency with the layering above.

---

## 3. What else could be fetched

The v24 schema, read from Google's own `googleAdsFields:search`:

| category | fields |
|---|---|
| ATTRIBUTE | 2,434 |
| METRIC | 278 |
| RESOURCE | 183 |
| SEGMENT | 155 |
| **total** | **3,050** (2,778 selectable) |

Selectable fields on the resources we already query: `campaign.` 138,
`ad_group.` 52, `ad_group_ad.` 184.

### `campaign.*` scalar attributes (35)

`accessible_bidding_strategy`, `ad_serving_optimization_status`,
`advertising_channel_sub_type`, `advertising_channel_type`,
`base_campaign`, `bidding_strategy`, `bidding_strategy_system_status`,
`bidding_strategy_type`, `brand_guidelines_enabled`, `campaign_budget`,
`campaign_group`, `contains_eu_political_advertising`, `end_date_time`,
`excluded_parent_asset_field_types`, `excluded_parent_asset_set_types`,
`experiment_type`, `feed_types`, `final_url_suffix`,
`hotel_property_asset_set`, `id`, `keyword_match_type`, `labels`,
`listing_type`, `missing_eu_political_advertising_declaration`, `name`,
`optimization_score`, `payment_mode`, `primary_status`,
`primary_status_reasons`, `resource_name`, `serving_status`,
`start_date_time`, `status`, `tracking_url_template`,
`view_through_conversion_optimization_enabled`

Not currently taken and plausibly useful: `campaign_budget`,
`advertising_channel_sub_type`, `optimization_score`, `primary_status`,
`labels`, `tracking_url_template`, `final_url_suffix`.

### `ad_group.*` scalar attributes (35)

`ad_rotation_mode`, `base_ad_group`, `campaign`, `cpc_bid_micros`,
`cpm_bid_micros`, `cpv_bid_micros`, `display_custom_bid_dimension`,
`effective_cpc_bid_micros`, `effective_target_cpa_micros`,
`effective_target_cpa_source`, `effective_target_cpc`,
`effective_target_cpc_source`, `effective_target_roas`,
`effective_target_roas_source`, `exclude_demographic_expansion`,
`excluded_parent_asset_field_types`, `excluded_parent_asset_set_types`,
`final_url_suffix`, `fixed_cpm_micros`, `id`, `labels`, `name`,
`optimized_targeting_enabled`, `percent_cpc_bid_micros`,
`primary_status`, `primary_status_reasons`, `resource_name`, `status`,
`target_cpa_micros`, `target_cpc_micros`, `target_cpm_micros`,
`target_cpv_micros`, `target_roas`, `tracking_url_template`, `type`

### `ad_group_ad.*` wrapper (10)

`action_items`, `ad_group`, `ad_strength`, `end_date_time`, `labels`,
`primary_status`, `primary_status_reasons`, `resource_name`,
`start_date_time`, `status`

`ad_strength` is Google's own creative-quality grade — the nearest
Google equivalent to a creative verdict.

### `ad_group_ad.ad.*` scalars (12)

`added_by_google_ads`, `device_preference`, `display_url`,
`final_mobile_urls`, `final_url_suffix`, `final_urls`, `id`, `name`,
`resource_name`, `system_managed_resource_source`,
`tracking_url_template`, `type`

`final_urls` is the landing page, which would join to the existing
landing-page analysis. The creative text itself lives in typed
sub-messages (`ad.responsive_search_ad.headlines` etc.), one shape per
ad type — not scalars, so it needs per-type handling.

### `metrics.*` — the ecommerce-relevant subset of 278

`cost_micros`, `clicks`, `impressions`, `ctr`, `average_cpc`,
`average_cpm`, `average_cost`, `interactions`, `interaction_rate`,
`conversions`, `conversions_value`, `conversions_by_conversion_date`,
`conversions_value_by_conversion_date`, `cost_per_conversion`,
`value_per_conversion`, `conversions_from_interactions_rate`,
`conversions_value_per_cost`, `all_conversions`,
`all_conversions_value`, `cost_per_all_conversions`,
`value_per_all_conversions`, `cross_device_conversions`,
`cross_device_conversions_value`, `view_through_conversions`,
`cost_of_goods_sold_micros`, `search_impression_share` (Search only),
`relative_ctr`, `invalid_clicks`, `organic_clicks`, `organic_impressions`

> **Trap, already paid for once.** `conversions_value` is PRIMARY
> conversion actions only and is what the media plan and
> `meta.conv_value` compare with. `all_conversions_value` counts every
> secondary action and read **Rs 456,427,216 against Rs 7,053,096** over
> the same 30 days — 65×. Using it puts a fictional number in MER.

### `segments.*` — 155

Time: `date`, `day_of_week`, `week`, `month`, `month_of_year`,
`quarter`, `year`, `hour`.
Delivery: `device`, `ad_network_type`, `ad_sub_network_type`, `slot`,
`click_type`, `ad_format_type`, `ad_destination_type`.
Conversions: `conversion_action`, `conversion_action_name`,
`conversion_action_category`, `conversion_lag_bucket`,
`conversion_attribution_event_type`, `external_conversion_source`,
`new_versus_returning_customers`.
Search: `search_term`, `match_type`, `keyword.info.text`,
`keyword.info.match_type`, `search_term_match_type`.
Geo: `geo_target_country/state/city/region/postal_code/metro/…`.
Structure: `campaign`, `ad_group`, `asset_group`.

**Shopping / PMax product segments** — the ones that reach SKU level:
`product_item_id`, `product_title`, `product_brand`,
`product_category_level1..5`, `product_type_l1..l5`, `product_channel`,
`product_condition`, `product_custom_attribute0..4`,
`product_feed_label`, `product_merchant_id`, `product_store_id`, plus
the `product_sold_*` family for what the conversion actually sold.

`segments.product_item_id` is the direct route to Google spend per SKU,
which is what the existing CPIS / SKU work has for Meta and not for
Google.

---

## 4. Traps found the hard way

1. **`campaign.start_date` and `campaign.end_date` do not exist in
   v24.** They answer `UNRECOGNIZED_FIELD`. The names are
   `start_date_time` / `end_date_time`.
2. **Those return account-local datetimes with no offset**
   (`"2020-12-05 02:05:05"`). Cast to `timestamp`, never `timestamptz`,
   or Postgres stamps them UTC and the value silently moves.
3. **11% of ads have no name** — 50 of 440, including **all 32
   responsive search ads**. Join to `google_ads.ad_label`, never
   `ad_name`.
4. **PMax has asset groups, not ad groups or ads.** It cannot emit
   `{adgroupid}` or `{creative}`, so the campaign is the deepest honest
   level for it — 677 of 688 `campaign_only` orders were PMax.
5. **`sag_organic` is not an ad.** It marks Google's free product
   listings. Crediting it would overstate paid Google by ~41% of what
   the paid orders are worth.
6. **ValueTrack order does not match the parameter names.**
   `utm_campaign` = campaign id, `utm_term` = **ad group** id,
   `utm_content` = **ad** id. Meta's matcher reads `utm_term` as an ad
   *set*, so the two agree on content and disagree on term. Do not
   share code between them on that assumption.
7. **`googleAdsFields:search` takes no `FROM` clause.** Querying the
   schema is `SELECT name, category, data_type, selectable` and nothing
   more, or it answers `UNEXPECTED_FROM_CLAUSE`.
8. **Cost is free, quota is not.** No per-call fee; one GAQL query is
   one operation however many rows return, against 15,000/day on Basic
   access.
