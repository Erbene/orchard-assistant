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
from .core import db
from .core.logging import configure_logging, get_logger
from .core.middleware import RequestContextMiddleware
from .mcp_server import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings())          # dual-mode structlog pipeline
    log = get_logger("app")
    log.info("app.startup", version=app.version)
    yield
    await db.dispose_all()
    log.info("app.shutdown")


app = FastAPI(
    title="Orchard Assistant API",
    version="0.2.0",
    summary="Layered CRUD (router -> service -> repository) for orchard zones and trees.",
    lifespan=lifespan,
)

# Outermost app middleware: correlation id + per-request logging + timing.
app.add_middleware(RequestContextMiddleware)

register_exception_handlers(app)
# Versioned API namespace: /api/v1/zones, /api/v1/trees, /api/v1/chat
app.include_router(api_router, prefix="/api/v1")

# MCP server over SSE for web-based AI clients (GET /mcp/sse, POST /mcp/messages/).
app.mount("/mcp", mcp.sse_app())


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
