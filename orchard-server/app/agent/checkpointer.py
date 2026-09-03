"""LangGraph Postgres checkpointers for the two interruptible graphs.

- the **Foreman** JIT negotiation (waits on the time / resource interrupts)
- the **Irrigation Supervisor** (waits at ``interrupt_before=["execute_rachio_action"]``
  for HITL approval)

Both persist to the ``checkpoints*`` tables in the same Postgres, keyed by
``thread_id`` (``jit-*`` vs ``irr-*``), so a paused graph survives a restart.

Uses the **sync** ``PostgresSaver`` + a sync ``psycopg`` pool: async psycopg
can't run on the Windows Proactor event loop uvicorn uses, so both graphs are
synchronous and their services run them via ``asyncio.to_thread``. Built lazily
per DSN (tests transparently get ``orchard_test``); closed from the app lifespan.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import Settings
from ..core.logging import get_logger

_log = get_logger("app.checkpointer")

# (kind, dsn) -> (pool, compiled_graph)
_graphs: dict[tuple[str, str], tuple[ConnectionPool, Any]] = {}


def _new_pool(settings: Settings) -> ConnectionPool:
    return ConnectionPool(
        settings.psycopg_dsn(),
        min_size=1,
        max_size=5,
        open=True,
        timeout=15,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )


def _build(settings: Settings, builder: Callable[[Any], Any]) -> tuple[ConnectionPool, Any]:
    from langgraph.checkpoint.postgres import PostgresSaver

    pool = _new_pool(settings)
    saver = PostgresSaver(pool)
    saver.setup()  # CREATE TABLE IF NOT EXISTS checkpoints* ...
    return pool, builder(saver)


async def _ensure(kind: str, settings: Settings, builder: Callable[[Any], Any]) -> Any:
    key = (kind, settings.psycopg_dsn())
    cached = _graphs.get(key)
    if cached is not None:
        return cached[1]
    pool, graph = await asyncio.to_thread(_build, settings, builder)
    _graphs[key] = (pool, graph)
    _log.info("checkpointer.ready", kind=kind, db=settings.postgres_db)
    return graph


async def ensure_foreman_graph(settings: Settings) -> Any:
    from .foreman import build_foreman_graph

    return await _ensure("foreman", settings, build_foreman_graph)


async def ensure_irrigation_graph(settings: Settings) -> Any:
    from .irrigation_supervisor import build_irrigation_graph

    return await _ensure(
        "irrigation", settings, lambda saver: build_irrigation_graph(settings, saver)
    )


async def close_checkpointers() -> None:
    for pool, _ in list(_graphs.values()):
        await asyncio.to_thread(pool.close)
    _graphs.clear()
