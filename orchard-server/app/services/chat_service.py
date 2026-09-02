"""Chat service - loads a conversation thread, runs the Orchestrator graph
over it, streams the answer as SSE events, and appends the turn to history.

The graph does one classify LLM call, then dispatches: a KB-grounded agronomy
answer, a bulk task completion, a refusal, small-talk, or a hand-off to the
``/schedule`` wizard. Ollama is required (the route returns 503 when it's not
reachable). History is server-owned: the client sends only the new message
plus a ``conversation_id`` (omitted on the first turn - a conversation is
created and its id comes back in the ``conversation`` event).
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

from ..config import Settings
from ..core import db
from ..core.logging import get_logger
from ..rag.vector_store import OrchardVectorStore
from ..repositories.conversation_repository import ConversationRepository
from ..repositories.source_repository import SourceRepository
from ..repositories.task_repository import TaskRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.chat import ChatMessageIn
from .conversation_service import ConversationService
from .source_service import SourceService
from .task_service import TaskService

_log = get_logger("app.chat")


def _word_chunks(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text) or [""]


class ChatService:
    def __init__(self, store: OrchardVectorStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    async def stream_reply(
        self, *, conversation_id: int | None, message: str
    ) -> AsyncIterator[dict]:
        """Yield event dicts: ``conversation`` (first), then ``tool`` /
        ``text-delta`` / ``redirect``. The route wraps each as an SSE frame and
        adds start/finish.

        Opens its own DB connection for the whole turn - a request-scoped
        ``Depends`` connection is torn down before this generator drains
        (FastAPI closes ``yield`` deps when the endpoint returns the
        ``StreamingResponse``, not when it finishes streaming)."""
        from ..agent.graph import build_graph  # lazy: avoids an import cycle

        async with db.connection(self._settings) as conn:
            convos = ConversationService(ConversationRepository(conn))
            cid, is_new = await convos.open_turn(conversation_id, message)
            history = await convos.history(cid)
            await convos.record_user(cid, message)

            sources = SourceService(
                SourceRepository(conn), TreeRepository(conn), self._store, self._settings
            )
            tasks = TaskService(TaskRepository(conn), TreeRepository(conn))
            graph = build_graph(sources, tasks, self._settings)

            turn = [*history, ChatMessageIn(role="user", content=message)]
            result = await graph.ainvoke({"messages": turn})

            answer = result.get("answer", "") or ""
            tool_calls = result.get("tool_calls") or []
            redirect = result.get("redirect")
            meta = {
                k: v
                for k, v in {
                    "route": result.get("route"),
                    "tool_calls": tool_calls,
                    "redirect": redirect,
                }.items()
                if v
            }
            await convos.record_assistant(cid, answer, meta)
            title = await convos.title_of(cid)

        yield {"type": "conversation", "id": cid, "title": title, "new": is_new}
        for call in tool_calls:
            yield {
                "type": "tool",
                "toolName": call["tool"],
                "args": call["args"],
                "result": call["result"],
            }
        for chunk in _word_chunks(answer):
            yield {"type": "text-delta", "delta": chunk}
        if redirect:
            yield {"type": "redirect", **redirect}

        _log.info("chat.turn", conversation_id=cid, route=result.get("route"))
