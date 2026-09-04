"""HTTP surface for the task inbox (the `/schedule` page's list).

    GET  /tasks                  -> pending tasks, priority-then-date, with plan/tree labels
    GET  /tasks/history          -> executed work log (completed by default)
    POST /tasks/{id}/complete    -> mark done  (+ spawn the template's next occurrence)
    POST /tasks/{id}/skip        -> mark skipped (+ still advance the recurrence)
    POST /tasks/{id}/defer       -> push out / unschedule

The Just-In-Time negotiation itself stays at `/api/v1/schedule/*` (the Foreman).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_task_service
from ...schemas.task import ExecutedTaskRead, InboxTaskRead, TaskRead
from ...services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[InboxTaskRead])
async def list_inbox(svc: TaskService = Depends(get_task_service)):
    return await svc.inbox()


@router.get("/history", response_model=list[ExecutedTaskRead])
async def task_history(
    tree_id: int | None = None,
    outcome: Literal["completed", "skipped"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    svc: TaskService = Depends(get_task_service),
):
    return await svc.list_history(tree_id=tree_id, outcome=outcome, limit=limit)


@router.post("/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.mark_complete(task_id)


@router.post("/{task_id}/skip", response_model=TaskRead)
async def skip_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.skip_task(task_id)


@router.post("/{task_id}/defer", response_model=TaskRead)
async def defer_task(task_id: int, svc: TaskService = Depends(get_task_service)):
    return await svc.defer_task(task_id)
