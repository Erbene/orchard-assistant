"""HTTP surface for irrigation zones.

Zones live in **Rachio**, not our database. Everything here is read-only
except ``POST /{zone_id}/water``, a manual watering run. There are deliberately
no create / update / delete routes - zone configuration is edited in the
official Rachio app.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...dependencies import get_rachio_service_dep
from ...schemas.zone import WaterZoneRequest, ZoneDetail
from ...services.rachio import RachioDevice, RachioService

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[RachioDevice], response_model_by_alias=False)
async def list_zones(rachio: RachioService = Depends(get_rachio_service_dep)):
    """Every Rachio zone, grouped by device. Read-only; 10-minute server cache."""
    return await rachio.get_devices_and_zones()


@router.get("/{zone_id}", response_model=ZoneDetail, response_model_by_alias=False)
async def get_zone(
    zone_id: str, rachio: RachioService = Depends(get_rachio_service_dep)
):
    """Full read-only configuration for one Rachio zone (404 if unknown)."""
    device, zone = await rachio.get_zone(zone_id)
    return ZoneDetail(device_id=device.id, device_name=device.name, zone=zone)


@router.post("/{zone_id}/water", status_code=status.HTTP_202_ACCEPTED)
async def water_zone(
    zone_id: str,
    payload: WaterZoneRequest,
    rachio: RachioService = Depends(get_rachio_service_dep),
) -> dict[str, str]:
    """Start a manual watering run on one zone. **Starts real hardware.**"""
    await rachio.start_zone_watering(zone_id, payload.duration_minutes * 60)
    return {
        "status": "started",
        "zone_id": zone_id,
        "duration_minutes": str(payload.duration_minutes),
    }
