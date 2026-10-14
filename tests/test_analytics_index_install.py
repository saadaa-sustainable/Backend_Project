"""Index deployment reuses existing definitions and stops on failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import optimize_analytics_indexes as installer


def existing(index, **overrides):
    return dict(name="existing_other_name", valid=True, ready=True, unrestricted=True,
                method="btree", keys=list(index.keys), included=list(index.include), **overrides)


@pytest.mark.parametrize("change", [None, 'valid', 'ready', 'unrestricted', 'method', 'keys', 'included'])
def test_equivalent_indexes_cover_keys_and_payload(change):
    spec = installer.INDEXES[1]
    row = existing(spec)
    if change in ('valid', 'ready', 'unrestricted'):
        row[change] = False
    elif change == 'method':
        row[change] = 'hash'
    elif change in ('keys', 'included'):
        row[change] = []
    assert installer.covers(row, spec) is (change is None)


def result(rows):
    return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


async def test_existing_equivalent_name_avoids_duplicate_indexes(monkeypatch):
    spec = installer.INDEXES[0]
    monkeypatch.setattr(installer, 'INDEXES', (spec,))
    conn = SimpleNamespace(execute=AsyncMock(return_value=result([existing(spec)])))
    await installer.apply_indexes(conn)
    conn.execute.assert_awaited_once()


async def test_missing_index_builds_concurrently_and_verifies(monkeypatch):
    spec = installer.INDEXES[0]
    monkeypatch.setattr(installer, 'INDEXES', (spec,))
    conn = SimpleNamespace(execute=AsyncMock(side_effect=[result([]), None, result([existing(spec)])]))
    await installer.apply_indexes(conn)
    assert str(conn.execute.call_args_list[1].args[0]) == spec.ddl
    assert spec.ddl.startswith('CREATE INDEX CONCURRENTLY')
    assert conn.execute.await_count == 3


@pytest.mark.parametrize('at_build', [False, True])
async def test_failure_stops_without_retry_or_next_index(at_build):
    failure = RuntimeError('database unavailable')
    responses = [result([]), failure] if at_build else [failure]
    conn = SimpleNamespace(execute=AsyncMock(side_effect=responses))
    with pytest.raises(RuntimeError, match='database unavailable'):
        await installer.apply_indexes(conn)
    assert conn.execute.await_count == len(responses)


async def test_invalid_same_name_is_not_silently_skipped_or_dropped():
    spec = installer.INDEXES[0]
    row = existing(spec)
    row.update(name=spec.name, valid=False)
    conn = SimpleNamespace(execute=AsyncMock(return_value=result([row])))
    with pytest.raises(RuntimeError, match='invalid or has a different definition'):
        await installer.apply_indexes(conn)
    conn.execute.assert_awaited_once()
