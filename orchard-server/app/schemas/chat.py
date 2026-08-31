"""Chat transport models.

Deliberately minimal - no model/provider config lives here. The chat endpoint
streams a stub reply today; these shapes are what a real agent loop would also
consume.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1)
