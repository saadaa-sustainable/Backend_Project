"""Exercise summary replacement and the production silver refresh boundary."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import dashboard_sessions as summary
from app.services.silver import shopify_flatten as silver


@pytest.fixture
def database():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE shopify_sessions(day TEXT, sessions NUMERIC, utm_source TEXT)"
    )
    # Sources chosen to exercise the Meta rule, not just to fill a column:
    # 'META' and ' ig ' must match (prefix, and the trim), 'kwikengage'
    # must not, and the NULL source must not. So day 1 is 200 sessions of
    # which 50 are Meta.
    connection.executemany("INSERT INTO shopify_sessions VALUES (?, ?, ?)", [
        ("2026-01-01", 50, "META"), ("2026-01-01", 150, "kwikengage"),
        ("2026-01-02", 0, " ig "), ("2026-01-03", None, "META"),
        (None, 500, "META"),
    ])
    connection.commit()

    async def execute(query):
        sql = str(query)
        if sql.startswith(("LOCK ", "SELECT pg_advisory", "ALTER ", "REVOKE ", "ANALYZE ")):
            return None
        # btrim is Postgres' spelling of SQL-standard trim; sqlite has
        # trim() with the same semantics for the no-argument form.
        return connection.execute(sql.replace("public.", "").replace("btrim(", "trim("))

    async def scalar(query):
        assert str(query) == summary._EXISTS
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='shopify_sessions_daily'"
        ).fetchone() is not None

    session = SimpleNamespace(execute=AsyncMock(side_effect=execute), scalar=AsyncMock(side_effect=scalar))
    yield connection, session
    connection.close()


def test_postgresql_summary_sql_parses():
    parse_sql = pytest.importorskip("pglast").parse_sql
    for query in (summary._EXISTS, summary._CREATE, summary._ADD_META_COLUMN,
                  summary._INSERT):
        parse_sql(query)


async def test_bootstrap_then_unchanged_source_does_no_scan(database):
    db, session = database
    assert await summary.refresh_dashboard_sessions(session, only_if_missing=True)
    db.commit()
    assert db.execute(
        "SELECT day,sessions,meta_sessions FROM shopify_sessions_daily ORDER BY day"
    ).fetchall() == [
        # 200 sessions on day 1, but only the 50 from utm_source=META
        # count as Meta -- kwikengage is WhatsApp tooling, not Meta.
        ("2026-01-01", 200, 50), ("2026-01-02", 0, 0),
    ]
    session.execute.reset_mock()
    assert not await summary.refresh_dashboard_sessions(session, only_if_missing=True)
    session.execute.assert_not_awaited()


async def test_replacement_updates_corrected_days_and_removes_deleted_days(database):
    db, session = database
    await summary.refresh_dashboard_sessions(session)
    db.commit()
    db.execute("DELETE FROM shopify_sessions")
    db.execute("INSERT INTO shopify_sessions VALUES ('2026-01-01', 17, 'facebook')")
    await summary.refresh_dashboard_sessions(session)
    db.commit()
    assert db.execute(
        "SELECT day,sessions,meta_sessions FROM shopify_sessions_daily"
    ).fetchall() == [("2026-01-01", 17, 17)]
    await summary.refresh_dashboard_sessions(session)
    assert db.execute("SELECT SUM(sessions) FROM shopify_sessions_daily").fetchone()[0] == 17


async def test_failed_replacement_preserves_committed_summary(database):
    db, session = database
    await summary.refresh_dashboard_sessions(session)
    db.commit()
    original_execute = session.execute.side_effect

    async def fail_insert(query):
        if str(query) == summary._INSERT:
            raise RuntimeError("aggregation failed")
        return await original_execute(query)

    session.execute.side_effect = fail_insert
    with pytest.raises(RuntimeError, match="aggregation failed"):
        await summary.refresh_dashboard_sessions(session)
    db.rollback()
    assert db.execute("SELECT SUM(sessions) FROM shopify_sessions_daily").fetchone()[0] == 200


@pytest.mark.parametrize("rebuild,missing", [(True, False), (False, True), (False, False)])
async def test_silver_refresh_maintains_summary_before_commit(monkeypatch, rebuild, missing):
    events = []
    entry = next(e for e in silver._TABLES if e.table == "shopify_sessions")
    monkeypatch.setattr(silver, "_TABLES", [entry])
    monkeypatch.setattr(silver, "ensure_shopify_tables", AsyncMock())
    monkeypatch.setattr(silver, "_watermarks", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(silver, "_needs_rebuild", lambda *_: (rebuild, "test"))

    async def refresh(session, *, only_if_missing=False):
        events.append("bootstrap" if only_if_missing else "summary")
        return rebuild or missing

    async def execute(query):
        if str(query) == entry.insert_sql:
            events.append("source")
        return SimpleNamespace(scalar_one=lambda: 2)

    async def commit():
        events.append("commit")

    monkeypatch.setattr(silver, "refresh_dashboard_sessions", refresh)
    session = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock(side_effect=commit))
    await silver.refresh_shopify_tables(session)
    assert events == (["source", "summary", "commit"] if rebuild else
                      ["bootstrap", "commit"] if missing else ["bootstrap"])


async def test_summary_failure_prevents_silver_commit(monkeypatch):
    entry = next(e for e in silver._TABLES if e.table == "shopify_sessions")
    monkeypatch.setattr(silver, "_TABLES", [entry])
    monkeypatch.setattr(silver, "ensure_shopify_tables", AsyncMock())
    monkeypatch.setattr(silver, "refresh_dashboard_sessions", AsyncMock(side_effect=RuntimeError("summary failed")))
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    with pytest.raises(RuntimeError, match="summary failed"):
        await silver.refresh_shopify_tables(session, force=True)
    session.commit.assert_not_awaited()
