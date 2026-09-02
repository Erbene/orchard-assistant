"""Transport models for the Care Plan engine (`/api/v1/.../care-plan`)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from ..agent.care_plan import CATEGORIES

Category = str  # one of app.agent.care_plan.CATEGORIES (kept as free-ish str at the edge)
RateClass = str  # "light" | "standard" | "heavy"


class ResourceLine(BaseModel):
    name: str
    quantity: float
    unit: str


class TaskTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tree_id: int
    name: str
    category: str
    rate_class: str
    interval_days: int
    estimated_minutes: int
    priority_score: float
    required_resources: list[str] = Field(default_factory=list)
    resource_plan: list[ResourceLine] = Field(default_factory=list)
    baseline_question: str | None = None
    anchor_date: date | None = None
    source_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TaskTemplateUpdate(BaseModel):
    """Partial edit from the Care Plan UI. Changing ``category`` / ``rate_class``
    re-scales minutes + resources from the tree's size; the others are taken
    verbatim. The template's open pending task is rescheduled/updated to match."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = None
    rate_class: str | None = None
    interval_days: int | None = Field(default=None, gt=0, le=730)
    estimated_minutes: int | None = Field(default=None, gt=0)
    priority_score: float | None = Field(default=None, ge=0, le=10)
    required_resources: list[str] | None = None


class BaselineQuestion(BaseModel):
    template_id: int
    name: str
    question: str


class CarePlan(BaseModel):
    tree_id: int
    templates: list[TaskTemplateRead] = Field(default_factory=list)
    baseline_questions: list[BaselineQuestion] = Field(default_factory=list)
    pending_task_count: int = 0
    generated: bool = False


class BaselineAnswer(BaseModel):
    template_id: int
    last_done: date | None = None


class BaselineRequest(BaseModel):
    answers: list[BaselineAnswer] = Field(default_factory=list)


# re-export so callers can validate against the canonical list
CARE_PLAN_CATEGORIES = list(CATEGORIES)
