"""Async PostgreSQL access - SQLAlchemy 2.0 + asyncpg.

Engines are lazily built and cached per DSN (same idiom as
``app/rag/vector_store.py``'s ``get_vector_store(settings)``), not a single
global singleton - the test suite runs against the same server but a
different ``postgres_db`` (see ``tests/conftest.py``), so the cache key has
to be settings-derived rather than process-wide.

Usage::

    from app.core import db

    async def get_connection(settings = Depends(get_settings_dep)):
        async with db.connection(settings) as conn:
            yield conn

There is no app-layer auth: Postgres enforces its own user/password and the
port is bound to ``127.0.0.1`` only (docker-compose.yml).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ..config import Settings
from .logging import get_logger

_log = get_logger("app.db")

_engines: dict[str, AsyncEngine] = {}


def get_engine(settings: Settings) -> AsyncEngine:
    """The pooled engine for ``settings``' DSN, building it on first use."""
    dsn = settings.sqlalchemy_dsn()
    engine = _engines.get(dsn)
    if engine is None:
        engine = create_async_engine(
            dsn,
            pool_size=settings.db_pool_size,          # persistent connections
            max_overflow=settings.db_max_overflow,    # burst capacity above pool_size
            pool_timeout=settings.db_pool_timeout,    # seconds to wait for a free conn
            pool_recycle=settings.db_pool_recycle,    # drop conns older than this (s)
            pool_pre_ping=True,                       # detect dead conns before use
            echo=settings.db_echo,
            connect_args={
                "timeout": 10,                        # connect timeout (s)
                "command_timeout": 30,                # per-statement timeout (s)
                "server_settings": {
                    "application_name": "orchard-api",
                    "jit": "off",                     # OLTP workload: JIT hurts
                },
            },
        )
        _engines[dsn] = engine
        _log.info("db.engine.created", dsn_host=settings.postgres_host, db=settings.postgres_db)
    return engine


@asynccontextmanager
async def connection(settings: Settings) -> AsyncIterator[AsyncConnection]:
    """A unit-of-work connection: commits on clean exit, rolls back on exception."""
    async with get_engine(settings).begin() as conn:
        yield conn


# Additive, idempotent DDL applied on startup so an existing Postgres volume
# picks up columns added after its init.sql first ran (there is no migration
# tool; a full schema change still needs `docker compose down -v`). This is the
# Postgres equivalent of the old sqlite `_backfill_columns`.
_STARTUP_DDL: tuple[str, ...] = (
    "ALTER TABLE tree_sources ADD COLUMN IF NOT EXISTS priority_order INT NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_tree_sources_priority ON tree_sources (tree_id, priority_order)",
)


async def apply_startup_ddl(settings: Settings) -> None:
    async with get_engine(settings).begin() as conn:
        for stmt in _STARTUP_DDL:
            await conn.execute(text(stmt))
    _log.info("db.startup_ddl.applied", statements=len(_STARTUP_DDL))


async def healthcheck(settings: Settings) -> bool:
    """``SELECT 1`` against the pool - for the app's ``/health`` endpoint."""
    try:
        async with get_engine(settings).connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - report, don't propagate
        _log.warning("db.healthcheck.failed", error=str(exc))
        return False


async def dispose_all() -> None:
    """Close every pooled connection across every cached engine."""
    for dsn, engine in list(_engines.items()):
        await engine.dispose()
        del _engines[dsn]
    _log.info("db.disposed")
