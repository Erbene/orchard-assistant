"""Low-level SQLite plumbing: connections and schema bootstrap.

This module knows nothing about HTTP, services, or Pydantic. Repositories
receive a live ``sqlite3.Connection`` and issue SQL against it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Settings


def connect(settings: Settings) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI resolves sync dependencies in a worker
    # thread while async route handlers run on the event-loop thread. Each
    # request still gets its own connection and uses it sequentially.
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to an existing table after its first release. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so init_db backfills them idempotently.
_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "task": (
        ("estimated_minutes", "INTEGER"),
        ("required_resources", "TEXT NOT NULL DEFAULT '[]'"),
    ),
}


def init_db(settings: Settings) -> None:
    ddl = Path(settings.schema_path).read_text(encoding="utf-8")
    conn = connect(settings)
    try:
        conn.executescript(ddl)
        _backfill_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _backfill_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
