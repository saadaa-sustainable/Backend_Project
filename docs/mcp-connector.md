# The SAADAA Analytics connector for Claude

A read-only MCP connector that lets Claude answer questions from the same
queries, definitions and caches the dashboard itself uses. It reads eleven
dashboard sections. It cannot change campaigns, budgets, data or schedules.

Written 2026-10-23 against the implementation in `app/services/assistant_mcp.py`,
`app/services/mcp_oauth.py` and `app/services/assistant_analytics.py`.

---

## 1. What it is, and what it is not

| Property | Value |
|---|---|
| Transport | Streamable HTTP MCP, stateless |
| Endpoint | `https://YOUR_HOST/mcp` |
| Tools | 11, every one read-only |
| Authentication | OAuth through the connector UI, **or** a bearer access key |
| Session length | **1 hour**, then the connector asks again |
| Rate limit | 30 calls per minute, 2 concurrent, **per key** |

**It cannot:** run SQL you write, read customer records, change anything, or
start/retry/stop a job. Every tool is declared `readOnlyHint`,
`destructiveHint: false`, `idempotentHint`.

**It is not a database.** It exposes the dashboard's *sections*, with their
definitions already applied. If a number is wrong in the dashboard, it is wrong
here too, identically — which is the point.

---

## 2. Before you connect: get an access key

You need a key that starts with `sda_`. Keys are issued per person, never
shared.

**Administrator**, once per person:

```sh
.venv/bin/python scripts/create_assistant_access_key.py --name 'Priya Sharma'
```

It prints two things:

* the **access key** — shown once, never recoverable. Send it to that person
  through a private channel.
* a **JSON hash entry** — merge it into `ASSISTANT_API_ACCESS_KEY_HASHES`.
  Merge, do not overwrite: replacing the value removes everyone else.

Only the SHA-256 hash is ever stored. Never paste a key into chat, a ticket, a
commit or a shared terminal log.

**Administrator**, once per deployment, in `.env`:

```ini
ASSISTANT_API_ENABLED=true
ASSISTANT_API_PUBLIC_ORIGIN=https://your-dashboard-host
ASSISTANT_API_MCP_URL=https://your-fastapi-host/mcp
ASSISTANT_API_SIGNING_KEY=<secrets.token_urlsafe(48)>
ASSISTANT_API_ACCESS_KEY_HASHES={"Priya Sharma":"<sha256>"}
```

Both URLs must be HTTPS (or `localhost` for development), carry no query or
fragment, and `ASSISTANT_API_MCP_URL` must end in exactly `/mcp`. If any of
that is wrong the OAuth routes are **not mounted at all** and a connector fails
discovery rather than failing confusingly later. Restart all backend workers
after changing these.

---

## 3. Connecting it to Claude

### The connector route (recommended)

1. In Claude, open **Settings → Connectors → Add custom connector**.
2. Paste the URL: `https://YOUR_HOST/mcp`
3. Claude discovers the OAuth metadata and registers itself automatically.
   You are not asked for a client ID or secret — there is none to copy.
4. Claude opens a page headed **"Connect SAADAA Analytics"**. It names the
   application asking, and states that access is read-only, dashboard-sections
   only, and lasts one hour.
5. Paste your `sda_…` access key into **Your assistant access key** and press
   **Allow access**.
6. Claude returns to the connector list with the connector enabled.

After an hour the connector asks again. That is deliberate: there is no
long-lived token sitting in a third party.

> **The page asks for your access key, not a password.** There is no account to
> log into. If you do not have a key, ask your administrator — do not reuse
> someone else's.

### The bearer-header route

For clients that let you set headers directly:

```text
URL:            https://YOUR_HOST/mcp
Authorization:  Bearer sda_YOUR_ACCESS_KEY
```

Credentials in the URL or query string do not authenticate. Neither do browser
cookies or Supabase keys.

### Checking it worked

Ask Claude:

> List the analytics tools you can use for SAADAA, and tell me the latest date
> each dataset has data for.

A healthy connector names eleven tools and returns dates from
`get_data_freshness`. If it names none, the connector is not attached. If it
errors, see §6.

---

## 4. How to prompt it well

This is the part that decides whether you get an answer or a guess.

### The rule

**A vague prompt gets a defaulted answer, not a wrong one — but you will not
know what was defaulted.** The assistant falls back to *the last 30 completed
days in Asia/Kolkata* whenever you do not say otherwise, and it will pick a
section for you. Both choices are invisible unless you state them.

So supply three things:

1. **Which section** — Ads Analyse, CPIS, First Click, Blended MER, …
2. **Which period**, or say "lifetime" explicitly
3. **Which basis** — Meta ROAS or Shopify ROAS, first click or last click,
   equal-split or value-weighted spend

### Paired examples

Each pair asks the same business question. The first gets a defended number;
the second gets *a* number.

---

**Spend and return**

> ✅ For 1–21 October 2026, give me Ads Analyse totals by campaign, sorted by
> spend, using **Shopify ROAS** not Meta ROAS. State the row limit and the
> full-population totals separately.

> ❌ How are my ads doing?

*Why it matters:* Meta ROAS is Meta's own attributed conversion value over
spend; Shopify ROAS is this project's Shopify-attributed revenue over spend.
They are different numbers and never interchangeable. The ranked rows are also
not the whole population — totals are returned separately.

---

**SKU economics**

> ✅ From the CPIS section, 30-day window, list SKUs whose **headroom** is
> negative. Show selling price, contribution margin, CPIS, ACoS and attributed
> units. Use the equal-split allocation.

> ❌ Which products are losing money?

*Why it matters:* `contribution_margin` in CPIS is a **flat model constant** —
selling price × 0.55 (35% COGS, 10% logistics). It is identical in percentage
terms for every SKU, so "which SKU has the worst margin" has no answer from it.
All the variation is in CPIS and ACoS. Ask for headroom.

---

**Attribution**

> ✅ From First Click, 1–21 October 2026, at **ad** grain, show the ten ads
> whose first-click revenue most exceeds their last-click revenue. Do not add
> the two columns together.

> ❌ Which ads drive the most revenue?

*Why it matters:* first-click and last-click revenue each carry the order's
**full** value. An order opened by ad X and closed by ad Y adds its whole value
to both. Reading a column down the page is valid; adding a row across
double-counts.

---

**Creative**

> ✅ From Asset Analysis, show assets whose status is inactive and that were
> **ever** winners, sorted by lifetime spend. Confirm these figures are lifetime,
> not for a chosen period.

> ❌ Show me my best creatives.

*Why it matters:* Asset Analysis is a lifetime rollup. "Was a winner once" and
"is winning now" are different questions and the tool distinguishes them with
`only=ever_won` and `only=won_fell`.

---

**Blended efficiency**

> ✅ Give me Blended MER by month for the last 6 completed months, and show
> **Platform MER** beside it. Explain which spend sources are included.

> ❌ What is our MER?

*Why it matters:* Blended MER divides **total store revenue** by total ad spend
and takes no platform's word for what it caused. Platform MER divides the
platforms' own claimed revenue by the same spend. Spend covers Meta, Google and
Kwikchat — and Kwikchat is a flat estimate, not measured.

---

**Landing pages**

> ✅ From Landing Page Analysis, 1–21 October 2026, show the top 20 pages by GA4
> sessions with add-to-cart and purchase rates, and say which session count is
> GA4's and which is Shopify's.

> ❌ Which pages convert best?

*Why it matters:* the section carries **two** session sources that do not agree,
and a conversion rate means different things depending which denominator was
used.

---

**Pipeline health**

> ✅ Use `get_refresh_status` for last night's cron run and `get_data_freshness`
> for the latest available date per dataset. Tell me explicitly which steps
> failed and whether a "running" record proves the job is still live.

> ❌ Is the data up to date?

*Why it matters:* a recorded `running` status is **not** proof a GitHub job is
alive, and a successful cron run is **not** proof the data is complete. The
tools return both facts; a vague question invites one confident sentence
covering neither.

### Three habits worth keeping

* **Ask it to state its assumptions.** "State the date range, filters and
  whether this is lifetime" costs nothing and makes a wrong answer visible.
* **Compare periods explicitly.** Ask for each period separately. Do not ask for
  "versus last month" and assume alignment.
* **Treat a null as unknown.** The tools return null where a figure is
  unavailable; it never means zero. If you see a dash, ask why.

---

## 5. What each tool answers

| Tool | Dashboard section | Ask it for |
|---|---|---|
| `get_dashboard_metrics` | Dashboard | KPI totals, Meta-driven session totals, session trend |
| `get_ad_performance` | Ads Analyse | spend, impressions, revenue by ad/campaign, with totals |
| `get_asset_performance` | Asset Analysis | lifetime creative rollup, winners and lapsed winners |
| `get_sku_economics` | CPIS | per-SKU spend, units, CPIS, ROAS, ACoS, headroom |
| `get_first_click_attribution` | First Click | both ends of the journey, by source / ad / ad set |
| `get_last_click_attribution` | Last Click UTM | individual orders with resolved ad, tier counts |
| `get_blended_mer` | Blended MER | revenue against Meta + Google + Kwikchat by period |
| `get_landing_page_performance` | Landing Page Analysis | per-page funnel, GA4 and Shopify sessions |
| `get_refresh_status` | — | cron runs, step outcomes, schedules |
| `get_data_freshness` | — | latest available date per dataset |
| `get_table_info` | — | table and column metadata only |

`get_table_info` returns **metadata only** — never rows, personal data, exact
counts or arbitrary SQL results.

---

## 6. Limits, failures and revocation

### Limits

* **30 calls per minute, 2 concurrent**, per key. A complex question may make
  several calls; two people on one key will throttle each other.
* **Request body** is capped at 64,000 bytes.
* **A result over 1,000,000 characters is refused** with a message asking for a
  smaller date range or limit. Narrow the window rather than retrying.

### What the errors mean

| Message | Cause |
|---|---|
| "API chat has not been enabled or its URLs are not configured" | `ASSISTANT_API_ENABLED` is false, or a URL is malformed |
| "API and MCP access has not been configured by the administrator" | `ACCESS_KEY_HASHES` or `SIGNING_KEY` missing or invalid |
| "Invalid MCP host" / "Invalid MCP origin" | the request did not arrive at the configured host |
| "Result is too large" | narrow the date range or lower the limit |
| "Could not read analytics. Stopped without retrying." | the read failed; it deliberately does not retry |

### Revoking access

Remove that person's entry from `ASSISTANT_API_ACCESS_KEY_HASHES` and restart
the backend workers. This kills the connector **and** every other use of that
key immediately. Keys are per person precisely so that one revocation does not
disturb anyone else.

### Safety properties worth knowing

* Tool results are treated as **untrusted data**, never instructions. An ad name
  containing "ignore previous instructions" is text, not a command.
* Open client registration is allowed, but the **authorization page is the
  gate** — registering a client gets you nothing without a valid access key.
* The redirect target is re-checked against the *registered* client, not the
  posted form, so a crafted authorization URL cannot collect a code minted from
  someone else's key.

---

## 7. See also

* `docs/ai-assistant.md` — the wider assistant: dashboard chat, the ChatGPT
  account option, deployment and verification.
* `docs/cpis-attribution.md` — what the CPIS numbers mean and their open issues.
