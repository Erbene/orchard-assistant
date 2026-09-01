"""Raw persistence for ``sources`` and the ``tree_sources`` mapping table."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]


class SourceRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # -- sources ----------------------------------------------------

    async def get(self, source_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM sources WHERE id = :id"), {"id": source_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def list(self) -> list[Row]:
        result = await self._conn.execute(text("SELECT * FROM sources ORDER BY id DESC"))
        return [dict(r) for r in result.mappings().all()]

    async def exists(self, source_id: int) -> bool:
        result = await self._conn.execute(
            text("SELECT 1 FROM sources WHERE id = :id"), {"id": source_id}
        )
        return result.first() is not None

    async def create(
        self,
        *,
        name: str,
        source_type: str,
        raw_content: str,
        file_path: str | None = None,
    ) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO sources (name, source_type, file_path, raw_content)"
                " VALUES (:name, :source_type, :file_path, :raw_content) RETURNING *"
            ),
            {
                "name": name,
                "source_type": source_type,
                "file_path": file_path,
                "raw_content": raw_content,
            },
        )
        return dict(result.mappings().one())

    async def set_file_path(self, source_id: int, file_path: str) -> None:
        await self._conn.execute(
            text("UPDATE sources SET file_path = :file_path WHERE id = :id"),
            {"file_path": file_path, "id": source_id},
        )

    async def rename(self, source_id: int, name: str) -> Row | None:
        await self._conn.execute(
            text("UPDATE sources SET name = :name WHERE id = :id"),
            {"name": name, "id": source_id},
        )
        return await self.get(source_id)

    async def delete(self, source_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM sources WHERE id = :id"), {"id": source_id}
        )
        return result.rowcount > 0

    # -- tree <-> source links -----------------------------------

    async def source_ids_for_tree(self, tree_id: int) -> list[int]:
        """Linked source ids in authority order (``priority_order`` ascending)."""
        result = await self._conn.execute(
            text(
                "SELECT source_id FROM tree_sources WHERE tree_id = :tree_id"
                " ORDER BY priority_order ASC, source_id ASC"
            ),
            {"tree_id": tree_id},
        )
        return [r[0] for r in result.all()]

    async def sources_for_tree(self, tree_id: int) -> list[Row]:
        """Linked sources in authority order (``priority_order`` ascending)."""
        result = await self._conn.execute(
            text(
                "SELECT s.* FROM sources s"
                " JOIN tree_sources ts ON ts.source_id = s.id"
                " WHERE ts.tree_id = :tree_id"
                " ORDER BY ts.priority_order ASC, s.id ASC"
            ),
            {"tree_id": tree_id},
        )
        return [dict(r) for r in result.mappings().all()]

    async def set_tree_links(self, tree_id: int, source_ids: list[int]) -> None:
        """Replace a tree's links. List order is persisted as ``priority_order``
        (index 0 = highest authority)."""
        await self._conn.execute(
            text("DELETE FROM tree_sources WHERE tree_id = :tree_id"), {"tree_id": tree_id}
        )
        unique_ids = list(dict.fromkeys(source_ids))
        if unique_ids:
            await self._conn.execute(
                text(
                    "INSERT INTO tree_sources (tree_id, source_id, priority_order)"
                    " VALUES (:tree_id, :source_id, :priority_order)"
                ),
                [
                    {"tree_id": tree_id, "source_id": sid, "priority_order": i}
                    for i, sid in enumerate(unique_ids)
                ],
            )
