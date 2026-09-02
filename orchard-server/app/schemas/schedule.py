"""Transport models for the Foreman's JIT scheduling loop (``/api/v1/schedule``)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ScheduleStep = Literal["need_time", "need_resources", "done"]


class ScheduleTask(BaseModel):
    id: int
    tree_id: int
    action_type: str
    estimated_minutes: int | None = None
    priority_score: float = 0.0
    effective_score: float | None = None
    required_resources: list[str] = Field(default_factory=list)
    escalated: bool = False
    drop_reason: str | None = None


class ScheduleEscalation(BaseModel):
    task_id: int
    action_type: str
    days_late: int
    multiplier: float
    reason: str


class ScheduleState(BaseModel):
    thread_id: str
    step: ScheduleStep
    available_minutes: int | None = None
    required_resources: list[str] = Field(default_factory=list)
    proposed_tasks: list[ScheduleTask] = Field(default_factory=list)
    dropped_tasks: list[ScheduleTask] = Field(default_factory=list)
    escalations: list[ScheduleEscalation] = Field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PlanRequest(BaseModel):
    available_minutes: int | None = Field(default=None, gt=0, le=1440)


class ResumeRequest(BaseModel):
    thread_id: str
    available_minutes: int | None = Field(default=None, gt=0, le=1440)
    have_resources: list[str] | None = None


class ReportRequest(BaseModel):
    thread_id: str | None = None
    text: str = Field(min_length=1)


class ReportResult(BaseModel):
    marked: list[int] = Field(default_factory=list)
    note: str


class CompleteRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1)
