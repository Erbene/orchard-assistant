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
from .irrigation.forecast_log import RainfallForecastService
from .irrigation.sensors import MoistureSensorService
from .repositories.conversation_repository import ConversationRepository
from .repositories.irrigation_config_repository import IrrigationConfigRepository
from .repositories.irrigation_proposal_repository import IrrigationProposalRepository
from .repositories.moisture_sensor_repository import MoistureSensorRepository
from .repositories.rainfall_forecast_repository import RainfallForecastRepository
from .repositories.source_repository import SourceRepository
from .repositories.executed_task_log_repository import ExecutedTaskLogRepository
from .repositories.task_repository import TaskRepository
from .repositories.task_template_repository import TaskTemplateRepository
from .repositories.tree_repository import TreeRepository
from .agent.checkpointer import ensure_foreman_graph, ensure_irrigation_graph
from .services.chat_service import ChatService
from .services.foreman_service import ForemanService
from .services.care_plan_service import CarePlanService
from .services.conversation_service import ConversationService
from .services.irrigation_service import (
    IrrigationConfigService,
    IrrigationSupervisorService,
)
from .services.rachio import RachioService, get_rachio_service
from .services.source_service import SourceService
from .services.water_balance import WaterBalanceService
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


def get_executed_task_log_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> ExecutedTaskLogRepository:
    return ExecutedTaskLogRepository(conn)


def get_task_repository(conn: AsyncConnection = Depends(get_connection)) -> TaskRepository:
    return TaskRepository(conn)


def get_source_repository(conn: AsyncConnection = Depends(get_connection)) -> SourceRepository:
    return SourceRepository(conn)


def get_task_template_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> TaskTemplateRepository:
    return TaskTemplateRepository(conn)


def get_moisture_sensor_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> MoistureSensorRepository:
    return MoistureSensorRepository(conn)


def get_rainfall_forecast_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> RainfallForecastRepository:
    return RainfallForecastRepository(conn)


def get_conversation_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> ConversationRepository:
    return ConversationRepository(conn)


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
    templates: TaskTemplateRepository = Depends(get_task_template_repository),
    log: ExecutedTaskLogRepository = Depends(get_executed_task_log_repository),
) -> TaskService:
    return TaskService(tasks, trees, templates, log)


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


def get_conversation_service(
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationService:
    return ConversationService(conversations)


def get_care_plan_service(
    templates: TaskTemplateRepository = Depends(get_task_template_repository),
    tasks: TaskRepository = Depends(get_task_repository),
    trees: TreeRepository = Depends(get_tree_repository),
    sources: SourceService = Depends(get_source_service),
    settings: Settings = Depends(get_settings_dep),
) -> CarePlanService:
    return CarePlanService(templates, tasks, trees, sources, settings)


# -- irrigation (Phase 1: services only, no routes yet) --------------

def get_moisture_sensor_service(
    sensors: MoistureSensorRepository = Depends(get_moisture_sensor_repository),
    trees: TreeRepository = Depends(get_tree_repository),
) -> MoistureSensorService:
    return MoistureSensorService(sensors, trees)


def get_rainfall_forecast_service(
    log: RainfallForecastRepository = Depends(get_rainfall_forecast_repository),
    settings: Settings = Depends(get_settings_dep),
) -> RainfallForecastService:
    return RainfallForecastService(log, settings)


def get_water_balance_service(
    sensors: MoistureSensorService = Depends(get_moisture_sensor_service),
    trees: TreeRepository = Depends(get_tree_repository),
    settings: Settings = Depends(get_settings_dep),
) -> WaterBalanceService:
    return WaterBalanceService(sensors, trees, settings)


def get_irrigation_config_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> IrrigationConfigRepository:
    return IrrigationConfigRepository(conn)


def get_irrigation_proposal_repository(
    conn: AsyncConnection = Depends(get_connection),
) -> IrrigationProposalRepository:
    return IrrigationProposalRepository(conn)


def get_irrigation_config_service(
    config: IrrigationConfigRepository = Depends(get_irrigation_config_repository),
    trees: TreeRepository = Depends(get_tree_repository),
    proposals: IrrigationProposalRepository = Depends(get_irrigation_proposal_repository),
) -> IrrigationConfigService:
    return IrrigationConfigService(config, trees, proposals)


async def get_irrigation_supervisor_service(
    water: WaterBalanceService = Depends(get_water_balance_service),
    trees: TreeRepository = Depends(get_tree_repository),
    config: IrrigationConfigRepository = Depends(get_irrigation_config_repository),
    proposals: IrrigationProposalRepository = Depends(get_irrigation_proposal_repository),
    settings: Settings = Depends(get_settings_dep),
) -> IrrigationSupervisorService:
    graph = await ensure_irrigation_graph(settings)
    return IrrigationSupervisorService(water, trees, config, proposals, graph, settings)


def get_chat_service(
    store: OrchardVectorStore = Depends(get_vector_store_dep),
    settings: Settings = Depends(get_settings_dep),
) -> ChatService:
    # No request-scoped DB connection here: ChatService.stream_reply opens its
    # own for the turn (a Depends connection is torn down before the
    # StreamingResponse body is drained).
    return ChatService(store, settings)
