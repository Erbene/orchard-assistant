"""Raw persistence for the ``task`` table.

Repositories deal only in primitives and ``dict`` rows - no Pydantic, no
business rules. ``required_resources`` is a ``jsonb`` column; a bare
``text()`` query carries no SQLAlchemy column typing, so it's written with an
explicit ``CAST(... AS jsonb)`` over a JSON-text bind param, and read back
tolerantly (asyncpg may hand back either the raw JSON text or an
already-decoded ``list`` depending on driver-level codecs - accept both
rather than assume one).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_MUTABLE = (
    "action_type",
    "status",
    "priority_score",
    "scheduled_date",
    "frequency_days",
    "estimated_minutes",
    "required_resources",
    "completed_at",
    "template_id",
)
_INSERTABLE = (
    "tree_id",
    "template_id",
    "action_type",
    "status",
    "priority_score",
    "scheduled_date",
    "frequency_days",
    "estimated_minutes",
    "required_resources",
)
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


def _column_sql(col: str) -> str:
    """Bind placeholder for one column. ``required_resources`` arrives as JSON
    text and needs an explicit jsonb cast (a bare ``text()`` query carries no
    column typing); ``CAST(:x AS jsonb)`` not ``:x::jsonb`` because SQLAlchemy's
    bind-param scanner rejects a name immediately followed by ``::``.
    Datetime/date columns get native objects from the service layer - no cast.
    """
    return f"CAST(:{col} AS jsonb)" if col in _JSON_COLUMNS else f":{col}"


class TaskRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, task_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM task WHERE id = :id"), {"id": task_id}
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

    async def list(
        self, *, status: str | None = None, tree_id: int | None = None
    ) -> list[Row]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if tree_id is not None:
            clauses.append("tree_id = :tree_id")
            params["tree_id"] = tree_id
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        result = await self._conn.execute(
            text(f"SELECT * FROM task{where} ORDER BY priority_score DESC, id ASC"),
            params,
        )
        return [_decode(dict(r)) for r in result.mappings().all()]

    async def list_pending(self, *, scheduled_before: date | None = None) -> list[Row]:
        """Pending tasks, highest ``priority_score`` first.

        ``scheduled_before`` (a ``date``) keeps only tasks due on or before that
        day *plus* any unscheduled task (those always need placing).
        """
        sql = (
            "SELECT t.*, tt.valid_months AS template_valid_months,"
            " tt.category AS template_category"
            " FROM task t"
            " LEFT JOIN task_templates tt ON tt.id = t.template_id"
            " WHERE t.status = 'pending'"
        )
        params: dict[str, Any] = {}
        if scheduled_before is not None:
            sql += " AND (scheduled_date IS NULL OR scheduled_date::date <= :before)"
            params["before"] = scheduled_before
        sql += (
            " ORDER BY priority_score DESC,"
            " scheduled_date IS NULL, scheduled_date ASC, id ASC"
        )
        result = await self._conn.execute(text(sql), params)
        rows: list[Row] = []
        for r in result.mappings().all():
            row = _decode(dict(r))
            vm = row.get("template_valid_months")
            row["template_valid_months"] = (
                json.loads(vm) if isinstance(vm, str) else (vm or [])
            )
            rows.append(row)
        return rows

    async def list_recent_completions(self, *, within_days: int = 90) -> list[Row]:
        """Completed tasks joined to template category + blocks (scheduling rules)."""
        result = await self._conn.execute(
            text(
                "SELECT t.tree_id, t.completed_at, tt.category AS template_category,"
                " tt.blocks AS template_blocks"
                " FROM task t"
                " JOIN task_templates tt ON tt.id = t.template_id"
                " WHERE t.status = 'completed'"
                " AND t.completed_at >= now() - make_interval(days => :days)"
                " ORDER BY t.completed_at DESC"
            ),
            {"days": within_days},
        )
        rows: list[Row] = []
        for r in result.mappings().all():
            row = dict(r)
            blocks = row.get("template_blocks")
            if isinstance(blocks, str):
                row["template_blocks"] = json.loads(blocks)
            elif blocks is None:
                row["template_blocks"] = []
            rows.append(row)
        return rows

    async def create(self, data: Row) -> Row:
        data = _encode(data)
        cols = [c for c in _INSERTABLE if c in data]
        placeholders = ", ".join(_column_sql(c) for c in cols)
        result = await self._conn.execute(
            text(
                f"INSERT INTO task ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *"
            ),
            {c: data[c] for c in cols},
        )
        return _decode(dict(result.mappings().one()))

    async def update(self, task_id: int, fields: Row) -> Row | None:
        allowed = _encode({k: v for k, v in fields.items() if k in _MUTABLE})
        if allowed:
            assignments = ", ".join(f"{k} = {_column_sql(k)}" for k in allowed)
            await self._conn.execute(
                text(f"UPDATE task SET {assignments} WHERE id = :task_id"),
                {**allowed, "task_id": task_id},
            )
        return await self.get(task_id)

    async def delete(self, task_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM task WHERE id = :id"), {"id": task_id}
        )
        return result.rowcount > 0

    # -- Care Plan support ------------------------------------------

    async def open_for_template(self, template_id: int) -> Row | None:
        """The single non-closed (pending/deferred) task for a template, if any."""
        result = await self._conn.execute(
            text(
                "SELECT * FROM task WHERE template_id = :tid"
                " AND status IN ('pending', 'deferred')"
                " ORDER BY id DESC LIMIT 1"
            ),
            {"tid": template_id},
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

    async def delete_open_for_template(self, template_id: int) -> None:
        await self._conn.execute(
            text(
                "DELETE FROM task WHERE template_id = :tid"
                " AND status IN ('pending', 'deferred')"
            ),
            {"tid": template_id},
        )

    async def inbox(self) -> list[Row]:
        """Pending tasks for the schedule inbox, joined to their template for
        display (category / plan name / computed resource amounts)."""
        result = await self._conn.execute(
            text(
                "SELECT t.*, tt.name AS template_name, tt.category AS template_category,"
                " tt.resource_plan AS template_resource_plan,"
                " tt.valid_months AS template_valid_months,"
                " tr.species AS tree_species, tr.variety AS tree_variety"
                " FROM task t"
                " LEFT JOIN task_templates tt ON tt.id = t.template_id"
                " JOIN tree tr ON tr.tree_id = t.tree_id"
                " WHERE t.status = 'pending'"
                " ORDER BY t.priority_score DESC,"
                " t.scheduled_date IS NULL, t.scheduled_date ASC, t.id ASC"
            )
        )
        rows: list[Row] = []
        for r in result.mappings().all():
            row = _decode(dict(r))
            rp = row.get("template_resource_plan")
            row["template_resource_plan"] = (
                json.loads(rp) if isinstance(rp, str) else (rp or [])
            )
            vm = row.get("template_valid_months")
            row["template_valid_months"] = (
                json.loads(vm) if isinstance(vm, str) else (vm or [])
            )
            rows.append(row)
        return rows
