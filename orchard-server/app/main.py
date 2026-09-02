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
from .agent.checkpointer import close_checkpointers
from .core.middleware import RequestContextMiddleware
from .mcp_server import mcp
from .services.rachio import get_rachio_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings())          # dual-mode structlog pipeline
    log = get_logger("app")
    log.info("app.startup", version=app.version)
    try:
        await db.apply_startup_ddl(get_settings())   # additive, idempotent
    except Exception:  # noqa: BLE001 - don't crash the app if the DB is down
        log.warning("app.startup_ddl.failed", exc_info=True)
    yield
    await db.dispose_all()
    await close_checkpointers()
    try:
        await get_rachio_service(get_settings()).aclose()
    except Exception:  # noqa: BLE001
        log.warning("app.rachio_close.failed", exc_info=True)
    log.info("app.shutdown")


app = FastAPI(
    title="Orchard Assistant API",
    version="0.2.0",
    summary="Layered service for orchard trees, tasks & knowledge base; irrigation zones read-only from Rachio.",
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
