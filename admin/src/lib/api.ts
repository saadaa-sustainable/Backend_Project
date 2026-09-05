// Thin fetch wrappers over this project's FastAPI admin routes
// (app/api/routers/admin.py). Kept deliberately free of any UI concerns —
// pages import types and call functions from here, nothing more.

// Default port is 8002 (was 8001 before a stuck-socket incident on
// 2026-08-29). Port 8000 is typically occupied by CTD's api_ae.py in
// local dev on this machine. Override with NEXT_PUBLIC_API_BASE_URL
// in .env.local if you're running this project's FastAPI backend
// somewhere else.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8002";

export type ColumnKind = "identity" | "numeric" | "jsonb" | "other";

export interface TableColumn {
  name: string;
  data_type: string;
  is_nullable: boolean;
  kind: ColumnKind;
  formula: string | null;
}

export interface TableSchema {
  name: string;
  row_count: number | null;
  columns: TableColumn[];
}

export interface TablesResponse {
  source: "information_schema" | "postgrest_openapi";
  tables: TableSchema[];
}

export type IngestSource = "meta" | "shopify" | "instagram";

export type MetaInsightsLevel = "account" | "campaign" | "adset" | "ad";
export type ShopifyObjectType = "shop" | "products" | "orders" | "customers" | "sessions";

export interface IngestRequest {
  sources: IngestSource[];
  date_start?: string; // YYYY-MM-DD -- required when "meta" is in sources
  date_end?: string; // YYYY-MM-DD -- required when "meta" is in sources
  target_table?: string; // required when "instagram" or "shopify" is in sources
  since?: string; // YYYY-MM-DD -- instagram only, optional start-date override
  // Meta only, optional -- omit for all four levels. Execution always runs
  // ad -> adset -> campaign -> account regardless of the order sent here
  // (backend re-sorts to META_LEVEL_FETCH_ORDER).
  meta_levels?: MetaInsightsLevel[];
  // Shopify only, optional -- omit for the default set (shop/products/
  // orders/customers/sessions). Uses date_start/date_end above (a real
  // range, unlike Instagram's single `since`).
  shopify_object_types?: ShopifyObjectType[];
}

export interface IngestSourceResult {
  source: IngestSource;
  status: "started" | "skipped" | "error";
  supports_date_range: boolean;
  detail: string;
}

export interface IngestRunResponse {
  run_id: string;
  started_at: string;
  results: IngestSourceResult[];
}

export type IngestSourceStatusValue = "running" | "succeeded" | "failed" | "skipped" | "stopped";

export interface LevelStatus {
  account_key: string | null;
  account_name: string | null;
  label: string;
  status: "succeeded" | "failed";
  error: string | null;
}

export interface IngestRunStatus {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  sources: Record<
    IngestSource,
    {
      status: IngestSourceStatusValue;
      rows_ingested: number | null;
      error: string | null;
      levels: LevelStatus[];
    }
  >;
}

export interface ObjectTypeCount {
  value: string;
  row_count: number;
}

export interface ObjectTypesResponse {
  table: string;
  column: string;
  values: ObjectTypeCount[];
}

export interface JsonbKey {
  key: string;
  types: string[];
  presence_count: number;
  presence_pct: number;
}

export interface JsonbKeysResponse {
  table: string;
  column: string;
  filter_column: string | null;
  filter_value: string | null;
  rows_scanned: number;
  keys: JsonbKey[];
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(
      `${init?.method ?? "GET"} ${path} failed (${res.status}): ${body.slice(0, 300)}`,
      res.status,
    );
  }
  return res.json() as Promise<T>;
}

export function fetchTables(): Promise<TablesResponse> {
  return request<TablesResponse>("/admin/tables");
}

export function triggerIngest(body: IngestRequest): Promise<IngestRunResponse> {
  return request<IngestRunResponse>("/admin/ingest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchIngestStatus(runId: string): Promise<IngestRunStatus> {
  return request<IngestRunStatus>(`/admin/ingest/${runId}`);
}

export function stopIngest(runId: string): Promise<IngestRunStatus> {
  return request<IngestRunStatus>(`/admin/ingest/${runId}/stop`, { method: "POST" });
}

export interface FlattenJob {
  key: string;
  label: string;
  source_table: string;
  target_tables: string[];
  auto_enabled: boolean;
  is_stale: boolean;
  source_max_extracted_at: string | null;
  last_run_status: "succeeded" | "failed" | null;
  last_run_at: string | null;
  last_run_triggered_by: "manual" | "auto_poll" | null;
  last_rows_written: Record<string, number> | null;
  last_error: string | null;
}

export function fetchFlattenJobs(): Promise<FlattenJob[]> {
  return request<FlattenJob[]>("/admin/flatten/jobs");
}

export function fetchFlattenJobsForTable(table: string): Promise<FlattenJob[]> {
  return request<FlattenJob[]>(`/admin/flatten/jobs/for-table/${encodeURIComponent(table)}`);
}

export function runFlattenJob(jobKey: string): Promise<FlattenJob> {
  return request<FlattenJob>(`/admin/flatten/jobs/${encodeURIComponent(jobKey)}/run`, {
    method: "POST",
  });
}

export function setFlattenAutoEnabled(jobKey: string, enabled: boolean): Promise<FlattenJob> {
  return request<FlattenJob>(`/admin/flatten/jobs/${encodeURIComponent(jobKey)}/auto`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export type RawTableSource = "instagram" | "shopify" | "meta";

export interface RawTableOut {
  name: string;
  row_count: number;
  last_updated: string | null;
}

export function fetchRawTables(source: RawTableSource): Promise<RawTableOut[]> {
  return request<RawTableOut[]>(`/admin/tables/raw?source=${source}`);
}

export interface RawTableResponse {
  status: "created" | "failed";
  table_name: string;
  error: string | null;
}

export function createRawTable(tableName: string, source: RawTableSource): Promise<RawTableResponse> {
  return request<RawTableResponse>("/admin/tables/raw", {
    method: "POST",
    body: JSON.stringify({ table_name: tableName, source }),
  });
}

export function fetchObjectTypes(table: string, column = "object_type"): Promise<ObjectTypesResponse> {
  const qs = new URLSearchParams({ column });
  return request<ObjectTypesResponse>(`/admin/tables/${encodeURIComponent(table)}/object-types?${qs}`);
}

export interface JsonbKeysParams {
  column?: string;
  filterColumn?: string | null;
  filterValue?: string | null;
}

export function fetchJsonbKeys(table: string, params: JsonbKeysParams = {}): Promise<JsonbKeysResponse> {
  const qs = new URLSearchParams();
  if (params.column) qs.set("column", params.column);
  // Always send filter_column explicitly, even empty -- the backend
  // defaults this param to "object_type" when it's *omitted*, so a
  // caller that wants "no filter" (tables with no object_type column)
  // must send an empty value, not skip the param, or the backend would
  // wrongly fall back to filtering on a column that doesn't exist there.
  qs.set("filter_column", params.filterColumn ?? "");
  if (params.filterValue !== undefined && params.filterValue !== null) {
    qs.set("filter_value", params.filterValue);
  }
  return request<JsonbKeysResponse>(`/admin/tables/${encodeURIComponent(table)}/jsonb-keys?${qs}`);
}

export interface FieldSpec {
  field: string;
  output_name?: string | null;
}

export interface CustomTableRequest {
  source_table: string;
  object_type?: string | null;
  fields: FieldSpec[];
  table_name: string;
  dry_run: boolean;
  overwrite?: boolean;
}

export interface CustomTableResponse {
  status: "preview" | "created" | "failed";
  table_name: string;
  sql: string;
  preview_columns: string[];
  row_count: number | null;
  error: string | null;
}

export function createCustomTable(body: CustomTableRequest): Promise<CustomTableResponse> {
  return request<CustomTableResponse>("/admin/tables/custom", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function fetchTableColumns(table: string): Promise<TableColumn[]> {
  return request<TableColumn[]>(`/admin/tables/${encodeURIComponent(table)}/columns`);
}

export type JoinType = "inner" | "left" | "right" | "full";

export interface JoinTableSpec {
  table: string;
  object_type?: string | null;
  fields: FieldSpec[];
  join_type?: JoinType;
  join_field?: string | null;
  anchor_join_field?: string | null;
}

export interface JoinedTableRequest {
  tables: JoinTableSpec[];
  table_name: string;
  dry_run: boolean;
}

export interface JoinedTableResponse {
  status: "preview" | "created" | "failed";
  table_name: string;
  sql: string;
  preview_columns: string[];
  row_count: number | null;
  error: string | null;
}

export function createJoinedTable(body: JoinedTableRequest): Promise<JoinedTableResponse> {
  return request<JoinedTableResponse>("/admin/tables/join", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type MetricOperation = "divide" | "multiply" | "add" | "subtract";
export type OperandBType = "column" | "constant";

export interface CustomMetricRequest {
  name: string;
  operation: MetricOperation;
  column_a: string;
  operand_b_type: OperandBType;
  operand_b_column?: string | null;
  operand_b_constant?: number | null;
  as_percentage: boolean;
  dry_run: boolean;
}

export interface CustomMetricResponse {
  status: "preview" | "created" | "failed";
  table: string;
  column_name: string;
  sql: string;
  error: string | null;
}

export function createCustomMetric(table: string, body: CustomMetricRequest): Promise<CustomMetricResponse> {
  return request<CustomMetricResponse>(`/admin/tables/${encodeURIComponent(table)}/custom-metric`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatResponse {
  message: string;
}

export function sendChatMessage(messages: ChatMessage[], model?: string): Promise<ChatResponse> {
  return request<ChatResponse>("/admin/assistant/chat", {
    method: "POST",
    body: JSON.stringify({ messages, model }),
  });
}

export interface AssistantModel {
  id: string;
  label: string;
  provider: "cloudflare" | "anthropic";
  note: string | null;
}

export function fetchAssistantModels(): Promise<AssistantModel[]> {
  return request<AssistantModel[]>("/admin/assistant/models");
}

export interface ContextDocument {
  id: string;
  filename: string;
  content_type: string;
  uploaded_at: string;
  char_count: number;
}

export function fetchContextDocuments(): Promise<ContextDocument[]> {
  return request<ContextDocument[]>("/admin/assistant/context");
}

export async function uploadContextDocument(file: File): Promise<ContextDocument> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE_URL}/admin/assistant/context`, {
    method: "POST",
    body: formData,
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(`POST /admin/assistant/context failed (${res.status}): ${body.slice(0, 300)}`, res.status);
  }
  return res.json() as Promise<ContextDocument>;
}

// --- Cron / Sync Status + Error Logs (app/api/routers/status.py, failed_jobs.py, ops.py) ---

export type BatchStatusValue = "running" | "success" | "partial_failure" | "failed";

export interface BatchSummary {
  batch_id: string;
  endpoint: string;
  account_key: string | null;
  account_name: string | null;
  sync_type: string;
  status: BatchStatusValue;
  records_fetched: number;
  records_failed: number;
  started_at: string;
  finished_at: string | null;
  triggered_by: string;
  error_message: string | null;
}

export interface StatusResponse {
  total_batches: number;
  running: number;
  succeeded: number;
  partial_failures: number;
  failed: number;
  recent_batches: BatchSummary[];
}

export interface StatusParams {
  endpoint?: string;
  account?: string;
  limit?: number;
}

function statusQuery(params: StatusParams): string {
  const qs = new URLSearchParams();
  if (params.endpoint) qs.set("endpoint", params.endpoint);
  if (params.account) qs.set("account", params.account);
  if (params.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export function fetchStatus(params: StatusParams = {}): Promise<StatusResponse> {
  return request<StatusResponse>(`/status${statusQuery(params)}`);
}

export function fetchLogs(params: StatusParams = {}): Promise<BatchSummary[]> {
  return request<BatchSummary[]>(`/logs${statusQuery(params)}`);
}

export interface FailedJobSchema {
  id: string;
  batch_id: string;
  endpoint: string;
  account_key: string | null;
  account_name: string | null;
  error_message: string;
  attempt_count: number;
  resolved: boolean;
  created_at: string;
  last_attempted_at: string;
}

export function fetchFailedJobs(params: StatusParams = {}): Promise<FailedJobSchema[]> {
  return request<FailedJobSchema[]>(`/failed-jobs${statusQuery(params)}`);
}

export interface RetryFailedJobsResponse {
  retried: number;
  resolved: number;
  still_failing: number;
}

export interface AdLifecycleRow {
  ad_id: string;
  ad_name: string | null;
  account_name: string | null;
  campaign_name: string | null;
  ad_effective_status: string | null;
  category: string | null;
  spend: number | null;
  roas: number | null;
  cost_per_ncp: number | null;
  cost_per_ftewv: number | null;
  purchases: number | null;
  ncp_count: number | null;
  ftewv_count: number | null;
  impressions: number | null;
  ctr_pct: number | null;
  f1_pass: boolean | null;
  f2_pass: boolean | null;
  f3_pass: boolean | null;
  f4_pass: boolean | null;
  lifecycle_refreshed_at: string | null;
}

export interface AdLifecycleResponse {
  rows: AdLifecycleRow[];
  total: number;
  category_counts: Record<string, number>;
}

export type AdLifecycleSort = "spend" | "roas" | "impressions" | "cost_per_ncp" | "cost_per_ftewv";

export interface AdLifecycleParams {
  account_name?: string;
  category?: string;
  ad_effective_status?: string;
  search?: string;
  sort?: AdLifecycleSort;
  limit?: number;
  offset?: number;
}

export function fetchAdLifecycle(params: AdLifecycleParams = {}): Promise<AdLifecycleResponse> {
  const qs = new URLSearchParams();
  if (params.account_name) qs.set("account_name", params.account_name);
  if (params.category) qs.set("category", params.category);
  if (params.ad_effective_status) qs.set("ad_effective_status", params.ad_effective_status);
  if (params.search) qs.set("search", params.search);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<AdLifecycleResponse>(`/admin/analytics/ad-lifecycle${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Ads Analyse -- wide per-ad table (Meta + Shopify-attributed revenue)
// ---------------------------------------------------------------------

export interface AdsAnalyseRow {
  // ── Historical tagging (public.ad_history_milestones) ──────────────
  // What the ad's category WAS on the 14th day of its life, versus the
  // `category` field below which is re-evaluated against today's
  // lifetime metrics. An ad that won its first fortnight and has since
  // decayed reads "Discarded" there and "Winner" here.
  category_at_day_14: string | null;
  // 'ok' | 'not_yet_14_days' | 'partial_history' | 'no_history'.
  // Explains a null verdict instead of leaving it ambiguous: Meta
  // insights in bronze begin 2026-01-01, so ads created earlier have no
  // first fortnight to replay.
  history_status: string | null;
  // Day cumulative impressions crossed 50,000 (the F1 gate), and the
  // same fact as an age. Null when never crossed, or when the ad
  // predates the daily range and the running sum would date it late.
  impressions_50k_date: string | null;
  days_to_50k: number | null;
  impressions_at_day_14: number | null;

  ad_id: string;
  adset_id: string | null;
  campaign_id: string | null;
  account_id: string | null;
  ad_name: string | null;
  ad_status: string | null;
  ad_effective_status: string | null;
  adset_name: string | null;
  campaign_name: string | null;
  account_name: string | null;
  category: string | null;
  spend: number | null;
  impressions: number | null;
  reach: number | null;
  frequency: number | null;
  purchases: number | null;
  conv_value: number | null;
  meta_conv_value: number | null;
  meta_roas: number | null;
  cost_per_purchase: number | null;
  ctr_pct: number | null;
  shopify_orders: number | null;
  shopify_revenue: number | null;
  shopify_aov: number | null;
  shopify_roas: number | null;
  cost_per_shopify_order: number | null;
  gold_refreshed_at: string | null;
  f1_pass: boolean | null;
  f2_pass: boolean | null;
  f3_pass: boolean | null;
  f4_pass: boolean | null;
  ncp_count: number | null;
  ftewv_count: number | null;
  cost_per_ncp: number | null;
  cost_per_ftewv: number | null;
  roas: number | null;
  contrib_margin_pct: number | null;
  profit_efficiency: number | null;
  cpr_1000: number | null;
  cpc_link: number | null;
  checkout_compl_pct: number | null;
  cr_lc_pct: number | null;
  atc_lc_pct: number | null;
  ci_atc_pct: number | null;
  ad_created_date: string | null;
  // Tier-2 derivables (backend computes in SELECT)
  link_clicks_raw: number | null;
  atc_count: number | null;
  ci_count: number | null;
  engagement_count: number | null;
  cost_per_1000: number | null;
  meta_shop_diff_pct: number | null;
  pct_reach_ftewv: number | null;
  ltv_reach: number | null;
  ltv_frequency: number | null;
  first_seen_date: string | null;
  // Asset resolution from content_asset_register /
  // content_graphic_register / content_influencer_posts. asset_match_source
  // is one of:
  //   'direct'           -- workflow-optimiser wrote a direct ad_id link
  //   'ctd_matched'      -- CTD's substring matcher found the ad_name
  //   'name_parsed'      -- regex-extracted from ad_name AND the code exists in a register table
  //   'name_synthetic'   -- regex-extracted from ad_name, code not yet in a register table
  asset_id: string | null;
  asset_media: "video" | "graphic" | "influencer" | null;
  asset_match_source: "direct" | "ctd_matched" | "name_parsed" | "name_synthetic" | null;
  // Per-ad media (ad_media silver, built from raw_dump_meta joins).
  // Coverage ~19% today (ads whose creative has an asset_feed_spec).
  // All null for the other 81% -- follow-up: /adcreatives fetcher.
  thumbnail_url: string | null;
  video_url: string | null;
  video_id: string | null;
  landing_page_url: string | null;
  link_display_url: string | null;
  is_video: boolean | null;
  // <page_id>_<post_id>. When present, the frontend builds a Facebook
  // post iframe embed to show the post exactly as it appears in
  // Ads Manager Preview -- 78% coverage today.
  effective_object_story_id: string | null;
  // Instagram permalink from CTD's ad_thumbnails mirror (89% coverage).
  // Feeds https://www.instagram.com/{p|reel}/{shortcode}/embed/captioned/
  // -- works for dark-post ads, unlike the FB plugin path.
  instagram_permalink: string | null;
  video_source_url: string | null;
}

export interface AdsAnalyseTotals {
  ad_count: number;
  spend: number;
  impressions: number;
  reach: number;
  purchases: number;
  conv_value: number;
  // null in 'delivery' mode when the picked window predates the daily
  // Shopify series -- unknown, not zero. The tiles render "—".
  shopify_orders: number | null;
  shopify_revenue: number | null;
  ncp_count: number;
  ftewv_count: number;
  avg_meta_roas: number | null;
  avg_shopify_roas: number | null;
  avg_ctr_pct: number | null;
}

export interface AdsAnalyseResponse {
  rows: AdsAnalyseRow[];
  total: number;
  /** Ad count per category under the current filters (except `category` itself).
   * Powers the KPI tiles that mirror CTD's Creative Testing view. */
  category_counts: Record<string, number>;
  /** Aggregate totals for the KPI strip -- kwikengage-style Marketing Insights row.
   * Reflects the same filter set as `rows`. */
  totals: AdsAnalyseTotals;
}

export type AdsAnalyseDateField = "created" | "first_seen" | "delivery";

export type AdsAnalyseSort =
  | "spend"
  | "meta_roas"
  | "shopify_roas"
  | "shopify_revenue"
  | "impressions"
  | "cost_per_ncp"
  | "cost_per_ftewv"
  | "contrib_margin_pct"
  | "roas";

export interface AdsAnalyseParams {
  account_name?: string;
  campaign_name?: string;
  ad_effective_status?: string;
  category?: string;
  /** Filter to ads that passed / failed a specific F-test. Backend accepts
   * each F flag independently; combine them for e.g. "F1+F2 passed but F3
   * failed" -- exactly the CTD Creative Testing power-user pattern. */
  f1_pass?: boolean;
  f2_pass?: boolean;
  f3_pass?: boolean;
  f4_pass?: boolean;
  search?: string;
  only_with_shopify_orders?: boolean;
  /** When both from_date and to_date are set, the window is applied
   * per date_field: 'created' filters rows by ad_created_date;
   * 'first_seen' filters by first_seen_date; 'delivery' keeps every
   * row but overlays windowed spend/impressions/reach. YYYY-MM-DD. */
  from_date?: string;
  to_date?: string;
  date_field?: AdsAnalyseDateField;
  sort?: AdsAnalyseSort;
  limit?: number;
  offset?: number;
}

export function fetchAdsAnalyse(params: AdsAnalyseParams = {}): Promise<AdsAnalyseResponse> {
  const qs = new URLSearchParams();
  if (params.account_name) qs.set("account_name", params.account_name);
  if (params.campaign_name) qs.set("campaign_name", params.campaign_name);
  if (params.ad_effective_status) qs.set("ad_effective_status", params.ad_effective_status);
  if (params.category) qs.set("category", params.category);
  if (params.f1_pass !== undefined) qs.set("f1_pass", String(params.f1_pass));
  if (params.f2_pass !== undefined) qs.set("f2_pass", String(params.f2_pass));
  if (params.f3_pass !== undefined) qs.set("f3_pass", String(params.f3_pass));
  if (params.f4_pass !== undefined) qs.set("f4_pass", String(params.f4_pass));
  if (params.search) qs.set("search", params.search);
  if (params.only_with_shopify_orders) qs.set("only_with_shopify_orders", "true");
  if (params.from_date) qs.set("from_date", params.from_date);
  if (params.to_date) qs.set("to_date", params.to_date);
  if (params.date_field) qs.set("date_field", params.date_field);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<AdsAnalyseResponse>(`/admin/analytics/ads-analyse${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Last Click UTM -- order-level Shopify -> Meta attribution
// ---------------------------------------------------------------------

export type UtmChannel =
  | "Meta"
  | "Google"
  | "Organic (IG)"
  | "Retention"
  | "Brand Collab"
  | "AI"
  | "Organic (Direct)"
  | "Loyalty"
  | "Other";

export interface UtmOrderRow {
  order_id: string;
  name: string | null;
  total_price: number | null;
  created_at: string | null;
  customer_id: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  utm_content: string | null;
  utm_term: string | null;
  tier: string | null;
  matched_ad_id: string | null;
  matched_ad_name: string | null;
  matched_adset_id: string | null;
  matched_campaign_id: string | null;
  matched_campaign_name: string | null;
  contact_email: string | null;
  customer_num_orders: number | null;
  channel: UtmChannel;
  has_match: boolean;
}

export interface ChannelSummary {
  count: number;
  sales: number;
}

export interface SourceBreakdown {
  utm_source: string | null;
  count: number;
  sales: number;
}

export interface UtmOrderResponse {
  rows: UtmOrderRow[];
  total: number;
  channel_counts: Record<UtmChannel, ChannelSummary>;
  tier_counts: Record<string, number>;
  channel_sources: Record<UtmChannel, SourceBreakdown[]>;
}

export interface LastClickUtmParams {
  channel?: UtmChannel;
  tier?: string;
  /** Comma-separated (multi-select popover in CTD). */
  utm_source?: string;
  utm_medium?: string;
  /** Comma-separated terms, prefix with "!" to exclude (CTD's IN/EX pill). */
  utm_campaign?: string;
  utm_content?: string;
  utm_term?: string;
  /** Same IN/EX comma format; matches matched_ad_name. */
  matched_value?: string;
  only_matched?: boolean;
  only_unmatched?: boolean;
  search?: string;
  from_date?: string; // YYYY-MM-DD
  to_date?: string;
  sort?: "created_at" | "total_price" | "customer_num_orders";
  limit?: number;
  offset?: number;
}

export function fetchLastClickUtm(params: LastClickUtmParams = {}): Promise<UtmOrderResponse> {
  const qs = new URLSearchParams();
  if (params.channel) qs.set("channel", params.channel);
  if (params.tier) qs.set("tier", params.tier);
  if (params.utm_source) qs.set("utm_source", params.utm_source);
  if (params.utm_medium) qs.set("utm_medium", params.utm_medium);
  if (params.utm_campaign) qs.set("utm_campaign", params.utm_campaign);
  if (params.utm_content) qs.set("utm_content", params.utm_content);
  if (params.utm_term) qs.set("utm_term", params.utm_term);
  if (params.matched_value) qs.set("matched_value", params.matched_value);
  if (params.only_matched) qs.set("only_matched", "true");
  if (params.only_unmatched) qs.set("only_unmatched", "true");
  if (params.search) qs.set("search", params.search);
  if (params.from_date) qs.set("from_date", params.from_date);
  if (params.to_date) qs.set("to_date", params.to_date);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<UtmOrderResponse>(`/admin/analytics/last-click-utm${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Landing Page Analysis
// ---------------------------------------------------------------------

export interface LandingPageRow {
  landing_page_path: string;
  window_from: string | null;
  window_to: string | null;
  sessions: number | null;
  visitors: number | null;
  cart_addition_sessions: number | null;
  checkout_sessions: number | null;
  bounces: number | null;
  ad_spend: number | null;
  ad_impressions: number | null;
  ad_conv_value: number | null;
  distinct_ads: number | null;
  atc_rate: number | null;
  checkout_rate: number | null;
  bounce_rate: number | null;
  cost_per_session: number | null;
}

export interface LandingPageResponse {
  rows: LandingPageRow[];
  total: number;
}

export interface LandingPageParams {
  search?: string;
  sort?: "sessions" | "ad_spend" | "cost_per_session" | "checkout_rate";
  limit?: number;
  offset?: number;
}

export function fetchLandingPages(params: LandingPageParams = {}): Promise<LandingPageResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<LandingPageResponse>(`/admin/analytics/landing-pages${s ? `?${s}` : ""}`);
}

export interface LandingPageAdRow {
  landing_page_path: string;
  ad_id: string;
  ad_name: string | null;
  ad_status: string | null;
  campaign_name: string | null;
  adset_name: string | null;
  account_name: string | null;
  preview_link: string | null;
  ad_link: string | null;
  impressions: number | null;
  spend: number | null;
  conv_value: number | null;
  purchases: number | null;
  meta_roas: number | null;
  shopify_orders: number | null;
  shopify_sales: number | null;
  shopify_roas: number | null;
  roas_gap_pct: number | null;
  page_sessions: number | null;
  page_atc_rate: number | null;
  page_bounce_rate: number | null;
  page_cost_per_sess: number | null;
}

export interface LandingPageAdBreakdownResponse {
  rows: LandingPageAdRow[];
  total: number;
}

export function fetchLandingPageAdBreakdown(landingPagePath: string): Promise<LandingPageAdBreakdownResponse> {
  const encoded = landingPagePath.split("/").filter(Boolean).map(encodeURIComponent).join("/");
  return request<LandingPageAdBreakdownResponse>(`/admin/analytics/landing-pages/${encoded}/ads`);
}

// ---------------------------------------------------------------------
// Shopify Explorer -- ad-hoc metric x dimension pivot
// ---------------------------------------------------------------------

export interface ShopifyExplorerField {
  key: string;
  label: string;
}

export interface ShopifyExplorerSchemaDataset {
  key: string;
  label: string;
  date_dimension: string | null;
  dimensions: ShopifyExplorerField[];
  metrics: ShopifyExplorerField[];
}

export interface ShopifyExplorerSchemaResponse {
  datasets: ShopifyExplorerSchemaDataset[];
}

export function fetchShopifyExplorerSchema(): Promise<ShopifyExplorerSchemaResponse> {
  return request<ShopifyExplorerSchemaResponse>(`/admin/analytics/shopify-explorer/schema`);
}

export interface ShopifyExplorerQueryRequest {
  dataset: string;
  dimensions: string[];
  metrics: string[];
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface ShopifyExplorerQueryResponse {
  columns: string[];
  rows: Record<string, string | number | null>[];
}

export function queryShopifyExplorer(body: ShopifyExplorerQueryRequest): Promise<ShopifyExplorerQueryResponse> {
  return request<ShopifyExplorerQueryResponse>(`/admin/analytics/shopify-explorer/query`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------
// Meta Explorer -- ad-hoc metric x dimension pivot over the full-width
// Meta insights tables (ad_lifecycle / adset_insights / campaign_insights)
// ---------------------------------------------------------------------

export interface MetaExplorerSchemaDataset {
  key: string;
  label: string;
  date_dimension: string | null;
  dimensions: ShopifyExplorerField[];
  metrics: ShopifyExplorerField[];
}

export interface MetaExplorerSchemaResponse {
  datasets: MetaExplorerSchemaDataset[];
}

export function fetchMetaExplorerSchema(): Promise<MetaExplorerSchemaResponse> {
  return request<MetaExplorerSchemaResponse>(`/admin/analytics/meta-explorer/schema`);
}

export interface MetaExplorerQueryRequest {
  dataset: string;
  dimensions: string[];
  metrics: string[];
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface MetaExplorerQueryResponse {
  columns: string[];
  rows: Record<string, string | number | null>[];
}

export function queryMetaExplorer(body: MetaExplorerQueryRequest): Promise<MetaExplorerQueryResponse> {
  return request<MetaExplorerQueryResponse>(`/admin/analytics/meta-explorer/query`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------
// Customer Journey -- order <-> ad match, extended to the customer
// ---------------------------------------------------------------------

export interface CustomerJourneyOrderRow {
  order_id: string;
  name: string | null;
  total_price: number | null;
  created_at: string | null;
  tier: string | null;
  matched_ad_id: string | null;
  matched_ad_name: string | null;
  matched_campaign_id: string | null;
  matched_campaign_name: string | null;
  customer_id: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_city: string | null;
  customer_country: string | null;
  customer_lifetime_orders: number | null;
  customer_lifetime_spend: number | null;
  rfm_group: string | null;
  predicted_spend_tier: string | null;
  customer_cohort_month: string | null;
  days_since_last_order: number | null;
}

export interface CustomerJourneyResponse {
  rows: CustomerJourneyOrderRow[];
  total: number;
  rfm_counts: Record<string, number>;
}

export interface CustomerJourneyParams {
  rfm_group?: string;
  tier?: string;
  only_matched?: boolean;
  only_with_customer?: boolean;
  search?: string;
  sort?: "created_at" | "total_price" | "customer_lifetime_spend";
  limit?: number;
  offset?: number;
}

export function fetchCustomerJourney(params: CustomerJourneyParams = {}): Promise<CustomerJourneyResponse> {
  const qs = new URLSearchParams();
  if (params.rfm_group) qs.set("rfm_group", params.rfm_group);
  if (params.tier) qs.set("tier", params.tier);
  if (params.only_matched) qs.set("only_matched", "true");
  if (params.only_with_customer) qs.set("only_with_customer", "true");
  if (params.search) qs.set("search", params.search);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<CustomerJourneyResponse>(`/admin/analytics/customer-journey${s ? `?${s}` : ""}`);
}

export interface CustomerJourneyDetailOrderRow {
  order_id: string;
  name: string | null;
  total_price: number | null;
  created_at: string | null;
  tier: string | null;
  matched_ad_id: string | null;
  matched_ad_name: string | null;
  matched_campaign_name: string | null;
}

export interface CustomerJourneyDetailResponse {
  customer_id: string;
  customer_name: string | null;
  email: string | null;
  lifetime_orders: number | null;
  lifetime_spend: number | null;
  rfm_group: string | null;
  predicted_spend_tier: string | null;
  first_order_date: string | null;
  last_order_date: string | null;
  orders: CustomerJourneyDetailOrderRow[];
  ads_touched: string[];
}

export function fetchCustomerJourneyDetail(customerId: string): Promise<CustomerJourneyDetailResponse> {
  return request<CustomerJourneyDetailResponse>(`/admin/analytics/customer-journey/${encodeURIComponent(customerId)}`);
}

// ---------------------------------------------------------------------
// CPIS -- cost per NCP / cost per item sold, by master SKU
// ---------------------------------------------------------------------

export type CpisWindow = "1d" | "7d" | "30d";

export interface CpisRow {
  master_sku: string;
  window_key: CpisWindow;
  window_from: string | null;
  window_to: string | null;
  units_sold: number | null;
  ending_inventory_units: number | null;
  avg_sell_through_rate: number | null;
  matched_ad_count: number | null;
  // Windowed metrics (computed from raw_dump_meta) — respect the picked window.
  ad_spend: number | null;
  ncp_count: number | null;
  cost_per_ncp: number | null;
  cost_per_unit_sold: number | null;
  // Lifetime reference values (from cpis_by_sku direct storage) so the
  // UI can show "windowed / lifetime" pairs.
  ad_spend_lifetime: number | null;
  ncp_count_lifetime: number | null;
}

export interface CpisResponse {
  rows: CpisRow[];
  total: number;
}

export interface CpisParams {
  window?: CpisWindow;
  search?: string;
  only_matched?: boolean;
  sort?: "ad_spend" | "cost_per_ncp" | "cost_per_unit_sold" | "units_sold";
  limit?: number;
  offset?: number;
}

export function fetchCpis(params: CpisParams = {}): Promise<CpisResponse> {
  const qs = new URLSearchParams();
  if (params.window) qs.set("window", params.window);
  if (params.search) qs.set("search", params.search);
  if (params.only_matched) qs.set("only_matched", "true");
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<CpisResponse>(`/admin/analytics/cpis${s ? `?${s}` : ""}`);
}

export interface CpisMatchedAdRow {
  ad_id: string;
  ad_name: string | null;
  ad_effective_status: string | null;
  account_name: string | null;
  category: string | null;
  spend: number | null;
  ncp_count: number | null;
  conv_value: number | null;
  roas: number | null;
  cost_per_ncp: number | null;
  impressions: number | null;
  clicks: number | null;
  ctr: number | null;
}

export interface CpisMatchedAdsResponse {
  master_sku: string;
  ads: CpisMatchedAdRow[];
}

export function fetchCpisMatchedAds(masterSku: string): Promise<CpisMatchedAdsResponse> {
  return request<CpisMatchedAdsResponse>(`/admin/analytics/cpis/${encodeURIComponent(masterSku)}/ads`);
}

// ---------------------------------------------------------------------
// CPIS via UTM-attributed orders (order.utm_content -> ad_id,
// order.line_items.sku -> master_sku). Real attribution, not correlation.
// See app/services/gold/cpis_utm.py for the module-level rationale.
// ---------------------------------------------------------------------

export type CpisUtmWindow = "7d" | "30d" | "90d";

export type CpisUtmSort =
  | "ad_spend"
  | "attributed_orders"
  | "attributed_units"
  | "attributed_revenue"
  | "cost_per_order"
  | "cost_per_unit_sold"
  | "roas";

export interface CpisUtmRow {
  master_sku: string;
  window_key: CpisUtmWindow;
  window_from: string | null;
  window_to: string | null;
  // Product context (from raw_dump_shopify products with SKU-tag match)
  product_name: string | null;
  category: string | null;
  product_type_count: number | null;
  price_min: number | null;
  price_max: number | null;
  variant_count: number | null;
  available_variant_count: number | null;
  // Name-matched (primary attribution: SKU code in ad_name)
  name_matched_ads: number | null;
  name_matched_spend: number | null;
  // UTM-matched spend (2026-09-02). For each SKU, sum of windowed spend
  // for the SET of ad_ids that appeared in this SKU's UTM-attributed
  // orders. Answers "how much did I spend on ads that actually reached
  // buyers of this SKU?" -- much broader than name_matched (which only
  // catches ads NAMED after the SKU). Deliberately double-counts across
  // SKUs -- an ad selling SMCP+SDCP counts 100% for both.
  utm_matched_ads: number | null;
  utm_matched_spend: number | null;
  utm_matched_ncp: number | null;
  name_matched_ncp: number | null;
  name_matched_roas_lifetime: number | null;
  name_matched_nc_roas: number | null;
  active_creative_count: number | null;
  winning_creative_count: number | null;
  active_spend_per_day: number | null;
  lc_avg_order_value: number | null;
  lc_avg_qty_per_order: number | null;
  // Sparkline: daily spend series for the picked window + previous
  // period total (same-length days before window_from) for a % change
  // comparison. Nulls when no name-matched ads had any spend.
  spend_trend_current: number[] | null;
  spend_trend_prev_total: number | null;
  // Inventory -- ONE Shopify source (2026-09-04). units_in_stock and
  // both in-stock rates roll up from raw_dump_shopify
  // products.variants[].inventoryQuantity on master_sku, so they
  // reconcile with each other and with variant_count above. Rates are
  // 0-100 percentages, already rounded to 1dp server-side.
  units_in_stock: number | null;
  // Denominator for variant_in_stock_rate. NOT variant_count above:
  // that counts non-price-test listings (the catalogue entry), this
  // counts every variant SKU holding stock (the inventory).
  variant_total_ct: number | null;
  variant_in_stock_ct: number | null;
  variant_in_stock_rate: number | null;
  // size_* counts DISTINCT sizes (the _<size> suffix on the variant
  // SKU) still available in ANY color -- catches size-run gaps the
  // variant rate hides. null when the SKU has no size-suffixed variants.
  size_total_ct: number | null;
  size_in_stock_ct: number | null;
  size_in_stock_rate: number | null;
  // Per-size stock breakdown, e.g. {"XS":12, "S":65, "M":29, ...}.
  // Not in the main table; kept for CSV export and drilldown.
  stock_by_size: Record<string, number | null> | null;
  // MapleMonk inventory-planning (variant-latest, aggregated per
  // master_sku from bq_inventory_daily's 90-day pull)
  mm_as_of_date: string | null;
  mm_variant_ct: number | null;
  mm_current_stock: number | null;
  mm_total_inprogress: number | null;
  mm_daily_quantity: number | null;
  mm_t45_quantity: number | null;
  mm_total_sales_45d: number | null;
  // Every DoQ variant MapleMonk publishes, aggregated to master SKU
  // (AVG across variants -- DoQ is a per-variant rate).
  mm_doq_7: number | null;
  mm_doq_15: number | null;
  mm_doq_30: number | null;
  mm_doq_45: number | null;
  mm_doq_90: number | null;
  mm_doq_365: number | null;
  mm_doq_7_30: number | null;
  mm_doq_30_45: number | null;
  mm_weighted_doq_45: number | null;
  mm_weightage_doq: number | null;
  mm_monthly_doq: number | null;
  mm_yearly_doq: number | null;
  mm_v_doq: number | null;
  mm_oos_days_30: number | null;
  mm_oos_days_90: number | null;
  mm_lead_time: number | null;
  mm_buffer_days: number | null;
  // Business-model columns (2026-09-03, matches ops sheet formulas):
  //   COGS = SP*35%, Gross Margin % = 65%, LOG&RTN = SP*10%, Contribution = SP*55%
  selling_price: number | null;
  cogs: number | null;
  gross_margin_pct: number | null;
  contribution_margin: number | null;
  logistics_return: number | null;
  // DoQ (Daily Order Quantity): mean units sold per day over the
  // trailing 30 days, from Shopify. A RATE (units/day), not days --
  // which is what makes total_doh = units_in_stock / daily_order_qty
  // come out in days. Replaces the MapleMonk mm_doq_30 column, which
  // was itself already a days figure; the two are not interchangeable.
  daily_order_qty: number | null;
  units_sold_30d: number | null;
  // ISO timestamp of the Shopify products snapshot behind
  // units_in_stock and the price ladder. Shown on the KPI tile so a
  // stale ingest doesn't read as a stock movement.
  inventory_as_of: string | null;
  ip_doq: number | null;
  total_doh: number | null;
  oos_pct: number | null;
  tentative_replenish_date: string | null;
  halo_sale_pct: number | null;
  pipeline_avail_to_test: number | null;
  // Per-SKU untested-asset backlog counts. Rendered as three columns
  // in the CPIS table so a merchant can see "how many videos / graphics
  // / influencer posts I still have queued for this SKU."
  // Influencer is 0 for every SKU today (SIF-<n>-P<n> nomenclature
  // carries no product code); tooltip explains.
  untested_video_ct: number | null;
  untested_graphic_ct: number | null;
  untested_influencer_ct: number | null;
  // Return metrics from BQ (MapleMonk consolidated returns, joined
  // per-window). null when the SKU has no rows in master_sku_returns
  // (small / new SKU with no return history yet).
  return_rate_pct: number | null;
  return_units: number | null;
  refund_value: number | null;
  // gross ROAS * (1 - return_rate/100). Same nulling behaviour.
  net_roas: number | null;
  // Creative-testing cadence: 1 test / week per 1L of weekly ad spend.
  // Compare against untested_video_ct + untested_graphic_ct to see if
  // the backlog covers next week's requirement.
  weekly_ad_spend: number | null;
  required_creatives_per_week: number | null;
  // UTM-attributed (secondary comparison signal). Two spend allocations
  // populated in one refresh pass -- attribution-mode toggle picks which
  // to render:
  //   equal   : each order carries the same slice of ad spend, then
  //             within-order split by line-item revenue
  //   value_weighted : each order carries spend proportional to its own
  //                    value (bigger baskets absorb more)
  // Both reconcile to the exact same total Meta ad-spend.
  attributed_orders: number | null;
  attributed_units: number | null;
  attributed_revenue: number | null;
  matched_ad_count: number | null;
  ad_spend: number | null;              // equal-per-order
  cost_per_order: number | null;
  cost_per_unit_sold: number | null;
  roas: number | null;
  ad_spend_vw: number | null;           // value-weighted
  cost_per_order_vw: number | null;
  cost_per_unit_sold_vw: number | null;
  roas_vw: number | null;
  // Halo counterpart -- basket effect from the same ad-driven orders.
  // Not counted in CPIS / ROAS (those use primary only).
  halo_orders: number | null;
  halo_units: number | null;
  halo_revenue: number | null;
  halo_spend: number | null;
  primary_weight: number | null;
  // Derived: attributed_revenue / attributed_units
  avg_selling_price: number | null;
}

export type CpisAttributionMode = "equal" | "value_weighted";

export interface CpisUtmResponse {
  rows: CpisUtmRow[];
  total: number;
  // Reconciliation totals for the picked window (added 2026-09-03).
  // The KPI strip surfaces these so the "Ad spend" tile reflects the
  // true Meta window total, not just the paginated-row sum:
  //   meta_total_spend   Meta actual spend in the window (from silver)
  //   attributed_spend   slice attributed to a catalog SKU (across ALL SKUs)
  //   untethered_spend   meta_total_spend - attributed_spend
  meta_total_spend: number | null;
  attributed_spend: number | null;
  untethered_spend: number | null;
}

export interface CpisUtmParams {
  window?: CpisUtmWindow;
  // Custom date range. When both are set, overrides `window` and pulls
  // a summed row set from cpis_by_sku_daily on the fly.
  from_date?: string;    // YYYY-MM-DD
  to_date?:   string;    // YYYY-MM-DD
  search?: string;
  // Default false server-side: the table shows the whole live catalogue,
  // with attribution columns at zero for SKUs no ad drove. Set true to
  // narrow to SKUs with at least one attributed order in the window.
  only_matched?: boolean;
  // Include archived SKUs -- zero stock, no active listing, nothing sold
  // in 30 days. ~11 of the 97 master SKUs. Off by default.
  include_archived?: boolean;
  sort?: CpisUtmSort;
  limit?: number;
  offset?: number;
}

export function fetchCpisUtm(params: CpisUtmParams = {}): Promise<CpisUtmResponse> {
  const qs = new URLSearchParams();
  if (params.from_date && params.to_date) {
    qs.set("from_date", params.from_date);
    qs.set("to_date",   params.to_date);
  } else if (params.window) {
    qs.set("window", params.window);
  }
  if (params.search) qs.set("search", params.search);
  if (params.only_matched !== undefined) qs.set("only_matched", String(params.only_matched));
  if (params.include_archived) qs.set("include_archived", "true");
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<CpisUtmResponse>(`/admin/analytics/cpis-utm${s ? `?${s}` : ""}`);
}

export interface CpisSpendTrendResponse {
  master_sku: string;
  window_key: CpisUtmWindow;
  window_from: string | null;
  window_to: string | null;
  spend_trend_current: number[];
  spend_trend_prev_total: number | null;
}

export function fetchCpisSpendTrend(masterSku: string, window: CpisUtmWindow): Promise<CpisSpendTrendResponse> {
  const qs = new URLSearchParams({ master_sku: masterSku, window });
  return request<CpisSpendTrendResponse>(`/admin/analytics/cpis-utm/spend-trend?${qs.toString()}`);
}

// ---------------------------------------------------------------------
// Instagram — per-post Silver read over public.insta_data
// ---------------------------------------------------------------------

export interface InstagramPostRow {
  id: string;
  source_id: string | null;
  media_id: string | null;
  ig_object_id: string | null;
  username: string | null;
  media_owner_username: string | null;
  caption: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
  media_type: string | null;
  media_product_type: string | null;
  media_audio_type: string | null;
  permalink: string | null;
  shortcode: string | null;
  posted_at: string | null;
  is_comment_enabled: boolean | null;
  is_shared_to_feed: boolean | null;
  is_ai_generated: boolean | null;
  like_count: number | null;
  comments_count: number | null;
  total_like_count: number | null;
  total_comments_count: number | null;
  total_views_count: number | null;
  saved_count: number | null;
  shares_count: number | null;
  reposts_count: number | null;
  insights_reach: number | null;
  insights_views: number | null;
  avg_watch_time_ms: number | null;
  total_watch_time_ms: number | null;
  reels_skip_rate_pct: number | null;
  insights_follows: number | null;
  insights_profile_visits: number | null;
  insights_profile_activity: number | null;
  insights_navigation: number | null;
  insights_replies: number | null;
  insights_total_interactions: number | null;
  ingested_at: string | null;
}

export interface InstagramProfile {
  username: string | null;
  ig_user_id: string | null;
  biography: string | null;
  website: string | null;
  profile_picture_url: string | null;
  followers_count: number | null;
  follows_count: number | null;
  media_count: number | null;
}

export interface InstagramSummary {
  total_posts: number;
  total_reach: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  avg_engagement_rate_pct: number | null;
  media_type_counts: Record<string, number>;
  profiles: InstagramProfile[];
  silver_last_ingested_at: string | null;
}

export interface InstagramPostsResponse {
  rows: InstagramPostRow[];
  total: number;
  summary: InstagramSummary;
}

export type InstagramSort =
  | "posted_at"
  | "like_count"
  | "comments_count"
  | "insights_reach"
  | "insights_views"
  | "total_views_count"
  | "insights_total_interactions";

export interface InstagramParams {
  username?: string;
  media_type?: string;
  media_product_type?: string;
  search?: string;
  from_date?: string;
  to_date?: string;
  sort?: InstagramSort;
  limit?: number;
  offset?: number;
}

export function fetchInstagram(params: InstagramParams = {}): Promise<InstagramPostsResponse> {
  const qs = new URLSearchParams();
  if (params.username) qs.set("username", params.username);
  if (params.media_type) qs.set("media_type", params.media_type);
  if (params.media_product_type) qs.set("media_product_type", params.media_product_type);
  if (params.search) qs.set("search", params.search);
  if (params.from_date) qs.set("from_date", params.from_date);
  if (params.to_date) qs.set("to_date", params.to_date);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<InstagramPostsResponse>(`/admin/analytics/instagram${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Saturation curve -- real Python-computed power-law fit (spend vs.
// conversions), not a canned table
// ---------------------------------------------------------------------

export type SaturationYMetric = "ncp_count" | "purchases" | "ftewv_count";

export interface SaturationPoint {
  ad_id: string;
  ad_name: string | null;
  spend: number;
  y: number;
}

export interface SaturationFit {
  a: number;
  b: number;
  r_squared: number;
  is_saturating: boolean;
  curve_points: { x: number; y: number }[];
}

export interface SaturationCurveResponse {
  y_metric: SaturationYMetric;
  y_label: string;
  points: SaturationPoint[];
  fit: SaturationFit | null;
  excluded_zero_or_missing: number;
}

export interface SaturationCurveParams {
  y_metric?: SaturationYMetric;
  master_sku?: string;
  category?: string;
  account_name?: string;
}

export function fetchSaturationCurve(params: SaturationCurveParams = {}): Promise<SaturationCurveResponse> {
  const qs = new URLSearchParams();
  if (params.y_metric) qs.set("y_metric", params.y_metric);
  if (params.master_sku) qs.set("master_sku", params.master_sku);
  if (params.category) qs.set("category", params.category);
  if (params.account_name) qs.set("account_name", params.account_name);
  const s = qs.toString();
  return request<SaturationCurveResponse>(`/admin/analytics/saturation-curve${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Overview summary -- powers the Dashboard tab's widget tiles
// ---------------------------------------------------------------------

export interface BreakdownItem {
  label: string;
  value: number;
}

export interface TopLandingPage {
  landing_page_path: string;
  sessions: number;
  ad_spend: number;
}

export interface TopCpisSku {
  master_sku: string;
  ad_spend: number;
  cost_per_ncp: number | null;
}

export interface OverviewSummaryResponse {
  total_spend: number;
  total_impressions: number;
  total_shopify_revenue: number;
  total_shopify_orders: number;
  category_breakdown: BreakdownItem[];
  channel_breakdown: BreakdownItem[];
  top_landing_pages: TopLandingPage[];
  top_cpis_skus: TopCpisSku[];
}

export function fetchOverviewSummary(): Promise<OverviewSummaryResponse> {
  return request<OverviewSummaryResponse>(`/admin/analytics/overview-summary`);
}

// Silver-table refresh cascade -- fires the 3 CPIS refresh scripts in
// sequence as a background asyncio task. Returns a run_id that can be
// used to tail progress via /logs?run_id=<id>.
export interface RefreshSilverResponse {
  run_id: string;
  started_at: string;
  scripts: string[];
}

export function triggerSilverRefresh(): Promise<RefreshSilverResponse> {
  return request<RefreshSilverResponse>(`/admin/refresh/silver-all`, { method: "POST" });
}

// CPIS data-freshness probe. Used to cap the date-range picker's
// default to_date to the freshest day the underlying tables have --
// avoids showing empty ranges when a merchant opens the page.
export interface CpisDataFreshness {
  max_meta_day: string | null;    // freshest Meta insight day (YYYY-MM-DD)
  max_orders_day: string | null;  // freshest Shopify processed_at day
  max_daily_day: string | null;   // freshest day in cpis_by_sku_daily
  distinct_skus: number;
  computed_at: string;
}

export function fetchCpisDataFreshness(): Promise<CpisDataFreshness> {
  return request<CpisDataFreshness>(`/admin/analytics/cpis-utm/data-freshness`);
}

// Untested assets — three media types (video / graphic / influencer),
// each backed by its own mirrored table from the legacy CTD dashboard.
// The endpoint normalizes them to a common row shape so a single UI
// component renders all three with media-aware column tweaks.
export type UntestedMedia = "video" | "graphic" | "influencer";

export interface UntestedAssetRow {
  id: string;
  media: UntestedMedia;
  title: string | null;             // username (inf) / product (graphic) / null (video)
  nomenclature: string | null;
  kind: string | null;              // asset_type / graphic_type / content_type
  sub_kind: string | null;          // category / audience_type / deliverable_type
  link: string | null;
  thumbnail: string | null;
  date_produced: string | null;
  created_at: string | null;
  candidate_master_sku: string | null;
  matched_master_sku: string | null;
  sku_attributed_orders: number | null;
  sku_ad_spend: number | null;
  sku_cost_per_order: number | null;
}

export interface UntestedAssetsResponse {
  media: UntestedMedia;
  total_rows: number;
  with_sku_match: number;
  without_sku_match: number;
  rows: UntestedAssetRow[];
  computed_at: string;
}

export interface UntestedAssetsParams {
  media?: UntestedMedia;
  has_sku?: boolean;
}

export function fetchUntestedAssets(params: UntestedAssetsParams = {}): Promise<UntestedAssetsResponse> {
  const q = new URLSearchParams();
  if (params.media) q.set("media", params.media);
  if (params.has_sku !== undefined) q.set("has_sku", String(params.has_sku));
  const qs = q.toString();
  return request<UntestedAssetsResponse>(`/admin/analytics/untested${qs ? `?${qs}` : ""}`);
}

// Dashboard tab -- per-widget fetchers. Fire in parallel and render
// each widget as its own data arrives (progressive loading).
export interface DashboardKpis {
  total_spend: number;
  total_impressions: number;
  total_shopify_revenue: number;
  total_shopify_orders: number;
}

export const fetchDashboardKpis = () =>
  request<DashboardKpis>(`/admin/analytics/dashboard/kpis`);
export const fetchDashboardCategoryBreakdown = () =>
  request<BreakdownItem[]>(`/admin/analytics/dashboard/category-breakdown`);
export const fetchDashboardChannelBreakdown = () =>
  request<BreakdownItem[]>(`/admin/analytics/dashboard/channel-breakdown`);
export const fetchDashboardTopLandingPages = () =>
  request<TopLandingPage[]>(`/admin/analytics/dashboard/top-landing-pages`);
export const fetchDashboardTopCpisSkus = () =>
  request<TopCpisSku[]>(`/admin/analytics/dashboard/top-cpis-skus`);

export function retryFailedJobs(maxJobs = 100): Promise<RetryFailedJobsResponse> {
  return request<RetryFailedJobsResponse>(`/failed-jobs/retry?max_jobs=${maxJobs}`, {
    method: "POST",
  });
}

export interface SchedulerJobOut {
  id: string;
  name: string;
  trigger: string;
  next_run_time: string | null;
}

export interface SchedulerStatusResponse {
  enabled: boolean;
  running: boolean;
  timezone: string;
  jobs: SchedulerJobOut[];
}

export function fetchSchedulerStatus(): Promise<SchedulerStatusResponse> {
  return request<SchedulerStatusResponse>("/admin/scheduler");
}

export type FileErrorSource = "shopify" | "instagram";

export interface FileErrorEntry {
  timestamp: string;
  label: string;
  object_type: string;
  message: string;
}

export interface FileErrorsResponse {
  source: FileErrorSource;
  total: number;
  errors: FileErrorEntry[];
}

export function fetchFileErrors(source: FileErrorSource, limit = 50): Promise<FileErrorsResponse> {
  return request<FileErrorsResponse>(`/admin/errors/files?source=${source}&limit=${limit}`);
}

export { ApiError };
