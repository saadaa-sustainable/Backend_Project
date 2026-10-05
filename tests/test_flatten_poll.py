"""Background refreshes must leave disabled data sources alone."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.silver import runner


@pytest.fixture
def poll(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock(), rollback=AsyncMock())
    ensure = AsyncMock()
    check = AsyncMock()
    monkeypatch.setattr(runner, "ensure_flatten_tables", ensure)
    monkeypatch.setattr(runner, "check_and_maybe_run", check)
    monkeypatch.setattr(runner, "FLATTEN_REGISTRY", {
        key: SimpleNamespace(key=key) for key in ("meta_entities", "meta_insights", "shopify_data")
    })
    result = MagicMock()
    session.execute.return_value = result
    return session, result, check


async def test_disabled_poller_never_reads_bronze_or_checks_staleness(poll):
    session, result, check = poll
    result.scalars.return_value.all.return_value = []
    await runner.run_auto_enabled_jobs(session)
    check.assert_not_awaited()
    session.execute.assert_awaited_once()
    assert "FROM flatten_settings WHERE auto_enabled = true" in str(session.execute.call_args.args[0])


async def test_only_enabled_known_jobs_are_considered(poll):
    session, result, check = poll
    result.scalars.return_value.all.return_value = ["meta_insights", "removed_job"]
    await runner.run_auto_enabled_jobs(session)
    check.assert_awaited_once_with(
        session, runner.FLATTEN_REGISTRY["meta_insights"], force=False, triggered_by="auto_poll"
    )


async def test_state_timeout_rolls_back_before_the_next_enabled_job(poll):
    session, result, check = poll
    result.scalars.return_value.all.return_value = ["meta_entities", "shopify_data"]

    async def execute_job(session, job, **kwargs):
        if job.key == "meta_entities":
            raise RuntimeError("canceling statement due to statement timeout")
        session.rollback.assert_awaited_once()

    check.side_effect = execute_job
    await runner.run_auto_enabled_jobs(session)
    assert check.await_count == 2
    session.rollback.assert_awaited_once()
