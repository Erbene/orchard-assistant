from fastapi import APIRouter

from .routes import chat, trees, zones

api_router = APIRouter()
api_router.include_router(zones.router)
api_router.include_router(trees.router)
api_router.include_router(chat.router)

__all__ = ["api_router"]
