"""Raw persistence for the ``executed_task_log`` table (completed/skipped snapshots)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_JSON_COLUMNS = ("required_resources",)


def _encode(fields: Row) -> Row:
    out = dict(fields)
    for col in _JSON_COLUMNS:
        if col in out and not isinstance(out[col], str):
            out[col] = json.dumps(out[col] or [])
    return out


def _decode(row: Row) -> Row:
    for col in _JSON_COLUMNS:
        value = row.get(col)
        row[col] = json.loads(value) if isinstance(value, str) else (value or [])
    return row


class ExecutedTaskLogRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, data: Row) -> Row:
        data = _encode(data)
        result = await self._conn.execute(
            text(
                "INSERT INTO executed_task_log ("
                " tree_id, template_id, task_id, action_type, category, outcome,"
                " scheduled_date, executed_at, estimated_minutes, required_resources"
                ") VALUES ("
                " :tree_id, :template_id, :task_id, :action_type, :category, :outcome,"
                " :scheduled_date, :executed_at, :estimated_minutes,"
                " CAST(:required_resources AS jsonb)"
                ") RETURNING *"
            ),
            {
                "tree_id": data["tree_id"],
                "template_id": data.get("template_id"),
                "task_id": data.get("task_id"),
                "action_type": data["action_type"],
                "category": data.get("category"),
                "outcome": data["outcome"],
                "scheduled_date": data.get("scheduled_date"),
                "executed_at": data["executed_at"],
                "estimated_minutes": data.get("estimated_minutes"),
                "required_resources": data["required_resources"],
            },
        )
        return _decode(dict(result.mappings().one()))

    async def list_history(
        self,
        *,
        tree_id: int | None = None,
        outcome: str | None = "completed",
        limit: int = 100,
    ) -> list[Row]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if tree_id is not None:
            clauses.append("l.tree_id = :tree_id")
            params["tree_id"] = tree_id
        if outcome is not None:
            clauses.append("l.outcome = :outcome")
            params["outcome"] = outcome
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        result = await self._conn.execute(
            text(
                "SELECT l.*, tr.species AS tree_species, tr.variety AS tree_variety"
                " FROM executed_task_log l"
                " JOIN tree tr ON tr.tree_id = l.tree_id"
                f"{where}"
                " ORDER BY l.executed_at DESC"
                " LIMIT :limit"
            ),
            params,
        )
        return [_decode(dict(r)) for r in result.mappings().all()]
