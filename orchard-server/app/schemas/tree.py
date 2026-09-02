"""Tree transport models.

``species`` and ``variety`` are free text - no enums, no closed vocabularies;
the validation agent only normalizes whitespace. ``age_days`` / ``age_years``
are derived from ``planted_date`` on read and never persisted.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


_HEIGHT = Field(default=None, gt=0, le=99, description="Canopy height in metres (Care Plan scaling).")
_SPREAD = Field(default=None, gt=0, le=99, description="Canopy spread in metres; defaults to 0.6 * height.")


class TreeCreate(BaseModel):
    species: str = Field(min_length=1, description="Free text, e.g. 'mango'.")
    variety: str = Field(min_length=1, description="Free text, e.g. 'Kent'.")
    zone_id: str | None = Field(
        default=None, description="Rachio zone id this tree is irrigated by (free text; not validated)."
    )
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    height_m: float | None = _HEIGHT
    canopy_spread_m: float | None = _SPREAD
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
    height_m: float | None = _HEIGHT
    canopy_spread_m: float | None = _SPREAD


class TreeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tree_id: int
    species: str
    variety: str
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    height_m: float | None = None
    canopy_spread_m: float | None = None
    has_care_plan: bool = False   # only the list endpoint sets this
    age_days: int | None = None
    age_years: float | None = None
