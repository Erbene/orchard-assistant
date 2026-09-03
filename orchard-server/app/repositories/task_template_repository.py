"""Raw persistence for ``task_templates`` (the per-tree Care Plan).

JSON columns (``required_resources``, ``resource_plan``, ``source_ids``) are
written with an explicit ``CAST(:x AS jsonb)`` over JSON text and read back
tolerantly, same idiom as ``task_repository``.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_JSON_COLUMNS = ("required_resources", "resource_plan", "source_ids", "valid_months")
_WRITABLE = (
    "name", "category", "rate_class", "interval_days", "estimated_minutes",
    "priority_score", "required_resources", "resource_plan", "baseline_question",
    "anchor_date", "source_ids", "valid_months", "biological_anchor",
    "anchor_offset_days",
)


def _encode(fields: Row) -> Row:
    out = dict(fields)
    for col in _JSON_COLUMNS:
        if col in out and not isinstance(out[col], str):
            out[col] = json.dumps(out[col] if out[col] is not None else [])
    return out


def _decode(row: Row) -> Row:
    for col in _JSON_COLUMNS:
        value = row.get(col)
        row[col] = json.loads(value) if isinstance(value, str) else (value or [])
    return row


def _placeholder(col: str) -> str:
    return f"CAST(:{col} AS jsonb)" if col in _JSON_COLUMNS else f":{col}"


class TaskTemplateRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, template_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM task_templates WHERE id = :id"), {"id": template_id}
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

    async def list_for_tree(self, tree_id: int) -> list[Row]:
        result = await self._conn.execute(
            text(
                "SELECT * FROM task_templates WHERE tree_id = :tid"
                " ORDER BY priority_score DESC, id ASC"
            ),
            {"tid": tree_id},
        )
        return [_decode(dict(r)) for r in result.mappings().all()]

    async def create(self, tree_id: int, data: Row) -> Row:
        payload = _encode(data)
        cols = [c for c in _WRITABLE if c in payload]
        result = await self._conn.execute(
            text(
                f"INSERT INTO task_templates (tree_id, {', '.join(cols)})"
                f" VALUES (:tree_id, {', '.join(_placeholder(c) for c in cols)})"
                " RETURNING *"
            ),
            {"tree_id": tree_id, **{c: payload[c] for c in cols}},
        )
        return _decode(dict(result.mappings().one()))

    async def update(self, template_id: int, patch: Row) -> Row | None:
        payload = _encode(patch)
        cols = [c for c in _WRITABLE if c in payload]
        if not cols:
            return await self.get(template_id)
        sets = ", ".join(f"{c} = {_placeholder(c)}" for c in cols)
        result = await self._conn.execute(
            text(
                f"UPDATE task_templates SET {sets}, updated_at = now()"
                " WHERE id = :id RETURNING *"
            ),
            {"id": template_id, **{c: payload[c] for c in cols}},
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

    async def delete(self, template_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM task_templates WHERE id = :id"), {"id": template_id}
        )
        return result.rowcount > 0

    async def replace_for_tree(self, tree_id: int, rows: list[Row]) -> list[Row]:
        """Drop the tree's templates and insert a fresh set (plan regeneration)."""
        await self._conn.execute(
            text("DELETE FROM task_templates WHERE tree_id = :tid"), {"tid": tree_id}
        )
        return [await self.create(tree_id, r) for r in rows]
