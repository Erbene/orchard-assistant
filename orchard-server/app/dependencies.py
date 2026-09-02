"""FastAPI dependency wiring.

Because FastAPI caches sub-dependencies per request, ``get_connection`` yields
one Postgres connection shared by every repository in that request - so a
request is a single transaction (commit on success, rollback on error).

Zones are not persisted locally - ``get_rachio_service_dep`` returns the
process-wide ``RachioService`` (Rachio Public API, read-only).

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
from .agent.checkpointer import ensure_foreman_graph
from .services.chat_service import ChatService
from .services.foreman_service import ForemanService
from .services.rachio import RachioService, get_rachio_service
from .services.source_service import SourceService
from .services.task_service import TaskService
from .services.tree_service import TreeService
from .services.validators import ValidationAgent, get_default_validation_agent


def get_settings_dep() -> Settings:
    return get_settings()


async def get_connection(
    settings: Settings = Depends(get_settings_dep),
) -> AsyncIterator[AsyncConnection]:
    async with db.connection(settings) as conn:
        yield conn


# -- repositories ------------------------------------------------------

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


# -- Rachio irrigation API (process singleton per Settings) ----------

def get_rachio_service_dep(
    settings: Settings = Depends(get_settings_dep),
) -> RachioService:
    return get_rachio_service(settings)


# -- validation agent -------------------------------------------------

def get_validation_agent() -> ValidationAgent:
    return get_default_validation_agent()


# -- services ---------------------------------------------------------

def get_tree_service(
    trees: TreeRepository = Depends(get_tree_repository),
    validator: ValidationAgent = Depends(get_validation_agent),
) -> TreeService:
    return TreeService(trees, validator)


def get_task_service(
    tasks: TaskRepository = Depends(get_task_repository),
    trees: TreeRepository = Depends(get_tree_repository),
) -> TaskService:
    return TaskService(tasks, trees)


async def get_foreman_service(
    tasks: TaskService = Depends(get_task_service),
    settings: Settings = Depends(get_settings_dep),
) -> ForemanService:
    graph = await ensure_foreman_graph(settings)
    return ForemanService(tasks, graph)


def get_source_service(
    sources: SourceRepository = Depends(get_source_repository),
    trees: TreeRepository = Depends(get_tree_repository),
    store: OrchardVectorStore = Depends(get_vector_store_dep),
    settings: Settings = Depends(get_settings_dep),
) -> SourceService:
    return SourceService(sources, trees, store, settings)


def get_chat_service() -> ChatService:
    return ChatService()
