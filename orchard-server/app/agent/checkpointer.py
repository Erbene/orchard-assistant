"""LangGraph Postgres checkpointer for the Foreman's multi-turn sessions.

A paused negotiation (waiting on the time or resource interrupt) is persisted
to the ``checkpoints*`` tables in the same Postgres, keyed by ``thread_id``,
so it survives a backend restart and is resumable.

Uses the **sync** ``PostgresSaver`` + a sync ``psycopg`` pool: async psycopg
can't run on the Windows Proactor event loop uvicorn uses, so the Foreman
graph is synchronous and ``ForemanService`` runs it via ``asyncio.to_thread``.
Built lazily per DSN (tests transparently get ``orchard_test``); closed from
the app lifespan.
"""
from __future__ import annotations

import asyncio
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import Settings
from ..core.logging import get_logger
from .foreman import build_foreman_graph

_log = get_logger("app.foreman")

# dsn -> (pool, compiled_graph)
_by_dsn: dict[str, tuple[ConnectionPool, Any]] = {}


def _build(settings: Settings) -> tuple[ConnectionPool, Any]:
    from langgraph.checkpoint.postgres import PostgresSaver

    pool = ConnectionPool(
        settings.psycopg_dsn(),
        min_size=1,
        max_size=5,
        open=True,
        timeout=15,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()  # CREATE TABLE IF NOT EXISTS checkpoints* ...
    return pool, build_foreman_graph(saver)


async def ensure_foreman_graph(settings: Settings) -> Any:
    """The compiled Foreman graph for ``settings``' database, creating the
    checkpoint tables + pool on first use (off the event loop)."""
    dsn = settings.psycopg_dsn()
    cached = _by_dsn.get(dsn)
    if cached is not None:
        return cached[1]
    pool, graph = await asyncio.to_thread(_build, settings)
    _by_dsn[dsn] = (pool, graph)
    _log.info("foreman.checkpointer.ready", db=settings.postgres_db)
    return graph


async def close_checkpointers() -> None:
    for pool, _ in list(_by_dsn.values()):
        await asyncio.to_thread(pool.close)
    _by_dsn.clear()
