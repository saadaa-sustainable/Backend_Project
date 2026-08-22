"""Schema Browser's "Flatten" feature — surfaces every registered
Bronze -> Silver flatten job, lets the admin trigger one manually, and
lets them switch its automatic (scheduled-poll-driven) refresh on/off.
See app/services/silver/registry.py for what's registered and
app/services/silver/runner.py for the staleness check + run logic.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.session import session_scope
from app.services.silver.registry import FLATTEN_REGISTRY, jobs_for_table
from app.services.silver.runner import JobState, check_and_maybe_run, get_job_state, set_auto_enabled

router = APIRouter(prefix="/admin/flatten", tags=["flatten"])


class FlattenJobOut(BaseModel):
    key: str
    label: str
    source_table: str
    target_tables: list[str]
    auto_enabled: bool
    is_stale: bool
    source_max_extracted_at: datetime | None
    last_run_status: str | None
    last_run_at: datetime | None
    last_run_triggered_by: str | None
    last_rows_written: dict[str, int] | None
    last_error: str | None


class SetAutoRequest(BaseModel):
    enabled: bool


def _to_out(state: JobState) -> FlattenJobOut:
    return FlattenJobOut(
        key=state.job.key,
        label=state.job.label,
        source_table=state.job.source_table,
        target_tables=list(state.job.target_tables),
        auto_enabled=state.auto_enabled,
        is_stale=state.is_stale,
        source_max_extracted_at=state.source_max_extracted_at,
        last_run_status=state.last_run_status,
        last_run_at=state.last_run_at,
        last_run_triggered_by=state.last_run_triggered_by,
        last_rows_written=state.last_rows_written,
        last_error=state.last_error,
    )


@router.get("/jobs", response_model=list[FlattenJobOut])
async def list_flatten_jobs() -> list[FlattenJobOut]:
    async with session_scope() as session:
        return [_to_out(await get_job_state(session, job)) for job in FLATTEN_REGISTRY.values()]


@router.get("/jobs/for-table/{table_name}", response_model=list[FlattenJobOut])
async def flatten_job_for_table(table_name: str) -> list[FlattenJobOut]:
    """Used by the Schema Browser to decide which Flatten panel(s) to show for
    whatever table is currently open -- empty list if no job is registered for
    this table (as either its source or one of its targets). A source table
    can back more than one job (e.g. raw_dump_meta backs both meta_entities
    and meta_insights), so this can return multiple."""
    jobs = jobs_for_table(table_name)
    async with session_scope() as session:
        return [_to_out(await get_job_state(session, job)) for job in jobs]


@router.post("/jobs/{job_key}/run", response_model=FlattenJobOut)
async def run_flatten_job(job_key: str) -> FlattenJobOut:
    job = FLATTEN_REGISTRY.get(job_key)
    if job is None:
        raise HTTPException(404, f"No flatten job registered with key '{job_key}'.")
    async with session_scope() as session:
        try:
            state = await check_and_maybe_run(session, job, force=True, triggered_by="manual")
        except Exception as exc:  # noqa: BLE001 -- surfaced to the admin panel as a clear error
            raise HTTPException(500, f"Flatten failed: {exc}") from exc
        return _to_out(state)


@router.put("/jobs/{job_key}/auto", response_model=FlattenJobOut)
async def set_flatten_auto(job_key: str, body: SetAutoRequest) -> FlattenJobOut:
    job = FLATTEN_REGISTRY.get(job_key)
    if job is None:
        raise HTTPException(404, f"No flatten job registered with key '{job_key}'.")
    async with session_scope() as session:
        await set_auto_enabled(session, job_key, body.enabled)
        state = await get_job_state(session, job)
        return _to_out(state)
