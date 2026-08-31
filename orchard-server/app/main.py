"""Composition root.

Run locally:
    cd orchard-server
    uvicorn app.main:app --reload

Interactive docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import api_router
from .api.errors import register_exception_handlers
from .config import get_settings
from .dependencies import _ensure_schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_schema(get_settings())
    yield


app = FastAPI(
    title="Orchard Assistant API",
    version="0.2.0",
    summary="Layered CRUD (router -> service -> repository) for orchard zones and trees.",
    lifespan=lifespan,
)

register_exception_handlers(app)
# Versioned API namespace: /api/v1/zones, /api/v1/trees, /api/v1/chat
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
