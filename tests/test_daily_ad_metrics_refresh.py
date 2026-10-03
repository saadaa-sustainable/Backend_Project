"""Execute refresh SQL in an isolated PostgreSQL schema, rolled back per test.

CI supplies TEST_DATABASE_URL. No production table names survive the schema
substitution and the search path excludes public (including Bronze reads).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from scripts import refresh_insights_daily_by_ad as daily
from scripts import refresh_raw_dump_meta_daily as raw


@pytest.fixture
def db(monkeypatch):
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL regression tests")
    conn = psycopg2.connect(dsn, connect_timeout=15)
    schema = "daily_metrics_test_" + uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '20s'")
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET LOCAL search_path = "{schema}", pg_catalog')
            for name in ("DDL", "STAGE_DDL", "PUBLISH_SQL", "DELETE_MISSING_SQL", "LIVE_MAX_DAY_SQL"):
                monkeypatch.setattr(daily, name, getattr(daily, name).replace("public.", f"{schema}."))
            cur.execute(daily.DDL)
            cur.execute("""
                CREATE TABLE raw_dump_meta (
                    id text PRIMARY KEY, meta_id text, raw_payload jsonb,
                    api_endpoint text, api_version text, batch_id text,
                    request_params jsonb, extracted_at timestamptz,
                    ingested_at timestamptz, sync_type text, payload_hash text,
                    processing_status text, object_type text, parent_ids jsonb,
                    is_nested boolean
                )
            """)
            yield conn, cur, schema
    finally:
        conn.rollback()
        conn.close()


def bronze(cur, row_id, payload, *, ingested="2026-10-03 00:00:00+00", object_type="insights"):
    cur.execute("""
        INSERT INTO raw_dump_meta (id, raw_payload, object_type, request_params, ingested_at)
        VALUES (%s, %s, %s, '{"time_increment":"1"}', %s)
    """, (row_id, Json(payload), object_type, ingested))


def stage(cur):
    cur.execute(daily.STAGE_DDL)
    cur.execute(daily.STAGE_SQL)
    cur.execute("ALTER TABLE pg_temp.insights_daily_by_ad_stage ADD PRIMARY KEY (ad_id, day)")


def test_daily_values_use_latest_duplicate_and_never_spread_period_totals(db):
    _, cur, _ = db
    payload = {"ad_id": "a", "date_start": "2026-10-02", "date_stop": "2026-10-02", "spend": "7"}
    bronze(cur, "older", payload, ingested="2026-10-02 00:00:00+00")
    bronze(cur, "newer", {**payload, "spend": "12", "impressions": "100", "inline_link_clicks": "3",
        "clicks": "5", "reach": "90", "actions": [
            {"action_type": "omni_purchase", "value": "2"},
            {"action_type": "purchase", "value": "9"},
            {"action_type": "offsite_conversion.custom.n", "value": "1"},
            {"action_type": "offsite_conversion.custom.f", "value": "4"}],
        "action_values": [{"action_type": "omni_purchase", "value": "80"}]})
    bronze(cur, "ncp", {"id": "n", "name": "NCP"}, object_type="custom_conversion")
    bronze(cur, "ftewv", {"id": "f", "name": "First-time EWV"}, object_type="custom_conversion")
    bronze(cur, "period", {**payload, "date_start": "2026-09-01", "spend": "999"})
    stage(cur)
    changed, removed, stats = daily.publish_stage(cur)
    assert (changed, removed, stats[0], stats[3]) == (1, 0, 1, date(2026, 10, 2))
    cur.execute("SELECT spend, impressions, clicks, all_clicks, reach, purchases, conv_value, ncp_count, ftewv_count FROM insights_daily_by_ad")
    assert cur.fetchone() == (12, 100, 3, 5, 90, 2, 80, 1, 4)


def test_publish_preserves_relation_views_rls_and_grants_and_is_idempotent(db):
    _, cur, _ = db
    cur.execute("INSERT INTO insights_daily_by_ad(ad_id, day, spend) VALUES ('a','2026-10-01',1), ('obsolete','2026-09-01',5)")
    cur.execute("CREATE VIEW daily_reader AS SELECT SUM(spend) AS spend FROM insights_daily_by_ad")
    cur.execute("CREATE TABLE insights_daily_by_ad_old (day date)")
    cur.execute("CREATE VIEW legacy_reader AS SELECT * FROM insights_daily_by_ad_old")
    cur.execute("GRANT SELECT ON insights_daily_by_ad TO PUBLIC")
    metadata = "SELECT oid, relrowsecurity, relacl FROM pg_class WHERE oid = 'insights_daily_by_ad'::regclass"
    cur.execute(metadata)
    before = cur.fetchone()
    bronze(cur, "a", {"ad_id":"a", "date_start":"2026-10-01", "date_stop":"2026-10-01", "spend":"10"})
    bronze(cur, "b", {"ad_id":"b", "date_start":"2026-10-02", "date_stop":"2026-10-02", "spend":"20"})
    stage(cur)
    assert daily.publish_stage(cur)[:2] == (2, 1)
    assert daily.publish_stage(cur)[:2] == (0, 0)
    cur.execute(metadata)
    assert cur.fetchone() == before
    cur.execute("SELECT spend FROM daily_reader")
    assert cur.fetchone()[0] == 30
    cur.execute("SELECT * FROM legacy_reader")
    assert cur.fetchall() == []


@pytest.mark.parametrize("stage_day", [None, "2026-09-26"])
def test_empty_or_regressing_source_cannot_erase_current_data(db, stage_day):
    _, cur, _ = db
    cur.execute("INSERT INTO insights_daily_by_ad(ad_id, day, spend) VALUES ('a','2026-10-02',12)")
    if stage_day:
        bronze(cur, "a", {"ad_id":"a", "date_start":stage_day, "date_stop":stage_day, "spend":"1"})
    stage(cur)
    with pytest.raises(RuntimeError, match="preserving the live table"):
        daily.publish_stage(cur)
    cur.execute("SELECT day, spend FROM insights_daily_by_ad")
    assert cur.fetchone() == (date(2026, 10, 2), 12)


def test_failed_publish_rolls_back_all_changes(db):
    _, cur, _ = db
    cur.execute("INSERT INTO insights_daily_by_ad(ad_id, day, spend) VALUES ('a','2026-10-02',12)")
    bronze(cur, "a", {"ad_id":"a", "date_start":"2026-10-02", "date_stop":"2026-10-02", "spend":"30"})
    stage(cur)
    cur.execute("SAVEPOINT before_publish")
    daily.publish_stage(cur)
    # A failure after upsert must still leave the previous snapshot intact.
    with pytest.raises(psycopg2.errors.DivisionByZero):
        cur.execute("SELECT 1/0")
    cur.execute("ROLLBACK TO SAVEPOINT before_publish")
    cur.execute("SELECT spend FROM insights_daily_by_ad")
    assert cur.fetchone()[0] == 12


def test_raw_daily_mirror_deduplicates_and_rejects_older_replays(db):
    _, cur, schema = db
    cur.execute("CREATE TABLE raw_dump_meta_daily (LIKE raw_dump_meta INCLUDING ALL)")
    cur.execute("CREATE UNIQUE INDEX daily_key ON raw_dump_meta_daily ((raw_payload->>'ad_id'), (raw_payload->>'date_start')) WHERE raw_payload->>'ad_id' IS NOT NULL AND raw_payload->>'date_start' IS NOT NULL")
    payload = {"ad_id":"a", "date_start":"2026-10-02", "date_stop":"2026-10-02", "spend":"1"}
    bronze(cur, "older", payload, ingested="2026-10-01 00:00:00+00")
    bronze(cur, "newer", {**payload, "spend":"12"})
    sql = raw.UPSERT_SQL.format(extra_where="").replace("public.", schema + ".")
    cur.execute(sql)
    cur.execute("SELECT COUNT(*), MAX(raw_payload->>'spend') FROM raw_dump_meta_daily")
    assert cur.fetchone() == (1, "12")
    cur.execute("DELETE FROM raw_dump_meta WHERE id='newer'")
    cur.execute(sql)
    assert cur.rowcount == 0


@pytest.mark.parametrize("kind", ["VIEW", "MATERIALIZED VIEW"])
def test_snapshot_rebind_cleanup_accepts_both_relation_kinds(db, kind):
    _, cur, schema = db
    cur.execute(f"CREATE {kind} meta_direct_active_30d AS SELECT 1 AS ad_id")
    ddl = (Path(__file__).resolve().parents[1] / "sql/snapshot_views.sql").read_text()
    cleanup = ddl[:ddl.index("-- The newest day")]
    cur.execute(cleanup.replace("public.", schema + ".").replace("n.nspname = 'public'", f"n.nspname = '{schema}'"))
    cur.execute("SELECT to_regclass(%s)", (schema + ".meta_direct_active_30d",))
    assert cur.fetchone()[0] is None
