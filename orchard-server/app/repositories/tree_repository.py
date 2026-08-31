"""Raw persistence for the ``tree`` table."""
from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]

_COLUMNS = (
    "tree_id",
    "species",
    "variety",
    "zone_id",
    "planted_date",
    "additional_context",
    "notes",
)
_MUTABLE = tuple(c for c in _COLUMNS if c != "tree_id")


class TreeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(
        self, *, species: str | None = None, zone_id: int | None = None
    ) -> list[Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if species is not None:
            clauses.append("species = ?")
            params.append(species)
        if zone_id is not None:
            clauses.append("zone_id = ?")
            params.append(zone_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(
            f"SELECT * FROM tree{where} ORDER BY tree_id", params
        )
        return [dict(r) for r in cur.fetchall()]

    def get(self, tree_id: int) -> Row | None:
        cur = self._conn.execute("SELECT * FROM tree WHERE tree_id = ?", (tree_id,))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def create(self, data: Row) -> Row:
        # Insert every mutable column, plus tree_id when the caller supplied one.
        cols = list(_MUTABLE)
        values: list[Any] = [data.get(c) for c in cols]
        if data.get("tree_id") is not None:
            cols = ["tree_id", *cols]
            values = [data["tree_id"], *values]
        placeholders = ", ".join("?" for _ in cols)
        cur = self._conn.execute(
            f"INSERT INTO tree ({', '.join(cols)}) VALUES ({placeholders})", values
        )
        new_id = data["tree_id"] if data.get("tree_id") is not None else cur.lastrowid
        row = self.get(int(new_id))
        assert row is not None
        return row

    def update(self, tree_id: int, fields: Row) -> Row | None:
        allowed = {k: v for k, v in fields.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = ?" for k in allowed)
            self._conn.execute(
                f"UPDATE tree SET {assignments} WHERE tree_id = ?",
                (*allowed.values(), tree_id),
            )
        return self.get(tree_id)

    def delete(self, tree_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM tree WHERE tree_id = ?", (tree_id,))
        return cur.rowcount > 0
