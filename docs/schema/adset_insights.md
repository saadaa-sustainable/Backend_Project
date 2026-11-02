# `adset_insights`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~3,287 rows (planner estimate) · 3584 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `adset_id` | `text` | no |  |
| 2 | `adset_name` | `text` | yes |  |
| 3 | `campaign_id` | `text` | yes |  |
| 4 | `campaign_name` | `text` | yes |  |
| 5 | `account_id` | `text` | yes |  |
| 6 | `account_name` | `text` | yes |  |
| 7 | `date_start` | `date` | yes |  |
| 8 | `date_stop` | `date` | yes |  |
| 9 | `account_currency` | `text` | yes |  |
| 10 | `action_values` | `jsonb` | yes |  |
| 11 | `actions` | `jsonb` | yes |  |
| 12 | `ad_click_actions` | `jsonb` | yes |  |
| 13 | `ad_impression_actions` | `jsonb` | yes |  |
| 14 | `adset_end` | `jsonb` | yes |  |
| 15 | `adset_start` | `jsonb` | yes |  |
| 16 | `anchor_event_attribution_setting` | `text` | yes |  |
| 17 | `anchor_events_performance_indicator` | `jsonb` | yes |  |
| 18 | `attribution_setting` | `text` | yes |  |
| 19 | `auction_bid` | `jsonb` | yes |  |
| 20 | `auction_competitiveness` | `jsonb` | yes |  |
| 21 | `auction_max_competitor_bid` | `jsonb` | yes |  |
| 22 | `buying_type` | `text` | yes |  |
| 23 | `canvas_avg_view_percent` | `numeric` | yes |  |
| 24 | `canvas_avg_view_time` | `numeric` | yes |  |
| 25 | `catalog_segment_actions` | `jsonb` | yes |  |
| 26 | `catalog_segment_value` | `jsonb` | yes |  |
| 27 | `catalog_segment_value_mobile_purchase_roas` | `jsonb` | yes |  |
| 28 | `catalog_segment_value_omni_purchase_roas` | `jsonb` | yes |  |
| 29 | `catalog_segment_value_website_purchase_roas` | `jsonb` | yes |  |
| 30 | `clicks` | `numeric` | yes |  |
| 31 | `conversion_lead_rate` | `jsonb` | yes |  |
| 32 | `conversion_rate_ranking` | `text` | yes |  |
| 33 | `conversion_values` | `jsonb` | yes |  |
| 34 | `conversions` | `jsonb` | yes |  |
| 35 | `converted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 36 | `converted_product_app_custom_event_fb_mobile_purchase_value` | `jsonb` | yes |  |
| 37 | `converted_product_offline_purchase` | `jsonb` | yes |  |
| 38 | `converted_product_offline_purchase_value` | `jsonb` | yes |  |
| 39 | `converted_product_omni_purchase` | `jsonb` | yes |  |
| 40 | `converted_product_omni_purchase_values` | `jsonb` | yes |  |
| 41 | `converted_product_quantity` | `jsonb` | yes |  |
| 42 | `converted_product_value` | `jsonb` | yes |  |
| 43 | `converted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 44 | `converted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 45 | `converted_promoted_product_app_custom_event_fb_mobile_purchase` | `jsonb` | yes |  |
| 46 | `converted_promoted_product_app_custom_event_fb_mobile_purchase_` | `jsonb` | yes |  |
| 47 | `converted_promoted_product_offline_purchase` | `jsonb` | yes |  |
| 48 | `converted_promoted_product_offline_purchase_value` | `jsonb` | yes |  |
| 49 | `converted_promoted_product_omni_purchase` | `jsonb` | yes |  |
| 50 | `converted_promoted_product_omni_purchase_values` | `jsonb` | yes |  |
| 51 | `converted_promoted_product_quantity` | `jsonb` | yes |  |
| 52 | `converted_promoted_product_value` | `jsonb` | yes |  |
| 53 | `converted_promoted_product_website_pixel_purchase` | `jsonb` | yes |  |
| 54 | `converted_promoted_product_website_pixel_purchase_value` | `jsonb` | yes |  |
| 55 | `cost_per_15_sec_video_view` | `jsonb` | yes |  |
| 56 | `cost_per_2_sec_continuous_video_view` | `jsonb` | yes |  |
| 57 | `cost_per_action_type` | `jsonb` | yes |  |
| 58 | `cost_per_ad_click` | `jsonb` | yes |  |
| 59 | `cost_per_conversion` | `jsonb` | yes |  |
| 60 | `cost_per_conversion_lead` | `jsonb` | yes |  |
| 61 | `cost_per_dda_countby_convs` | `jsonb` | yes |  |
| 62 | `cost_per_estimated_ad_recallers` | `jsonb` | yes |  |
| 63 | `cost_per_inline_link_click` | `numeric` | yes |  |
| 64 | `cost_per_inline_post_engagement` | `numeric` | yes |  |
| 65 | `cost_per_objective_result` | `jsonb` | yes |  |
| 66 | `cost_per_one_thousand_ad_impression` | `jsonb` | yes |  |
| 67 | `cost_per_outbound_click` | `jsonb` | yes |  |
| 68 | `cost_per_result` | `jsonb` | yes |  |
| 69 | `cost_per_thruplay` | `jsonb` | yes |  |
| 70 | `cost_per_unique_action_type` | `jsonb` | yes |  |
| 71 | `cost_per_unique_click` | `numeric` | yes |  |
| 72 | `cost_per_unique_conversion` | `jsonb` | yes |  |
| 73 | `cost_per_unique_inline_link_click` | `numeric` | yes |  |
| 74 | `cost_per_unique_outbound_click` | `jsonb` | yes |  |
| 75 | `cpc` | `numeric` | yes |  |
| 76 | `cpm` | `numeric` | yes |  |
| 77 | `cpp` | `numeric` | yes |  |
| 78 | `created_time` | `timestamp with time zone` | yes |  |
| 79 | `creative_diversity_data` | `jsonb` | yes |  |
| 80 | `creative_diversity_label` | `text` | yes |  |
| 81 | `creative_diversity_score` | `text` | yes |  |
| 82 | `creative_fatigue_summary` | `jsonb` | yes |  |
| 83 | `creative_fatigued_ads` | `jsonb` | yes |  |
| 84 | `ctr` | `numeric` | yes |  |
| 85 | `dda_countby_convs` | `jsonb` | yes |  |
| 86 | `dda_results` | `jsonb` | yes |  |
| 87 | `engagement_rate_ranking` | `text` | yes |  |
| 88 | `estimated_ad_recall_rate` | `jsonb` | yes |  |
| 89 | `estimated_ad_recallers` | `jsonb` | yes |  |
| 90 | `frequency` | `numeric` | yes |  |
| 91 | `full_view_impressions` | `numeric` | yes |  |
| 92 | `full_view_reach` | `numeric` | yes |  |
| 93 | `impressions` | `numeric` | yes |  |
| 94 | `inline_link_click_ctr` | `numeric` | yes |  |
| 95 | `inline_link_clicks` | `numeric` | yes |  |
| 96 | `inline_post_engagement` | `numeric` | yes |  |
| 97 | `instagram_upcoming_event_reminders_set` | `numeric` | yes |  |
| 98 | `instant_experience_clicks_to_open` | `jsonb` | yes |  |
| 99 | `instant_experience_clicks_to_start` | `jsonb` | yes |  |
| 100 | `instant_experience_outbound_clicks` | `jsonb` | yes |  |
| 101 | `interactive_component_tap` | `jsonb` | yes |  |
| 102 | `landing_page_view_per_link_click` | `numeric` | yes |  |
| 103 | `marketing_messages_cost_per_delivered` | `numeric` | yes |  |
| 104 | `marketing_messages_cost_per_link_btn_click` | `numeric` | yes |  |
| 105 | `marketing_messages_delivered` | `numeric` | yes |  |
| 106 | `marketing_messages_delivery_rate` | `numeric` | yes |  |
| 107 | `marketing_messages_link_btn_click` | `numeric` | yes |  |
| 108 | `marketing_messages_media_view_rate` | `jsonb` | yes |  |
| 109 | `marketing_messages_phone_call_btn_click_rate` | `jsonb` | yes |  |
| 110 | `marketing_messages_quick_reply_btn_click_rate` | `numeric` | yes |  |
| 111 | `marketing_messages_read` | `numeric` | yes |  |
| 112 | `marketing_messages_read_rate` | `numeric` | yes |  |
| 113 | `marketing_messages_read_rate_benchmark` | `numeric` | yes |  |
| 114 | `marketing_messages_sent` | `numeric` | yes |  |
| 115 | `marketing_messages_spend` | `numeric` | yes |  |
| 116 | `mobile_app_purchase_roas` | `jsonb` | yes |  |
| 117 | `multi_event_conversion_attribution_setting` | `text` | yes |  |
| 118 | `objective` | `text` | yes |  |
| 119 | `objective_result_rate` | `jsonb` | yes |  |
| 120 | `objective_results` | `jsonb` | yes |  |
| 121 | `optimization_goal` | `text` | yes |  |
| 122 | `outbound_clicks` | `jsonb` | yes |  |
| 123 | `outbound_clicks_ctr` | `jsonb` | yes |  |
| 124 | `page_engagement` | `jsonb` | yes |  |
| 125 | `post_engagement` | `jsonb` | yes |  |
| 126 | `product_group_retailer_id` | `jsonb` | yes |  |
| 127 | `product_retailer_id` | `jsonb` | yes |  |
| 128 | `product_views` | `jsonb` | yes |  |
| 129 | `purchase_per_landing_page_view` | `numeric` | yes |  |
| 130 | `purchase_roas` | `jsonb` | yes |  |
| 131 | `qualifying_question_qualify_answer_rate` | `jsonb` | yes |  |
| 132 | `quality_ranking` | `text` | yes |  |
| 133 | `reach` | `numeric` | yes |  |
| 134 | `result_rate` | `jsonb` | yes |  |
| 135 | `result_values_performance_indicator` | `text` | yes |  |
| 136 | `results` | `jsonb` | yes |  |
| 137 | `shops_assisted_purchases` | `numeric` | yes |  |
| 138 | `social_spend` | `numeric` | yes |  |
| 139 | `spend` | `numeric` | yes |  |
| 140 | `unique_actions` | `jsonb` | yes |  |
| 141 | `unique_clicks` | `numeric` | yes |  |
| 142 | `unique_ctr` | `numeric` | yes |  |
| 143 | `unique_inline_link_click_ctr` | `numeric` | yes |  |
| 144 | `unique_inline_link_clicks` | `numeric` | yes |  |
| 145 | `unique_link_clicks_ctr` | `numeric` | yes |  |
| 146 | `unique_outbound_clicks` | `jsonb` | yes |  |
| 147 | `unique_outbound_clicks_ctr` | `jsonb` | yes |  |
| 148 | `updated_time` | `timestamp with time zone` | yes |  |
| 149 | `video_30_sec_watched_actions` | `jsonb` | yes |  |
| 150 | `video_6_sec_watched_actions` | `jsonb` | yes |  |
| 151 | `video_avg_time_watched_actions` | `jsonb` | yes |  |
| 152 | `video_continuous_2_sec_watched_actions` | `jsonb` | yes |  |
| 153 | `video_p100_watched_actions` | `jsonb` | yes |  |
| 154 | `video_p25_watched_actions` | `jsonb` | yes |  |
| 155 | `video_p50_watched_actions` | `jsonb` | yes |  |
| 156 | `video_p75_watched_actions` | `jsonb` | yes |  |
| 157 | `video_p95_watched_actions` | `jsonb` | yes |  |
| 158 | `video_play_actions` | `jsonb` | yes |  |
| 159 | `video_play_curve_actions` | `jsonb` | yes |  |
| 160 | `video_play_retention_0_to_15s_actions` | `jsonb` | yes |  |
| 161 | `video_play_retention_20_to_60s_actions` | `jsonb` | yes |  |
| 162 | `video_play_retention_graph_actions` | `jsonb` | yes |  |
| 163 | `video_thruplay_watched_actions` | `jsonb` | yes |  |
| 164 | `video_time_watched_actions` | `jsonb` | yes |  |
| 165 | `website_ctr` | `jsonb` | yes |  |
| 166 | `website_purchase_roas` | `jsonb` | yes |  |
| 167 | `wish_bid` | `numeric` | yes |  |
| 168 | `extracted_at` | `timestamp with time zone` | yes |  |
| 169 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `adset_insights_pkey`
  - `CREATE UNIQUE INDEX adset_insights_pkey ON public.adset_insights USING btree (adset_id)`
- Index — `ix_adset_insights_account_name`: `CREATE INDEX ix_adset_insights_account_name ON public.adset_insights USING btree (account_name)`
- Index — `ix_adset_insights_campaign_id`: `CREATE INDEX ix_adset_insights_campaign_id ON public.adset_insights USING btree (campaign_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more
- `product_group_retailer_id` → `ad_insights`, `ad_lifecycle`, `campaign_insights`
- `product_retailer_id` → `ad_insights`, `ad_lifecycle`, `campaign_insights`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
