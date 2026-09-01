"""User context transport models.

A single (singleton, ``id = 1``) record holding the scheduling constraints
the Foreman agent must respect when planning tasks.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserContextBase(BaseModel):
    available_labor_hours_per_day: float = Field(
        default=8.0,
        ge=0,
        description="Total person-hours of labor available on a normal working day.",
    )
    available_products: list[str] = Field(
        default_factory=list,
        description="Free-text names of products/equipment on hand (fertilizers, sprays, tools).",
    )


class UserContextUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    available_labor_hours_per_day: float | None = Field(default=None, ge=0)
    available_products: list[str] | None = None


class UserContextRead(UserContextBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime
