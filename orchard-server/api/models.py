"""Pydantic request/response models for the orchard API."""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Species(str, Enum):
    mango = "mango"
    sapodilla = "sapodilla"
    sugar_apple = "sugar_apple"


class SoilDrainage(str, Enum):
    sandy_fast_draining = "sandy_fast_draining"
    loamy = "loamy"


# --- Zone -----------------------------------------------------------------

class ZoneBase(BaseModel):
    name: str = Field(min_length=1)
    soil_drainage: SoilDrainage | None = None


class ZoneCreate(ZoneBase):
    zone_id: str = Field(min_length=1)


class ZoneUpdate(BaseModel):
    """All fields optional; only provided fields are changed."""
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    soil_drainage: SoilDrainage | None = None


class Zone(ZoneBase):
    zone_id: str


# --- Tree ---------------------------------------------------------------

class TreeBase(BaseModel):
    species: Species
    variety: str = Field(min_length=1)
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None


class TreeCreate(TreeBase):
    # Optional: let SQLite assign the id when omitted.
    tree_id: int | None = Field(default=None, gt=0)


class TreeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    species: Species | None = None
    variety: str | None = Field(default=None, min_length=1)
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None


class Tree(TreeBase):
    tree_id: int
    age_days: int | None = None
    age_years: float | None = None
