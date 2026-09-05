"""Zone transport models.

Zone hardware/config lives in Rachio (read-only here). The local ``zone``
table stores an optional grower label; display falls back to the Rachio zone
number.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..services.rachio import RachioZone


class ZoneLabelUpdate(BaseModel):
    """Set or clear the local grower label for a Rachio zone."""

    label: str | None = Field(
        default=None,
        max_length=80,
        description="Display label. Empty or null clears it (fallback to zone number).",
    )


class ZoneLabelRead(BaseModel):
    zone_id: str
    label: str | None = None
    display_name: str
    zone_number: int | None = None


class ZoneDetail(BaseModel):
    """One Rachio zone plus the device it belongs to."""

    device_id: str
    device_name: str
    zone: RachioZone


class WaterZoneRequest(BaseModel):
    """Body for ``POST /api/v1/zones/{zone_id}/water`` - the only zone write."""

    duration_minutes: int = Field(
        gt=0, le=180, description="Manual run length in minutes (1-180)."
    )
