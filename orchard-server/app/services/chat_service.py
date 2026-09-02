"""Chat service - runs the Orchestrator graph and yields SSE events.

The graph does one classify LLM call, then dispatches: a KB-grounded agronomy
answer, a bulk task completion, a refusal, small-talk, or a hand-off to the
``/schedule`` wizard. Ollama is required (the route returns 503 when it's not
reachable).
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from ..config import Settings
from ..core import db
from ..core.logging import get_logger
from ..rag.vector_store import OrchardVectorStore
from ..repositories.source_repository import SourceRepository
from ..repositories.task_repository import TaskRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.chat import ChatMessageIn
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
        self, messages: Sequence[ChatMessageIn]
    ) -> AsyncIterator[dict]:
        """Yield event dicts: ``{"type": "tool" | "text-delta" | "redirect", ...}``.
        The route wraps each as an SSE frame and adds start/finish.

        The graph opens its own DB connection for the whole turn - a
        request-scoped ``Depends`` connection is torn down before this
        generator runs (FastAPI closes ``yield`` dependencies when the
        endpoint returns the ``StreamingResponse``, not when it drains)."""
        from ..agent.graph import build_graph  # lazy: avoids an import cycle

        async with db.connection(self._settings) as conn:
            sources = SourceService(
                SourceRepository(conn), TreeRepository(conn), self._store, self._settings
            )
            tasks = TaskService(TaskRepository(conn), TreeRepository(conn))
            graph = build_graph(sources, tasks, self._settings)
            result = await graph.ainvoke({"messages": list(messages)})

        for call in result.get("tool_calls", []):
            yield {
                "type": "tool",
                "toolName": call["tool"],
                "args": call["args"],
                "result": call["result"],
            }
        for chunk in _word_chunks(result.get("answer", "")):
            yield {"type": "text-delta", "delta": chunk}
        if result.get("redirect"):
            yield {"type": "redirect", **result["redirect"]}

        _log.info("chat.turn", route=result.get("route"))
