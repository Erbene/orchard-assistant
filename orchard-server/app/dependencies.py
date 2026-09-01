"""FastAPI dependency wiring.

The dependency graph:

    get_settings_dep
          |
    get_connection ------------------------------.
      |          |                               |
    get_zone_repository        get_tree_repository
      |     \\                    /       |
      |      \\                  /        |
    get_zone_service        get_tree_service
                     \\        /
                  get_validation_agent

Because FastAPI caches sub-dependencies per request, ``get_connection`` yields
one Postgres connection shared by every repository in that request - so a
request is a single transaction (commit on success, rollback on error).

Tests override ``get_settings_dep`` to point at the disposable ``orchard_test``
database / ``orchard_knowledge_test`` collection (see ``tests/conftest.py``);
nothing else needs to change.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from .config import Settings, get_settings
from .core import db
from .rag.vector_store import OrchardVectorStore, get_vector_store
from .repositories.source_repository import SourceRepository
from .repositories.task_repository import TaskRepository
from .repositories.tree_repository import TreeRepository
from .repositories.zone_repository import ZoneRepository
from .services.chat_service import ChatService
from .services.source_service import SourceService
from .services.task_service import TaskService
from .services.tree_service import TreeService
from .services.validators import ValidationAgent, get_default_validation_agent
from .services.zone_service import ZoneService


def get_settings_dep() -> Settings:
    return get_settings()


async def get_connection(
    settings: Settings = Depends(get_settings_dep),
) -> AsyncIterator[AsyncConnection]:
    async with db.connection(settings) as conn:
        yield conn


# -- repositories ------------------------------------------------------

def get_zone_repository(conn: AsyncConnection = Depends(get_connection)) -> ZoneRepository:
    return ZoneRepository(conn)


def get_tree_repository(conn: AsyncConnection = Depends(get_connection)) -> TreeRepository:
    return TreeRepository(conn)


def get_task_repository(conn: AsyncConnection = Depends(get_connection)) -> TaskRepository:
    return TaskRepository(conn)


def get_source_repository(conn: AsyncConnection = Depends(get_connection)) -> SourceRepository:
    return SourceRepository(conn)


# -- vector store (process singleton per Settings) --------------------

def get_vector_store_dep(
    settings: Settings = Depends(get_settings_dep),
) -> OrchardVectorStore:
    return get_vector_store(settings)


# -- validation agent -------------------------------------------------

def get_validation_agent() -> ValidationAgent:
    return get_default_validation_agent()


# -- services ---------------------------------------------------------

def get_zone_service(
    repo: ZoneRepository = Depends(get_zone_repository),
    validator: ValidationAgent = Depends(get_validation_agent),
) -> ZoneService:
    return ZoneService(repo, validator)


def get_tree_service(
    trees: TreeRepository = Depends(get_tree_repository),
    zones: ZoneRepository = Depends(get_zone_repository),
    validator: ValidationAgent = Depends(get_validation_agent),
) -> TreeService:
    return TreeService(trees, zones, validator)


def get_task_service(
    tasks: TaskRepository = Depends(get_task_repository),
    trees: TreeRepository = Depends(get_tree_repository),
) -> TaskService:
    return TaskService(tasks, trees)


def get_source_service(
    sources: SourceRepository = Depends(get_source_repository),
    trees: TreeRepository = Depends(get_tree_repository),
    store: OrchardVectorStore = Depends(get_vector_store_dep),
    settings: Settings = Depends(get_settings_dep),
) -> SourceService:
    return SourceService(sources, trees, store, settings)


def get_chat_service() -> ChatService:
    return ChatService()
