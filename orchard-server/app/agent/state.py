"""Shared state for the Orchestrator graph.

One turn in, one answer out - conversation history arrives in each request
(the graph is stateless, no checkpointer). The Foreman's multi-turn
negotiation lives in ``app/agent/foreman.py`` + ``/api/v1/schedule/*``.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from .orchestrator import Route


class OrchestratorState(TypedDict, total=False):
    messages: Sequence[Any]         # {role, content}-like, newest last
    active_tree_id: int | None
    route: Route
    task_ids: list[int]
    reply: str                     # classifier-supplied text (non-agronomy routes)
    answer: str                    # final assistant text
    redirect: dict[str, str] | None   # {"href": "/schedule", "label": "..."}
    tool_calls: list[dict[str, Any]]  # [{"tool", "args", "result"}]
