"""Transport models for persisted assistant conversations (`/api/v1/conversations`)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)
