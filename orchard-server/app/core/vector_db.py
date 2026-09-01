"""ChromaDB HTTP client for the containerised vector server.

The server runs in docker-compose (``chromadb`` service), persists to a named
volume, and is bound to ``127.0.0.1:8000`` only. No auth: no credentials, no
headers - see docker-compose.yml.

This is the low-level client only; ``app/rag/vector_store.py``'s
``OrchardVectorStore`` wraps it with the actual collection (name driven by
``Settings.chroma_collection``, so tests can point at an isolated one).
"""
from __future__ import annotations

from functools import lru_cache

import chromadb
from chromadb.api import ClientAPI
from chromadb.config import Settings as ChromaSettings

from ..config import get_settings
from .logging import get_logger

_log = get_logger("app.vector_db")


@lru_cache
def get_chroma_client() -> ClientAPI:
    """Process-wide unauthenticated HTTP client. Fails fast if the server is down.

    Host/port are the same for every run mode (one shared container); only
    the *collection name* differs between real and test data, which is
    ``OrchardVectorStore``'s job, not this client's.
    """
    settings = get_settings()
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=False,
        headers=None,  # explicitly no auth headers
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=False,
        ),
    )
    client.heartbeat()  # raises if unreachable
    _log.info(
        "chroma.connected", host=settings.chroma_host, port=settings.chroma_port
    )
    return client


def healthcheck() -> bool:
    """For the app's ``/health`` endpoint."""
    try:
        get_chroma_client().heartbeat()
        return True
    except Exception as exc:  # noqa: BLE001 - report, don't propagate
        _log.warning("chroma.healthcheck.failed", error=str(exc))
        return False
