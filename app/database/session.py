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
    """Return the process-wide async engine, creating it on first use.

    ``connect_args={"statement_cache_size": 0}`` is essential when
    DATABASE_URL points at Supabase's *transaction-mode* pooler (port
    6543). In that mode pgbouncer swaps the actual Postgres backend
    connection between transactions -- so any prepared statement
    asyncpg cached against the previous connection is invalid on the
    next one, producing errors like
    ``prepared statement "__asyncpg_stmt_N__" does not exist``.
    Disabling the client-side cache forces every SQL to be sent as a
    fresh unprepared query, which is what pgbouncer expects.

    Session-mode (port 5432) can safely leave the cache on but has a
    much lower client cap; setting cache_size=0 there is a minor
    perf loss (~sub-ms per query) but avoids branching on URL shape.
    Keeping it off unconditionally is the safer default.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        # 2026-09-15: NullPool is off. The historic reason was
        # pgbouncer-transaction-mode DuplicatePreparedStatementError --
        # asyncpg's default __asyncpg_stmt_N__ counter would collide
        # with a name pgbouncer's rotated backend still remembered.
        # `prepared_statement_name_func` (below) UUIDs every statement
        # name so a real pool is safe: collisions are impossible
        # regardless of how connections are recycled.
        #
        # Why this matters for perf: with NullPool, every HTTP request
        # opened a fresh asyncpg connection, and the TLS + auth
        # handshake to Supabase dominated cold latency (~135s on Render
        # for /ads-analyse, which blows through the 120s HTTP gateway
        # timeout). A modest pool (5 core + 10 overflow) hands out a
        # warm connection in ~1ms, and pool_pre_ping cheaply rejects
        # any connection pgbouncer has since recycled.
        import uuid as _uuid
        _engine = create_async_engine(
            settings.database.database_url,
            echo=settings.database.echo,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
            connect_args={
                "statement_cache_size": 0,
                "prepared_statement_name_func": lambda: f"__ctd_{_uuid.uuid4().hex[:12]}__",
            },
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
