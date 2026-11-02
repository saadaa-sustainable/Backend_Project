# `ad_lifecycle`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,115 rows (planner estimate) · 62 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_name` | `text` | yes |  |
| 3 | `adset_id` | `text` | yes |  |
| 4 | `adset_name` | `text` | yes |  |
| 5 | `campaign_id` | `text` | yes |  |
| 6 | `campaign_name` | `text` | yes |  |
| 7 | `account_id` | `text` | yes |  |
| 8 | `account_name` | `text` | yes |  |
| 9 | `date_start` | `date` | yes |  |
| 10 | `date_stop` | `date` | yes |  |
| 11 | `account_currency` | `text` | yes |  |
| 12 | `action_values` | `jsonb` | yes |  |
| 13 | `actions` | `jsonb` | yes |  |
| 14 | `ad_click_actions` | `jsonb` | yes |  |
| 15 | `ad_impression_actions` | `jsonb` | yes |  |
| 16 | `adset_end` | `jsonb` | yes |  |
| 17 | `adset_start` | `jsonb` | yes |  |
| 18 | `anchor_event_attribution_setting` | `text` | yes |  |
| 19 | `anchor_events_performance_indicator` | `jsonb` | yes |  |
| 20 | `attribution_setting` | `text` | yes |  |
| 21 | `auction_bid` | `jsonb` | yes |  |
| 22 | `auction_competitiveness` | `jsonb` | yes |  |
| 23 | `auction_max_competitor_bid` | `jsonb` | yes |  |
| 24 | `buying_type` | `text` | yes |  |
| 25 | `canvas_avg_view_percent` | `numeric` | yes |  |
| 26 | `canvas_avg_view_time` | `numeric` | yes |  |
| 27 | `catalog_segment_actions` | `jsonb` | yes |  |
| 28 | `catalog_segment_value` | `jsonb` | yes |  |
| 29 | `catalog_segment_value_mobile_purchase_roas` | `jsonb` | yes |  |
| 30 | `catalog_segment_value_omni_purchase_roas` | `jsonb` | yes |  |
| 31 | `catalog_segment_value_website_purchase_roas` | `jsonb` | yes |  |
| 32 | `clicks` | `numeric` | yes |  |
| 33 | `conversion_lead_rate` | `jsonb` | yes |  |
| 34 | `conversion_rate_ranking` | `text` | yes |  |
| 35 | `conversion_values` | `jsonb` | yes |  |
| 36 | `conversions` | `jsonb` | yes |  |
| 37 | `converted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 38 | `converted_product_app_custom_event_fb_mobile_purchase_value` | `jsonb` | yes |  |
| 39 | `converted_product_offline_purchase` | `jsonb` | yes |  |
| 40 | `converted_product_offline_purchase_value` | `jsonb` | yes |  |
| 41 | `converted_product_omni_purchase` | `jsonb` | yes |  |
| 42 | `converted_product_omni_purchase_values` | `jsonb` | yes |  |
| 43 | `converted_product_quantity` | `jsonb` | yes |  |
| 44 | `converted_product_value` | `jsonb` | yes |  |
| 45 | `converted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 46 | `converted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 47 | `converted_promoted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 48 | `converted_promoted_product_app_custom_event_fb_mobile_purchase_` | `jsonb` | yes |  |
| 49 | `converted_promoted_product_offline_purchase` | `jsonb` | yes |  |
| 50 | `converted_promoted_product_offline_purchase_value` | `jsonb` | yes |  |
| 51 | `converted_promoted_product_omni_purchase` | `jsonb` | yes |  |
| 52 | `converted_promoted_product_omni_purchase_values` | `jsonb` | yes |  |
| 53 | `converted_promoted_product_quantity` | `jsonb` | yes |  |
| 54 | `converted_promoted_product_value` | `jsonb` | yes |  |
| 55 | `converted_promoted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 56 | `converted_promoted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 57 | `cost_per_15_sec_video_view` | `jsonb` | yes |  |
| 58 | `cost_per_2_sec_continuous_video_view` | `jsonb` | yes |  |
| 59 | `cost_per_action_type` | `jsonb` | yes |  |
| 60 | `cost_per_ad_click` | `jsonb` | yes |  |
| 61 | `cost_per_conversion` | `jsonb` | yes |  |
| 62 | `cost_per_conversion_lead` | `jsonb` | yes |  |
| 63 | `cost_per_dda_countby_convs` | `jsonb` | yes |  |
| 64 | `cost_per_estimated_ad_recallers` | `jsonb` | yes |  |
| 65 | `cost_per_inline_link_click` | `numeric` | yes |  |
| 66 | `cost_per_inline_post_engagement` | `numeric` | yes |  |
| 67 | `cost_per_objective_result` | `jsonb` | yes |  |
| 68 | `cost_per_one_thousand_ad_impression` | `jsonb` | yes |  |
| 69 | `cost_per_outbound_click` | `jsonb` | yes |  |
| 70 | `cost_per_result` | `jsonb` | yes |  |
| 71 | `cost_per_thruplay` | `jsonb` | yes |  |
| 72 | `cost_per_unique_action_type` | `jsonb` | yes |  |
| 73 | `cost_per_unique_click` | `numeric` | yes |  |
| 74 | `cost_per_unique_conversion` | `jsonb` | yes |  |
| 75 | `cost_per_unique_inline_link_click` | `numeric` | yes |  |
| 76 | `cost_per_unique_outbound_click` | `jsonb` | yes |  |
| 77 | `cpc` | `numeric` | yes |  |
| 78 | `cpm` | `numeric` | yes |  |
| 79 | `cpp` | `numeric` | yes |  |
| 80 | `created_time` | `timestamp with time zone` | yes |  |
| 81 | `creative_diversity_data` | `jsonb` | yes |  |
| 82 | `creative_diversity_label` | `text` | yes |  |
| 83 | `creative_diversity_score` | `text` | yes |  |
| 84 | `creative_fatigue_summary` | `jsonb` | yes |  |
| 85 | `creative_fatigued_ads` | `jsonb` | yes |  |
| 86 | `ctr` | `numeric` | yes |  |
| 87 | `dda_countby_convs` | `jsonb` | yes |  |
| 88 | `dda_results` | `jsonb` | yes |  |
| 89 | `engagement_rate_ranking` | `text` | yes |  |
| 90 | `estimated_ad_recall_rate` | `jsonb` | yes |  |
| 91 | `estimated_ad_recallers` | `jsonb` | yes |  |
| 92 | `frequency` | `numeric` | yes |  |
| 93 | `full_view_impressions` | `numeric` | yes |  |
| 94 | `full_view_reach` | `numeric` | yes |  |
| 95 | `impressions` | `numeric` | yes |  |
| 96 | `inline_link_click_ctr` | `numeric` | yes |  |
| 97 | `inline_link_clicks` | `numeric` | yes |  |
| 98 | `inline_post_engagement` | `numeric` | yes |  |
| 99 | `instagram_upcoming_event_reminders_set` | `numeric` | yes |  |
| 100 | `instant_experience_clicks_to_open` | `jsonb` | yes |  |
| 101 | `instant_experience_clicks_to_start` | `jsonb` | yes |  |
| 102 | `instant_experience_outbound_clicks` | `jsonb` | yes |  |
| 103 | `interactive_component_tap` | `jsonb` | yes |  |
| 104 | `landing_page_view_per_link_click` | `numeric` | yes |  |
| 105 | `marketing_messages_cost_per_delivered` | `numeric` | yes |  |
| 106 | `marketing_messages_cost_per_link_btn_click` | `numeric` | yes |  |
| 107 | `marketing_messages_delivered` | `numeric` | yes |  |
| 108 | `marketing_messages_delivery_rate` | `numeric` | yes |  |
| 109 | `marketing_messages_link_btn_click` | `numeric` | yes |  |
| 110 | `marketing_messages_media_view_rate` | `jsonb` | yes |  |
| 111 | `marketing_messages_phone_call_btn_click_rate` | `jsonb` | yes |  |
| 112 | `marketing_messages_quick_reply_btn_click_rate` | `numeric` | yes |  |
| 113 | `marketing_messages_read` | `numeric` | yes |  |
| 114 | `marketing_messages_read_rate` | `numeric` | yes |  |
| 115 | `marketing_messages_read_rate_benchmark` | `numeric` | yes |  |
| 116 | `marketing_messages_sent` | `numeric` | yes |  |
| 117 | `marketing_messages_spend` | `numeric` | yes |  |
| 118 | `mobile_app_purchase_roas` | `jsonb` | yes |  |
| 119 | `multi_event_conversion_attribution_setting` | `text` | yes |  |
| 120 | `objective` | `text` | yes |  |
| 121 | `objective_result_rate` | `jsonb` | yes |  |
| 122 | `objective_results` | `jsonb` | yes |  |
| 123 | `optimization_goal` | `text` | yes |  |
| 124 | `outbound_clicks` | `jsonb` | yes |  |
| 125 | `outbound_clicks_ctr` | `jsonb` | yes |  |
| 126 | `page_engagement` | `jsonb` | yes |  |
| 127 | `post_engagement` | `jsonb` | yes |  |
| 128 | `product_group_retailer_id` | `jsonb` | yes |  |
| 129 | `product_retailer_id` | `jsonb` | yes |  |
| 130 | `product_views` | `jsonb` | yes |  |
| 131 | `purchase_per_landing_page_view` | `numeric` | yes |  |
| 132 | `purchase_roas` | `jsonb` | yes |  |
| 133 | `qualifying_question_qualify_answer_rate` | `jsonb` | yes |  |
| 134 | `quality_ranking` | `text` | yes |  |
| 135 | `reach` | `numeric` | yes |  |
| 136 | `result_rate` | `jsonb` | yes |  |
| 137 | `result_values_performance_indicator` | `text` | yes |  |
| 138 | `results` | `jsonb` | yes |  |
| 139 | `shops_assisted_purchases` | `numeric` | yes |  |
| 140 | `social_spend` | `numeric` | yes |  |
| 141 | `spend` | `numeric` | yes |  |
| 142 | `unique_actions` | `jsonb` | yes |  |
| 143 | `unique_clicks` | `numeric` | yes |  |
| 144 | `unique_ctr` | `numeric` | yes |  |
| 145 | `unique_inline_link_click_ctr` | `numeric` | yes |  |
| 146 | `unique_inline_link_clicks` | `numeric` | yes |  |
| 147 | `unique_link_clicks_ctr` | `numeric` | yes |  |
| 148 | `unique_outbound_clicks` | `jsonb` | yes |  |
| 149 | `unique_outbound_clicks_ctr` | `jsonb` | yes |  |
| 150 | `updated_time` | `timestamp with time zone` | yes |  |
| 151 | `video_30_sec_watched_actions` | `jsonb` | yes |  |
| 152 | `video_6_sec_watched_actions` | `jsonb` | yes |  |
| 153 | `video_avg_time_watched_actions` | `jsonb` | yes |  |
| 154 | `video_continuous_2_sec_watched_actions` | `jsonb` | yes |  |
| 155 | `video_p100_watched_actions` | `jsonb` | yes |  |
| 156 | `video_p25_watched_actions` | `jsonb` | yes |  |
| 157 | `video_p50_watched_actions` | `jsonb` | yes |  |
| 158 | `video_p75_watched_actions` | `jsonb` | yes |  |
| 159 | `video_p95_watched_actions` | `jsonb` | yes |  |
| 160 | `video_play_actions` | `jsonb` | yes |  |
| 161 | `video_play_curve_actions` | `jsonb` | yes |  |
| 162 | `video_play_retention_0_to_15s_actions` | `jsonb` | yes |  |
| 163 | `video_play_retention_20_to_60s_actions` | `jsonb` | yes |  |
| 164 | `video_play_retention_graph_actions` | `jsonb` | yes |  |
| 165 | `video_thruplay_watched_actions` | `jsonb` | yes |  |
| 166 | `video_time_watched_actions` | `jsonb` | yes |  |
| 167 | `website_ctr` | `jsonb` | yes |  |
| 168 | `website_purchase_roas` | `jsonb` | yes |  |
| 169 | `wish_bid` | `numeric` | yes |  |
| 170 | `extracted_at` | `timestamp with time zone` | yes |  |
| 171 | `updated_at` | `timestamp with time zone` | yes |  |
| 172 | `ad_status` | `text` | yes |  |
| 173 | `ad_effective_status` | `text` | yes |  |
| 174 | `ad_created_time` | `timestamp with time zone` | yes |  |
| 175 | `purchases` | `numeric` | yes |  |
| 176 | `conv_value` | `numeric` | yes |  |
| 177 | `checkout_initiate` | `numeric` | yes |  |
| 178 | `add_to_cart` | `numeric` | yes |  |
| 179 | `ncp_count` | `numeric` | yes |  |
| 180 | `ftewv_count` | `numeric` | yes |  |
| 181 | `cost_per_purchase` | `numeric` | yes |  |
| 182 | `thruplays` | `numeric` | yes |  |
| 183 | `three_sec_video_plays` | `numeric` | yes |  |
| 184 | `video_play_time` | `numeric` | yes |  |
| 185 | `outbound_clicks_count` | `numeric` | yes |  |
| 186 | `post_engagements` | `numeric` | yes |  |
| 187 | `engagement_count` | `numeric` | yes |  |
| 188 | `ctr_pct` | `numeric` | yes |  |
| 189 | `cpc_link` | `numeric` | yes |  |
| 190 | `cpr_1000` | `numeric` | yes |  |
| 191 | `checkout_compl_pct` | `numeric` | yes |  |
| 192 | `cr_lc_pct` | `numeric` | yes |  |
| 193 | `atc_lc_pct` | `numeric` | yes |  |
| 194 | `ci_atc_pct` | `numeric` | yes |  |
| 195 | `roas` | `numeric` | yes |  |
| 196 | `cost_per_ncp` | `numeric` | yes |  |
| 197 | `cost_per_ftewv` | `numeric` | yes |  |
| 198 | `profit_efficiency` | `numeric` | yes |  |
| 199 | `contrib_margin_pct` | `numeric` | yes |  |
| 200 | `f1_pass` | `boolean` | yes |  |
| 201 | `f2_pass` | `boolean` | yes |  |
| 202 | `f3_pass` | `boolean` | yes |  |
| 203 | `f4_pass` | `boolean` | yes |  |
| 204 | `category` | `text` | yes |  |
| 205 | `lifecycle_refreshed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `ad_lifecycle_pkey`
  - `CREATE UNIQUE INDEX ad_lifecycle_pkey ON public.ad_lifecycle USING btree (ad_id)`
- Index — `ix_ad_lifecycle_account_name`: `CREATE INDEX ix_ad_lifecycle_account_name ON public.ad_lifecycle USING btree (account_name)`
- Index — `ix_ad_lifecycle_ad_name_trgm`: `CREATE INDEX ix_ad_lifecycle_ad_name_trgm ON public.ad_lifecycle USING gin (ad_name gin_trgm_ops)`
- Index — `ix_ad_lifecycle_campaign_id`: `CREATE INDEX ix_ad_lifecycle_campaign_id ON public.ad_lifecycle USING btree (campaign_id)`
- Index — `ix_ad_lifecycle_category`: `CREATE INDEX ix_ad_lifecycle_category ON public.ad_lifecycle USING btree (category)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more
- `product_group_retailer_id` → `ad_insights`, `adset_insights`, `campaign_insights`
- `product_retailer_id` → `ad_insights`, `adset_insights`, `campaign_insights`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
