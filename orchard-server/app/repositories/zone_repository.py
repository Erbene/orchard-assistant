"""Raw persistence for the local ``zone`` overlay (grower labels).

Rachio owns the irrigation zone itself; this table only stores an optional
display label keyed by the Rachio zone id.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]


class ZoneRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, zone_id: str) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM zone WHERE zone_id = :z"),
            {"z": zone_id},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def all_labels(self) -> dict[str, str]:
        """zone_id -> non-empty label."""
        result = await self._conn.execute(
            text(
                "SELECT zone_id, label FROM zone"
                " WHERE label IS NOT NULL AND btrim(label) <> ''"
            )
        )
        return {r["zone_id"]: r["label"] for r in result.mappings().all()}

    async def upsert(self, zone_id: str, label: str | None) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO zone (zone_id, label) VALUES (:zone_id, :label)"
                " ON CONFLICT (zone_id) DO UPDATE SET"
                " label = EXCLUDED.label, updated_at = now()"
                " RETURNING *"
            ),
            {"zone_id": zone_id, "label": label},
        )
        return dict(result.mappings().one())
