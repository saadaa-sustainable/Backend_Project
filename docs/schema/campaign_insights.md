# `campaign_insights`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~616 rows (planner estimate) · 864 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `campaign_id` | `text` | no |  |
| 2 | `campaign_name` | `text` | yes |  |
| 3 | `account_id` | `text` | yes |  |
| 4 | `account_name` | `text` | yes |  |
| 5 | `date_start` | `date` | yes |  |
| 6 | `date_stop` | `date` | yes |  |
| 7 | `account_currency` | `text` | yes |  |
| 8 | `action_values` | `jsonb` | yes |  |
| 9 | `actions` | `jsonb` | yes |  |
| 10 | `ad_click_actions` | `jsonb` | yes |  |
| 11 | `ad_impression_actions` | `jsonb` | yes |  |
| 12 | `adset_end` | `jsonb` | yes |  |
| 13 | `adset_start` | `jsonb` | yes |  |
| 14 | `anchor_event_attribution_setting` | `text` | yes |  |
| 15 | `anchor_events_performance_indicator` | `jsonb` | yes |  |
| 16 | `attribution_setting` | `text` | yes |  |
| 17 | `auction_bid` | `jsonb` | yes |  |
| 18 | `auction_competitiveness` | `jsonb` | yes |  |
| 19 | `auction_max_competitor_bid` | `jsonb` | yes |  |
| 20 | `buying_type` | `text` | yes |  |
| 21 | `canvas_avg_view_percent` | `numeric` | yes |  |
| 22 | `canvas_avg_view_time` | `numeric` | yes |  |
| 23 | `catalog_segment_actions` | `jsonb` | yes |  |
| 24 | `catalog_segment_value` | `jsonb` | yes |  |
| 25 | `catalog_segment_value_mobile_purchase_roas` | `jsonb` | yes |  |
| 26 | `catalog_segment_value_omni_purchase_roas` | `jsonb` | yes |  |
| 27 | `catalog_segment_value_website_purchase_roas` | `jsonb` | yes |  |
| 28 | `clicks` | `numeric` | yes |  |
| 29 | `conversion_lead_rate` | `jsonb` | yes |  |
| 30 | `conversion_rate_ranking` | `text` | yes |  |
| 31 | `conversion_values` | `jsonb` | yes |  |
| 32 | `conversions` | `jsonb` | yes |  |
| 33 | `converted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 34 | `converted_product_app_custom_event_fb_mobile_purchase_value` | `jsonb` | yes |  |
| 35 | `converted_product_offline_purchase` | `jsonb` | yes |  |
| 36 | `converted_product_offline_purchase_value` | `jsonb` | yes |  |
| 37 | `converted_product_omni_purchase` | `jsonb` | yes |  |
| 38 | `converted_product_omni_purchase_values` | `jsonb` | yes |  |
| 39 | `converted_product_quantity` | `jsonb` | yes |  |
| 40 | `converted_product_value` | `jsonb` | yes |  |
| 41 | `converted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 42 | `converted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 43 | `converted_promoted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 44 | `converted_promoted_product_app_custom_event_fb_mobile_purchase_` | `jsonb` | yes |  |
| 45 | `converted_promoted_product_offline_purchase` | `jsonb` | yes |  |
| 46 | `converted_promoted_product_offline_purchase_value` | `jsonb` | yes |  |
| 47 | `converted_promoted_product_omni_purchase` | `jsonb` | yes |  |
| 48 | `converted_promoted_product_omni_purchase_values` | `jsonb` | yes |  |
| 49 | `converted_promoted_product_quantity` | `jsonb` | yes |  |
| 50 | `converted_promoted_product_value` | `jsonb` | yes |  |
| 51 | `converted_promoted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 52 | `converted_promoted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 53 | `cost_per_15_sec_video_view` | `jsonb` | yes |  |
| 54 | `cost_per_2_sec_continuous_video_view` | `jsonb` | yes |  |
| 55 | `cost_per_action_type` | `jsonb` | yes |  |
| 56 | `cost_per_ad_click` | `jsonb` | yes |  |
| 57 | `cost_per_conversion` | `jsonb` | yes |  |
| 58 | `cost_per_conversion_lead` | `jsonb` | yes |  |
| 59 | `cost_per_dda_countby_convs` | `jsonb` | yes |  |
| 60 | `cost_per_estimated_ad_recallers` | `jsonb` | yes |  |
| 61 | `cost_per_inline_link_click` | `numeric` | yes |  |
| 62 | `cost_per_inline_post_engagement` | `numeric` | yes |  |
| 63 | `cost_per_objective_result` | `jsonb` | yes |  |
| 64 | `cost_per_one_thousand_ad_impression` | `jsonb` | yes |  |
| 65 | `cost_per_outbound_click` | `jsonb` | yes |  |
| 66 | `cost_per_result` | `jsonb` | yes |  |
| 67 | `cost_per_thruplay` | `jsonb` | yes |  |
| 68 | `cost_per_unique_action_type` | `jsonb` | yes |  |
| 69 | `cost_per_unique_click` | `numeric` | yes |  |
| 70 | `cost_per_unique_conversion` | `jsonb` | yes |  |
| 71 | `cost_per_unique_inline_link_click` | `numeric` | yes |  |
| 72 | `cost_per_unique_outbound_click` | `jsonb` | yes |  |
| 73 | `cpc` | `numeric` | yes |  |
| 74 | `cpm` | `numeric` | yes |  |
| 75 | `cpp` | `numeric` | yes |  |
| 76 | `created_time` | `timestamp with time zone` | yes |  |
| 77 | `creative_diversity_data` | `jsonb` | yes |  |
| 78 | `creative_diversity_label` | `text` | yes |  |
| 79 | `creative_diversity_score` | `text` | yes |  |
| 80 | `creative_fatigue_summary` | `jsonb` | yes |  |
| 81 | `creative_fatigued_ads` | `jsonb` | yes |  |
| 82 | `ctr` | `numeric` | yes |  |
| 83 | `dda_countby_convs` | `jsonb` | yes |  |
| 84 | `dda_results` | `jsonb` | yes |  |
| 85 | `engagement_rate_ranking` | `text` | yes |  |
| 86 | `estimated_ad_recall_rate` | `jsonb` | yes |  |
| 87 | `estimated_ad_recallers` | `jsonb` | yes |  |
| 88 | `frequency` | `numeric` | yes |  |
| 89 | `full_view_impressions` | `numeric` | yes |  |
| 90 | `full_view_reach` | `numeric` | yes |  |
| 91 | `impressions` | `numeric` | yes |  |
| 92 | `inline_link_click_ctr` | `numeric` | yes |  |
| 93 | `inline_link_clicks` | `numeric` | yes |  |
| 94 | `inline_post_engagement` | `numeric` | yes |  |
| 95 | `instagram_upcoming_event_reminders_set` | `numeric` | yes |  |
| 96 | `instant_experience_clicks_to_open` | `jsonb` | yes |  |
| 97 | `instant_experience_clicks_to_start` | `jsonb` | yes |  |
| 98 | `instant_experience_outbound_clicks` | `jsonb` | yes |  |
| 99 | `interactive_component_tap` | `jsonb` | yes |  |
| 100 | `landing_page_view_per_link_click` | `numeric` | yes |  |
| 101 | `marketing_messages_cost_per_delivered` | `numeric` | yes |  |
| 102 | `marketing_messages_cost_per_link_btn_click` | `numeric` | yes |  |
| 103 | `marketing_messages_delivered` | `numeric` | yes |  |
| 104 | `marketing_messages_delivery_rate` | `numeric` | yes |  |
| 105 | `marketing_messages_link_btn_click` | `numeric` | yes |  |
| 106 | `marketing_messages_media_view_rate` | `jsonb` | yes |  |
| 107 | `marketing_messages_phone_call_btn_click_rate` | `jsonb` | yes |  |
| 108 | `marketing_messages_quick_reply_btn_click_rate` | `numeric` | yes |  |
| 109 | `marketing_messages_read` | `numeric` | yes |  |
| 110 | `marketing_messages_read_rate` | `numeric` | yes |  |
| 111 | `marketing_messages_read_rate_benchmark` | `numeric` | yes |  |
| 112 | `marketing_messages_sent` | `numeric` | yes |  |
| 113 | `marketing_messages_spend` | `numeric` | yes |  |
| 114 | `mobile_app_purchase_roas` | `jsonb` | yes |  |
| 115 | `multi_event_conversion_attribution_setting` | `text` | yes |  |
| 116 | `objective` | `text` | yes |  |
| 117 | `objective_result_rate` | `jsonb` | yes |  |
| 118 | `objective_results` | `jsonb` | yes |  |
| 119 | `optimization_goal` | `text` | yes |  |
| 120 | `outbound_clicks` | `jsonb` | yes |  |
| 121 | `outbound_clicks_ctr` | `jsonb` | yes |  |
| 122 | `page_engagement` | `jsonb` | yes |  |
| 123 | `post_engagement` | `jsonb` | yes |  |
| 124 | `product_group_retailer_id` | `jsonb` | yes |  |
| 125 | `product_retailer_id` | `jsonb` | yes |  |
| 126 | `product_views` | `jsonb` | yes |  |
| 127 | `purchase_per_landing_page_view` | `numeric` | yes |  |
| 128 | `purchase_roas` | `jsonb` | yes |  |
| 129 | `qualifying_question_qualify_answer_rate` | `jsonb` | yes |  |
| 130 | `quality_ranking` | `text` | yes |  |
| 131 | `reach` | `numeric` | yes |  |
| 132 | `result_rate` | `jsonb` | yes |  |
| 133 | `result_values_performance_indicator` | `text` | yes |  |
| 134 | `results` | `jsonb` | yes |  |
| 135 | `shops_assisted_purchases` | `numeric` | yes |  |
| 136 | `social_spend` | `numeric` | yes |  |
| 137 | `spend` | `numeric` | yes |  |
| 138 | `unique_actions` | `jsonb` | yes |  |
| 139 | `unique_clicks` | `numeric` | yes |  |
| 140 | `unique_ctr` | `numeric` | yes |  |
| 141 | `unique_inline_link_click_ctr` | `numeric` | yes |  |
| 142 | `unique_inline_link_clicks` | `numeric` | yes |  |
| 143 | `unique_link_clicks_ctr` | `numeric` | yes |  |
| 144 | `unique_outbound_clicks` | `jsonb` | yes |  |
| 145 | `unique_outbound_clicks_ctr` | `jsonb` | yes |  |
| 146 | `updated_time` | `timestamp with time zone` | yes |  |
| 147 | `video_30_sec_watched_actions` | `jsonb` | yes |  |
| 148 | `video_6_sec_watched_actions` | `jsonb` | yes |  |
| 149 | `video_avg_time_watched_actions` | `jsonb` | yes |  |
| 150 | `video_continuous_2_sec_watched_actions` | `jsonb` | yes |  |
| 151 | `video_p100_watched_actions` | `jsonb` | yes |  |
| 152 | `video_p25_watched_actions` | `jsonb` | yes |  |
| 153 | `video_p50_watched_actions` | `jsonb` | yes |  |
| 154 | `video_p75_watched_actions` | `jsonb` | yes |  |
| 155 | `video_p95_watched_actions` | `jsonb` | yes |  |
| 156 | `video_play_actions` | `jsonb` | yes |  |
| 157 | `video_play_curve_actions` | `jsonb` | yes |  |
| 158 | `video_play_retention_0_to_15s_actions` | `jsonb` | yes |  |
| 159 | `video_play_retention_20_to_60s_actions` | `jsonb` | yes |  |
| 160 | `video_play_retention_graph_actions` | `jsonb` | yes |  |
| 161 | `video_thruplay_watched_actions` | `jsonb` | yes |  |
| 162 | `video_time_watched_actions` | `jsonb` | yes |  |
| 163 | `website_ctr` | `jsonb` | yes |  |
| 164 | `website_purchase_roas` | `jsonb` | yes |  |
| 165 | `wish_bid` | `numeric` | yes |  |
| 166 | `extracted_at` | `timestamp with time zone` | yes |  |
| 167 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `campaign_insights_pkey`
  - `CREATE UNIQUE INDEX campaign_insights_pkey ON public.campaign_insights USING btree (campaign_id)`
- Index — `ix_campaign_insights_account_name`: `CREATE INDEX ix_campaign_insights_account_name ON public.campaign_insights USING btree (account_name)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more
- `product_group_retailer_id` → `ad_insights`, `ad_lifecycle`, `adset_insights`
- `product_retailer_id` → `ad_insights`, `ad_lifecycle`, `adset_insights`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
