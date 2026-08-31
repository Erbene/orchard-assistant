"""Zone transport models.

All descriptive fields are free text - no enums, no closed vocabularies. The
service layer runs them through the validation agent only for light
normalization. ``zone_id`` is assigned by the database (auto-increment).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1)
    soil_drainage: str | None = Field(
        default=None,
        description="Free text, e.g. 'sandy fast draining', 'fast', 'heavy clay'.",
    )
    water_source: str | None = Field(
        default=None,
        description="Free text - irrigation water source (well, canal, municipal, rainwater, …).",
    )


class ZoneUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    soil_drainage: str | None = None
    water_source: str | None = None


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zone_id: int
    name: str
    soil_drainage: str | None = None
    water_source: str | None = None
