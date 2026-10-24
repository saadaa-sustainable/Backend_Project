# Dashboard AI assistant

The dashboard offers two independent connections: **ChatGPT account** (the
existing hosted OAuth flow) and **API chat** (team-billed OpenAI or Anthropic API chat).
API chat is selected by default and opens directly without user sign-in or an access key.
The separate ChatGPT account flow still requires its own authentication.
The backend also exposes a standard, authenticated **Streamable HTTP MCP server
at `/mcp`**. All three use the same bounded, read-only analytics tools and caches.

## The tool surface

One tool per dashboard section. Each wraps the SAME analytics function the section
itself calls, so a client gets the dashboard's numbers, definitions and caches rather
than raw SQL over Supabase -- and the caveats travel with them, in the tool
description and in every result's `source.basis`.

| tool | section | what it answers |
| --- | --- | --- |
| `get_dashboard_metrics` | Dashboard | KPI totals, Meta-driven sessions, session trends |
| `get_ad_performance` | Ads Analyse | per-ad spend, ROAS, orders, by delivery date |
| `get_asset_performance` | Asset Analysis | lifetime creative rollup, winner history |
| `get_sku_economics` | CPIS | per-SKU allocated spend, CPIS, ACoS, headroom |
| `get_first_click_attribution` | First Click | both ends of the GA4 journey, ROAS pair |
| `get_last_click_attribution` | Last Click UTM | orders resolved to ad / ad set / campaign |
| `get_blended_mer` | Blended MER | revenue over Meta + Google + Kwikchat spend |
| `get_landing_page_performance` | Landing Page Analysis | GA4 + Shopify sessions, funnel rates, last-click orders |
| `get_refresh_status` | -- | cron runs, step outcomes, schedules |
| `get_data_freshness` | -- | latest available date per dataset |
| `get_table_info` | -- | public schema metadata |

Three things the descriptions carry that a schema cannot, because getting them
wrong produces confident nonsense rather than an error:

* **CPIS `contribution_margin` is a flat model constant** -- `selling_price x 0.55`
  -- identical in percentage terms for every SKU. All per-SKU variation comes from
  CPIS and ACoS.
* **CPIS preset windows and custom ranges are different measurements**, not just
  different bounds. They differ by about 32% over the same 30 days, so every result
  states which basis produced it.
* **First Click's two revenue columns each carry the order's FULL value** and
  overlap. A column may be totalled down the page; a row must never be added across.
* **Landing Page Analysis carries two session counts that disagree.** `ga4_sessions`
  and `shopify_sessions` count differently; neither corrects the other and they must
  not be added. Its `source` filter narrows ONLY the last-click order and revenue
  columns, so a filtered row mixes one channel's orders with every channel's sessions.

Adding a section means one input model, one registry entry and one dispatch branch
in `app/services/assistant_analytics.py`. The MCP server exposes whatever the
registry declares, and the tests assert exactly that -- no list of names to keep in
sync in three places.
Changing connections preserves each conversation while the page stays open.
There is no automatic switch between billing accounts.

Within API chat, the **Model** selector groups GPT and Claude separately.
Changing the model preserves the conversation and sends subsequent questions,
conversation history and relevant tool results to the selected provider.
The selector is disabled while an answer is running. Claude models remain visible
but disabled until the backend's Anthropic key is configured. Key presence means
configured, not that billing or access to every listed model has been verified.
Use **Refresh models** after a local `.env` key or model-list change. This reloads
the catalog without clearing the conversation or contacting either provider.
The backend invalidates its settings cache when `.env` changes, including key
rotation and removal. Hosted environment-variable changes still require a restart.

API/MCP access works independently of ChatGPT OAuth provisioning. It is disabled
until an administrator configures the credentials below. No analytics schema
changes or database migrations are required.

## API chat and MCP setup

### Direct API chat (no user authentication)

Create a project
key in the [OpenAI API dashboard](https://platform.openai.com/api-keys) and add it
directly to the backend's private environment or project-root `.env`:

```dotenv
ASSISTANT_API_OPENAI_KEY=YOUR_PRIVATE_OPENAI_PROJECT_KEY
ASSISTANT_API_MODEL=YOUR_MODEL_ID
ASSISTANT_API_ENABLED=true
ASSISTANT_API_REQUIRE_USER_AUTH=false
```

To use your Anthropic API credits, add a key from the
[Claude Console](https://platform.claude.com/settings/keys) to the same private backend environment:

```dotenv
ASSISTANT_API_ANTHROPIC_KEY=YOUR_PRIVATE_ANTHROPIC_KEY
```

For a personal or service-account key that is not scoped to one workspace, also set:

```dotenv
ASSISTANT_API_ANTHROPIC_WORKSPACE_ID=YOUR_WORKSPACE_ID
```

Copy the `wrkspc_…` ID from [Claude Console → Workspaces](https://platform.claude.com/settings/workspaces).
Both chat requests and the provider verification script send it in the
`anthropic-workspace-id` header. Anthropic requires this header for unscoped keys;
a key scoped to a workspace can omit it. See [Anthropic authentication](https://platform.claude.com/docs/en/manage-claude/authentication).
An HTTP 400 asking for a workspace means this setting is missing; it does not
establish that the API key or credits are invalid. Unknown provider errors are
reported with their HTTP status, without exposing response bodies or credentials.

After changing the local `.env`, reload the assistant or click **Refresh models**.
Restart FastAPI after changing hosted environment variables.
No database migration or user-auth change is needed. With this key configured,
the selector offers **Claude Sonnet 5.5**, **Claude Haiku 5.5**, and **Claude Opus
5.5**, using the IDs in the [official Claude model catalog](https://platform.claude.com/docs/en/models/overview).
The existing `ASSISTANT_API_MODEL` remains the default GPT choice when its key is
configured. An Anthropic-only configuration is also supported; the first enabled
Claude model becomes the default.

Optional administrator allowlists use JSON arrays:

```dotenv
ASSISTANT_API_ANTHROPIC_MODELS='["claude-sonnet-5-5","claude-haiku-5-5","claude-opus-5-5"]'
ASSISTANT_API_OPENAI_MODELS='["gpt-6-luna","gpt-6.1-sol","gpt-6-astra"]'
```

The default GPT choices are Luna, Sol, and Astra from the
[official OpenAI catalog](https://developers.openai.com/api/docs/models).
Override `ASSISTANT_API_OPENAI_MODELS` with Responses/tool-compatible GPT IDs
available to your OpenAI project, or `[]` to offer only `ASSISTANT_API_MODEL`.
The existing `ASSISTANT_API_MODEL` is always included and stays the default.
Clients cannot submit arbitrary model IDs outside these allowlists.
Claude calls go directly to Anthropic's Messages API using its own key; GPT calls
continue to use OpenAI. Both use the same read-only MCP tool catalog, source links,
timeouts, request limits and authorization checks. Provider errors and data-tool
errors stop the turn without retrying or switching provider.

Keep these values on the FastAPI backend, outside the frontend and chat.
API keys are loaded
server-side as described in [OpenAI's authentication documentation](https://developers.openai.com/api/reference/overview).

After adding the key, list available models if needed, then check the selected one:

```sh
.venv/bin/python scripts/check_assistant_provider.py --list-models
.venv/bin/python scripts/check_assistant_provider.py
.venv/bin/python scripts/check_assistant_provider.py --provider anthropic
# Check another configured Claude model without generating an answer:
.venv/bin/python scripts/check_assistant_provider.py --provider anthropic --model claude-haiku-5-5
```

This check makes one model-read request, without inference, database access or
user-auth setup. It prints no keys or provider error bodies and stops on the first
failure. A successful model-read check does not verify billing or Responses tool
support; those require a small inference test. User authentication is not required
for direct API chat. Anyone who can reach these chat routes can ask about this
dataset using the team API account; there are no individual user permissions in this mode.

### Deployment configuration

Set these on the **FastAPI backend**, as private environment variables:

| Variable | Value / requirement |
|---|---|
| `ASSISTANT_API_ENABLED` | `true` after the remaining values are configured |
| `ASSISTANT_API_PUBLIC_ORIGIN` | `https://backend-project-admin.onrender.com` (no trailing slash) |
| `ASSISTANT_API_MCP_URL` | `https://backend-project-mlk9.onrender.com/mcp`, or your actual **FastAPI** origin plus `/mcp` |
| `ASSISTANT_API_REQUIRE_USER_AUTH` | `false` for direct dashboard chat (default); `true` restores the access-key form |
| `ASSISTANT_API_SIGNING_KEY` | Optional for direct chat; required for external MCP/access-key mode, at least 32 random characters |
| `ASSISTANT_API_ACCESS_KEY_HASHES` | Optional for direct chat; required for external MCP/access-key mode, JSON label-to-hash mapping |
| `ASSISTANT_API_OPENAI_KEY` | Team OpenAI project API key; enables GPT choices |
| `ASSISTANT_API_MODEL` | Default Responses API model ID available to that OpenAI project |
| `ASSISTANT_API_OPENAI_MODELS` | Optional JSON array of additional approved GPT IDs |
| `ASSISTANT_API_ANTHROPIC_KEY` | Team Anthropic API key; enables Claude choices and uses that account's credits |
| `ASSISTANT_API_ANTHROPIC_WORKSPACE_ID` | `wrkspc_…` ID; required for an Anthropic key that is not scoped to a workspace |
| `ASSISTANT_API_ANTHROPIC_MODELS` | Optional JSON array overriding the Claude model list above |

Set `ASSISTANT_API_PUBLIC_ORIGIN` to the **same value on the Next.js frontend
server**. Set its `ASSISTANT_BACKEND_URL` to your FastAPI origin. These are
server-only values; never use `NEXT_PUBLIC_*` for credentials. API/MCP-only mode
does not need a persistent auth disk or any `CHATGPT_*` values.

Deploy both services and open `/user/assistant`. API chat is immediately usable
when the provider key/model are configured; no connect/disconnect step is needed.
The provider key stays on FastAPI. A random HttpOnly visitor cookie groups request
limits only; it is not authentication. The browser preserves each provider
conversation when switching tabs.

### Optional access keys for external MCP clients

External `/mcp` access remains bearer-protected even when dashboard chat is direct.
It is optional and does not need to be configured for dashboard chat.

Generate the signing secret privately using `secrets.token_urlsafe(48)`. Issue a
separate access key to each approved person using:

```sh
.venv/bin/python scripts/create_assistant_access_key.py --name 'Team member'
```

The command prints the private key once and a JSON hash entry. Give the key to
that person through a private channel; merge the hash entry into
`ASSISTANT_API_ACCESS_KEY_HASHES`. Do not overwrite other users when adding an
entry. Do not paste keys into chat, commit them, or retain terminal output in
shared logs. A user key and the OpenAI provider key are different credentials.

To restore dashboard access-key authentication later, set
`ASSISTANT_API_REQUIRE_USER_AUTH=true` and restart all backend workers. The dashboard
then shows the access-key form and external MCP details.

### External clients

Configure an MCP client supporting Streamable HTTP and custom bearer headers:

```text
URL: https://YOUR_FASTAPI_HOST/mcp
Authorization: Bearer YOUR_ASSISTANT_ACCESS_KEY
```

Credentials in URL/query parameters, browser cookies, and Supabase service-role
keys do not authenticate MCP. This endpoint uses provisioned bearer keys; it
does not implement MCP OAuth discovery. OAuth-only connector UIs need a separate
OAuth resource-server integration. The existing **ChatGPT account** option in
the dashboard is unaffected.

To connect from the OpenAI Responses API directly, use a remote MCP tool as
described in [OpenAI's MCP guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp):

```python
import os
import httpx

response = httpx.post(
    'https://api.openai.com/v1/responses',
    headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']},
    json={
        'model': os.environ['OPENAI_MODEL'],
        'input': 'Show spend and Shopify ROAS for the last 7 completed days.',
        'store': False,
        'tools': [{
            'type': 'mcp',
            'server_label': 'saadaa_analytics',
            'server_url': os.environ['SAADAA_MCP_URL'],
            'authorization': os.environ['SAADAA_ASSISTANT_ACCESS_KEY'],
            'allowed_tools': ['get_dashboard_metrics', 'get_ad_performance', 'get_asset_performance',
                              'get_sku_economics', 'get_first_click_attribution',
                              'get_last_click_attribution', 'get_blended_mer',
                              'get_landing_page_performance',
                              'get_refresh_status', 'get_data_freshness', 'get_table_info'],
            'require_approval': 'never',  # Explicitly approved read-only tools only.
        }],
    },
    timeout=260,
)
response.raise_for_status()
```

The remote URL must be publicly reachable over HTTPS for this direct provider
connection. The provider receives the delegated MCP credential and returned data.
Dashboard API chat instead uses an SDK MCP client over local ASGI HTTP: it performs
the real initialize/list/call protocol without a round trip back to Render. Its
principal is passed in private ASGI request context, which HTTP headers cannot
forge. Only questions, tool schemas and returned analytics are sent to OpenAI.

External clients can also POST `/admin/assistant/api/chat` with their bearer key
and the `messages`/`mode: "analytics"` body shown below, and GET
`/admin/assistant/api/models`. This uses the configured **team API billing**.
Clients cannot select unapproved models or raw-SQL mode.

### API/MCP limits and revocation

- Direct chat visitors and approved external MCP keys read the same SAADAA dataset.
  Tools cover dashboard metrics, ads, assets, SKU economics (CPIS), first-click and
  last-click attribution, blended MER, operational status and public schema metadata.
  Raw table records, logs, customer records and secrets are not tools.
- No arbitrary SQL, schema-management, ingestion, or write tools are exposed.
  Analytics transactions receive `READ ONLY` and the existing query timeout.
- Remove a hash and restart/reload **all backend workers** to revoke the user
  key, browser sessions and derived MCP credentials. Rotate the signing secret
  to invalidate all signed sessions. Disconnect clears this browser's cookie and
  conversation; it does not revoke the user's external MCP key or an already
  copied session. Signed sessions expire after eight hours.
- Limits per worker: 10 chats/minute/visitor or key, 30 chats/minute overall,
  30 tool calls/minute/visitor or key and 120 tool calls/minute overall. One chat
  and one tool call at a time per visitor/key; two concurrent chats and two
  concurrent tools overall. Rotating visitor IDs cannot bypass the overall cap.
  These are process-local, not distributed quotas.
  Use a shared limiter before scaling out if a global limit is required.
- API bodies are capped at 256 KB and MCP bodies at 64 KB; tool responses at
  1 MB. API/ChatGPT chat is capped at 240 seconds, ten tools and eight model turns, with
  4,000 output tokens per model response. External MCP clients control their
  own overall model loop; the server still enforces per-call limits.
- Model and tool connection failures stop immediately with no automatic retry
  or provider fallback. A configured model must support Responses function tools.
- MCP SDK is pinned to the supported 1.x maintenance line to retain the existing
  FastAPI/httpx stack; Pydantic is raised to 2.11.10 for SDK compatibility. MCP is
  stateless; unsupported GET event streams and DELETE sessions return 405.

## Hosted ChatGPT setup

OpenAI's [website flow](https://developers.openai.com/siwc/website) supports
Authorization Code + PKCE + OpenID Connect for provisioned partner clients.
[Request hosted-app access](https://developers.openai.com/siwc/request-client-id)
and explicitly request **ChatGPT plan usage**, as well as identity sign-in.
The public [plan-usage documentation](https://developers.openai.com/siwc/token-sharing-open-source)
describes the eligible open-source/local flow; it does not automatically grant
this Render-hosted application access. Confirm your partner client's approved
scopes, token authentication method, resource and inference contract with OpenAI
before enabling plan usage. Do not use `dynamic_agent_client` or another app's
client ID for this hosted dashboard.

Register these exact callbacks with OpenAI for the environments you intend to use:

- Production: `https://backend-project-admin.onrender.com/api/assistant/chatgpt/callback`
- Local development: `http://localhost:3000/api/assistant/chatgpt/callback`

Set these **backend secrets/environment variables** in Render. Do not put them
in `NEXT_PUBLIC_*`, paste secrets into chat, or commit a credential file:

| Variable | Value / requirement |
|---|---|
| `CHATGPT_OAUTH_ENABLED` | `true` only after provisioning and setup below |
| `CHATGPT_CLIENT_ID` | OpenAI-issued `oaiapp_...` for this application |
| `CHATGPT_TOKEN_AUTH_METHOD` | Registered method: `none` or `client_secret_basic` |
| `CHATGPT_CLIENT_SECRET` | Required only for a confidential client using Basic auth |
| `CHATGPT_PUBLIC_ORIGIN` | `https://backend-project-admin.onrender.com`, no trailing slash |
| `CHATGPT_ALLOWED_EMAILS` | Comma-separated exact **verified** team email addresses; empty denies all |
| `CHATGPT_AUTH_DB_PATH` | Absolute path on a **private persistent disk**, e.g. `/var/data/assistant-auth/sessions.auth.sqlite` |
| `CHATGPT_ENCRYPTION_KEY` | Fernet encryption key, stored separately from that disk |
| `CHATGPT_PLAN_USAGE_ENABLED` | Initially `false`; set `true` only when OpenAI approves the hosted inference contract |

Generate the encryption key privately with Python's
`cryptography.fernet.Fernet.generate_key()`. Never copy it into logs or source
control. Changing this key invalidates existing encrypted records: rotate by
disabling the connection, revoking outstanding grants, clearing the auth store,
installing the new key, and requiring new sign-ins. Do not silently replace the
key while retaining an unreadable store.

Set these on the **Next.js frontend server**, without `NEXT_PUBLIC_`:

- `CHATGPT_PUBLIC_ORIGIN`: the same public origin as the backend.
- `ASSISTANT_BACKEND_URL`: `https://backend-project-mlk9.onrender.com` (or the
  actual backend origin for the deployment).

Locally, both sides default to frontend origin `http://localhost:3000`; the
frontend proxy defaults to backend `http://localhost:8002`. Backend credentials,
approved emails, a private absolute auth-store path and encryption key still
need explicit setup. The feature never starts a connection while unconfigured.

### Session and permission behavior

- The browser uses same-origin Next.js routes, avoiding third-party cookie
  dependence between the two Render services. It only holds opaque HttpOnly,
  SameSite=Lax session/transaction cookies; production cookies are Secure.
- State, nonce and PKCE verifier live server-side. Transactions expire after
  ten minutes and are consumed atomically once. The ID token signature,
  issuer, audience, expiry, issued-at, nonce and authorized party are verified.
- Exact verified email approval is a **single-dataset team permission**: every
  approved team member can read the current SAADAA analytics dataset. This is
  not brand/tenant-specific row authorization. Identity keys retain issuer,
  client ID and subject; there is no automatic linking by email.
- Approval is rechecked on requests and before each tool invocation. Removing
  an address in configuration takes effect after configuration reload/restart.
- Identity-only login succeeds without an access or refresh token, but cannot
  run inference. The plan path additionally requires the actual returned
  `chatgpt.tokens.use.direct` grant. A requested scope is never treated as granted.
- OAuth records are encrypted on disk. SQLite and atomic leases support
  multiple workers **on a single backend host sharing the same disk**. Before
  adding backend replicas, replace this store with shared transactional storage.
  An ephemeral Render filesystem loses sessions on restart and is unsuitable.
- Sessions expire after eight hours. Rotating refreshes are serialized; a failed
  refresh invalidates the connection rather than reusing an ambiguous token.
  Provider errors stop immediately without retries or alternate billing.
- Disconnect attempts remote refresh-token revocation once, deletes local
  tokens, clears the browser session and conversation, and reports if remote
  revocation was not confirmed. Users can also remove the app in ChatGPT Settings.
- The account model list is fetched with that account's token and cached in its
  encrypted session for five minutes. Inference uses the public Responses API
  with `store: false`, `stream: true`; an answer is accepted only after
  `response.completed`. This setting is not a claim of zero provider retention.
- Returned business data is processed by OpenAI to answer the user's question.
  No Supabase credentials, raw SQL tools, or write tools are exposed to ChatGPT.
- Analytics database transactions are read-only, with a 120-second database
  statement timeout, applied lazily on connection acquisition so cache hits
  remain connection-free. No warehouse tables, roles or policies are changed.

**Scope:** enabling OAuth **or API/MCP access** disables the legacy shared-provider assistant routes,
including admin chat/context routes, so the bounded read-only tools remain the chat interface.
It does **not** add authentication to every existing dashboard/admin API. Those
existing routes require a separate application-wide access-control rollout.
All assistant users currently have the same dataset permission, so reusing the
existing dataset cache is appropriate; introduce authorization-aware cache keys
before adding different dataset permissions.

Render and any request-log middleware should redact callback query parameters
(`code`, `state`) and all cookies/authorization headers. Application errors and
UI redirects never echo upstream token/error bodies. Review platform access-log
configuration as part of deployment; it cannot be verified in offline tests.

## User assistant

Open `/user/assistant` and ask a question in **API chat**. No user authentication
is required in direct mode. To use the separate ChatGPT connection, select
**ChatGPT account** and complete its identity/plan authorization.
Both connections and external MCP expose these six tools:

| Tool | Data and behavior |
|---|---|
| `get_dashboard_metrics` | Existing Dashboard KPI, session-summary or daily session-trend handler |
| `get_ad_performance` | Existing Ads Analyse handler, using **delivery dates** for period performance, including full filtered totals |
| `get_asset_performance` | Existing Asset Analysis **lifetime** handler, including active/inactive and historical-winner filters |
| `get_refresh_status` | Recent `backend_project` run records, safe step outcomes, checked-out workflow schedules and the separate process scheduler |
| `get_data_freshness` | Latest dates for Meta ads, Shopify orders, SKU daily, Shopify sessions, landing-page sessions and Shopify daily sales |
| `get_table_info` | Paginated public table/view metadata, estimated row counts and column types; no raw records |

Example questions:

- “What were spend and Shopify revenue from 1 to 15 October 2026?”
- “Show the top 10 ads by Shopify ROAS during September 2026.”
- “Which inactive assets were winners in the past? Show lifetime spend and Meta ROAS.”
- “Show daily cost per session and conversion rate for the last 7 days.”
- “Did the latest daily refresh succeed? Which steps failed?”
- “Is our Meta and Shopify data up to date?”
- “List Shopify tables and show the columns of shopify_orders.”

The prompt requires exact periods and metric bases. If no dates are supplied,
the tools use the last 30 completed days in Asia/Kolkata. Explicit ranges must
include both endpoints, cannot be in the future, and are limited to 366 days.
Lifetime is explicit. Asset Analysis exposes lifetime values only; it does not
misrepresent ad creation-date filtering as performance during those dates.

The server returns source metadata independently of the model's written answer:
section link, filters, period basis, and retrieval time. The chat displays this
under **Sources and filters**. Links open the relevant section; the listed
filters must be applied there to reproduce the result. Retrieval time is not
an ingestion timestamp. Coverage fields and missing values from the original
handlers remain intact; unknown values are not converted to zero.

## Performance and failures

The tools call existing Python analytics handlers, so they retain those handlers'
calculation logic and process-local response caches. Cache sharing requires the
same filter arguments. No extra queries are introduced to calculate the metrics.
Creating a tool's database session does not acquire a connection on a cache hit.

The operational tools use separate 60-second caches. Freshness MAX queries use
leading B-tree indexes or tables estimated at no more than 50,000 rows; larger
unindexed/unanalyzed tables are reported unknown without a scan. Latest event
dates do not prove full ingestion or absence of historical gaps. Lag is measured
against yesterday in IST, not a guaranteed SLA. Cron records are persisted
observations, not live GitHub queue/process checks. Interrupted jobs can leave
a `running` record. Raw errors/logs and schema defaults are omitted.

- At most 50 returned ads/assets per tool call, with totals and a truncation flag.
- SQL statements have 120 seconds; each analytics tool has 130 seconds including connection/cache wait.
- The internal MCP client waits 140 seconds per call. API/ChatGPT turns have 240 seconds,
  with 250 seconds at the Next.js proxy and 260 seconds in the browser. These replace
  the old 9-second SQL, 10-second tool and 12-second MCP cutoffs.
- ChatGPT session leases cover the full turn, preventing concurrent token refreshes during slow reads.
- At most ten tool calls per assistant turn; the disabled legacy assistant retains its separate limits.
- Provider/database failures stop the turn. Anthropic SDK automatic retries are disabled.
- A failed question returns to the input box for editing or manual resubmission.
- Conversations have message/character limits and a **New conversation** control.
- Chat requests no longer invalidate the browser's retained analytics cache.

These are cancellation limits, not promised response times. A cold database
query can still exceed the budget and return an explicit error. The model can
also misunderstand a question: source details remain visible for verification.

## Existing admin workflow

When both `CHATGPT_OAUTH_ENABLED=false` and `ASSISTANT_API_ENABLED=false`, `/assistant`
retains the original Cloudflare / Claude schema/document workflow using
`mode: "database"`. When either assistant mode is enabled, legacy assistant endpoints
return 403 and cannot be used as a fallback. The ChatGPT endpoint rejects database
mode; the user analytics toolset has no generated-SQL or context-document tool.

Example request to the authenticated `/api/assistant/chatgpt/chat` proxy:

```json
{
  "mode": "analytics",
  "messages": [{"role": "user", "content": "Which inactive assets were winners in the past?"}]
}
```

Chat returns `message` plus `sources`. Credentials remain server-side. No live
provider call or database access is required to run the automated tests below.

## Verification

Local verification on 17 October 2026:

- 631 backend tests passed (9 skipped), 101 frontend tests passed; TypeScript and targeted lint checks passed.
- Browser fixtures verified direct chat without authentication requests, retained conversations,
  explicit failure handling, disabled configuration, and returning to the ChatGPT tab after OAuth.
- Live read-only Supabase checks: table list 0.22s, columns 0.41s, six-dataset freshness 0.41s,
  and recent cron/scheduler status 0.55s. These are individual observations, not latency guarantees.
- One live dashboard-proxy → API → MCP → Supabase → OpenAI answer completed in 9.19s,
  correctly reporting Meta's latest date with a source and completeness caveat.

```sh
.venv/bin/python -m pytest tests/test_assistant_mcp.py tests/test_assistant_operations.py tests/test_chatgpt_connection.py tests/test_assistant_analytics.py tests/test_analytics_cache.py -q
cd admin
npm test
./node_modules/.bin/tsc --noEmit
```

The tests exercise signed JWT verification, callback replay/CSRF defenses,
permission checks, encrypted storage, cross-worker leases, rotating tokens,
disconnect failures, the actual Responses loop and tool dispatch against mocked
provider/database I/O, filters, cache reuse, missingness and request budgets. The
MCP tests use the real SDK client and server, including initialize, tool discovery,
tool execution, read-only enforcement, authentication, invalid origins/hosts,
revocation and an API-billed Responses tool loop with fixture data. Browser
checks use explicitly labelled fixture responses for desktop/mobile rendering,
source details and error recovery. Production model quality and live query
latency still need to be evaluated against the chosen provider and deployment.
The existing fixed-width application sidebar leaves very little chat width on
phones; a responsive navigation change remains outside this first implementation.

## Longer analytics queries

The assistant no longer stops queries after 10 seconds. Its transaction-local SQL
limit is 120 seconds, tool budget 130 seconds, and full API/ChatGPT turn budget
240 seconds. MCP, Next.js and browser deadlines allow each inner layer to finish
or return its error. This changes assistant request budgets only; dashboard metric
SQL, database-wide settings, read-only access and no-retry behavior are preserved.

Verification for this change: 121 focused backend tests, 102 frontend tests,
TypeScript and targeted lint checks passed. A real MCP/Responses fixture with a
13-second data read verifies that both former 10-second and 12-second cutoffs are
removed. A session test verifies that ChatGPT connections stay leased during
longer reads. The API prompt now supplies today's IST date for relative-date
questions such as “last 7 days.” A live request for “Give me the analytics for
spend for the last 7 days” completed successfully through the dashboard proxy
in 96.76 seconds, using delivery dates 10–16 October 2026. This validates the
longer timeout path, not a query-speed improvement.

## Before activation

Changes are implemented locally; production configuration and external
provider-to-MCP reachability require verification after deployment. Test direct
chat and compare a small answer with the dashboard. If external MCP is enabled,
also test a valid and revoked key from the intended client. Keep provider spending
limits and request-header/body redaction configured on the hosting platform.

No hosted OAuth credentials, OpenAI approval or live ChatGPT plan grant have been
verified in this workspace. The supplied hosted plan flow is gated and must be
checked against the provisioned partner contract before production use. Once
configured, verify a real approved-user login, denied-user login, identity-only
consent, plan consent, a small analytics question, token renewal and disconnect
in staging. Confirm query timings and answers against the dashboard. Write/action
capabilities remain outside this implementation.
