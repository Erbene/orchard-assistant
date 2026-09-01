"""Application configuration.

Kept dependency-free (plain dataclass + env) so it can be imported from
anywhere - services, repositories, or a future MCP server - without pulling
in web framework state.

Persistence is Postgres (+ pgvector) and a Chroma HTTP server, always - see
``docker-compose.yml``. There is no embedded/SQLite fallback: every run mode
(``docker compose up``, ``./dev.ps1``, ``pytest``) talks to the same two
containers, distinguished only by ``postgres_db`` / ``chroma_collection``
(the test suite points those at disposable, isolated names - see
``tests/conftest.py``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Uploaded source files (not Postgres/Chroma data - plain disk storage).
    uploads_dir: str = field(
        default_factory=lambda: os.environ.get("ORCHARD_UPLOADS_DIR", str(_ROOT / "uploads"))
    )
    # Observability (see app/core/logging.py)
    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "DEBUG")
    )
    environment: str = field(
        default_factory=lambda: os.environ.get("ENVIRONMENT", "development")
    )
    log_format: str = field(
        default_factory=lambda: os.environ.get("LOG_FORMAT", "")  # "console" | "json" | ""
    )

    # PostgreSQL (docker-compose "postgres" service - app/core/db.py)
    database_url: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "")
    )
    postgres_host: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_HOST", "localhost")
    )
    postgres_port: int = field(
        # bare-metal default: compose publishes Postgres on host 5433 (5432 may
        # be a native install). The backend *container* sets POSTGRES_PORT=5432.
        default_factory=lambda: int(os.environ.get("POSTGRES_PORT", "5433"))
    )
    postgres_user: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_USER", "orchard")
    )
    postgres_password: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", "orchard")
    )
    postgres_db: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_DB", "orchard")
    )
    db_pool_size: int = field(
        default_factory=lambda: int(os.environ.get("DB_POOL_SIZE", "20"))
    )
    db_max_overflow: int = field(
        default_factory=lambda: int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    )
    db_pool_timeout: float = field(
        default_factory=lambda: float(os.environ.get("DB_POOL_TIMEOUT", "30"))
    )
    db_pool_recycle: int = field(
        default_factory=lambda: int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    )
    db_echo: bool = field(default_factory=lambda: _bool("DB_ECHO", default=False))

    # ChromaDB HTTP server (docker-compose "chromadb" service - app/core/vector_db.py)
    chroma_host: str = field(
        default_factory=lambda: os.environ.get("CHROMA_HOST", "localhost")
    )
    chroma_port: int = field(
        # bare-metal default: compose publishes Chroma on host 8001 (8000 is
        # the local uvicorn). The backend *container* sets CHROMA_PORT=8000.
        default_factory=lambda: int(os.environ.get("CHROMA_PORT", "8001"))
    )
    chroma_collection: str = field(
        default_factory=lambda: os.environ.get("CHROMA_COLLECTION", "orchard_knowledge")
    )

    def sqlalchemy_dsn(self) -> str:
        """asyncpg DSN. ``DATABASE_URL`` wins if set, else assembled from parts."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
