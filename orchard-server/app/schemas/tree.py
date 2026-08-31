"""Tree transport models.

``species`` and ``variety`` are free text (no enums); the validation agent
canonicalizes them in the service layer. ``age_days`` / ``age_years`` are
derived from ``planted_date`` on read and never persisted.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class TreeCreate(BaseModel):
    species: str = Field(min_length=1, description="Free text, e.g. 'mango'. Canonicalized on write.")
    variety: str = Field(min_length=1, description="Free text, e.g. 'Kent'. Canonicalized on write.")
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    tree_id: int | None = Field(default=None, gt=0, description="Optional; assigned by the store when omitted.")


class TreeUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    species: str | None = Field(default=None, min_length=1)
    variety: str | None = Field(default=None, min_length=1)
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None


class TreeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tree_id: int
    species: str
    variety: str
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    age_days: int | None = None
    age_years: float | None = None
