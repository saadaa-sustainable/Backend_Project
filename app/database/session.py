"""Async engine / session management.

A single process-wide engine is created lazily and reused for the lifetime
of the application, backed by SQLAlchemy's async connection pool. FastAPI
route handlers obtain a session through :func:`get_db_session`, while
background/scheduler code uses :func:`session_scope` for an explicit
commit/rollback context.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database.database_url,
            echo=settings.database.echo,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout_seconds,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory (cached)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    Commits on a clean request, rolls back if the route raised — mirrors
    :func:`session_scope`'s semantics so writes made through this
    dependency actually persist instead of being silently dropped when the
    session closes uncommitted.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for scheduler / service code outside the request cycle.

    Commits on clean exit, rolls back on exception, always closes the
    session.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool (call on app shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
