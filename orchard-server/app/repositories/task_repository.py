"""Raw persistence for the ``task`` table.

Repositories deal only in primitives and ``dict`` rows - no Pydantic, no
business rules. Integrity violations propagate as ``sqlite3.IntegrityError``
for the service layer to interpret.
"""
from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]

_COLUMNS = (
    "id",
    "tree_id",
    "action_type",
    "status",
    "priority_score",
    "scheduled_date",
    "frequency_days",
    "created_at",
    "completed_at",
)
_MUTABLE = (
    "action_type",
    "status",
    "priority_score",
    "scheduled_date",
    "frequency_days",
    "completed_at",
)
_INSERTABLE = (
    "tree_id",
    "action_type",
    "status",
    "priority_score",
    "scheduled_date",
    "frequency_days",
)


class TaskRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, task_id: int) -> Row | None:
        cur = self._conn.execute("SELECT * FROM task WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def list(
        self, *, status: str | None = None, tree_id: int | None = None
    ) -> list[Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if tree_id is not None:
            clauses.append("tree_id = ?")
            params.append(tree_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(
            f"SELECT * FROM task{where} ORDER BY priority_score DESC, id ASC",
            params,
        )
        return [dict(r) for r in cur.fetchall()]

    def list_pending(self, *, scheduled_before: str | None = None) -> list[Row]:
        """Pending tasks, highest ``priority_score`` first.

        ``scheduled_before`` (ISO date or datetime) keeps only tasks due on or
        before that day *plus* any unscheduled tasks (they always need placing).
        Unscheduled tasks sort after scheduled ones within the same priority.
        """
        sql = "SELECT * FROM task WHERE status = 'pending'"
        params: list[Any] = []
        if scheduled_before is not None:
            sql += (
                " AND (scheduled_date IS NULL"
                " OR date(scheduled_date) <= date(?))"
            )
            params.append(scheduled_before)
        sql += (
            " ORDER BY priority_score DESC,"
            " scheduled_date IS NULL, scheduled_date ASC, id ASC"
        )
        cur = self._conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def create(self, data: Row) -> Row:
        cols = [c for c in _INSERTABLE if c in data]
        placeholders = ", ".join("?" for _ in cols)
        cur = self._conn.execute(
            f"INSERT INTO task ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        row = self.get(int(cur.lastrowid))
        assert row is not None  # just inserted
        return row

    def update(self, task_id: int, fields: Row) -> Row | None:
        allowed = {k: v for k, v in fields.items() if k in _MUTABLE}
        if allowed:
            assignments = ", ".join(f"{k} = ?" for k in allowed)
            self._conn.execute(
                f"UPDATE task SET {assignments} WHERE id = ?",
                (*allowed.values(), task_id),
            )
        return self.get(task_id)

    def delete(self, task_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
        return cur.rowcount > 0
