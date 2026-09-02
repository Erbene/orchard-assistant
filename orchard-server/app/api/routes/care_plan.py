"""HTTP surface for the per-tree Care Plan.

    GET    /trees/{id}/care-plan            -> templates + baseline questions
    POST   /trees/{id}/care-plan/generate   -> run the Agronomist, replace the plan (503 if Ollama down)
    POST   /trees/{id}/care-plan/baseline   -> answers -> materialise the first tasks
    PATCH  /care-plan/templates/{id}        -> edit a template (re-scales, resyncs the open task)
    DELETE /care-plan/templates/{id}        -> remove a template + its open task
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...dependencies import get_care_plan_service
from ...schemas.care_plan import (
    BaselineRequest,
    CarePlan,
    TaskTemplateRead,
    TaskTemplateUpdate,
)
from ...schemas.task import TaskRead
from ...services.care_plan_service import CarePlanService

router = APIRouter(tags=["care-plan"])


@router.get("/trees/{tree_id}/care-plan", response_model=CarePlan)
async def get_care_plan(
    tree_id: int, svc: CarePlanService = Depends(get_care_plan_service)
):
    return await svc.get_plan(tree_id)


@router.post("/trees/{tree_id}/care-plan/generate", response_model=CarePlan)
async def generate_care_plan(
    tree_id: int, svc: CarePlanService = Depends(get_care_plan_service)
):
    return await svc.generate(tree_id)


@router.post(
    "/trees/{tree_id}/care-plan/baseline", response_model=list[TaskRead]
)
async def apply_baseline(
    tree_id: int,
    payload: BaselineRequest,
    svc: CarePlanService = Depends(get_care_plan_service),
):
    return await svc.apply_baseline(tree_id, payload.answers)


@router.patch("/care-plan/templates/{template_id}", response_model=TaskTemplateRead)
async def update_template(
    template_id: int,
    payload: TaskTemplateUpdate,
    svc: CarePlanService = Depends(get_care_plan_service),
):
    return await svc.update_template(template_id, payload)


@router.delete(
    "/care-plan/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_template(
    template_id: int, svc: CarePlanService = Depends(get_care_plan_service)
):
    await svc.delete_template(template_id)
