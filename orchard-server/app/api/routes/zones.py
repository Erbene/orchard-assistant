"""HTTP surface for irrigation zones.

Zone hardware/config lives in **Rachio** (read-only except a manual water
run). Local grower labels live in our ``zone`` table and overlay every
Rachio zone in the response.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...dependencies import get_rachio_service_dep, get_zone_service
from ...schemas.zone import (
    WaterZoneRequest,
    ZoneDetail,
    ZoneInUseRead,
    ZoneInUseUpdate,
    ZoneLabelRead,
    ZoneLabelUpdate,
)
from ...services.rachio import RachioDevice, RachioService
from ...services.zone_service import ZoneService

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[RachioDevice], response_model_by_alias=False)
async def list_zones(
    rachio: RachioService = Depends(get_rachio_service_dep),
    zones: ZoneService = Depends(get_zone_service),
):
    """Every Rachio zone, grouped by device, with local labels applied."""
    devices = await rachio.get_devices_and_zones()
    return await zones.overlay_devices(devices)


@router.put("/{zone_id}/label", response_model=ZoneLabelRead)
async def set_zone_label(
    zone_id: str,
    payload: ZoneLabelUpdate,
    zones: ZoneService = Depends(get_zone_service),
):
    """Set or clear the local display label for a Rachio zone."""
    return await zones.set_label(zone_id, payload.label)


@router.put("/{zone_id}/in-use", response_model=ZoneInUseRead)
async def set_zone_in_use(
    zone_id: str,
    payload: ZoneInUseUpdate,
    zones: ZoneService = Depends(get_zone_service),
):
    """Mark a zone as in use or unused. Unused zones stay off planning surfaces."""
    return await zones.set_in_use(zone_id, payload.in_use)


@router.get("/{zone_id}", response_model=ZoneDetail, response_model_by_alias=False)
async def get_zone(
    zone_id: str,
    rachio: RachioService = Depends(get_rachio_service_dep),
    zones: ZoneService = Depends(get_zone_service),
):
    """Full read-only Rachio configuration for one zone, plus the local label."""
    device, zone = await rachio.get_zone(zone_id)
    return ZoneDetail(
        device_id=device.id,
        device_name=device.name,
        zone=await zones.overlay_zone(zone),
    )


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
