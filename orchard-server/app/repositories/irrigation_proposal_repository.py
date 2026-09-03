"""Raw persistence for ``irrigation_proposal`` - the HITL approval queue,
one row per supervisor deliberation (keyed by the LangGraph ``thread_id``).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]


def _decode(row: Row) -> Row:
    for col in ("payload", "result"):
        value = row.get(col)
        if isinstance(value, str):
            row[col] = json.loads(value)
    return row


class IrrigationProposalRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, thread_id: str) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM irrigation_proposal WHERE thread_id = :t"),
            {"t": thread_id},
        )
        row = result.mappings().first()
        return _decode(dict(row)) if row is not None else None

    async def list(self, *, status: str | None = None, limit: int = 100) -> list[Row]:
        sql = "SELECT * FROM irrigation_proposal"
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            sql += " WHERE status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        result = await self._conn.execute(text(sql), params)
        return [_decode(dict(r)) for r in result.mappings().all()]

    async def upsert(self, data: Row) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO irrigation_proposal"
                " (thread_id, zone_id, for_date, status, action, summary, payload, result, resolved_at)"
                " VALUES (:thread_id, :zone_id, :for_date, :status, :action, :summary,"
                " CAST(:payload AS jsonb), CAST(:result AS jsonb), :resolved_at)"
                " ON CONFLICT (thread_id) DO UPDATE SET"
                " status = EXCLUDED.status, action = EXCLUDED.action,"
                " summary = EXCLUDED.summary, payload = EXCLUDED.payload,"
                " result = EXCLUDED.result, resolved_at = EXCLUDED.resolved_at"
                " RETURNING *"
            ),
            {
                "thread_id": data["thread_id"],
                "zone_id": data["zone_id"],
                "for_date": data["for_date"],
                "status": data.get("status", "pending"),
                "action": data["action"],
                "summary": data.get("summary", ""),
                "payload": json.dumps(data.get("payload") or {}, default=str),
                "result": json.dumps(data["result"], default=str) if data.get("result") else None,
                "resolved_at": data.get("resolved_at"),
            },
        )
        return _decode(dict(result.mappings().one()))

    async def resolve(self, thread_id: str, status: str, result: dict | None) -> Row | None:
        await self._conn.execute(
            text(
                "UPDATE irrigation_proposal SET status = :s,"
                " result = CAST(:r AS jsonb), resolved_at = :at WHERE thread_id = :t"
            ),
            {
                "s": status,
                "r": json.dumps(result, default=str) if result is not None else None,
                "at": datetime.now(timezone.utc),
                "t": thread_id,
            },
        )
        return await self.get(thread_id)
