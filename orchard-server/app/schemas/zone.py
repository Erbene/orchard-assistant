"""Zone transport models.

Categorical fields (``soil_drainage``) are plain ``str`` - no enums. The
service layer hands them to the validation agent, which decides whether the
value is domain-valid and returns a canonical form.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ZoneCreate(BaseModel):
    zone_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    soil_drainage: str | None = Field(
        default=None,
        description="Free text, e.g. 'sandy fast draining', 'loam'. Canonicalized on write.",
    )


class ZoneUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    soil_drainage: str | None = None


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zone_id: str
    name: str
    soil_drainage: str | None = None
