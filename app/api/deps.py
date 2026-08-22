"""FastAPI dependency providers.

Every route depends on these rather than constructing sessions/clients
inline, so tests can override them (``app.dependency_overrides``) with
fakes/mocks without touching route code.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.services.meta.client import MetaAPIClient
from app.services.meta.orchestrator import MultiAccountSyncCoordinator


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


async def get_meta_client() -> AsyncGenerator[MetaAPIClient, None]:
    """A single-account client (defaults to the first configured account) —
    used only where "which account" genuinely doesn't matter, like the
    `/health` connectivity check. Sync routes use `CoordinatorDep` instead,
    which fans out across every configured account by default."""
    async with MetaAPIClient() as client:
        yield client


SessionDep = Annotated[AsyncSession, Depends(get_session)]
MetaClientDep = Annotated[MetaAPIClient, Depends(get_meta_client)]


async def get_coordinator() -> MultiAccountSyncCoordinator:
    """No session dependency here on purpose: :class:`MultiAccountSyncCoordinator`
    processes accounts concurrently and gives each its own DB session
    internally (a shared ``AsyncSession`` isn't safe across concurrent
    coroutines) — see its class docstring."""
    return MultiAccountSyncCoordinator()


CoordinatorDep = Annotated[MultiAccountSyncCoordinator, Depends(get_coordinator)]
