"""Task transport models (JIT scheduling model).

A ``Task`` is a unit of orchard work linked to one ``Tree``. ``action_type``
is free text; ``status`` is a state-machine field constrained to
``pending`` / ``completed`` / ``deferred``. ``estimated_minutes`` and
``required_resources`` feed the Just-In-Time scheduling fit.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "completed", "deferred", "skipped"]


class TaskBase(BaseModel):
    action_type: str = Field(
        min_length=1,
        description="Free-text work type, e.g. 'prune', 'fertilize', 'irrigate'.",
    )
    priority_score: float = Field(
        default=0.0, description="Relative urgency; higher sorts first in the queue."
    )
    scheduled_date: datetime | None = Field(
        default=None, description="When the task is planned. NULL = needs placing."
    )
    frequency_days: int | None = Field(
        default=None, gt=0, description="If set, the task recurs every N days."
    )
    estimated_minutes: int | None = Field(
        default=None,
        gt=0,
        description="Estimated hands-on labor time in minutes (used for JIT fit).",
    )
    required_resources: list[str] = Field(
        default_factory=list,
        description="Free-text names of products/equipment the task needs.",
    )


class TaskCreate(TaskBase):
    tree_id: int = Field(gt=0, description="Id of the tree this task belongs to.")
    status: TaskStatus = "pending"


class TaskUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    action_type: str | None = Field(default=None, min_length=1)
    status: TaskStatus | None = None
    priority_score: float | None = None
    scheduled_date: datetime | None = None
    frequency_days: int | None = Field(default=None, gt=0)
    estimated_minutes: int | None = Field(default=None, gt=0)
    required_resources: list[str] | None = None


class TaskPriorityUpdate(BaseModel):
    """One row of a batch priority / schedule update."""

    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)
    priority_score: float | None = Field(
        default=None, description="New priority score, or omit to leave unchanged."
    )
    scheduled_date: datetime | None = Field(
        default=None, description="New scheduled datetime, or omit to leave unchanged."
    )


class TaskBaselineItem(BaseModel):
    """One baseline task the LLM must fully specify (minutes + resources are
    REQUIRED here - the JIT model needs them up front)."""

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1)
    estimated_minutes: int = Field(gt=0)
    required_resources: list[str] = Field(default_factory=list)
    priority_score: float = 0.0
    frequency_days: int | None = Field(default=None, gt=0)
    scheduled_date: datetime | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tree_id: int
    template_id: int | None = None
    template_category: str | None = None
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None = None
    window_closes_on: date | None = None
    out_of_season: bool = False


class InboxResourceLine(BaseModel):
    name: str
    quantity: float
    unit: str


class InboxTaskRead(TaskRead):
    """A pending task enriched for the schedule inbox with its template +
    tree labels and the computed resource amounts."""

    template_name: str | None = None
    template_category: str | None = None
    template_resource_plan: list[InboxResourceLine] = Field(default_factory=list)
    tree_species: str
    tree_variety: str
    window_closes_on: date | None = None
    out_of_season: bool = False
