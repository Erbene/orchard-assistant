"""HTTP surface for the task inbox (the `/schedule` page's list).

    GET  /tasks                  -> pending tasks, priority-then-date, with plan/tree labels
    POST /tasks/{id}/complete    -> mark done  (+ spawn the template's next occurrence)
    POST /tasks/{id}/skip        -> mark skipped (+ still advance the recurrence)
    POST /tasks/{id}/defer       -> push out / unschedule

The Just-In-Time negotiation itself stays at `/api/v1/schedule/*` (the Foreman).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...dependencies import get_task_service
from ...schemas.task import InboxTaskRead, TaskRead
from ...services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[InboxTaskRead])
async def list_inbox(svc: TaskService = Depends(get_task_service)):
    return await svc.inbox()


@router.post("/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.mark_complete(task_id)


@router.post("/{task_id}/skip", response_model=TaskRead)
async def skip_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.skip_task(task_id)


@router.post("/{task_id}/defer", response_model=TaskRead)
async def defer_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.defer_task(task_id)
