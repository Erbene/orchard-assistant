"""Transport models for the Care Plan engine (`/api/v1/.../care-plan`)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..agent.care_plan import CATEGORIES
from ..schemas.tree import _normalize_month_list

Category = str  # one of app.agent.care_plan.CATEGORIES (kept as free-ish str at the edge)
RateClass = str  # "light" | "standard" | "heavy"
BiologicalAnchor = Literal["flowering", "harvest", "dormancy"]


class TreePhenologyRead(BaseModel):
    flowering_month: int | None = None
    harvest_month: int | None = None
    dormancy_month: int | None = None
    flowering_months: list[int] = Field(default_factory=list)
    harvest_months: list[int] = Field(default_factory=list)
    dormancy_months: list[int] = Field(default_factory=list)

    @classmethod
    def from_tree_row(cls, tree: dict) -> TreePhenologyRead:
        flowering = tree.get("expected_flowering_months") or []
        if not flowering and tree.get("expected_flowering_month") is not None:
            flowering = [tree["expected_flowering_month"]]
        harvest = tree.get("expected_harvest_months") or []
        if not harvest and tree.get("expected_harvest_month") is not None:
            harvest = [tree["expected_harvest_month"]]
        dormancy = tree.get("expected_dormancy_months") or []
        if not dormancy and tree.get("expected_dormancy_month") is not None:
            dormancy = [tree["expected_dormancy_month"]]
        flowering = _normalize_month_list(list(flowering))
        harvest = _normalize_month_list(list(harvest))
        dormancy = _normalize_month_list(list(dormancy))
        return cls(
            flowering_month=flowering[0] if flowering else tree.get("expected_flowering_month"),
            harvest_month=harvest[0] if harvest else tree.get("expected_harvest_month"),
            dormancy_month=dormancy[0] if dormancy else tree.get("expected_dormancy_month"),
            flowering_months=flowering,
            harvest_months=harvest,
            dormancy_months=dormancy,
        )


class ResourceLine(BaseModel):
    name: str
    quantity: float
    unit: str


class TemplateBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    min_gap_days: int = Field(ge=1, le=365)

    @field_validator("category")
    @classmethod
    def _category_in_list(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
        return value


def _validate_blocks(value: list[TemplateBlock] | None) -> list[TemplateBlock]:
    if not value:
        return []
    if len(value) > 8:
        raise ValueError("blocks may contain at most 8 entries")
    seen: set[str] = set()
    for block in value:
        if block.category in seen:
            raise ValueError("blocks categories must be unique")
        seen.add(block.category)
    return value


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
    valid_months: list[int] = Field(default_factory=list)
    biological_anchor: BiologicalAnchor | None = None
    anchor_offset_days: int | None = None
    blocks: list[TemplateBlock] = Field(default_factory=list)
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
    valid_months: list[int] | None = None
    biological_anchor: BiologicalAnchor | None = None
    anchor_offset_days: int | None = None
    blocks: list[TemplateBlock] | None = None

    @field_validator("blocks")
    @classmethod
    def _blocks(cls, value: list[TemplateBlock] | None) -> list[TemplateBlock] | None:
        if value is None:
            return None
        return _validate_blocks(value)


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
    phenology: TreePhenologyRead = Field(default_factory=TreePhenologyRead)


class BaselineAnswer(BaseModel):
    template_id: int
    last_done: date | None = None


class BaselineRequest(BaseModel):
    answers: list[BaselineAnswer] = Field(default_factory=list)
    flowering_month: int | None = Field(default=None, ge=1, le=12)
    harvest_month: int | None = Field(default=None, ge=1, le=12)
    dormancy_month: int | None = Field(default=None, ge=1, le=12)
    flowering_months: list[int] = Field(default_factory=list)
    harvest_months: list[int] = Field(default_factory=list)
    dormancy_months: list[int] = Field(default_factory=list)

    @field_validator("flowering_months", "harvest_months", "dormancy_months", mode="before")
    @classmethod
    def _validate_month_lists(cls, value: list[int] | None) -> list[int]:
        return _normalize_month_list(value or [])

    def resolved_phenology(self) -> dict[str, list[int] | int | None]:
        """Prefer list fields; fall back to singular month aliases."""
        out: dict[str, list[int] | int | None] = {}
        for plural, singular in (
            ("flowering_months", "flowering_month"),
            ("harvest_months", "harvest_month"),
            ("dormancy_months", "dormancy_month"),
        ):
            months = getattr(self, plural)
            if not months:
                single = getattr(self, singular)
                months = [single] if single is not None else []
            months = _normalize_month_list(months)
            out[plural] = months
            out[singular] = months[0] if months else None
        return out


# re-export so callers can validate against the canonical list
CARE_PLAN_CATEGORIES = list(CATEGORIES)
