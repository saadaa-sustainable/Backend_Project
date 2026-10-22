"""Operational evidence, bounded discovery and safe freshness behavior."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.services import assistant_operations as ops


def result(rows=None, scalar=None):
    return SimpleNamespace(mappings=lambda: rows or [], scalar=lambda: scalar)


@pytest.fixture(autouse=True)
def empty_caches():
    for fn in (ops.table_info, ops.data_freshness, ops.refresh_status):
        fn.analytics_cache.entries.clear()


@pytest.mark.parametrize("latest,status,lag,day", [
    (None, "no_data", None, None),
    ("2026-10-16", "current", 0, "2026-10-16"),
    ("2026-10-14", "lagging", 2, "2026-10-14"),
    ("2026-10-18", "future_date", 0, "2026-10-18"),
    ("2026-10-15 20:00:00+00", "current", 0, "2026-10-16"),
])
def test_freshness_uses_completed_ist_days_without_claiming_completeness(latest, status, lag, day):
    data = ops.coverage(latest, date(2026, 10, 17))
    assert data == {"latest_date": day, "expected_through": "2026-10-16", "status": status, "lag_days": lag}


async def test_freshness_skips_heavy_unindexed_and_missing_tables_and_reuses_cache():
    session = SimpleNamespace(execute=AsyncMock(side_effect=[result([
        {"table_name": "insights_daily_by_ad", "column_name": "day", "indexed": True, "estimated_rows": 300000},
        {"table_name": "shopify_orders", "column_name": "created_at", "indexed": False, "estimated_rows": 400000},
    ]), result([{"dataset": "meta_ads", "latest": None}])]))
    data = await ops.data_freshness(ops.FreshnessInput(), session)
    datasets = {r["dataset"]: r for r in data["data"]["datasets"]}
    assert datasets["meta_ads"]["status"] == "no_data"
    assert datasets["meta_ads"]["lag_days"] is None
    assert datasets["shopify_orders"]["status"] == "unknown"
    assert "heavy scan" in datasets["shopify_orders"]["reason"]
    assert datasets["shopify_sales"]["status"] == "unknown"
    assert "unavailable" in datasets["shopify_sales"]["reason"]
    assert "shopify_orders" not in str(session.execute.await_args.args[0])
    assert "complete coverage" in data["data"]["notes"][0]
    other_session = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("Cache hit must not read DB")))
    assert await ops.data_freshness(ops.FreshnessInput(), other_session) == data


async def test_table_list_is_paginated_estimated_and_metadata_only():
    session = SimpleNamespace(execute=AsyncMock(return_value=result([
        {"name": "a", "kind": "table", "estimated_rows": 40},
        {"name": "b", "kind": "view", "estimated_rows": None},
        {"name": "c", "kind": "table", "estimated_rows": 1},
    ])))
    data = (await ops.table_info(ops.TablesInput(limit=2, offset=4), session))["data"]
    assert len(data["tables"]) == 2 and data["has_more"] and data["next_offset"] == 6
    assert data["tables"][1]["estimated_rows"] is None
    assert "not exact" in data["notes"][0]


async def test_table_columns_and_missing_table_are_explicit():
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        result([{"name": "orders", "kind": "table", "estimated_rows": 4}]),
        result([{"name": "id", "type": "bigint", "nullable": False}]), result([]),
    ]))
    data = (await ops.table_info(ops.TablesInput(table="orders"), session))["data"]
    assert data["tables"][0]["columns"] == [{"name": "id", "type": "bigint", "nullable": False}]
    assert not data["tables"][0]["columns_truncated"]
    missing = (await ops.table_info(ops.TablesInput(table="missing"), session))["data"]
    assert missing["tables"] == [] and not missing["has_more"]


@pytest.mark.parametrize("schema,values", [
    (ops.TablesInput, {"table": "orders; DROP TABLE orders"}),
    (ops.TablesInput, {"sql": "select 1"}), (ops.TablesInput, {"limit": 51}),
    (ops.TablesInput, {"offset": -1}), (ops.FreshnessInput, {"dataset": "private_tokens"}),
    (ops.RefreshInput, {"limit": 21}),
])
def test_arbitrary_sql_and_unbounded_requests_rejected(schema, values):
    with pytest.raises(ValidationError):
        schema(**values)


async def test_old_running_record_does_not_claim_live_github_execution(monkeypatch):
    from app.api.routers import ops as router
    scheduler = router.SchedulerStatusResponse(enabled=False, running=False, timezone="Asia/Kolkata", jobs=[])
    monkeypatch.setattr(router, "get_scheduler_status", AsyncMock(return_value=scheduler))
    session = SimpleNamespace(execute=AsyncMock(side_effect=[result(scalar=True), result([{
        "id": 1, "run_started": datetime(2020, 1, 1, tzinfo=timezone.utc), "run_finished": None,
        "duration_s": None, "status": "running", "workflow_run": "123", "n_steps_ok": 2,
        "n_steps_fail": 0, "error_present": False, "steps": [],
    }])]))
    data = (await ops.refresh_status(ops.RefreshInput(), session))["data"]
    assert data["ledger_available"] and data["runs"][0]["status"] == "running"
    assert data["runs"][0]["live_execution_verified"] is False
    assert data["process_scheduler"]["enabled"] is False
    assert "Live GitHub" in data["notes"][1]


def test_workflow_metadata_comes_from_files_not_an_assumed_daily_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "WORKFLOWS", tmp_path)
    (tmp_path / "daily-refresh.yml").write_text('name: Fixture\non:\n  workflow_dispatch:\n  schedule:\n    - cron: "30 1 * * *"\n# - cron: "bad"\n')
    (tmp_path / "shopify-refresh.yml").write_text('name: Manual\non:\n  workflow_dispatch:\n')
    daily, manual = ops.workflow_definitions()
    assert daily["cron_utc"] == ["30 1 * * *"] and daily["manual_dispatch"]
    assert manual["cron_utc"] == [] and manual["manual_dispatch"]
