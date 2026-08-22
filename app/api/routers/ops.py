"""Admin-panel "Cron / Sync Status" and "Error Logs" sections.

Two genuinely different error/status sources exist in this codebase and
neither had an HTTP route before this file:

* Meta syncs are DB-backed (``sync_batches``/``failed_jobs``, see
  ``status.py``/``failed_jobs.py`` for the existing read routes this
  router deliberately does NOT duplicate) and the scheduler
  (``app/scheduler/scheduler.py``) is a real, running ``AsyncIOScheduler``
  singleton -- ``GET /admin/scheduler`` below is the first thing to ever
  introspect it over HTTP.
* Shopify/Instagram ingestion (``scripts/ingest_shopify.py``/
  ``scripts/ingest_instagram.py``) are standalone scripts with no DB
  access at all -- their errors only ever land in flat
  ``logs/{shopify,instagram}_ingest_errors.log`` files. ``GET
  /admin/errors/files`` parses those.  ``source`` is a fixed ``Literal``,
  never a client-supplied path, so there's no path-traversal surface.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import get_settings
from app.scheduler.scheduler import get_scheduler

router = APIRouter(prefix="/admin", tags=["admin", "ops"])

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ERROR_LOG_FILES: dict[str, Path] = {
    "shopify": _REPO_ROOT / "logs" / "shopify_ingest_errors.log",
    "instagram": _REPO_ROOT / "logs" / "instagram_ingest_errors.log",
}

# Matches the "=== <timestamp> | <label> | object_type=<x> ===\n<body>" block
# format both ingest_shopify.py and ingest_instagram.py write on every error.
_LOG_BLOCK_RE = re.compile(
    r"^=== (?P<timestamp>\S+) \| (?P<label>.+?) \| object_type=(?P<object_type>\S+) ===\n"
    r"(?P<body>.*?)(?=\n=== |\Z)",
    re.MULTILINE | re.DOTALL,
)


class SchedulerJobOut(BaseModel):
    id: str
    name: str
    trigger: str
    next_run_time: datetime | None


class SchedulerStatusResponse(BaseModel):
    enabled: bool
    running: bool
    timezone: str
    jobs: list[SchedulerJobOut]


@router.get("/scheduler", response_model=SchedulerStatusResponse)
async def get_scheduler_status() -> SchedulerStatusResponse:
    settings = get_settings().scheduler
    scheduler = get_scheduler()
    jobs = [
        SchedulerJobOut(
            id=job.id, name=job.name, trigger=str(job.trigger), next_run_time=job.next_run_time
        )
        for job in sorted(scheduler.get_jobs(), key=lambda j: j.id)
    ]
    return SchedulerStatusResponse(
        enabled=settings.enabled, running=scheduler.running, timezone=settings.timezone, jobs=jobs
    )


class FileErrorEntry(BaseModel):
    timestamp: str
    label: str
    object_type: str
    message: str


class FileErrorsResponse(BaseModel):
    source: str
    total: int
    errors: list[FileErrorEntry]


@router.get("/errors/files", response_model=FileErrorsResponse)
async def get_file_errors(
    source: Literal["shopify", "instagram"],
    limit: int = Query(default=50, ge=1, le=500),
) -> FileErrorsResponse:
    path = _ERROR_LOG_FILES[source]
    if not path.exists():
        return FileErrorsResponse(source=source, total=0, errors=[])

    content = path.read_text(encoding="utf-8", errors="replace")
    entries: list[FileErrorEntry] = []
    for m in _LOG_BLOCK_RE.finditer(content):
        body = m.group("body").strip()
        message = body.removeprefix("Error: ")
        entries.append(
            FileErrorEntry(
                timestamp=m.group("timestamp"),
                label=m.group("label").strip(),
                object_type=m.group("object_type"),
                message=message,
            )
        )

    entries.reverse()  # the file is append-only oldest-first; newest-first is more useful here
    return FileErrorsResponse(source=source, total=len(entries), errors=entries[:limit])
