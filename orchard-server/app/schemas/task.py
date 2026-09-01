"""Task transport models.

A ``Task`` is a unit of orchard work linked to one ``Tree``. ``action_type``
is free text (no controlled vocabulary, consistent with the rest of the
domain); ``status`` is a genuine state-machine field constrained to
``pending`` / ``completed`` / ``deferred``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "completed", "deferred"]


class TaskBase(BaseModel):
    action_type: str = Field(
        min_length=1,
        description="Free-text work type, e.g. 'prune', 'fertilize', 'irrigate', 'scout_pests'.",
    )
    priority_score: float = Field(
        default=0.0,
        description="Relative urgency; higher sorts first in the queue.",
    )
    scheduled_date: datetime | None = Field(
        default=None,
        description="When the task is planned. NULL means unscheduled / needs placing.",
    )
    frequency_days: int | None = Field(
        default=None,
        gt=0,
        description="If set, the task recurs every N days (a new pending task is spawned on completion).",
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


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tree_id: int
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None = None
