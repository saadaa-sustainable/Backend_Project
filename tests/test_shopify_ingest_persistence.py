"""Exercise ingestion ordering and real upsert behavior without external services."""
from datetime import date, datetime, timezone
import json
import re
import sqlite3
import uuid
from unittest.mock import AsyncMock

import pytest

from scripts import ingest_shopify as ingest
from scripts import refresh_all_daily as daily


STORE = ingest.ShopifyStore("1", "Fixture store", "fixture.invalid", "fixture-token")


class LocalConnection:
    """Execute the generated INSERT in SQLite; adapt only driver value types."""

    def __init__(self, db):
        self.db = db
        self.statements = []
        self.closed = False

    async def execute(self, sql, *values):
        assert not self.closed
        self.statements.append((sql, values))
        # The generated $n parameters occur once each, in argument order.
        sql = re.sub(r"\$\d+", "?", sql)
        values = [str(v) if isinstance(v, (uuid.UUID, datetime)) else v for v in values]
        self.db.execute(sql, values)
        self.db.commit()

    async def close(self):
        self.closed = True


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.create_function("now", 0, lambda: "2026-10-16 12:00:00")
    connection.execute("""CREATE TABLE raw_dump_shopify (
        id TEXT PRIMARY KEY, source_id TEXT, raw_payload TEXT,
        api_endpoint TEXT, api_version TEXT, batch_id TEXT,
        request_params TEXT, extracted_at TEXT, sync_type TEXT,
        payload_hash TEXT, processing_status TEXT, object_type TEXT,
        parent_ids TEXT, is_nested INTEGER,
        ingested_at TEXT DEFAULT 'initial'
    )""")
    connection.execute(ingest._ENSURE_UNIQUE_INDEX_SQL)
    yield connection
    connection.close()


def rows(items, object_type="orders"):
    return ingest._build_rows(
        ingest.FetchResult(STORE, object_type, items=items),
        batch_id=uuid.uuid4(), api_version="2026-10",
        extracted_at=datetime(2026, 10, 16, tzinfo=timezone.utc),
    )


async def test_bulk_write_updates_payloads_without_duplicating_existing_rows(db):
    conn = LocalConnection(db)
    original = rows([{"id": "order-1", "total_price": 10}])
    await ingest._insert_rows(conn, "raw_dump_shopify", original)
    updates = rows([{"id": f"order-{i}", "total_price": i * 100} for i in range(1, 1002)])
    assert await ingest._insert_rows(conn, "raw_dump_shopify", updates) == 1001
    # 1,001 rows require three executions, rather than 1,001 executions.
    assert len(conn.statements) == 4
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify").fetchone()[0] == 1001
    row = db.execute("SELECT id,raw_payload,ingested_at FROM raw_dump_shopify WHERE source_id='order-1'").fetchone()
    assert row[0] == original[0]["id"]
    assert json.loads(row[1])["total_price"] == 100
    assert row[2] != "initial"
    assert all(len(values) <= 32767 for _, values in conn.statements)


async def test_duplicate_keys_keep_first_identity_and_last_payload(db):
    conn = LocalConnection(db)
    batch = rows([{"id": "same", "version": 1}, {"id": "same", "version": 2}])
    assert await ingest._insert_rows(conn, "raw_dump_shopify", batch) == 2
    assert len(conn.statements) == 1
    assert len(conn.statements[0][1]) == len(batch[0])
    saved = db.execute("SELECT id,raw_payload FROM raw_dump_shopify").fetchall()
    assert len(saved) == 1
    assert saved[0][0] == batch[0]["id"]
    assert json.loads(saved[0][1])["version"] == 2
    # Same ID on another source must remain a separate record.
    await ingest._insert_rows(conn, "raw_dump_shopify", rows([{"id": "same"}], "products"))
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify").fetchone()[0] == 2


async def test_null_keys_and_duplicates_across_batches_preserve_previous_semantics(db):
    conn = LocalConnection(db)
    batch = rows([{"id": "a"}, {"id": "b"}])
    for row in batch:
        row["source_id"] = None
    await ingest._insert_rows(conn, "raw_dump_shopify", batch)
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify WHERE source_id IS NULL").fetchone()[0] == 2
    await ingest._insert_rows(conn, "raw_dump_shopify", rows([
        {"id": "repeat", "version": 1}, {"id": "repeat", "version": 2},
    ]), chunk_size=1)
    payload = db.execute("SELECT raw_payload FROM raw_dump_shopify WHERE source_id='repeat'").fetchone()[0]
    assert json.loads(payload)["version"] == 2


async def test_large_chunks_respect_driver_parameter_limit(db):
    conn = LocalConnection(db)
    await ingest._insert_rows(conn, "raw_dump_shopify", rows([
        {"id": str(i)} for i in range(3000)
    ]), chunk_size=3000)
    assert len(conn.statements) == 2
    assert all(len(values) <= 32767 for _, values in conn.statements)
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify").fetchone()[0] == 3000


async def run_cli(monkeypatch, db, fetch, *, no_insert=False):
    connections = []

    async def connect(*args, **kwargs):
        assert kwargs["statement_cache_size"] == 0
        conn = LocalConnection(db)
        connections.append(conn)
        return conn

    monkeypatch.setattr("asyncpg.connect", connect)
    monkeypatch.setattr(ingest, "_fetch_shopifyql_table", fetch)
    monkeypatch.setattr(ingest, "_log_fetch_error", lambda _: None)
    result = await ingest._run_and_report(
        [STORE], ["sessions", "inventory"],
        None if no_insert else "postgresql://fixture.invalid/test", "raw_dump_shopify",
        page_size=250, max_pages=None, date_start=date(2026, 10, 15),
        date_end=date(2026, 10, 16), api_version="2026-10", no_insert=no_insert,
    )
    return result, connections


async def test_session_rows_are_committed_before_later_fetch_fails(monkeypatch, db):
    async def fetch(client, store, object_type, start, end):
        if object_type == "inventory":
            saved = db.execute("SELECT raw_payload FROM raw_dump_shopify WHERE object_type='sessions'").fetchone()
            assert json.loads(saved[0])["day"] == "2026-10-16"
            return ingest.FetchResult(store, object_type, error="later source failed")
        assert (start, end) == (date(2026, 10, 15), date(2026, 10, 16))
        return ingest.FetchResult(store, object_type, items=[{"day": "2026-10-16", "sessions": 42}])

    result, connections = await run_cli(monkeypatch, db, fetch)
    assert result == 1
    assert len(connections) == 1
    assert connections[0].closed


async def test_failed_fetch_does_not_save_its_partial_items(monkeypatch, db):
    fetch = AsyncMock(side_effect=lambda client, store, kind, *_: ingest.FetchResult(
        store, kind, items=[{"day": "2026-10-16", "sessions": 1}], error="incomplete response",
    ))
    result, connections = await run_cli(monkeypatch, db, fetch)
    assert result == 1
    assert connections == []
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify").fetchone()[0] == 0


async def test_no_insert_does_not_open_database_connection(monkeypatch, db):
    fetch = AsyncMock(side_effect=lambda client, store, kind, *_: ingest.FetchResult(
        store, kind, items=[{"day": "2026-10-16", "sessions": 1}],
    ))
    result, connections = await run_cli(monkeypatch, db, fetch, no_insert=True)
    assert result == 0
    assert connections == []
    assert db.execute("SELECT COUNT(*) FROM raw_dump_shopify").fetchone()[0] == 0


def test_daily_dashboard_sources_precede_large_secondary_sources():
    types = daily.DEFAULT_SHOPIFY_OBJECT_TYPES.split(",")
    for secondary in ("inventory", "fulfillments"):
        assert types.index("sessions") < types.index(secondary)
        assert types.index("orders") < types.index(secondary)
    assert set(types) == {
        "products", "inventory", "orders", "sales", "sales_daily",
        "customer_analytics", "discounts", "fulfillments", "sessions",
    }
