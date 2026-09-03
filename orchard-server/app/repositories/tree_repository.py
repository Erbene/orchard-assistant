"""Raw persistence for the ``tree`` table."""
from __future__ import annotations

import json
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
    "expected_flowering_month",
    "expected_harvest_month",
    "expected_dormancy_month",
    "expected_flowering_months",
    "expected_harvest_months",
    "expected_dormancy_months",
)
_JSON_COLUMNS = (
    "expected_flowering_months",
    "expected_harvest_months",
    "expected_dormancy_months",
)
_MUTABLE = tuple(c for c in _COLUMNS if c != "tree_id")


def _encode(fields: Row) -> Row:
    out = dict(fields)
    for col in _JSON_COLUMNS:
        if col in out and not isinstance(out[col], str):
            out[col] = json.dumps(out[col] if out[col] is not None else [])
    return out


def _decode(row: Row) -> Row:
    for col in _JSON_COLUMNS:
        value = row.get(col)
        if isinstance(value, str):
            row[col] = json.loads(value)
        elif value is None:
            row[col] = []
    return row


def _placeholder(col: str) -> str:
    return f"CAST(:{col} AS jsonb)" if col in _JSON_COLUMNS else f":{col}"


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
        return [_decode(dict(r)) for r in result.mappings().all()]

    async def get(self, tree_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM tree WHERE tree_id = :id"), {"id": tree_id}
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

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
        payload = _encode(data)
        cols = [c for c in _MUTABLE if c in payload]
        if payload.get("tree_id") is not None:
            cols = ["tree_id", *[c for c in cols if c != "tree_id"]]
        placeholders = ", ".join(_placeholder(c) for c in cols)
        params = {c: payload.get(c) for c in cols}
        result = await self._conn.execute(
            text(
                f"INSERT INTO tree ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"
            ),
            params,
        )
        return _decode(dict(result.mappings().one()))

    async def update(self, tree_id: int, fields: Row) -> Row | None:
        payload = _encode(fields)
        allowed = {k: v for k, v in payload.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = {_placeholder(k)}" for k in allowed)
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
