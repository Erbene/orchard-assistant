"""Raw persistence for ``moisture_sensor`` (Irrigation Phase 1)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_MUTABLE = ("label", "tree_id", "zone_id")


class MoistureSensorRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, sensor_id: str) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM moisture_sensor WHERE id = :id"), {"id": sensor_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def list(self) -> list[Row]:
        result = await self._conn.execute(
            text("SELECT * FROM moisture_sensor ORDER BY id")
        )
        return [dict(r) for r in result.mappings().all()]

    async def for_tree(self, tree_id: int) -> list[Row]:
        result = await self._conn.execute(
            text("SELECT * FROM moisture_sensor WHERE tree_id = :tid ORDER BY id"),
            {"tid": tree_id},
        )
        return [dict(r) for r in result.mappings().all()]

    async def for_zone(self, zone_id: str) -> list[Row]:
        result = await self._conn.execute(
            text("SELECT * FROM moisture_sensor WHERE zone_id = :zid ORDER BY id"),
            {"zid": zone_id},
        )
        return [dict(r) for r in result.mappings().all()]

    async def create(self, data: Row) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO moisture_sensor (id, label, tree_id, zone_id)"
                " VALUES (:id, :label, :tree_id, :zone_id) RETURNING *"
            ),
            {
                "id": data["id"],
                "label": data.get("label"),
                "tree_id": data.get("tree_id"),
                "zone_id": data.get("zone_id"),
            },
        )
        return dict(result.mappings().one())

    async def update(self, sensor_id: str, patch: Row) -> Row | None:
        cols = [c for c in _MUTABLE if c in patch]
        if not cols:
            return await self.get(sensor_id)
        sets = ", ".join(f"{c} = :{c}" for c in cols)
        await self._conn.execute(
            text(f"UPDATE moisture_sensor SET {sets} WHERE id = :id"),
            {"id": sensor_id, **{c: patch[c] for c in cols}},
        )
        return await self.get(sensor_id)

    async def delete(self, sensor_id: str) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM moisture_sensor WHERE id = :id"), {"id": sensor_id}
        )
        return result.rowcount > 0
