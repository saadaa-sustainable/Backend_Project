"""The Meta webhook receiver, and the delta refresh that does the work it
cannot.

The property worth pinning hardest is the signature: it has to be computed
over the exact bytes Meta sent. Verify a re-serialised parse instead and
every event is rejected with a 401 that looks, from the outside, exactly
like a wrong app secret -- so these tests send a body whose JSON does not
round-trip to itself.

The second property is the one that cost this feature its original design:
Meta's `ad_account` topic has six fields and none of them fires on a status
flip or an edit. A test that asserted the field list loosely would let
someone "fix" the gap by subscribing to a field that does not exist.
"""

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routers import webhooks
from app.services.meta import live_refresh
from app.services.meta.webhook_processor import _account_keys_for, extract_targets

SECRET = "app-secret"

#: Key order and spacing deliberately not what json.dumps would produce,
#: so a receiver that hashed a re-serialised parse would fail these.
RAW = (b'{"object":"ad_account","entry":[{"id":"act_1136644150469466",'
       b'  "time":1761500000,"changes":[{"field":"with_issues_ad_objects",'
       b'"value":{"id":"120254055950310422","level":"AD","error_code":1815869}}]}]}')


def sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def settings(**kwargs):
    base = {"meta_webhook_verify_token": "verify-me",
            "meta": SimpleNamespace(app_secret=SECRET, accounts=[])}
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- signature

def test_a_valid_signature_over_the_raw_bytes_passes(monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    webhooks._verify_meta_signature(RAW, sign(RAW))      # must not raise


def test_a_signature_over_a_reserialised_body_is_refused(monkeypatch):
    # The whole trap, as a test. json.dumps of the parsed body is valid
    # JSON with the same meaning and different bytes; hashing that is the
    # mistake that silently rejects every real event.
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    reserialised = json.dumps(json.loads(RAW)).encode()
    assert reserialised != RAW
    with pytest.raises(HTTPException) as e:
        webhooks._verify_meta_signature(RAW, sign(reserialised))
    assert e.value.status_code == 401


@pytest.mark.parametrize("supplied", [None, "", "deadbeef", "sha1=" + "0" * 40,
                                      "sha256=" + "0" * 64])
def test_a_missing_or_wrong_signature_is_refused(supplied, monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    with pytest.raises(HTTPException) as e:
        webhooks._verify_meta_signature(RAW, supplied)
    assert e.value.status_code == 401


def test_an_unconfigured_receiver_refuses_everything(monkeypatch):
    # Same dangerous default as the EasyEcom side: a public URL with the
    # check disabled is an open write path into the warehouse.
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: settings(meta=SimpleNamespace(app_secret=None, accounts=[])))
    with pytest.raises(HTTPException) as e:
        webhooks._verify_meta_signature(RAW, sign(RAW))
    assert e.value.status_code == 503


def test_the_signature_is_compared_in_constant_time():
    import inspect
    src = inspect.getsource(webhooks._verify_meta_signature)
    assert "compare_digest" in src
    assert "== expected" not in src


# ---------------------------------------------------------------- handshake

async def test_the_handshake_echoes_the_challenge_as_the_bare_body(monkeypatch):
    # Meta wants hub.challenge and nothing else -- not JSON, not a wrapper.
    # A wrapped body means the callback URL never registers.
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    body = await webhooks.meta_webhook_verify(
        hub_mode="subscribe", hub_verify_token="verify-me", hub_challenge="12345")
    assert body == "12345"


async def test_a_wrong_verify_token_does_not_register_the_url(monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    with pytest.raises(HTTPException) as e:
        await webhooks.meta_webhook_verify(
            hub_mode="subscribe", hub_verify_token="wrong", hub_challenge="12345")
    assert e.value.status_code == 403


async def test_an_unset_verify_token_cannot_be_matched_by_an_empty_one(monkeypatch):
    # The failure mode to avoid: unset == "" would let anyone complete the
    # handshake and point a subscription at us.
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: settings(meta_webhook_verify_token=None))
    with pytest.raises(HTTPException) as e:
        await webhooks.meta_webhook_verify(
            hub_mode="subscribe", hub_verify_token="", hub_challenge="12345")
    assert e.value.status_code == 503


# ------------------------------------------------------- what Meta can send

def test_the_subscribable_fields_are_exactly_the_six_meta_documents():
    # Pinned exactly, because the tempting "fix" for the status-change gap
    # is to subscribe to `effective_status` -- a field that does not exist
    # on this topic. Subscribing to it silently yields no events at all.
    assert webhooks.META_FIELDS == {
        "ads_async_creation_request", "creative_fatigue", "ad_recommendations",
        "in_process_ad_objects", "product_set_issue", "with_issues_ad_objects",
    }
    assert "effective_status" not in webhooks.META_FIELDS
    assert "ad" not in webhooks.META_FIELDS


@pytest.mark.parametrize("field,value,expected", [
    ("with_issues_ad_objects", {"id": "1", "level": "AD"}, {"ad": ["1"]}),
    ("with_issues_ad_objects", {"id": "2", "level": "AD_SET"}, {"adset": ["2"]}),
    ("in_process_ad_objects", {"id": "3", "level": "CAMPAIGN"}, {"campaign": ["3"]}),
    # adgroup_id is Meta's older name for an ad set id, not an ad id.
    ("creative_fatigue", {"adgroup_id": "4"}, {"adset": ["4"]}),
    ("ad_recommendations", {"ad_object_ids": ["5", "6"]}, {"ad": ["5", "6"]}),
    # No Silver creative table, so a CREATIVE-level event is stored and
    # skipped rather than guessed at.
    ("with_issues_ad_objects", {"id": "7", "level": "CREATIVE"}, {}),
    # A field we hold nothing for, and one Meta may add later.
    ("product_set_issue", {"product_set_id": "8"}, {}),
    ("something_new", {"id": "9", "level": "AD"}, {}),
])
def test_each_field_maps_to_the_level_it_actually_names(field, value, expected):
    ids, _ = extract_targets({"object": "ad_account", "entry": [
        {"id": "act_123", "changes": [{"field": field, "value": value}]}]})
    assert ids == expected


def test_the_account_is_read_from_the_entry_with_or_without_the_act_prefix():
    _, accounts = extract_targets({"entry": [
        {"id": "act_111", "changes": [{"field": "creative_fatigue",
                                       "value": {"adgroup_id": "1",
                                                 "ad_account_id": "222"}}]},
        {"id": "333", "changes": []}]})
    assert accounts == {"111", "222", "333"}


@pytest.mark.parametrize("payload", [
    {}, {"entry": None}, {"entry": ["not-a-dict"]},
    {"entry": [{"id": "act_1", "changes": "not-a-list"}]},
    {"entry": [{"id": "act_1", "changes": [{"field": "with_issues_ad_objects",
                                            "value": "not-a-dict"}]}]},
    {"entry": [{"id": "act_1", "changed_fields": [{"field": "creative_fatigue",
                                                   "value": {"adgroup_id": "1"}}]}]},
])
def test_an_unexpected_payload_shape_yields_nothing_rather_than_raising(payload):
    # This runs in a background task after Meta already got its 200. An
    # exception here would be logged somewhere nobody looks; returning
    # nothing leaves the stored row to re-read.
    ids, _ = extract_targets(payload)
    assert isinstance(ids, dict)


def test_an_unconfigured_account_is_skipped_rather_than_guessed(monkeypatch):
    # Every Bronze row carries the account it came from. Defaulting an
    # unknown account to the first configured one would file one account's
    # ads under another account's name in Silver.
    import app.services.meta.webhook_processor as wp
    monkeypatch.setattr(wp, "get_settings", lambda: SimpleNamespace(
        meta=SimpleNamespace(accounts=[SimpleNamespace(account_id="111", key="1")])))
    assert _account_keys_for({"111"}) == ["1"]
    assert _account_keys_for({"999"}) == []
    assert _account_keys_for({"111", "999"}) == ["1"]


# ------------------------------------------------------------- delta refresh

def test_the_delta_filters_on_each_level_s_own_updated_time_field():
    # Graph rejects `ad.updated_time` on the /campaigns edge, so the field
    # name has to track the level, not the account.
    assert live_refresh._UPDATED_TIME_FIELD == {
        "campaign": "campaign.updated_time",
        "adset": "adset.updated_time",
        "ad": "ad.updated_time",
    }


@pytest.mark.parametrize("level,expected", [
    ("campaign", "campaign"), ("adset", "adset"), ("ad", "ad"),
])
def test_bronze_object_types_line_up_with_the_flatten_levels(level, expected):
    from app.services.meta.entity_flatten import _LEVELS, _LEVEL_ORDER
    assert live_refresh._SERVICES[level].object_type == expected
    assert level in _LEVELS
    # Campaign before ad set before ad: the child INSERTs join their
    # parent's name out of the table refreshed just before them.
    assert _LEVEL_ORDER == ("campaign", "adset", "ad")


def test_the_scoped_refresh_reuses_the_full_rebuild_s_own_sql():
    # The two must agree row for row. Sharing the template is what makes
    # that structural instead of a thing to remember: a column added to
    # the full rebuild cannot go missing from the scoped one.
    from app.services.meta import entity_flatten as ef
    for level, (table, pk, alias, template) in ef._LEVELS.items():
        assert "{extra}" in template
        assert f"INSERT INTO {table}" in template
        scoped = template.format(extra=f" AND {alias}meta_id = ANY(:ids)")
        assert "{" not in scoped
        # Same column list, same ordering, same DISTINCT ON -- the only
        # difference is the added predicate.
        assert scoped.replace(f" AND {alias}meta_id = ANY(:ids)", "") == \
            template.format(extra="")


async def test_nothing_to_refresh_costs_no_api_call_and_no_write(monkeypatch):
    called = []
    monkeypatch.setattr(live_refresh, "_sync",
                        lambda *a, **k: called.append(a) or (None, []))
    monkeypatch.setattr(live_refresh, "refresh_entities_for_ids",
                        lambda *a, **k: called.append("flatten"))
    assert await live_refresh.refresh_objects(
        None, {"ad": [], "creative": ["x"]}, account_key="1") == {}
    assert called == []


async def test_a_cold_start_is_capped_instead_of_asking_for_all_of_history():
    # Without the cap, the first run on an empty Bronze asks Meta for every
    # edit the account has ever had.
    import time
    from unittest.mock import AsyncMock

    session = SimpleNamespace(execute=AsyncMock(
        return_value=SimpleNamespace(scalar=lambda: None)))
    since = await live_refresh.last_fetch_epoch(
        session, account_key="1", overlap_seconds=900, max_lookback_days=7)
    assert abs(since - (int(time.time()) - 7 * 86400)) < 5


async def test_a_long_outage_catches_up_on_its_own_without_a_stored_cursor():
    # The watermark is read off Bronze, so being down for a day means the
    # next run asks for a day of changes -- no cursor to lose or reset.
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock

    last = datetime.now(timezone.utc) - timedelta(hours=30)
    session = SimpleNamespace(execute=AsyncMock(
        return_value=SimpleNamespace(scalar=lambda: last)))
    since = await live_refresh.last_fetch_epoch(
        session, account_key="1", overlap_seconds=900, max_lookback_days=7)
    assert abs(since - (int(last.timestamp()) - 900)) < 5


async def test_the_overlap_re_reads_rather_than_risks_missing_an_edit():
    # Bronze is append-only, so re-reading an unchanged object is free.
    # Missing one because its edit landed mid-run is not recoverable until
    # the nightly.
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    last = datetime.now(timezone.utc)
    session = SimpleNamespace(execute=AsyncMock(
        return_value=SimpleNamespace(scalar=lambda: last)))
    since = await live_refresh.last_fetch_epoch(
        session, account_key="1", overlap_seconds=900, max_lookback_days=7)
    assert since < int(last.timestamp())


def test_silver_is_never_written_without_going_through_bronze():
    # meta_ads is rebuilt by DISTINCT ON (meta_id) ORDER BY extracted_at
    # DESC over raw_dump_meta. An UPDATE straight into it would show on the
    # dashboard and then be silently reverted by the next full rebuild --
    # right, then wrong, with nothing in between to explain it.
    import inspect
    src = inspect.getsource(live_refresh)
    for table in ("meta_ads", "meta_adsets", "meta_campaigns"):
        assert f"UPDATE {table}" not in src
        assert f"INSERT INTO {table}" not in src
    assert "service.sync(" in src          # Bronze first, always


async def test_a_brand_new_ad_pulls_the_parent_silver_has_never_seen(monkeypatch):
    # A webhook about a new ad arrives before any sync has seen its ad set.
    # The ad INSERT joins adset_name out of meta_adsets, so without this
    # the ad lands on the dashboard with blank parent names.
    from unittest.mock import AsyncMock

    synced = []

    async def fake_sync(session, level, account_key, request_params, triggered_by):
        synced.append((level, tuple(request_params.get("object_ids") or ())))
        return f"batch-{level}", list(request_params.get("object_ids") or ())

    monkeypatch.setattr(live_refresh, "_sync", fake_sync)

    # Bronze says the fetched ad belongs to adset A1 in campaign C1; both
    # queries report them absent from Silver.
    async def execute(statement, params=None):
        sql = str(statement)
        if "parent_ids ->> 'campaign_id'" in sql:
            return [SimpleNamespace(_mapping={"campaign_id": "C1", "adset_id": "A1"})]
        if "meta_adsets" in sql:
            return [("A1",)]
        if "meta_campaigns" in sql:
            return [("C1",)]
        return []

    flattened = {}
    monkeypatch.setattr(live_refresh, "refresh_entities_for_ids",
                        AsyncMock(side_effect=lambda s, ids: flattened.update(ids) or {}))

    await live_refresh.refresh_objects(
        SimpleNamespace(execute=execute), {"ad": ["AD1"]}, account_key="1")

    assert ("ad", ("AD1",)) in synced
    assert ("adset", ("A1",)) in synced, "the unseen ad set was never fetched"
    assert ("campaign", ("C1",)) in synced, "the unseen campaign was never fetched"
    # And all three reach the flatten, parents included.
    assert flattened == {"ad": ["AD1"], "adset": ["A1"], "campaign": ["C1"]}


def test_a_requested_object_that_came_back_empty_is_left_alone(monkeypatch):
    # A deleted or moved object can no longer be read, so there is no
    # replacement snapshot. Re-flattening it would delete the Silver row
    # and re-insert the same stale Bronze; the nightly reconciles
    # deletions. The scoped flatten must only see what was really fetched.
    import inspect
    src = inspect.getsource(live_refresh.refresh_objects)
    assert "unreadable" in src
    assert "refresh_entities_for_ids(session, fetched)" in src
    assert "refresh_entities_for_ids(session, wanted)" not in src


async def test_one_rate_limited_level_does_not_cost_the_others(monkeypatch):
    # Meta throttles per edge. Ads are what the dashboard mostly shows, so
    # a throttled /campaigns call must not skip the ad refresh. The
    # watermark is derived from Bronze, so the throttled level is simply
    # still pending at the next interval.
    from unittest.mock import AsyncMock

    async def fake_sync(session, level, account_key, request_params, triggered_by):
        if level == "campaign":
            raise RuntimeError("(#80004) There have been too many calls")
        return f"batch-{level}", [f"{level}-1"]

    monkeypatch.setattr(live_refresh, "_sync", fake_sync)
    monkeypatch.setattr(live_refresh, "_pull_missing_parents", AsyncMock())
    flattened = {}
    monkeypatch.setattr(live_refresh, "refresh_entities_for_ids",
                        AsyncMock(side_effect=lambda s, ids: flattened.update(ids) or {}))

    await live_refresh.refresh_changed_since(None, account_key="1", since_epoch=1)

    assert "campaign" not in flattened
    assert flattened == {"adset": ["adset-1"], "ad": ["ad-1"]}


async def test_a_webhook_whose_background_task_was_lost_is_still_processed(monkeypatch):
    # A FastAPI background task lives in the serving process, so a restart
    # between the 200 and the refresh loses the task -- but not the row,
    # which is the whole reason custody comes before interpretation.
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    import app.services.meta.webhook_processor as wp

    queries = []

    class FakeSession:
        async def execute(self, statement, params=None):
            queries.append((str(statement), params))
            return [(7,), (8,)]

    @asynccontextmanager
    async def scope():
        yield FakeSession()

    monkeypatch.setattr(wp, "session_scope", scope)
    processed = AsyncMock()
    monkeypatch.setattr(wp, "process_meta_event", processed)

    assert await wp.process_pending_meta_events() == 2
    assert [c.args[0] for c in processed.await_args_list] == [7, 8]

    sql, params = queries[0]
    assert "processed_at IS NULL" in sql
    # An age floor, so the sweep cannot race a background task that is
    # still in flight and refresh the same event twice at once.
    assert "received_at <" in sql and params["min_age_seconds"] == 120


async def test_the_payload_is_stored_before_anything_interprets_it(monkeypatch):
    # Meta retries a non-200 for a while and then disables the
    # subscription outright. So custody comes first and interpretation
    # happens after the response: a payload shape we do not recognise
    # must not be able to cost us the subscription.
    from unittest.mock import AsyncMock

    order = []

    class FakeSession:
        async def execute(self, statement, params=None):
            order.append(("stored", params["source"], params["payload"]))
            return SimpleNamespace(scalar_one=lambda: 99)

        async def commit(self):
            order.append(("committed",))

    class FakeBackground:
        def add_task(self, fn, *args):
            order.append(("queued", fn.__name__, args))

    class FakeRequest:
        headers = {"content-type": "application/json",
                   "x-hub-signature-256": "must-not-be-stored",
                   "user-agent": "facebookexternalua"}

        async def body(self):
            return RAW

    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    result = await webhooks.meta_webhook(
        FakeRequest(), FakeSession(), FakeBackground(), signature=sign(RAW))

    assert result == {"received": True, "id": 99}
    assert [o[0] for o in order] == ["stored", "committed", "queued"]
    assert order[0][1] == "meta"
    # Verbatim: the exact bytes, not a re-serialisation, so a payload that
    # differs from the docs is still there to re-read.
    assert json.loads(order[0][2]) == json.loads(RAW)
    assert order[2][1] == "process_meta_event"
    # And the signature never reaches storage.
    assert "must-not-be-stored" not in order[0][2]


async def test_an_unsigned_post_is_refused_before_it_is_stored(monkeypatch):
    stored = []

    class FakeSession:
        async def execute(self, *a, **k):
            stored.append(a)
            return SimpleNamespace(scalar_one=lambda: 1)

        async def commit(self):
            pass

    class FakeRequest:
        headers = {}

        async def body(self):
            return RAW

    monkeypatch.setattr(webhooks, "get_settings", lambda: settings())
    with pytest.raises(HTTPException) as e:
        await webhooks.meta_webhook(
            FakeRequest(), FakeSession(), SimpleNamespace(add_task=lambda *a: None),
            signature=None)
    assert e.value.status_code == 401
    assert stored == [], "an unsigned body must not reach the warehouse"


def test_the_watermark_is_read_from_the_sync_log_not_from_bronze():
    # max(extracted_at) over raw_dump_meta has no index for
    # parent_ids ->> 'account_key', so it walks back along
    # ix_raw_dump_meta_extracted_at for 21,542 blocks and 2.1s per
    # account. The poll reads this every few minutes.
    sql = str(live_refresh._WATERMARK)
    assert "sync_batches" in sql
    assert "raw_dump_meta" not in sql
    # started_at, not finished_at: every row a batch wrote has an
    # extracted_at at or after the batch began, so starting there cannot
    # leave a gap.
    assert "max(started_at)" in sql
    assert "finished_at" not in sql
    # 'failed' must not advance the watermark past data it never read --
    # and the status values have to be the ones this codebase writes.
    from app.models.sync import BatchStatus
    assert f"'{BatchStatus.SUCCESS}'" in sql
    assert f"'{BatchStatus.FAILED}'" not in sql


def test_an_id_scoped_batch_does_not_advance_the_watermark():
    # refresh_objects fetches a handful of named ids. That is no evidence
    # about anything else that changed, so counting it as a full survey
    # would silently skip the window between it and the real last sync.
    sql = str(live_refresh._WATERMARK)
    assert "object_ids" in sql and "NOT coalesce" in sql


async def test_a_throttled_account_does_not_hold_up_the_healthy_ones(monkeypatch):
    # Measured: against an account already over its CPU budget, the
    # client's backoff spent 37 minutes across six attempts before a 200.
    # Run sequentially, that one account holds the others behind it for
    # longer than the whole interval -- and max_instances: 1 then
    # coalesces away the runs meant to cover them.
    import asyncio

    from app.scheduler import jobs

    started, finished = [], []

    async def one(account_key, *, overlap, lookback):
        started.append(account_key)
        if account_key == "1":
            await asyncio.sleep(0.05)      # stands in for the 37 minutes
        finished.append(account_key)

    monkeypatch.setattr(jobs, "_delta_sync_one_account", one)
    monkeypatch.setattr(jobs, "process_pending_meta_events", lambda: asyncio.sleep(0))
    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(
        scheduler=SimpleNamespace(meta_delta_overlap_seconds=900,
                                  meta_delta_max_lookback_days=7),
        meta=SimpleNamespace(accounts=[SimpleNamespace(key="1"), SimpleNamespace(key="2"),
                                       SimpleNamespace(key="3")])))

    await jobs.run_meta_delta_sync()

    assert started == ["1", "2", "3"]
    # The healthy accounts finished while account 1 was still waiting.
    assert finished == ["2", "3", "1"]


async def test_one_account_s_failure_is_logged_and_the_others_still_run(monkeypatch):
    import asyncio

    from app.scheduler import jobs

    ran = []

    async def one(account_key, *, overlap, lookback):
        if account_key == "2":
            raise RuntimeError("boom")
        ran.append(account_key)

    monkeypatch.setattr(jobs, "_delta_sync_one_account", one)
    monkeypatch.setattr(jobs, "process_pending_meta_events", lambda: asyncio.sleep(0))
    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(
        scheduler=SimpleNamespace(meta_delta_overlap_seconds=900,
                                  meta_delta_max_lookback_days=7),
        meta=SimpleNamespace(accounts=[SimpleNamespace(key=k) for k in ("1", "2", "3")])))

    # A failure the per-account handler cannot catch -- opening the
    # session happens outside its try -- must not cancel the accounts
    # running alongside it.
    await jobs.run_meta_delta_sync()
    assert ran == ["1", "3"]
