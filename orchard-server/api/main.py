"""Orchard assistant HTTP API.

Run locally:
    cd orchard-server
    pip install -r requirements.txt
    uvicorn api.main:app --reload

Interactive docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import trees, zones


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Orchard Assistant API",
    version="0.1.0",
    summary="CRUD for orchard zones and trees.",
    lifespan=lifespan,
)

app.include_router(zones.router)
app.include_router(trees.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
