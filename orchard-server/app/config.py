"""Application configuration.

Kept dependency-free (plain dataclass + env) so it can be imported from
anywhere - services, repositories, or a future MCP server - without pulling
in web framework state.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "orchard.db"


@dataclass(frozen=True)
class Settings:
    db_path: str = field(
        default_factory=lambda: os.environ.get("ORCHARD_DB_PATH", str(_DEFAULT_DB))
    )
    schema_path: str = field(
        default_factory=lambda: str(Path(__file__).with_name("sql") / "schema.sql")
    )


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
