"""Zone transport models.

Zones are the grower's **Rachio** irrigation zones, read live and **read-only**
(all configuration is edited in the Rachio app). The rich device/zone objects
are ``RachioDevice`` / ``RachioZone`` in ``app/services/rachio.py``; this
module only adds the request/response wrappers the router needs.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..services.rachio import RachioZone


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
