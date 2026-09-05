"""Test harness for the Postgres + Chroma stack.

There is no SQLite. Every test runs against the same containers the app uses
(``docker compose``'s ``postgres`` / ``chromadb``), but against a disposable,
isolated slice:

* Postgres database ``orchard_test`` (separate from the real ``orchard``),
  created + schema-loaded once per session, every table ``TRUNCATE``d before
  each test.
* Chroma collection ``orchard_knowledge_test`` (separate from
  ``orchard_knowledge``), emptied before each test.

The session fixture starts the containers if they aren't already running
(``scripts.ensure_stack``); it never tears them down.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

# Tests are hermetic: ignore any real orchard-server/.env, and Rachio is
# always mocked / never really configured. Set BEFORE app.config imports.
os.environ["ORCHARD_SKIP_DOTENV"] = "1"
os.environ["ORCHARD_SUPERVISOR_LOOP"] = "0"
os.environ["ORCHARD_DEMO"] = "0"
os.environ["RACHIO_API_KEY"] = ""
os.environ["LANGCHAIN_TRACING_V2"] = "false"   # no LangSmith calls in CI
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"  # unreachable -> template fallback

import asyncpg
import pytest

from app.config import Settings, get_settings
from app.rag.vector_store import get_vector_store
from scripts.ensure_stack import ensure_stack

TEST_DB = "orchard_test"
TEST_COLLECTION = "orchard_knowledge_test"

_INIT_SQL = Path(__file__).resolve().parent.parent / "docker" / "postgres" / "init.sql"
_TABLES = (
    "source_chunks", "tree_sources", "executed_task_log", "task", "task_templates",
    "moisture_sensor", "rainfall_forecast_log",
    "irrigation_zone_config", "irrigation_proposal", "irrigation_config",
    "zone", "sources", "tree",
    "chat_message", "conversation",                         # assistant history
    "checkpoint_writes", "checkpoint_blobs", "checkpoints",  # langgraph, when present
)


def stack_settings(**overrides) -> Settings:
    """Canonical Settings for a test: disposable DB + collection."""
    return Settings(postgres_db=TEST_DB, chroma_collection=TEST_COLLECTION, **overrides)


def _admin_dsn(dbname: str) -> str:
    s = get_settings()  # picks up POSTGRES_HOST/PORT/USER/PASSWORD from env, else localhost
    return f"postgresql://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{dbname}"


async def _provision() -> None:
    # 1. create orchard_test if missing (CREATE DATABASE can't run in a txn /
    #    while connected to the target db, so do it from the real db).
    admin = await asyncpg.connect(_admin_dsn(get_settings().postgres_db))
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await admin.close()

    # 2. apply the schema (idempotent - init.sql is all IF NOT EXISTS), then
    #    the additive/structural migrations the app applies on startup so an
    #    orchard_test created by an older schema catches up (matches
    #    db.apply_startup_ddl for the real DB).
    from app.core.db import _STARTUP_DDL

    conn = await asyncpg.connect(_admin_dsn(TEST_DB))
    try:
        await conn.execute(_INIT_SQL.read_text(encoding="utf-8"))
        for stmt in _STARTUP_DDL:
            await conn.execute(stmt)
    finally:
        await conn.close()


async def _truncate() -> None:
    conn = await asyncpg.connect(_admin_dsn(TEST_DB))
    try:
        existing = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        targets = [t for t in _TABLES if t in existing]
        if targets:
            await conn.execute(
                f"TRUNCATE {', '.join(targets)} RESTART IDENTITY CASCADE"
            )
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _stack() -> None:
    ensure_stack()
    asyncio.run(_provision())


@pytest.fixture(autouse=True)
def _clean(_stack) -> None:
    asyncio.run(_truncate())
    try:
        get_vector_store(stack_settings()).clear()
    except Exception:  # noqa: BLE001 - a test that never touches Chroma shouldn't fail here
        pass
