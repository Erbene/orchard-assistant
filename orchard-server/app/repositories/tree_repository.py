"""Raw persistence for the ``tree`` table."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list(
        self, *, species: str | None = None, zone_id: int | None = None
    ) -> list[Row]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if species is not None:
            clauses.append("species = :species")
            params["species"] = species
        if zone_id is not None:
            clauses.append("zone_id = :zone_id")
            params["zone_id"] = zone_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        result = await self._conn.execute(
            text(f"SELECT * FROM tree{where} ORDER BY tree_id"), params
        )
        return [dict(r) for r in result.mappings().all()]

    async def get(self, tree_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM tree WHERE tree_id = :id"), {"id": tree_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def create(self, data: Row) -> Row:
        # Insert every mutable column, plus tree_id when the caller supplied one.
        cols = list(_MUTABLE)
        if data.get("tree_id") is not None:
            cols = ["tree_id", *cols]
        placeholders = ", ".join(f":{c}" for c in cols)
        params = {c: data.get(c) for c in cols}
        result = await self._conn.execute(
            text(
                f"INSERT INTO tree ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"
            ),
            params,
        )
        return dict(result.mappings().one())

    async def update(self, tree_id: int, fields: Row) -> Row | None:
        allowed = {k: v for k, v in fields.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = :{k}" for k in allowed)
            await self._conn.execute(
                text(f"UPDATE tree SET {assignments} WHERE tree_id = :tree_id"),
                {**allowed, "tree_id": tree_id},
            )
        return await self.get(tree_id)

    async def delete(self, tree_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM tree WHERE tree_id = :id"), {"id": tree_id}
        )
        return result.rowcount > 0
