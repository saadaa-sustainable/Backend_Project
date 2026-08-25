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

export interface IngestRequest {
  sources: IngestSource[];
  date_start?: string; // YYYY-MM-DD -- required when "meta" is in sources
  date_end?: string; // YYYY-MM-DD -- required when "meta" is in sources
  target_table?: string; // required when "instagram" is in sources
  since?: string; // YYYY-MM-DD -- instagram only, optional start-date override
  // Meta only, optional -- omit for all four levels. Execution always runs
  // ad -> adset -> campaign -> account regardless of the order sent here
  // (backend re-sorts to META_LEVEL_FETCH_ORDER).
  meta_levels?: MetaInsightsLevel[];
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
