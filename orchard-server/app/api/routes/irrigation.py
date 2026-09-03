"""HTTP surface for the Irrigation workflow (Phase 3).

    GET  /irrigation/overview                       -> schedule + supervisor config + queue size
    PUT  /irrigation/config/supervisor              -> {frequency_hours?, auto_approve_skips?}
    PUT  /irrigation/config/zones/{zone_id}         -> baseline minutes / days / supervised
    POST /irrigation/supervisor/run                 -> run the deliberation flow now
    GET  /irrigation/proposals?status=pending       -> the HITL approval queue
    POST /irrigation/proposals/{thread_id}/approve  -> resume the graph past the interrupt
    POST /irrigation/proposals/{thread_id}/reject   -> abort
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...dependencies import (
    get_irrigation_config_service,
    get_irrigation_supervisor_service,
)
from ...schemas.irrigation import (
    IrrigationOverview,
    SupervisorConfig,
    SupervisorConfigUpdate,
    SupervisorProposal,
    SupervisorRunResult,
    ZoneConfig,
    ZoneConfigUpdate,
)
from ...services.irrigation_service import (
    IrrigationConfigService,
    IrrigationSupervisorService,
)
from pydantic import BaseModel, Field

router = APIRouter(prefix="/irrigation", tags=["irrigation"])


class _RunRequest(BaseModel):
    zone_ids: list[str] | None = Field(default=None)


@router.get("/overview", response_model=IrrigationOverview)
async def overview(svc: IrrigationConfigService = Depends(get_irrigation_config_service)):
    return await svc.overview()


@router.put("/config/supervisor", response_model=SupervisorConfig)
async def update_supervisor_config(
    payload: SupervisorConfigUpdate,
    svc: IrrigationConfigService = Depends(get_irrigation_config_service),
):
    return await svc.update_supervisor(payload)


@router.put("/config/zones/{zone_id}", response_model=ZoneConfig)
async def update_zone_config(
    zone_id: str,
    payload: ZoneConfigUpdate,
    svc: IrrigationConfigService = Depends(get_irrigation_config_service),
):
    return await svc.update_zone(zone_id, payload)


@router.post("/supervisor/run", response_model=SupervisorRunResult)
async def run_supervisor(
    payload: _RunRequest | None = None,
    svc: IrrigationSupervisorService = Depends(get_irrigation_supervisor_service),
):
    return await svc.run(zone_ids=(payload.zone_ids if payload else None))


@router.get("/proposals", response_model=list[SupervisorProposal])
async def list_proposals(
    status: str | None = None,
    svc: IrrigationSupervisorService = Depends(get_irrigation_supervisor_service),
):
    return await svc.list_proposals(status=status)


@router.post("/proposals/{thread_id}/approve", response_model=SupervisorProposal)
async def approve_proposal(
    thread_id: str,
    svc: IrrigationSupervisorService = Depends(get_irrigation_supervisor_service),
):
    return await svc.approve(thread_id)


@router.post("/proposals/{thread_id}/reject", response_model=SupervisorProposal)
async def reject_proposal(
    thread_id: str,
    svc: IrrigationSupervisorService = Depends(get_irrigation_supervisor_service),
):
    return await svc.reject(thread_id)
