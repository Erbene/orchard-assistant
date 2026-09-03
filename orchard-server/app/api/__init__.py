from fastapi import APIRouter

from .routes import (
    care_plan,
    chat,
    conversations,
    irrigation,
    schedule,
    sources,
    tasks,
    trees,
    zones,
)

api_router = APIRouter()
api_router.include_router(zones.router)
api_router.include_router(trees.router)
api_router.include_router(sources.router)
api_router.include_router(schedule.router)
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(care_plan.router)
api_router.include_router(tasks.router)
api_router.include_router(irrigation.router)

__all__ = ["api_router"]
