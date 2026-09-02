"""Raw persistence for ``conversation`` and its ``chat_message`` rows.

``meta`` is a ``jsonb`` column (route / tool_calls / redirect for an assistant
turn); a bare ``text()`` query carries no column typing, so it's written with
an explicit ``CAST(:meta AS jsonb)`` over JSON text and read back tolerantly.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]


def _decode(row: Row) -> Row:
    value = row.get("meta")
    row["meta"] = json.loads(value) if isinstance(value, str) else (value or {})
    return row


class ConversationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # -- conversations ---------------------------------------------

    async def create(self, *, title: str) -> Row:
        result = await self._conn.execute(
            text("INSERT INTO conversation (title) VALUES (:title) RETURNING *"),
            {"title": title},
        )
        return dict(result.mappings().one())

    async def get(self, conversation_id: int) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM conversation WHERE id = :id"), {"id": conversation_id}
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def list(self) -> list[Row]:
        result = await self._conn.execute(
            text("SELECT * FROM conversation ORDER BY updated_at DESC, id DESC")
        )
        return [dict(r) for r in result.mappings().all()]

    async def rename(self, conversation_id: int, title: str) -> Row | None:
        await self._conn.execute(
            text(
                "UPDATE conversation SET title = :title, updated_at = now()"
                " WHERE id = :id"
            ),
            {"title": title, "id": conversation_id},
        )
        return await self.get(conversation_id)

    async def touch(self, conversation_id: int) -> None:
        await self._conn.execute(
            text("UPDATE conversation SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )

    async def delete(self, conversation_id: int) -> bool:
        result = await self._conn.execute(
            text("DELETE FROM conversation WHERE id = :id"), {"id": conversation_id}
        )
        return result.rowcount > 0

    # -- messages -------------------------------------------------

    async def add_message(
        self, conversation_id: int, role: str, content: str, meta: dict[str, Any]
    ) -> Row:
        result = await self._conn.execute(
            text(
                "INSERT INTO chat_message (conversation_id, role, content, meta)"
                " VALUES (:cid, :role, :content, CAST(:meta AS jsonb)) RETURNING *"
            ),
            {
                "cid": conversation_id,
                "role": role,
                "content": content,
                "meta": json.dumps(meta or {}),
            },
        )
        return _decode(dict(result.mappings().one()))

    async def messages(self, conversation_id: int) -> list[Row]:
        result = await self._conn.execute(
            text(
                "SELECT * FROM chat_message WHERE conversation_id = :cid ORDER BY id ASC"
            ),
            {"cid": conversation_id},
        )
        return [_decode(dict(r)) for r in result.mappings().all()]
