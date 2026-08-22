# Meta Marketing API → Medallion (Bronze/Silver/Gold) Ingestion Service

A production-grade FastAPI service that ingests raw data from the Meta
Marketing API — accounts, campaigns, ad sets, ads, creatives, assets,
audiences, pixels, custom conversions, activities, business assets,
catalogs, products, labels, and the full Insights (performance metrics)
engine — into a PostgreSQL **Bronze layer**, then computes the Silver
(cleaned/joined) and Gold (business-ready aggregate) layers on top, all in
Python within this same service.

This is the ingestion+compute engine behind a Creative Testing Dashboard
that previously ran on ad-hoc `requests`-based cron scripts writing
directly to Supabase — this service replaces that pipeline's HTTP/retry
logic with a proper async client, and reorganizes the previously flat,
30-ish-table Supabase schema into three explicit layers.

No Docker, Redis, Celery, Kafka, or Airflow — it's a single Python process
(FastAPI + APScheduler) you run directly with `uvicorn`.

## Architecture

```
app/
├── api/                # FastAPI routers + request-scoped dependencies
│   └── routers/        # sync.py, status.py, failed_jobs.py
├── core/                # exceptions, Meta credential handling, field/breakdown/attribution registries
├── database/            # async SQLAlchemy engine + session management
├── models/               # SQLAlchemy ORM models — Bronze is one table (see below)
├── schemas/              # Pydantic v2 request/response schemas
├── repositories/         # persistence layer (generic Bronze repo + batch/failed-job repos)
├── services/meta/         # one ingestion service per Meta endpoint + generic API client
├── scheduler/             # APScheduler jobs (daily/hourly/backfill/retry)
├── logging/                # structlog configuration
└── config.py               # Pydantic Settings (env-driven)
```

### Bronze: one table, not one-per-entity

Every Meta object type — accounts, campaigns, ad sets, ads, creatives,
insights, images, videos, audiences, pixels, custom conversions,
activities, business assets, catalogs, products, labels — lands in a
single consolidated table, **`raw_dump_meta`** (`app/models/raw_dump.py`),
tagged by an `object_type` column. Bronze's only job is "get the exact
bytes Meta returned into Postgres" — there's no reason to fragment that
across 18 tables. All structuring, unnesting, typing, and joining happens
in Silver, which reads `raw_dump_meta` filtered by `object_type`.

Two fetch shapes land in this table:
- **Flat** (`is_nested=false`) — one row per Meta object, from the normal
  per-endpoint services (`CampaignSyncService`, `AdSyncService`, etc.).
- **Nested** (`is_nested=true`) — one row per top-level object holding a
  whole expanded child tree (e.g. a campaign with its ad sets and ads
  embedded inline), from `CampaignTreeSyncService`
  (`app/services/meta/nested_tree.py`). This exists specifically to cut
  API call volume/rate-limit pressure on large accounts by using Graph
  API's nested field-expansion syntax instead of one paginated request per
  level — see that module's docstring for the real trade-offs (nested
  connections cap out at their own `.limit()` and don't auto-paginate).
  It's an opt-in alternative to campaigns+adsets+ads, not run by default
  alongside them (`/sync/campaign_tree`, excluded from `/sync/all`).

Every row also has a `parent_ids` JSONB column — a denormalized
convenience (e.g. `{"account_id": ..., "campaign_id": ...}` on an ad set
row) so Silver can filter/join without parsing the full `raw_payload` for
the common case. It's never authoritative — always re-derivable from
`raw_payload`.

**Design principles applied:**
- **Repository pattern** — services never touch SQLAlchemy sessions directly.
- **Template method** — `BaseMetaSyncService` implements the batch
  lifecycle (open batch → stream → chunk-insert → close batch) once;
  concrete services (`CampaignSyncService`, etc.) only implement "what to
  fetch" (`fetch_records`) and "what parent ids to denormalize"
  (`extract_parent_ids`).
- **Registry pattern** — `app/core/meta_registry.py` is the single source
  of truth for insight metrics, breakdowns, attribution windows, and
  per-object field lists. Adding a new Meta field is a one-line change, not
  a code change.
- **Dependency injection** — FastAPI `Depends()` wires sessions/clients;
  everything is overridable in tests.
- `raw_dump_meta` conforms to `BronzeMixin`: `id`, `meta_id`, `raw_payload`,
  `api_endpoint`, `api_version`, `batch_id`, `request_params`,
  `extracted_at`, `ingested_at`, `sync_type`, `payload_hash`,
  `processing_status`, plus `object_type`, `parent_ids`, `is_nested`.

## Requirements

- **Python 3.12+** (the codebase uses `StrEnum`, `X | Y` unions evaluated
  via `from __future__ import annotations`, `datetime.UTC`, and other
  3.11/3.12 standard library additions).
- **PostgreSQL 14+** running locally (no Docker — install via your OS
  package manager, e.g. `brew install postgresql@16` on macOS).
- A Meta Marketing API **System User access token** with `ads_read` (and
  `ads_management` if you'll eventually write back) permission on every ad
  account you configure — a System User token with Business Manager access
  can cover several accounts with one token, which is the normal
  multi-account setup this service expects.

> This code was authored in an environment that only had system Python
> 3.9 available (no `pip`/`poetry`/`pyenv`/`brew` on `PATH`), so the full
> app (SQLAlchemy models, FastAPI) could not be executed there — it uses
> `StrEnum`/`X | Y` runtime evaluation/`datetime.UTC` that need 3.11+.
> Every module was written and manually syntax-checked (`ast.parse`). One
> piece *was* verified live in that same 3.9 environment:
> `scripts/dry_run_meta.py` (deliberately stdlib+requests only, no 3.12
> dependency) successfully authenticated and fetched real ad data,
> confirming the credential/account-discovery scheme works end-to-end
> against the real Meta API. Still run the full `pytest` suite yourself
> after installing Python 3.12+ before relying on the rest in production.

## Setup

### 1. Install Python 3.12+ and create a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

With Poetry (preferred):

```bash
poetry install
```

Or with pip:

```bash
pip install -r requirements.txt
```

### 3. Create the PostgreSQL database

```bash
createuser meta_ingest --pwprompt   # set password to "meta_ingest" to match .env.example, or customize
createdb meta_ingest --owner=meta_ingest
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `META_ACCESS_TOKEN` — your long-lived Meta access token
- `META_ACCOUNT_1_ID` (and `_NAME`) — your first ad account id (with or
  without the `act_` prefix) and a local label. Add `META_ACCOUNT_2_ID`,
  `META_ACCOUNT_3_ID`, ... for more — no code change needed, the service
  discovers however many are configured and syncs every one of them by
  default (see [Multi-account behavior](#multi-account-behavior) below).
- `META_API_VERSION` — e.g. `v21.0`
- `DATABASE_URL` / `DATABASE_URL_SYNC` — if you changed the DB user/password/name above

### 5. Run database migrations

```bash
alembic upgrade head
```

This creates every Bronze table plus the `sync_batches` / `failed_jobs`
operational tables (see `alembic/versions/0001_initial_bronze_schema.py`).

### 6. Start the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or:

```bash
python -m app.main
```

Visit `http://localhost:8000/docs` for interactive OpenAPI docs.

### 7. Run the test suite

```bash
pytest
```

Tests in `tests/test_client.py` mock the Graph API via `respx` — no
network access or live credentials required. `tests/test_meta_registry.py`
and `tests/test_schemas.py` are pure unit tests. Repository/database
integration tests were intentionally not faked against SQLite (the
`JSONB`/`UUID` Postgres column types don't behave identically there) — add
`tests/test_repositories.py` against a real local Postgres instance if you
want DB-level coverage.

## Multi-account behavior

Every `/sync/*` route runs against **every configured account by default**
(`META_ACCOUNT_1_ID`, `META_ACCOUNT_2_ID`, ...) — pass `"account": "2"` in
the request body to scope a call to just one. Responses are always a list,
one entry per account touched:

```json
{
  "batches": [
    {"account_key": "1", "account_name": "Main Store", "endpoint": "campaigns", "status": "success", ...},
    {"account_key": "2", "account_name": "Sustainable Line", "endpoint": "campaigns", "status": "success", ...}
  ]
}
```

Business-scoped endpoints (`business_assets`, `catalogs`, `products` —
Business Manager data, not tied to any one ad account) run **once**
regardless of how many accounts are configured, not once per account,
since that would just write duplicate rows. Every `raw_dump_meta` row is
also tagged with `account_key`/`account_name` in its `parent_ids` column
automatically (see `BaseMetaSyncService.build_row`), and every
`sync_batches`/`failed_jobs` row carries the same, so `/status`,
`/logs`, and `/failed-jobs` all accept an `?account=` filter. Retries
replay a failed job against the *same* account it originally failed on
(`FailedJob.account_key`), not an arbitrary default.

**Accounts run concurrently, not one after another.**
`MultiAccountSyncCoordinator` (`app/services/meta/orchestrator.py`) gives
each account its own DB session and its own `MetaAPIClient`, then fires
every account's work via `asyncio.gather`, bounded by
`MAX_CONCURRENT_ACCOUNT_SYNCS` (default 4) so a large account roster can't
open unbounded DB connections. This is necessary, not just faster: a
single SQLAlchemy `AsyncSession` cannot be safely used from multiple
coroutines at once, so real parallelism means real separate sessions —
which also means each account's writes commit independently, so one
account's failure never blocks or rolls back another's. For `sync_all`,
exactly one account (the first, by config order — independent of which
finishes first) fetches business-scoped data; the rest skip it.

## Usage

### Trigger a sync manually

```bash
# Every configured account
curl -X POST http://localhost:8000/sync/campaigns -H "Content-Type: application/json" -d '{}'

# Just one account
curl -X POST http://localhost:8000/sync/campaigns -H "Content-Type: application/json" -d '{"account": "2"}'

curl -X POST http://localhost:8000/sync/insights -H "Content-Type: application/json" -d '{
  "levels": ["campaign", "adset", "ad"],
  "date_preset": "last_30d",
  "time_increment": "1",
  "breakdowns": [["age", "gender"], ["publisher_platform", "platform_position"]],
  "action_breakdowns": ["action_type"],
  "attribution_windows": ["1d_click", "7d_click", "28d_click"],
  "use_unified_attribution_setting": true,
  "filtering": [{"field": "campaign.effective_status", "operator": "IN", "value": ["ACTIVE"]}],
  "sort": ["spend_descending"]
}'
curl -X POST http://localhost:8000/sync/all -H "Content-Type: application/json" -d '{"sync_type": "manual"}'
```

For a full historical backfill (`date_preset=maximum` across every level), pass
`"use_async": true` in the `/sync/insights` body — this submits the request via
Meta's async report-run flow (`POST` → poll `report_run_id` → `GET` results)
instead of a synchronous paginated `GET`, avoiding request timeouts on large
accounts. See `InsightsSyncRequest` in `app/schemas/sync.py` for the complete
parameter set (`time_ranges`, `summary`, `product_id_limit`, `locale`, etc.).

### Check status

```bash
curl http://localhost:8000/health
curl http://localhost:8000/status
curl "http://localhost:8000/status?account=2"          # just one account
curl http://localhost:8000/logs?limit=20
curl http://localhost:8000/failed-jobs
curl -X POST http://localhost:8000/failed-jobs/retry
```

### Quick connectivity check without running the API

```bash
python3 scripts/dry_run_meta.py               # first configured account, one ad, no DB writes
python3 scripts/dry_run_meta.py --account 2    # a specific account
```

Deliberately stdlib+`requests`-only (no 3.12 dependency) — useful for
verifying a token/account before wiring up the full service.

### Scheduled jobs

Controlled via `SCHEDULER_*` env vars:

- `daily_sync` — every day at `SCHEDULER_DAILY_SYNC_HOUR:SCHEDULER_DAILY_SYNC_MINUTE`,
  full breadth across every endpoint + Insights (last 30 days).
- `hourly_sync` — optional (`SCHEDULER_HOURLY_SYNC_ENABLED=true`), refreshes
  campaigns/adsets/ads + Insights (last 3 days).
- `retry_failed_jobs` — every `SCHEDULER_RETRY_INTERVAL_MINUTES`, replays
  the failed-jobs queue.
- Historical backfill is intentionally **not** scheduled automatically
  (`date_preset=maximum` across every level/endpoint is expensive) — trigger
  it once via `app.scheduler.jobs.run_historical_backfill()` or wire up a
  one-off `/sync/backfill` call in your own ops tooling.

## Rate-limit handling

`MetaAPIClient` (`app/services/meta/client.py`) handles both kinds of limit
Meta documents in its [Business Use Case rate limiting
reference](https://developers.facebook.com/docs/graph-api/overview/rate-limiting#buc-rate-limits):

- **Platform (app-level)** — legacy codes (`4`, `17`, `32`, `613`), reported
  via the `X-App-Usage` header.
- **Business Use Case (per ad account/page/business)** — codes `80000`
  (Ads Insights), `80001`–`80009`, `80014`, reported via
  `X-Business-Use-Case-Usage`. Meta applies BUC limits in preference to
  platform limits whenever both could apply, and `80000` is the one this
  service is most likely to hit, since Insights is by far its
  highest-volume endpoint.

Both proactive throttling (pausing before Meta actually blocks you, based
on usage-header percentages) and reactive backoff (after a 429 or a
rate-limit error code) prefer Meta's own
`estimated_time_to_regain_access` field (minutes until throttling ends,
reported alongside the BUC usage percentages) over a synthetic exponential
backoff — falling back to the exponential formula only when Meta hasn't
reported an estimate. `ads_api_access_tier` (`development_access` vs.
`standard_access`) is logged alongside rate-limit events for operator
visibility, since a persistently low ceiling is otherwise hard to diagnose
without an extra API call.

Meta's other documented mitigation — "switch to other ad accounts and come
back to this one later" — is effectively how `MultiAccountSyncCoordinator`
already behaves: each account gets its own client and its own usage
budget, so one account's throttling never blocks another's.

## Extending

**Add a new simple entity endpoint** (e.g. a Meta object type not yet
covered): write a `BaseMetaSyncService` subclass in `app/services/meta/`
setting `endpoint_name` + `object_type` (add the type to `MetaObjectType`
in `app/models/raw_dump.py`) and implementing `fetch_records()` (and
optionally `extract_parent_ids()`/`extract_meta_id()` for services keyed
unusually), then register it in `SIMPLE_SERVICE_REGISTRY` in
`app/services/meta/registry.py`. No new table or migration needed — it
writes into the existing `raw_dump_meta`. The `/sync/{endpoint}` route,
scheduler inclusion in `sync_all()`, and failed-job retry all pick it up
automatically.

**Add a new Insights metric/breakdown/attribution window**: add it to the
relevant list in `app/core/meta_registry.py`. No ingestion code changes.

## Known limitations / honest caveats

- **Offline events**: the Graph API does not expose bulk readback of
  individual previously-uploaded offline conversion events — it's an
  upload-oriented product. `OfflineEventSyncService` ingests the offline
  event *set* resource (name/config/usage stats) per
  `offline_event_set_id`, which is the closest thing Meta actually exposes
  for GET.
- **Incrementality / Conversion Lift**: not retrievable via `/insights` at
  all. `resolve_attribution_windows(["incrementality"])` raises a clear
  `ValueError` explaining you need Meta's separate Lift Study API rather
  than silently returning non-incremental numbers.
- **DDA (data-driven attribution)**: requested by *omitting*
  `action_attribution_windows` so Meta applies the ad account's configured
  attribution setting — pass `attribution_windows=["dda"]` alone to trigger
  this.
- Business-asset/catalog edges (`owned_pages`, `owned_product_catalogs`,
  etc.) require `META_BUSINESS_ID` and the token having the relevant
  Business Manager permissions; without it those services raise a clear
  `ConfigurationError` rather than silently returning nothing.
