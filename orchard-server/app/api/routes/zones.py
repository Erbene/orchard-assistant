"""HTTP surface for zones. Parse request -> call service -> shape response.
No business logic, no SQL, no validation rules live here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...dependencies import get_zone_service
from ...schemas.zone import ZoneCreate, ZoneRead, ZoneUpdate
from ...services.zone_service import ZoneService

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[ZoneRead])
async def list_zones(service: ZoneService = Depends(get_zone_service)):
    return await service.list_zones()


@router.get("/{zone_id}", response_model=ZoneRead)
async def get_zone(zone_id: str, service: ZoneService = Depends(get_zone_service)):
    return await service.get_zone(zone_id)


@router.post("", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
async def create_zone(
    payload: ZoneCreate, service: ZoneService = Depends(get_zone_service)
):
    return await service.create_zone(payload)


@router.patch("/{zone_id}", response_model=ZoneRead)
async def update_zone(
    zone_id: str,
    payload: ZoneUpdate,
    service: ZoneService = Depends(get_zone_service),
):
    return await service.update_zone(zone_id, payload)


@router.delete(
    "/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_zone(zone_id: str, service: ZoneService = Depends(get_zone_service)):
    await service.delete_zone(zone_id)
