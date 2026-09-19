"""Keep legacy lifetime timing intact when refreshing an existing mirror."""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sync_module(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/sync_ad_metrics_external.py"
    spec = importlib.util.spec_from_file_location("ad_timing_sync_under_test", path)
    module = importlib.util.module_from_spec(spec)
    # Script imports must not load the developer's real database credentials.
    with patch("dotenv.load_dotenv"):
        spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SOURCE_DSN", "fake-source")
    monkeypatch.setattr(module, "TARGET_DSN", "fake-target")
    monkeypatch.setattr(module.psycopg2, "connect", MagicMock())
    return module


def test_lifetime_timing_columns_use_dates_and_integer_day_counts(sync_module):
    expected = {
        "first_seen_date": "date",
        "impressions_50k_date": "date",
        "date_of_result": "date",
        "days_to_result": "integer",
        "days_to_50k": "integer",
    }
    for column, sql_type in expected.items():
        assert re.search(rf"\b{column} {sql_type}\b", sync_module.DDL)
    assert sync_module._COLUMN_MAP["date_target_imp_achieved"] == "impressions_50k_date"
    assert sync_module._COLUMN_MAP["days_to_target_f1"] == "days_to_50k"


def test_existing_mirror_is_extended_before_exact_timing_values_are_written(
    sync_module, monkeypatch,
):
    source_records = [
        {
            "ad_id": "crossed-late",
            "ad_created": date(2025, 1, 1),
            "amount_spent": 123.45,
            "first_seen_date": date(2025, 1, 9),
            "date_target_imp_achieved": date(2025, 2, 18),
            "date_of_result": date(2025, 2, 18),
            "days_to_result": 40,
            "days_to_target_f1": 40,
        },
        {
            "ad_id": "created-fallback",
            "ad_created": date(2026, 9, 19),
            "date_of_result": date(2026, 10, 3),
        },
    ]
    source = MagicMock()
    source_cursor = source.cursor.return_value.__enter__.return_value

    def source_execute(query):
        columns = query.removeprefix("SELECT ").split(" FROM ", 1)[0].split(", ")
        source_cursor.fetchall.return_value = [
            tuple(record.get(column) for column in columns) for record in source_records
        ]

    source_cursor.execute.side_effect = source_execute
    target = MagicMock()
    target_cursor = target.cursor.return_value.__enter__.return_value
    target_cursor.fetchone.return_value = (len(source_records),)
    sync_module.psycopg2.connect.side_effect = [source, target]
    monkeypatch.setattr(sync_module.sys, "argv", ["sync_ad_metrics_external.py", "--skip-daily"])

    # Model an installation that already has the mirror's original schema.
    new_columns = {"first_seen_date", "date_of_result", "days_to_result"}
    existing_columns = set(sync_module.TARGET_COLUMNS) - new_columns | {"synced_at"}
    added_columns = {}
    operations = []

    def target_execute(query):
        operations.append(query)
        match = re.fullmatch(
            r"ALTER TABLE public.ad_metrics_external "
            r"ADD COLUMN IF NOT EXISTS (\w+) (\w+)", query,
        )
        if match:
            column, sql_type = match.groups()
            existing_columns.add(column)
            added_columns[column] = sql_type

    target_cursor.execute.side_effect = target_execute
    mirrored_rows = []

    def insert_values(cursor, query, payload, *, page_size):
        assert cursor is target_cursor
        columns = query.split("(", 1)[1].split(")", 1)[0].split(", ")
        assert set(columns) <= existing_columns, "New fields must be added before INSERT"
        assert operations[-1] == "TRUNCATE public.ad_metrics_external"
        mirrored_rows.extend(dict(zip(columns, row, strict=True)) for row in payload)

    monkeypatch.setattr(sync_module, "execute_values", insert_values)

    assert sync_module.main() == 0
    assert added_columns == {
        "first_seen_date": "date", "date_of_result": "date", "days_to_result": "integer",
    }
    crossed, fallback = mirrored_rows
    assert crossed["first_seen_date"] == date(2025, 1, 9)
    assert crossed["impressions_50k_date"] == crossed["date_of_result"] == date(2025, 2, 18)
    assert crossed["days_to_50k"] == crossed["days_to_result"] == 40
    assert crossed["spend"] == 123.45
    assert fallback["date_of_result"] == date(2026, 10, 3)
    assert fallback["first_seen_date"] is None
    assert fallback["impressions_50k_date"] is None
    assert fallback["days_to_50k"] is None
    assert fallback["days_to_result"] is None
    assert crossed["synced_at"] == fallback["synced_at"]
    source.close.assert_called_once()
    target.close.assert_called_once()
    target.__enter__.assert_called_once()  # Migration and refresh share one transaction.
    assert sync_module.psycopg2.connect.call_count == 2  # --skip-daily stays respected.


@pytest.mark.parametrize("dry_run", [False, True])
def test_empty_source_or_dry_run_never_changes_target_schema(sync_module, monkeypatch, dry_run):
    source = MagicMock()
    cursor = source.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    sync_module.psycopg2.connect.return_value = source
    argv = ["sync_ad_metrics_external.py", "--skip-daily"]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(sync_module.sys, "argv", argv)
    write = MagicMock()
    monkeypatch.setattr(sync_module, "execute_values", write)

    assert sync_module.main() == (0 if dry_run else 1)
    sync_module.psycopg2.connect.assert_called_once_with("fake-source")
    write.assert_not_called()


@pytest.fixture
def backfill_module():
    path = Path(__file__).resolve().parents[1] / "scripts/backfill_ad_result_timing.py"
    spec = importlib.util.spec_from_file_location("ad_timing_backfill_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_source_file_cannot_override_target_or_environment(
    backfill_module, monkeypatch, tmp_path,
):
    project_env = tmp_path / "project.env"
    project_env.write_text("DATABASE_URL_SYNC=postgresql+psycopg2://target\n")
    source_env = tmp_path / "source.env"
    source_env.write_text(
        "SUPABASE_DB_URL=postgresql://source\n"
        "DATABASE_URL_SYNC=postgresql://wrong-target\n"
        "TIMING_TEST_SENTINEL=changed\n"
    )
    monkeypatch.setattr(backfill_module, "PROJECT_ENV", project_env)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TIMING_TEST_SENTINEL", "original")

    assert backfill_module._connections(source_env) == (
        "postgresql://source", "postgresql://target",
    )
    assert backfill_module.os.environ["TIMING_TEST_SENTINEL"] == "original"


@pytest.mark.parametrize("apply", [False, True])
def test_backfill_uses_readonly_source_and_one_target_transaction(
    backfill_module, monkeypatch, apply,
):
    source, target = MagicMock(), MagicMock()
    rows = [("ad", date(2025, 1, 9), date(2025, 2, 18), 40, date(2025, 2, 18), 40)]
    source.cursor.return_value.__enter__.return_value.fetchall.return_value = rows
    target.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
    connect = MagicMock(side_effect=[source, target])
    monkeypatch.setattr(backfill_module, "_connect", connect)
    update = MagicMock(return_value=1)
    monkeypatch.setattr(backfill_module, "_update_rows", update)

    assert backfill_module._run("source", "target", apply=apply, deadline=123) == 0
    assert connect.call_args_list[0].kwargs == {"readonly": True}
    assert connect.call_args_list[1].kwargs == {"readonly": not apply}
    if apply:
        update.assert_called_once_with(
            target.cursor.return_value.__enter__.return_value, rows, 123,
        )
    else:
        update.assert_not_called()
    target.__enter__.assert_called_once()
    source.close.assert_called_once()
    target.close.assert_called_once()


def test_backfill_batches_only_timing_updates_and_preserves_exact_nulls(
    backfill_module, monkeypatch,
):
    pglast = pytest.importorskip("pglast")
    from pglast import ast

    cursor = MagicMock()
    # All-null dates must remain valid through explicitly typed VALUES.
    rows = [(str(index), None, None, None, None, None) for index in range(501)]
    batches = []

    def execute_values(cursor_arg, query, values, *, template, page_size, fetch):
        assert cursor_arg is cursor
        assert template == "(%s::text, %s::date, %s::date, %s::integer, %s::date, %s::integer)"
        assert page_size == 500 and fetch
        batches.append(values)
        return [(row[0],) for row in values]

    monkeypatch.setattr(backfill_module, "execute_values", execute_values)
    assert backfill_module._update_rows(cursor, rows, time.monotonic() + 45) == 501
    assert [len(batch) for batch in batches] == [500, 1]
    assert batches[0] + batches[1] == rows

    query = backfill_module.UPDATE_SQL.replace(
        "%s", "('ad'::text, NULL::date, NULL::date, NULL::integer, NULL::date, NULL::integer)",
    )
    statements = pglast.parse_sql(query)
    assert len(statements) == 1
    statement = statements[0].stmt
    assert isinstance(statement, ast.UpdateStmt)
    assert statement.relation.relname == "ad_metrics_external"
    assert {column.name for column in statement.targetList} == {
        "first_seen_date", "impressions_50k_date", "days_to_50k",
        "date_of_result", "days_to_result",
    }
    assert "target.ad_id = incoming.ad_id" in query
    assert "IS DISTINCT FROM" in query


def test_backfill_empty_source_never_opens_target(backfill_module, monkeypatch):
    source = MagicMock()
    source.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    connect = MagicMock(return_value=source)
    monkeypatch.setattr(backfill_module, "_connect", connect)

    with pytest.raises(ValueError, match="Source returned no ads"):
        backfill_module._run("source", "target", apply=True, deadline=123)
    connect.assert_called_once_with("source", readonly=True)


def test_backfill_connection_failure_stops_without_retry_or_credentials(
    backfill_module, monkeypatch, capsys,
):
    monkeypatch.setattr(backfill_module.sys, "argv", ["backfill_ad_result_timing.py", "--apply"])
    monkeypatch.setattr(backfill_module, "_connections", lambda _path: ("source", "target"))
    connect = MagicMock(side_effect=backfill_module.psycopg2.OperationalError("secret-password"))
    monkeypatch.setattr(backfill_module, "_connect", connect)

    assert backfill_module.main() == 1
    connect.assert_called_once_with("source", readonly=True)
    output = capsys.readouterr()
    assert "OperationalError" in output.err
    assert "No retries" in output.err
    assert "secret-password" not in output.err + output.out


def test_backfill_expired_budget_cannot_start_another_batch(backfill_module, monkeypatch):
    write = MagicMock()
    monkeypatch.setattr(backfill_module, "execute_values", write)
    cursor = MagicMock()

    with pytest.raises(TimeoutError):
        backfill_module._update_rows(cursor, [("ad", None, None, None, None, None)], 0)
    write.assert_not_called()
    cursor.execute.assert_not_called()
