"""Coarse growth-stage estimate for the irrigation supervisor.

**Basic** phenology metadata: a month -> stage lookup (hemisphere-aware) with a
few subtropical-evergreen overrides. This is a deliberate stopgap until per-tree
phenology lands (``future_work/care-plan-biological-constraints.md``) - it gives
the supervisor a sense of "flowering vs. dormancy" without a biological calendar
in the schema.
"""
from __future__ import annotations

from datetime import date

STAGES = (
    "dormancy",
    "bud_break",
    "flowering",
    "fruit_set",
    "fruit_development",
    "harvest",
    "post_harvest",
    "vegetative",
)

# Northern-hemisphere generic deciduous/temperate orchard calendar.
_GENERIC_N: dict[int, str] = {
    1: "dormancy", 2: "dormancy", 3: "bud_break", 4: "flowering",
    5: "fruit_set", 6: "fruit_development", 7: "fruit_development",
    8: "harvest", 9: "harvest", 10: "post_harvest", 11: "post_harvest",
    12: "dormancy",
}

# Subtropical evergreens flower late winter / early spring and hold canopy
# year-round (no true dormancy) - a keyword-matched override.
_EVERGREEN_N: dict[int, str] = {
    1: "flowering", 2: "flowering", 3: "fruit_set", 4: "fruit_set",
    5: "fruit_development", 6: "fruit_development", 7: "fruit_development",
    8: "harvest", 9: "harvest", 10: "post_harvest", 11: "vegetative",
    12: "vegetative",
}
_EVERGREEN_KEYWORDS = (
    "mango", "citrus", "lemon", "lime", "orange", "avocado", "sapodilla", "guava",
    "jaboticaba", "jabuticaba", "lychee", "banana",
)

# Target soil moisture (VWC %) per stage - wetter through bloom / fruit set,
# drier in dormancy and at harvest (mild stress firms fruit, cuts split).
_TARGET_VWC: dict[str, float] = {
    "dormancy": 16.0,
    "bud_break": 24.0,
    "flowering": 30.0,
    "fruit_set": 30.0,
    "fruit_development": 27.0,
    "harvest": 22.0,
    "post_harvest": 22.0,
    "vegetative": 25.0,
}


def _shift_month(month: int, hemisphere: str) -> int:
    """Southern hemisphere: offset the calendar by 6 months."""
    if hemisphere.upper().startswith("S"):
        return (month + 5) % 12 + 1
    return month


def growth_stage(species: str, on_date: date | None = None, *, hemisphere: str = "N") -> str:
    on_date = on_date or date.today()
    month = _shift_month(on_date.month, hemisphere)
    table = (
        _EVERGREEN_N
        if any(k in (species or "").lower() for k in _EVERGREEN_KEYWORDS)
        else _GENERIC_N
    )
    return table[month]


def target_vwc_for_stage(stage: str, *, fallback: float = 25.0) -> float:
    return _TARGET_VWC.get(stage, fallback)
