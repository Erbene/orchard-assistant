"""HTTP surface for the Foreman's interactive JIT scheduling loop.

    POST /plan     -> starts a session, returns the first interrupt (need_time)
    POST /resume   -> answers an interrupt, returns the next step or the schedule
    POST /report   -> "I finished task 3 and 5" -> marks them complete
    POST /complete -> the UI "Mark Complete" button (bulk)

Only /report and /complete write to the database.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...dependencies import get_foreman_service
from ...schemas.schedule import (
    CompleteRequest,
    PlanRequest,
    ReportRequest,
    ReportResult,
    ResumeRequest,
    ScheduleState,
)
from ...schemas.task import TaskRead
from ...services.exceptions import DomainValidationError
from ...services.foreman_service import ForemanService

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/plan", response_model=ScheduleState)
async def plan(
    payload: PlanRequest, svc: ForemanService = Depends(get_foreman_service)
):
    return await svc.start(payload.available_minutes)


@router.post("/resume", response_model=ScheduleState)
async def resume(
    payload: ResumeRequest, svc: ForemanService = Depends(get_foreman_service)
):
    if payload.have_resources is not None:
        value: object = payload.have_resources
    elif payload.available_minutes is not None:
        value = payload.available_minutes
    else:
        raise DomainValidationError("resume", "provide available_minutes or have_resources")
    return await svc.resume(payload.thread_id, value)


@router.post("/report", response_model=ReportResult)
async def report(
    payload: ReportRequest, svc: ForemanService = Depends(get_foreman_service)
):
    marked, note = await svc.report(payload.text)
    return ReportResult(marked=marked, note=note)


@router.post("/complete", response_model=list[TaskRead])
async def complete(
    payload: CompleteRequest, svc: ForemanService = Depends(get_foreman_service)
):
    return await svc.complete(payload.task_ids)
