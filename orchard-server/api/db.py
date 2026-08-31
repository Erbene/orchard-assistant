"""SQLite connection handling and schema bootstrap."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Override with ORCHARD_DB_PATH; ":memory:" is not useful here because each
# connection would get its own database.
DB_PATH = os.environ.get(
    "ORCHARD_DB_PATH", str(Path(__file__).resolve().parent.parent / "orchard.db")
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a connection wrapped in a transaction (commit on success)."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
