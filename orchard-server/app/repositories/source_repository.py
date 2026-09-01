"""Raw persistence for ``sources`` and the ``tree_sources`` mapping table."""
from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]


class SourceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- sources ----------------------------------------------------

    def get(self, source_id: int) -> Row | None:
        cur = self._conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def list(self) -> list[Row]:
        cur = self._conn.execute("SELECT * FROM sources ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]

    def exists(self, source_id: int) -> bool:
        cur = self._conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,))
        return cur.fetchone() is not None

    def create(
        self,
        *,
        name: str,
        source_type: str,
        raw_content: str,
        file_path: str | None = None,
    ) -> Row:
        cur = self._conn.execute(
            "INSERT INTO sources (name, source_type, file_path, raw_content)"
            " VALUES (?, ?, ?, ?)",
            (name, source_type, file_path, raw_content),
        )
        row = self.get(int(cur.lastrowid))
        assert row is not None
        return row

    def set_file_path(self, source_id: int, file_path: str) -> None:
        self._conn.execute(
            "UPDATE sources SET file_path = ? WHERE id = ?", (file_path, source_id)
        )

    def rename(self, source_id: int, name: str) -> Row | None:
        self._conn.execute(
            "UPDATE sources SET name = ? WHERE id = ?", (name, source_id)
        )
        return self.get(source_id)

    def delete(self, source_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return cur.rowcount > 0

    # -- tree <-> source links -----------------------------------

    def source_ids_for_tree(self, tree_id: int) -> list[int]:
        cur = self._conn.execute(
            "SELECT source_id FROM tree_sources WHERE tree_id = ? ORDER BY source_id",
            (tree_id,),
        )
        return [r[0] for r in cur.fetchall()]

    def sources_for_tree(self, tree_id: int) -> list[Row]:
        cur = self._conn.execute(
            "SELECT s.* FROM sources s"
            " JOIN tree_sources ts ON ts.source_id = s.id"
            " WHERE ts.tree_id = ? ORDER BY s.id DESC",
            (tree_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def set_tree_links(self, tree_id: int, source_ids: list[int]) -> None:
        self._conn.execute("DELETE FROM tree_sources WHERE tree_id = ?", (tree_id,))
        self._conn.executemany(
            "INSERT INTO tree_sources (tree_id, source_id) VALUES (?, ?)",
            [(tree_id, sid) for sid in dict.fromkeys(source_ids)],
        )
