"""Raw persistence for the ``zone`` table.

Repositories deal only in primitives and ``dict`` rows. No Pydantic, no
business rules, no HTTP. Integrity violations propagate as
``sqlalchemy.exc.IntegrityError`` for the service layer to interpret.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_MUTABLE = ("name", "soil_drainage", "water_source")


class ZoneRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list(self) -> list[Row]:
        result = await self._conn.execute(text("SELECT * FROM zone ORDER BY zone_id"))
        return [dict(r) for r in result.mappings().all()]

    async def get(self, zone_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM zone WHERE zone_id = :id"), {"id": zone_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def exists(self, zone_id: int) -> bool:
        result = await self._conn.execute(
            text("SELECT 1 FROM zone WHERE zone_id = :id"), {"id": zone_id}
        )
        return result.first() is not None

    async def create(self, name: str, soil_drainage: str | None, water_source: str | None) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO zone (name, soil_drainage, water_source)"
                " VALUES (:name, :soil, :water) RETURNING *"
            ),
            {"name": name, "soil": soil_drainage, "water": water_source},
        )
        return dict(result.mappings().one())

    async def update(self, zone_id: int, fields: Row) -> Row | None:
        allowed = {k: v for k, v in fields.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = :{k}" for k in allowed)
            await self._conn.execute(
                text(f"UPDATE zone SET {assignments} WHERE zone_id = :zone_id"),
                {**allowed, "zone_id": zone_id},
            )
        return await self.get(zone_id)

    async def delete(self, zone_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM zone WHERE zone_id = :id"), {"id": zone_id}
        )
        return result.rowcount > 0
