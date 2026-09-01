"""Raw persistence for the singleton ``user_context`` table.

``available_products`` is stored as a JSON string and returned already
decoded to ``list[str]``.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

Row = dict[str, Any]

_SINGLETON_ID = 1
_MUTABLE = ("available_labor_hours_per_day", "available_products")


class UserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self) -> Row | None:
        cur = self._conn.execute(
            "SELECT * FROM user_context WHERE id = ?", (_SINGLETON_ID,)
        )
        row = cur.fetchone()
        return self._decode(dict(row)) if row is not None else None

    def create_default(self) -> Row:
        self._conn.execute(
            "INSERT OR IGNORE INTO user_context (id) VALUES (?)",
            (_SINGLETON_ID,),
        )
        row = self.get()
        assert row is not None
        return row

    def update(self, fields: Row) -> Row:
        sets: list[str] = []
        values: list[Any] = []
        for key in _MUTABLE:
            if key not in fields:
                continue
            sets.append(f"{key} = ?")
            value = fields[key]
            values.append(
                json.dumps(value) if key == "available_products" else value
            )
        sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        self._conn.execute(
            f"UPDATE user_context SET {', '.join(sets)} WHERE id = ?",
            (*values, _SINGLETON_ID),
        )
        row = self.get()
        assert row is not None
        return row

    @staticmethod
    def _decode(row: Row) -> Row:
        raw = row.get("available_products") or "[]"
        row["available_products"] = json.loads(raw)
        return row
