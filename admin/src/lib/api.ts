// Thin fetch wrappers over this project's FastAPI admin routes
// (app/api/routers/admin.py). Kept deliberately free of any UI concerns —
// pages import types and call functions from here, nothing more.

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  ad_id: string;
  ad_name: string | null;
  ad_status: string | null;
  ad_effective_status: string | null;
  adset_name: string | null;
  campaign_name: string | null;
  account_name: string | null;
  category: string | null;
  spend: number | null;
  impressions: number | null;
  purchases: number | null;
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
}

export interface AdsAnalyseResponse {
  rows: AdsAnalyseRow[];
  total: number;
}

export type AdsAnalyseSort = "spend" | "meta_roas" | "shopify_roas" | "shopify_revenue" | "impressions";

export interface AdsAnalyseParams {
  account_name?: string;
  campaign_name?: string;
  ad_effective_status?: string;
  search?: string;
  only_with_shopify_orders?: boolean;
  sort?: AdsAnalyseSort;
  limit?: number;
  offset?: number;
}

export function fetchAdsAnalyse(params: AdsAnalyseParams = {}): Promise<AdsAnalyseResponse> {
  const qs = new URLSearchParams();
  if (params.account_name) qs.set("account_name", params.account_name);
  if (params.campaign_name) qs.set("campaign_name", params.campaign_name);
  if (params.ad_effective_status) qs.set("ad_effective_status", params.ad_effective_status);
  if (params.search) qs.set("search", params.search);
  if (params.only_with_shopify_orders) qs.set("only_with_shopify_orders", "true");
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.offset) qs.set("offset", String(params.offset));
  const s = qs.toString();
  return request<AdsAnalyseResponse>(`/admin/analytics/ads-analyse${s ? `?${s}` : ""}`);
}

// ---------------------------------------------------------------------
// Last Click UTM -- order-level Shopify -> Meta attribution
// ---------------------------------------------------------------------

export type UtmChannel = "Meta" | "Google" | "Retention" | "Other";

export interface UtmOrderRow {
  order_id: string;
  name: string | null;
  total_price: number | null;
  created_at: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  utm_content: string | null;
  utm_term: string | null;
  tier: string | null;
  matched_ad_id: string | null;
  matched_ad_name: string | null;
  matched_campaign_id: string | null;
  matched_campaign_name: string | null;
  channel: UtmChannel;
}

export interface ChannelSummary {
  count: number;
  sales: number;
}

export interface UtmOrderResponse {
  rows: UtmOrderRow[];
  total: number;
  channel_counts: Record<UtmChannel, ChannelSummary>;
  tier_counts: Record<string, number>;
}

export interface LastClickUtmParams {
  channel?: UtmChannel;
  tier?: string;
  utm_source?: string;
  utm_campaign?: string;
  search?: string;
  sort?: "created_at" | "total_price";
  limit?: number;
  offset?: number;
}

export function fetchLastClickUtm(params: LastClickUtmParams = {}): Promise<UtmOrderResponse> {
  const qs = new URLSearchParams();
  if (params.channel) qs.set("channel", params.channel);
  if (params.tier) qs.set("tier", params.tier);
  if (params.utm_source) qs.set("utm_source", params.utm_source);
  if (params.utm_campaign) qs.set("utm_campaign", params.utm_campaign);
  if (params.search) qs.set("search", params.search);
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
  ad_spend: number | null;
  ncp_count: number | null;
  cost_per_ncp: number | null;
  cost_per_unit_sold: number | null;
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
  spend: number | null;
  ncp_count: number | null;
  category: string | null;
}

export interface CpisMatchedAdsResponse {
  master_sku: string;
  ads: CpisMatchedAdRow[];
}

export function fetchCpisMatchedAds(masterSku: string): Promise<CpisMatchedAdsResponse> {
  return request<CpisMatchedAdsResponse>(`/admin/analytics/cpis/${encodeURIComponent(masterSku)}/ads`);
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
