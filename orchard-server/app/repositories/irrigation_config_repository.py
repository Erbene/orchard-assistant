"""Raw persistence for ``irrigation_zone_config`` + the singleton
``irrigation_config`` (Irrigation Phase 3)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_ZONE_FIELDS = ("baseline_minutes", "supervised")
_SUPERVISOR_FIELDS = ("supervisor_frequency_hours", "auto_approve_skips")


class IrrigationConfigRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # -- singleton supervisor config -----------------------------

    async def get_supervisor(self) -> Row:
        result = await self._conn.execute(
            text("SELECT * FROM irrigation_config WHERE id = 1")
        )
        row = result.mappings().first()
        if row is None:
            await self._conn.execute(
                text("INSERT INTO irrigation_config (id) VALUES (1) ON CONFLICT DO NOTHING")
            )
            result = await self._conn.execute(
                text("SELECT * FROM irrigation_config WHERE id = 1")
            )
            row = result.mappings().one()
        return dict(row)

    async def update_supervisor(self, patch: Row) -> Row:
        await self.get_supervisor()  # self-heal: ensure the id=1 row exists first
        cols = [c for c in _SUPERVISOR_FIELDS if c in patch]
        if cols:
            sets = ", ".join(f"{c} = :{c}" for c in cols)
            await self._conn.execute(
                text(
                    f"UPDATE irrigation_config SET {sets}, updated_at = now() WHERE id = 1"
                ),
                {c: patch[c] for c in cols},
            )
        return await self.get_supervisor()

    # -- per-zone config ---------------------------------------

    async def get_zone(self, zone_id: str) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM irrigation_zone_config WHERE zone_id = :z"),
            {"z": zone_id},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def all_zones(self) -> dict[str, Row]:
        result = await self._conn.execute(text("SELECT * FROM irrigation_zone_config"))
        return {r["zone_id"]: dict(r) for r in result.mappings().all()}

    async def upsert_zone(self, zone_id: str, patch: Row) -> Row:
        cols = [c for c in _ZONE_FIELDS if c in patch]
        insert_cols = ["zone_id", *cols]
        placeholders = ", ".join(f":{c}" for c in insert_cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols) or "zone_id = EXCLUDED.zone_id"
        result = await self._conn.execute(
            text(
                f"INSERT INTO irrigation_zone_config ({', '.join(insert_cols)})"
                f" VALUES ({placeholders})"
                f" ON CONFLICT (zone_id) DO UPDATE SET {updates}, updated_at = now()"
                " RETURNING *"
            ),
            {"zone_id": zone_id, **{c: patch[c] for c in cols}},
        )
        return dict(result.mappings().one())
