"""Raw persistence for the ``zone`` table.

Repositories deal only in primitives and ``dict`` rows. No Pydantic, no
business rules, no HTTP. Integrity violations propagate as
``sqlite3.IntegrityError`` for the service layer to interpret.
"""
from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]

_COLUMNS = ("zone_id", "name", "soil_drainage", "water_source")
_MUTABLE = ("name", "soil_drainage", "water_source")


class ZoneRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[Row]:
        cur = self._conn.execute("SELECT * FROM zone ORDER BY zone_id")
        return [dict(r) for r in cur.fetchall()]

    def get(self, zone_id: int) -> Row | None:
        cur = self._conn.execute("SELECT * FROM zone WHERE zone_id = ?", (zone_id,))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def exists(self, zone_id: int) -> bool:
        cur = self._conn.execute("SELECT 1 FROM zone WHERE zone_id = ?", (zone_id,))
        return cur.fetchone() is not None

    def create(self, name: str, soil_drainage: str | None, water_source: str | None) -> Row:
        cur = self._conn.execute(
            "INSERT INTO zone (name, soil_drainage, water_source) VALUES (?, ?, ?)",
            (name, soil_drainage, water_source),
        )
        row = self.get(int(cur.lastrowid))
        assert row is not None  # just inserted
        return row

    def update(self, zone_id: int, fields: Row) -> Row | None:
        allowed = {k: v for k, v in fields.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = ?" for k in allowed)
            self._conn.execute(
                f"UPDATE zone SET {assignments} WHERE zone_id = ?",
                (*allowed.values(), zone_id),
            )
        return self.get(zone_id)

    def delete(self, zone_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM zone WHERE zone_id = ?", (zone_id,))
        return cur.rowcount > 0
