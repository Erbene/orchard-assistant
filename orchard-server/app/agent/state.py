"""Shared graph state for the orchard scheduling agent."""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State threaded through every node.

    ``messages`` accumulates (``add_messages`` reducer). The JIT fields below
    start as ``None`` / empty and are filled in over the conversation - the
    Foreman node blocks and asks the user whenever ``available_minutes`` is
    still missing.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    active_tree_id: int | None
    available_minutes: int | None
    confirmed_resources: list[str]
