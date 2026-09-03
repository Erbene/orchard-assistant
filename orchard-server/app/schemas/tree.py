"""Tree transport models.

``species`` and ``variety`` are free text - no enums, no closed vocabularies;
the validation agent only normalizes whitespace. ``age_days`` / ``age_years``
are derived from ``planted_date`` on read and never persisted.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_HEIGHT = Field(default=None, gt=0, le=99, description="Canopy height in metres (Care Plan scaling).")
_SPREAD = Field(default=None, gt=0, le=99, description="Canopy spread in metres; defaults to 0.6 * height.")
_GPH = Field(default=None, ge=0, le=500, description="Whole-tree drip delivery, gallons/hour (irrigation).")
_WETTED = Field(default=None, gt=0, le=100, description="Estimated soil area the drip emitters wet, m2 (irrigation).")


def _normalize_month_list(value: list[int] | None) -> list[int]:
    if not value:
        return []
    seen: set[int] = set()
    out: list[int] = []
    for m in value:
        if not isinstance(m, int) or m < 1 or m > 12 or m in seen:
            continue
        seen.add(m)
        out.append(m)
        if len(out) >= 4:
            break
    return sorted(out)


def _dual_write_singular(data: dict) -> dict:
    """When month lists are present, mirror the first entry into singular columns."""
    pairs = (
        ("expected_flowering_months", "expected_flowering_month"),
        ("expected_harvest_months", "expected_harvest_month"),
        ("expected_dormancy_months", "expected_dormancy_month"),
    )
    for plural, singular in pairs:
        if plural in data:
            months = data[plural] or []
            data[singular] = months[0] if months else None
    return data


def _dual_read_lists(data: dict) -> dict:
    """Populate list fields from JSONB or fall back to singular columns."""
    pairs = (
        ("expected_flowering_months", "expected_flowering_month"),
        ("expected_harvest_months", "expected_harvest_month"),
        ("expected_dormancy_months", "expected_dormancy_month"),
    )
    for plural, singular in pairs:
        raw = data.get(plural)
        if raw:
            data[plural] = _normalize_month_list(list(raw))
        elif data.get(singular) is not None:
            data[plural] = [data[singular]]
        else:
            data[plural] = []
    return data


class TreeCreate(BaseModel):
    species: str = Field(min_length=1, description="Free text, e.g. 'mango'.")
    variety: str = Field(min_length=1, description="Free text, e.g. 'Kent'.")
    zone_id: str | None = Field(
        default=None, description="Rachio zone id this tree is irrigated by (free text; not validated)."
    )
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    height_m: float | None = _HEIGHT
    canopy_spread_m: float | None = _SPREAD
    estimated_gph: float | None = _GPH
    wetted_area_m2: float | None = _WETTED
    expected_flowering_month: int | None = Field(default=None, ge=1, le=12)
    expected_harvest_month: int | None = Field(default=None, ge=1, le=12)
    expected_dormancy_month: int | None = Field(default=None, ge=1, le=12)
    expected_flowering_months: list[int] = Field(default_factory=list)
    expected_harvest_months: list[int] = Field(default_factory=list)
    expected_dormancy_months: list[int] = Field(default_factory=list)
    tree_id: int | None = Field(default=None, gt=0, description="Optional; assigned by the store when omitted.")

    @field_validator(
        "expected_flowering_months",
        "expected_harvest_months",
        "expected_dormancy_months",
        mode="before",
    )
    @classmethod
    def _validate_month_lists(cls, value: list[int] | None) -> list[int]:
        return _normalize_month_list(value or [])

    @model_validator(mode="after")
    def _sync_phenology(self) -> TreeCreate:
        pairs = (
            ("expected_flowering_months", "expected_flowering_month"),
            ("expected_harvest_months", "expected_harvest_month"),
            ("expected_dormancy_months", "expected_dormancy_month"),
        )
        for plural, singular in pairs:
            months = getattr(self, plural)
            singular_val = getattr(self, singular)
            if months:
                object.__setattr__(self, singular, months[0])
            elif singular_val is not None and not months:
                object.__setattr__(self, plural, [singular_val])
        return self


class TreeUpdate(BaseModel):
    """Partial update - only fields explicitly supplied are changed."""

    model_config = ConfigDict(extra="forbid")

    species: str | None = Field(default=None, min_length=1)
    variety: str | None = Field(default=None, min_length=1)
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    height_m: float | None = _HEIGHT
    canopy_spread_m: float | None = _SPREAD
    estimated_gph: float | None = _GPH
    wetted_area_m2: float | None = _WETTED
    expected_flowering_month: int | None = Field(default=None, ge=1, le=12)
    expected_harvest_month: int | None = Field(default=None, ge=1, le=12)
    expected_dormancy_month: int | None = Field(default=None, ge=1, le=12)
    expected_flowering_months: list[int] | None = None
    expected_harvest_months: list[int] | None = None
    expected_dormancy_months: list[int] | None = None

    @field_validator(
        "expected_flowering_months",
        "expected_harvest_months",
        "expected_dormancy_months",
        mode="before",
    )
    @classmethod
    def _validate_month_lists(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        return _normalize_month_list(value)

    @model_validator(mode="after")
    def _sync_phenology(self) -> TreeUpdate:
        pairs = (
            ("expected_flowering_months", "expected_flowering_month"),
            ("expected_harvest_months", "expected_harvest_month"),
            ("expected_dormancy_months", "expected_dormancy_month"),
        )
        fields_set = self.model_fields_set
        for plural, singular in pairs:
            if plural in fields_set:
                months = getattr(self, plural) or []
                object.__setattr__(self, singular, months[0] if months else None)
        return self


class TreeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tree_id: int
    species: str
    variety: str
    zone_id: str | None = None
    planted_date: date | None = None
    additional_context: str | None = None
    notes: str | None = None
    height_m: float | None = None
    canopy_spread_m: float | None = None
    estimated_gph: float | None = None
    wetted_area_m2: float | None = None
    expected_flowering_month: int | None = None
    expected_harvest_month: int | None = None
    expected_dormancy_month: int | None = None
    expected_flowering_months: list[int] = Field(default_factory=list)
    expected_harvest_months: list[int] = Field(default_factory=list)
    expected_dormancy_months: list[int] = Field(default_factory=list)
    has_care_plan: bool = False   # only the list endpoint sets this
    age_days: int | None = None
    age_years: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_phenology(cls, data: object) -> object:
        if isinstance(data, dict):
            return _dual_read_lists(dict(data))
        return data
