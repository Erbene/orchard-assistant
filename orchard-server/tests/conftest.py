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
from pathlib import Path

import asyncpg
import pytest

from app.config import Settings, get_settings
from app.rag.vector_store import get_vector_store
from scripts.ensure_stack import ensure_stack

TEST_DB = "orchard_test"
TEST_COLLECTION = "orchard_knowledge_test"

_INIT_SQL = Path(__file__).resolve().parent.parent / "docker" / "postgres" / "init.sql"
_TABLES = ("source_chunks", "tree_sources", "task", "sources", "tree", "zone")


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

    # 2. apply the schema (idempotent - init.sql is all IF NOT EXISTS).
    conn = await asyncpg.connect(_admin_dsn(TEST_DB))
    try:
        await conn.execute(_INIT_SQL.read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def _truncate() -> None:
    conn = await asyncpg.connect(_admin_dsn(TEST_DB))
    try:
        await conn.execute(
            f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"
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
