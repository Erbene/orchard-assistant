"""FastAPI dependency wiring.

The dependency graph:

    get_settings_dep
          |
    get_connection ------------------------------.
      |          |                               |
    get_zone_repository        get_tree_repository
      |     \\                    /       |
      |      \\                  /        |
    get_zone_service        get_tree_service
                     \\        /
                  get_validation_agent

Because FastAPI caches sub-dependencies per request, ``get_connection`` yields
one connection shared by every repository in that request - so a request is a
single transaction (commit on success, rollback on error).

Tests override ``get_settings_dep`` (or set ``ORCHARD_DB_PATH``) to point at a
throwaway database; nothing else needs to change.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends

from .config import Settings, get_settings
from .db import connect, init_db
from .repositories.tree_repository import TreeRepository
from .repositories.zone_repository import ZoneRepository
from .services.tree_service import TreeService
from .services.validators import ValidationAgent, get_default_validation_agent
from .services.zone_service import ZoneService

# Paths whose schema has already been ensured this process.
_initialized: set[str] = set()


def get_settings_dep() -> Settings:
    return get_settings()


def _ensure_schema(settings: Settings) -> None:
    if settings.db_path not in _initialized:
        init_db(settings)
        _initialized.add(settings.db_path)


def get_connection(
    settings: Settings = Depends(get_settings_dep),
) -> Iterator["object"]:
    _ensure_schema(settings)
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# -- repositories ------------------------------------------------------

def get_zone_repository(conn=Depends(get_connection)) -> ZoneRepository:
    return ZoneRepository(conn)


def get_tree_repository(conn=Depends(get_connection)) -> TreeRepository:
    return TreeRepository(conn)


# -- validation agent -------------------------------------------------

def get_validation_agent() -> ValidationAgent:
    return get_default_validation_agent()


# -- services ---------------------------------------------------------

def get_zone_service(
    repo: ZoneRepository = Depends(get_zone_repository),
    validator: ValidationAgent = Depends(get_validation_agent),
) -> ZoneService:
    return ZoneService(repo, validator)


def get_tree_service(
    trees: TreeRepository = Depends(get_tree_repository),
    zones: ZoneRepository = Depends(get_zone_repository),
    validator: ValidationAgent = Depends(get_validation_agent),
) -> TreeService:
    return TreeService(trees, zones, validator)
