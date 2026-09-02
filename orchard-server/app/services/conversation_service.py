"""Conversation history: list / read / rename / delete, plus the turn helpers
``ChatService`` uses to load a thread and append to it.

HTTP-agnostic; raises ``NotFoundError``. The Orchestrator graph stays
stateless - this is the durable store it reads from and writes back to.
"""
from __future__ import annotations

import re

from ..repositories.conversation_repository import ConversationRepository
from ..schemas.chat import ChatMessageIn
from ..schemas.conversation import ChatMessageRead, ConversationDetail, ConversationRead
from .exceptions import NotFoundError

_TITLE_MAX = 60


def title_from(message: str) -> str:
    """A short conversation title from the first user message."""
    flat = re.sub(r"\s+", " ", message).strip()
    if len(flat) <= _TITLE_MAX:
        return flat or "New conversation"
    return flat[:_TITLE_MAX].rsplit(" ", 1)[0] + "…"


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self._repo = conversations

    # -- CRUD over history --------------------------------------

    async def list(self) -> list[ConversationRead]:
        return [ConversationRead.model_validate(r) for r in await self._repo.list()]

    async def detail(self, conversation_id: int) -> ConversationDetail:
        row = await self._repo.get(conversation_id)
        if row is None:
            raise NotFoundError(f"conversation {conversation_id} not found")
        messages = [
            ChatMessageRead.model_validate(m)
            for m in await self._repo.messages(conversation_id)
        ]
        return ConversationDetail(**row, messages=messages)

    async def rename(self, conversation_id: int, title: str) -> ConversationRead:
        row = await self._repo.rename(conversation_id, title.strip())
        if row is None:
            raise NotFoundError(f"conversation {conversation_id} not found")
        return ConversationRead.model_validate(row)

    async def delete(self, conversation_id: int) -> None:
        if not await self._repo.delete(conversation_id):
            raise NotFoundError(f"conversation {conversation_id} not found")

    # -- turn helpers (used by ChatService) --------------------

    async def open_turn(
        self, conversation_id: int | None, first_message: str
    ) -> tuple[int, bool]:
        """Resolve the conversation for this turn, creating one if needed.
        Returns ``(id, is_new)``. Raises ``NotFoundError`` for a stale id."""
        if conversation_id is not None:
            if await self._repo.get(conversation_id) is None:
                raise NotFoundError(f"conversation {conversation_id} not found")
            return conversation_id, False
        row = await self._repo.create(title=title_from(first_message))
        return row["id"], True

    async def history(self, conversation_id: int) -> list[ChatMessageIn]:
        return [
            ChatMessageIn(role=m["role"], content=m["content"])
            for m in await self._repo.messages(conversation_id)
        ]

    async def record_user(self, conversation_id: int, content: str) -> None:
        await self._repo.add_message(conversation_id, "user", content, {})

    async def record_assistant(
        self, conversation_id: int, content: str, meta: dict
    ) -> None:
        await self._repo.add_message(conversation_id, "assistant", content, meta)
        await self._repo.touch(conversation_id)

    async def title_of(self, conversation_id: int) -> str:
        row = await self._repo.get(conversation_id)
        return row["title"] if row else ""
