from fastapi import APIRouter

from .routes import trees, zones

api_router = APIRouter()
api_router.include_router(zones.router)
api_router.include_router(trees.router)

__all__ = ["api_router"]
