# Meta webhooks — what Meta will and will not tell you

## The headline, because it shapes everything else

**Meta does not send a webhook when an ad's status changes or when an ad
is edited.** There is no such subscription. The `ad_account` topic has
exactly six fields, and none of them is `effective_status`, `status`,
`ad`, `adset` or `campaign`:

| Field | Fires when | `value` carries |
|---|---|---|
| `in_process_ad_objects` | an ad object **leaves** IN_PROCESS review | `id`, `level`, `status_name` |
| `with_issues_ad_objects` | an ad object is **set to** WITH_ISSUES | `id`, `level`, `error_code`, `error_summary`, `error_message` |
| `creative_fatigue` | Meta judges a creative fatigued | `ad_account_id`, `adgroup_id`, `creative_fatigue_level`, `creative_fatigue_message` |
| `ad_recommendations` | Meta has a recommendation | `ad_account_id`, `ad_object_ids`, `recommendation_type`, … |
| `ads_async_creation_request` | an async ad-creation job finishes | `status`, `result`, `result_id`, `error_code`, `error_message` |
| `product_set_issue` | a catalog product set has a problem | `ad_account_id`, `product_set_id`, `type`, `description`, `recommended_action` |

Source: <https://developers.facebook.com/docs/graph-api/webhooks/reference/ad-account>

So a webhook alone cannot do what "update the dashboard the moment an ad
is paused" needs. Subscribing to `effective_status` does not fail loudly
— it is simply not a field on this topic, and you get silence.

`level` is one of `CAMPAIGN`, `AD_SET`, `AD`, `CREATIVE`. We hold no
Silver creative table, so `CREATIVE` events are stored and skipped.
`adgroup_id` on `creative_fatigue` is Meta's older name for an **ad set**
id, not an ad id — reading it as an ad id silently refreshes the wrong
object.

## So there are two mechanisms, not one

```
                     ┌─ webhook  ──→ review outcomes, issue flags, fatigue
   what changed? ────┤                (seconds, event-driven)
                     └─ delta poll ─→ status flips, edits, budgets, names
                                      (minutes, every 5 min by default)
```

Both land in the same place, through the same code
(`app/services/meta/live_refresh.py`):

```
fetch the changed objects from the Graph API
        ↓
append a raw_dump_meta row with a fresh extracted_at     ← Bronze
        ↓
re-flatten just those ids into meta_campaigns/adsets/ads ← Silver
```

### Bronze first is not a style preference

`meta_ads` is not a table anyone writes to. It is rebuilt by
`DISTINCT ON (meta_id) ORDER BY extracted_at DESC` over `raw_dump_meta`.
An `UPDATE meta_ads SET ad_status = …` would appear on the dashboard and
then be **silently reverted** by the next full rebuild — the dashboard
would be right, then wrong, with nothing in between to explain it.

Appending a Bronze row with a fresh `extracted_at` makes the change the
newest snapshot, so every later rebuild agrees with what we just showed.

`refresh_entities_for_ids` splices a `meta_id = ANY(:ids)` predicate into
the *same* INSERT templates the full rebuild uses, so the two cannot
drift. A scoped lookup costs **19 shared blocks** against the
`ix_raw_dump_meta_object_type_meta_id` index; the full rebuild scans 1.7M
Bronze rows.

### The delta poll

`run_meta_delta_sync` asks Meta, per level, for everything whose
`updated_time` is newer than our watermark:

```json
[{"field": "ad.updated_time", "operator": "GREATER_THAN", "value": 1761500000}]
```

The field name tracks the level — `campaign.updated_time`,
`adset.updated_time`, `ad.updated_time`. Graph rejects `ad.updated_time`
on the `/campaigns` edge.

Meta does the filtering, so a quiet interval costs three empty pages per
account rather than a walk of every ad.

The watermark is `max(extracted_at)` from Bronze for that account, minus
`SCHEDULER_META_DELTA_OVERLAP_SECONDS` (default 900). It is **derived,
not stored**, which makes it self-healing: down for a day means the next
run asks for a day of changes, and a nightly full sync moves it forward
for free. `SCHEDULER_META_DELTA_MAX_LOOKBACK_DAYS` (default 7) caps a
cold start so the first run cannot ask for every edit in the account's
history. The overlap re-reads a few minutes we have already seen —
Bronze is append-only, so a re-read is harmless, while missing an edit
that landed mid-run is not.

## The receiver

`GET /webhooks/meta` is the one-time handshake. It checks
`hub.verify_token` against `META_WEBHOOK_VERIFY_TOKEN` and returns
`hub.challenge` **as the bare body** — not JSON, not wrapped. Wrap it and
the callback URL never registers.

`POST /webhooks/meta` verifies `X-Hub-Signature-256` and then stores the
body verbatim in `webhook_events` before anything interprets it, exactly
as the EasyEcom receiver does. Meta retries a non-200 for a while and
then disables the subscription outright, so interpretation happens in a
background task *after* the response: a payload shape we do not
recognise must not be able to cost us the subscription.

### The signature trap

The HMAC is over the **raw request bytes**, never over a re-serialised
parse:

```python
hmac.new(app_secret.encode(), await request.body(), hashlib.sha256).hexdigest()
```

`json.dumps(json.loads(raw))` is valid JSON with the same meaning and
different bytes — different key order, different whitespace. Hash that
and every genuine event is rejected with a 401 that looks, from the
outside, exactly like a wrong app secret. `tests/test_meta_webhook.py`
pins this with a body whose JSON deliberately does not round-trip.

Neither the signature nor EasyEcom's `Access-Token` is among the headers
kept on the stored row (`_KEEP_HEADERS`): storing a credential next to
the data it protects undoes the point of having one.

### An unconfigured account is skipped, not guessed

Every Bronze row is stamped with the account it came from. Defaulting an
unrecognised `ad_account_id` to the first configured account would file
one account's ads under another account's name in Silver — harder to
notice and harder to undo than an event left unprocessed. The event's
`process_error` records it instead.

## The rate limit is CPU, not calls

Measured live on 2026-10-26, from `X-Business-Use-Case-Usage`:

| Account | `call_count` | `total_cputime` | `total_time` | tier |
|---|---|---|---|---|
| 1 Raho Saadaa | 1% | **108%** | 81% | `development_access` |
| 2 Fourth Ad Account | 0% | 0% | 0% | `development_access` |
| 3 Third Ad Account | 0% | 0% | 0% | `development_access` |

Account 1's `call_count` is 1% while its CPU is over 100%, so the
constraint is the cost of each call, not the number of them. All three
accounts are on **`development_access`**, where that allowance is small.
Moving the app to Standard Access would raise it; that needs App Review
and Business Verification, which is not something this code can do.

**The delta poll is not what exhausted it.** Measured directly against
account 2 on a clean budget — three filtered pages, exactly one interval
of `run_meta_delta_sync` for one account:

| Call | HTTP | Rows | Time | CPU after |
|---|---|---|---|---|
| `/campaigns?filtering=campaign.updated_time` | 200 | 0 | 0.5s | 1% |
| `/adsets?filtering=adset.updated_time` | 200 | 0 | 0.5s | ~0% |
| `/ads?filtering=ad.updated_time` | 200 | 0 | 0.5s | ~0% |

A whole cycle is **1% of the hourly CPU budget and 1.5 seconds**. At 15
minutes that is ~4%/hour per account; even a 5-minute interval would be
~12%/hour. Account 1 was already above its limit before any of this ran
(its first probe came back `(#80004) too many calls`), so **something
else is consuming that account's budget** — worth finding, but not this
feature. Account 1 also carries ~12,600 ads against account 2's handful,
so its per-cycle scan costs more than the 1% measured here; the 15-minute
default leaves room for that rather than assuming the numbers transfer.

Recovery is slow and not monotonic: 108% → 105% over five minutes, then
back to 111%, as calls age out of the one-hour window rather than being
refunded.

While an account sits above 90% the client waits instead of calling, so
that account's delta refresh is skipped until its budget recovers. The
other accounts are unaffected — each has its own budget.

This is why:

* the default interval is **15 minutes**
  (`SCHEDULER_META_DELTA_INTERVAL_MINUTES`) — measured headroom allows 5,
  but not while account 1 is pinned by an unidentified consumer;
* `run_meta_delta_sync` catches per level, so a throttled `/campaigns`
  call does not cost the ad refresh;
* the watermark is read from `sync_batches`, not from
  `max(extracted_at)` on Bronze — the Bronze form walks back along
  `ix_raw_dump_meta_extracted_at` for **21,542 blocks and 2.1s per
  account**, which is absurd for something read every interval.
  `sync_batches` costs **2 blocks**.

The client already waits proactively above 90% usage
(`USAGE_THROTTLE_THRESHOLD` in `app/services/meta/client.py`), so setting
the interval too low degrades into skipped runs rather than a throttled
account — but it does mean an over-eager interval buys nothing.

## Verified end to end, 2026-10-26

One real run of `run_meta_delta_sync` against account 2 (`act_1349767139294217`),
real API, real writes, watermark 2026-10-23 01:39:

```
campaigns  →  9 changed → Bronze → meta_campaigns
adsets     →  7 changed → Bronze → meta_adsets
ads        → 100 changed → Bronze → meta_ads
33 seconds end to end
meta_ads for the account: 3,050 → 3,078 rows
max(updated_at):          2026-10-23 01:38 → 2026-10-26 14:14
```

Every refreshed ad came out with its `adset_name` and `campaign_name`
populated, so the parent pull works.

And the invariant the whole design rests on, checked against real data —
all 3,078 of that account's ads in `meta_ads` match the newest Bronze
snapshot exactly on `ad_status`, `ad_effective_status` and `updated_at`:

| ads checked | agree | disagree |
|---|---|---|
| 3,078 | 3,078 | 0 |

A later full rebuild will produce the same rows the scoped refresh just
wrote.

## Known state as of 2026-10-26

`meta_campaigns` / `meta_adsets` / `meta_ads` were last refreshed
**2026-10-23 01:39 UTC**, three days stale, and `sync_batches` shows no
successful entity sync since. That is the gap this feature closes: it is
not that an hour was too slow, it is that nothing was running.

Separately, **account 1 (Raho Saadaa) sits above 100% of its CPU budget
with a 1% call count**, and it was already there before any of this work
touched it. Accounts 2 and 3 read 1%. Until that consumer is identified,
account 1's delta refresh will be skipped by the client's proactive wait
whenever it runs — the other two accounts are unaffected, since each has
its own budget.

## Configuration

| Variable | Purpose |
|---|---|
| `META_APP_SECRET` | signs/verifies `X-Hub-Signature-256` (already set) |
| `META_WEBHOOK_VERIFY_TOKEN` | any random string; echoed on the handshake |
| `SCHEDULER_META_DELTA_SYNC_ENABLED` | default `true` |
| `SCHEDULER_META_DELTA_INTERVAL_MINUTES` | default `5` |
| `SCHEDULER_META_DELTA_OVERLAP_SECONDS` | default `900` |
| `SCHEDULER_META_DELTA_MAX_LOOKBACK_DAYS` | default `7` |

## Registering the subscription

Once `META_WEBHOOK_VERIFY_TOKEN` is set and deployed, with an **app
access token** (`<app-id>|<app-secret>`):

```
POST /v21.0/<APP_ID>/subscriptions
  object=ad_account
  callback_url=https://<host>/webhooks/meta
  fields=with_issues_ad_objects,in_process_ad_objects,creative_fatigue,ad_recommendations
  verify_token=<META_WEBHOOK_VERIFY_TOKEN>
```

Meta calls `GET /webhooks/meta` during this request; it has to be live
first. Then, per ad account, with a **user/system access token** and no
`fields` parameter:

```
POST /v21.0/act_<AD_ACCOUNT_ID>/subscribed_apps
```

Verify with `GET /v21.0/<APP_ID>/subscriptions` and
`GET /v21.0/act_<ID>/subscribed_apps`.
