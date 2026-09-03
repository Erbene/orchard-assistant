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
    "height_m",
    "canopy_spread_m",
    "estimated_gph",
    "wetted_area_m2",
)
_MUTABLE = tuple(c for c in _COLUMNS if c != "tree_id")


class TreeRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list(
        self, *, species: str | None = None, zone_id: str | None = None
    ) -> list[Row]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if species is not None:
            clauses.append("t.species = :species")
            params["species"] = species
        if zone_id is not None:
            clauses.append("t.zone_id = :zone_id")
            params["zone_id"] = zone_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        result = await self._conn.execute(
            text(
                "SELECT t.*, EXISTS ("
                " SELECT 1 FROM task_templates tt WHERE tt.tree_id = t.tree_id"
                ") AS has_care_plan"
                f" FROM tree t{where} ORDER BY t.tree_id"
            ),
            params,
        )
        return [dict(r) for r in result.mappings().all()]

    async def get(self, tree_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM tree WHERE tree_id = :id"), {"id": tree_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def distinct_zone_ids(self) -> list[str]:
        """Non-null zone ids that have at least one tree (irrigation supervisor)."""
        result = await self._conn.execute(
            text(
                "SELECT DISTINCT zone_id FROM tree"
                " WHERE zone_id IS NOT NULL AND zone_id <> '' ORDER BY zone_id"
            )
        )
        return [r[0] for r in result.all()]

    async def zone_tree_counts(self) -> dict[str, int]:
        result = await self._conn.execute(
            text(
                "SELECT zone_id, count(*) AS n FROM tree"
                " WHERE zone_id IS NOT NULL AND zone_id <> '' GROUP BY zone_id"
            )
        )
        return {r["zone_id"]: r["n"] for r in result.mappings().all()}

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
