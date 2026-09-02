"""Chat transport models.

The server owns conversation history: a turn is just ``{conversation_id?,
message}``. The server loads prior turns from Postgres, runs the Orchestrator
graph over the whole thread, and appends the user message + the answer.
``ChatMessageIn`` is the internal {role, content} shape the graph consumes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str = Field(min_length=1)
