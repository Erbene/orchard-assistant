"""Knowledge-base source transport models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["file", "text"]


class SourceCreate(BaseModel):
    """Internal write model used by the ingestion service (not a request body -
    the HTTP endpoint takes multipart form data)."""

    name: str = Field(min_length=1)
    source_type: SourceType
    file_path: str | None = None
    raw_content: str


class SourceRead(BaseModel):
    """List/summary view - omits the (potentially large) raw content."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: SourceType
    file_path: str | None = None
    upload_date: datetime


class SourceDetail(SourceRead):
    raw_content: str


class SourceRename(BaseModel):
    name: str = Field(min_length=1)


class TreeSourcesUpdate(BaseModel):
    """Replace the full set of sources linked to a tree."""

    source_ids: list[int] = Field(default_factory=list)
