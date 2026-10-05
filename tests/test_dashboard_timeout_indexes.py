"""Query-plan regressions and interrupted maintenance behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg2
import pytest

from scripts.apply_dashboard_timeout_indexes import build_indexes


def test_valid_indexes_are_not_rebuilt():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [(True, "shopify_order_attribution"), (True, "raw_dump_meta")]
    build_indexes(conn)
    assert conn.autocommit is True
    assert not any("CREATE INDEX" in str(c.args[0]) for c in cur.execute.call_args_list)


def test_invalid_index_is_rebuilt_and_first_failure_stops_the_process():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (False, "shopify_order_attribution")

    def execute(statement, *args):
        if "CREATE INDEX CONCURRENTLY" in str(statement):
            raise psycopg2.errors.LockNotAvailable("lock timeout")

    cur.execute.side_effect = execute
    with pytest.raises(psycopg2.errors.LockNotAvailable):
        build_indexes(conn)
    statements = [str(c.args[0]) for c in cur.execute.call_args_list]
    assert any("DROP INDEX CONCURRENTLY" in s for s in statements)
    assert sum("CREATE INDEX CONCURRENTLY" in s for s in statements) == 1
    assert not any("ix_raw_dump_meta_extracted_at" in str(c) for c in cur.execute.call_args_list)


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


def test_postgres_uses_indexes_and_keeps_null_dates_last():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL plan tests")
    conn = psycopg2.connect(dsn, connect_timeout=12)
    schema = "dashboard_index_test_" + uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '20s'")
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET LOCAL search_path = "{schema}", pg_catalog')
            cur.execute("CREATE TABLE raw_dump_meta (extracted_at timestamptz)")
            cur.execute("CREATE TABLE shopify_order_attribution (order_id int, created_at timestamptz)")
            cur.execute("INSERT INTO raw_dump_meta SELECT '2026-01-01'::timestamptz + n * interval '1 minute' FROM generate_series(1,10000) n")
            cur.execute("INSERT INTO shopify_order_attribution SELECT n, CASE WHEN n % 100 = 0 THEN NULL ELSE '2026-01-01'::timestamptz + n * interval '1 minute' END FROM generate_series(1,10000) n")
            path = Path(__file__).parents[1] / "supabase/migrations/20261005125000_dashboard_timeout_indexes.sql"
            migration = path.read_text().replace("public.", f'"{schema}".')
            cur.execute(migration)
            cur.execute(migration)  # Recording an already-built migration is safe.
            cur.execute("ANALYZE raw_dump_meta")
            cur.execute("ANALYZE shopify_order_attribution")
            for query, expected_index in (
                ("SELECT MAX(extracted_at) FROM raw_dump_meta", "ix_raw_dump_meta_extracted_at"),
                ("SELECT order_id, created_at FROM shopify_order_attribution ORDER BY created_at DESC NULLS LAST LIMIT 100", "ix_soa_created_desc_nulls_last"),
            ):
                cur.execute("EXPLAIN (FORMAT JSON) " + query)
                nodes = list(_nodes(cur.fetchone()[0][0]["Plan"]))
                assert any(n.get("Index Name") == expected_index for n in nodes)
                assert not any(n["Node Type"] in ("Seq Scan", "Sort") for n in nodes)
            cur.execute("SELECT order_id FROM shopify_order_attribution ORDER BY created_at DESC NULLS LAST LIMIT 3")
            assert cur.fetchall() == [(9999,), (9998,), (9997,)]
            cur.execute("SELECT created_at FROM shopify_order_attribution ORDER BY created_at DESC NULLS LAST OFFSET 9900")
            assert cur.fetchall() == [(None,)] * 100
    finally:
        conn.rollback()
        conn.close()
