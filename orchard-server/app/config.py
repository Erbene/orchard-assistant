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
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from ``orchard-server/.env`` for bare-metal runs
    (uvicorn, ``python -m app.mcp_server``, dev.ps1). Existing env vars always
    win (docker compose / the shell). Uses ``python-dotenv`` when importable,
    otherwise a minimal built-in parser so this never silently no-ops just
    because the running interpreter lacks the package. The test suite sets
    ``ORCHARD_SKIP_DOTENV=1`` to stay hermetic.
    """
    if os.environ.get("ORCHARD_SKIP_DOTENV") or not path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
        return
    except ImportError:
        print(
            f"[config] python-dotenv not installed for {sys.executable}; "
            f"using the built-in .env parser",
            file=sys.stderr,
        )
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if val[:1] in {'"', "'"} and val[-1:] == val[:1]:
            val = val[1:-1]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        os.environ[key] = val


_load_dotenv(_ROOT / ".env")


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

    # Local LLM (Ollama). The Foreman narration is optional (templated
    # fallback); the Orchestrator / Agronomist REQUIRE it (chat -> 503 without).
    ollama_base_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    foreman_model: str = field(
        default_factory=lambda: os.environ.get("FOREMAN_MODEL", "qwen2.5:14b")
    )
    agent_model: str = field(
        default_factory=lambda: os.environ.get("AGENT_MODEL", "qwen2.5:7b-instruct")
    )

    # Rachio Smart Irrigation API (app/services/rachio.py) - optional; zone
    # endpoints/tools return 503 when the key is unset.
    rachio_api_key: str = field(
        default_factory=lambda: os.environ.get("RACHIO_API_KEY", "")
    )
    rachio_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "RACHIO_BASE_URL", "https://api.rach.io/1/public"
        )
    )

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

    @property
    def rachio_enabled(self) -> bool:
        return bool(self.rachio_api_key)

    def sqlalchemy_dsn(self) -> str:
        """asyncpg DSN. ``DATABASE_URL`` wins if set, else assembled from parts."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def psycopg_dsn(self) -> str:
        """psycopg3 DSN (no ``+asyncpg``) for the LangGraph Postgres checkpointer.

        ``localhost`` is normalized to ``127.0.0.1``: psycopg_pool's background
        connect worker can stall resolving ``localhost`` to IPv6 first on
        Windows, and the compose ports are IPv4-bound anyway.
        """
        dsn = self.database_url or self.sqlalchemy_dsn()
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        return dsn.replace("@localhost:", "@127.0.0.1:", 1)


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
