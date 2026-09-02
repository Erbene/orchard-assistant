"""Deterministic size-scaling for the Care Plan engine.

The Agronomist LLM only picks *which* routine tasks a tree needs, a ``category``
and a ``rate_class``. Everything numeric - labour minutes and product
quantities - is computed here from the tree's canopy volume, so a plan is
reproducible and auditable (the eval log flags qwen2.5:7b as unreliable at
dosing math).

All constants are tunable; they are rough field estimates, not label rates.
Nothing here calls a model or touches the DB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Category = Literal[
    "fertilize", "mulch", "prune", "scout", "spray",
    "irrigation", "weed", "stake", "soil_test", "other",
]
RateClass = Literal["light", "standard", "heavy"]

CATEGORIES: tuple[Category, ...] = (
    "fertilize", "mulch", "prune", "scout", "spray",
    "irrigation", "weed", "stake", "soil_test", "other",
)

_RATE_MULT: dict[RateClass, float] = {"light": 0.5, "standard": 1.0, "heavy": 2.0}
_SPREAD_RATIO = 0.6           # canopy spread as a fraction of height when unknown
_MIN_HEIGHT_M = 0.3           # a whip / newly planted tree
_DEFAULT_HEIGHT_M = 2.0       # used when height is not recorded yet


def canopy_volume_m3(height_m: float | None, spread_m: float | None = None) -> float:
    """Half-ellipsoid canopy volume: (2/3)·π·(spread/2)²·height."""
    h = max(float(height_m) if height_m else _DEFAULT_HEIGHT_M, _MIN_HEIGHT_M)
    s = float(spread_m) if spread_m else h * _SPREAD_RATIO
    s = max(s, 0.2)
    return (2.0 / 3.0) * math.pi * (s / 2.0) ** 2 * h


@dataclass(frozen=True)
class ResourceLine:
    name: str
    quantity: float
    unit: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "quantity": round(self.quantity, 2), "unit": self.unit}


@dataclass(frozen=True)
class ScaledTask:
    estimated_minutes: int
    resource_plan: list[ResourceLine]

    @property
    def required_resources(self) -> list[str]:
        # Foreman-facing: bare names, de-duped, order preserved.
        return list(dict.fromkeys(r.name for r in self.resource_plan))


@dataclass(frozen=True)
class _Rate:
    base_minutes: float
    minutes_per_m3: float
    # (name, unit, quantity per m3 of canopy) - scaled by the rate multiplier
    consumables: tuple[tuple[str, str, float], ...] = ()
    # fixed tools, never scaled
    tools: tuple[str, ...] = ()
    # extra tool added when the tree is tall
    tall_tool: tuple[str, float] | None = None   # (name, height_m threshold)


_RATES: dict[Category, _Rate] = {
    "fertilize": _Rate(
        base_minutes=8, minutes_per_m3=1.6,
        consumables=(("Balanced fertilizer (8-3-9)", "kg", 0.12),),
    ),
    "mulch": _Rate(
        base_minutes=12, minutes_per_m3=3.0,
        consumables=(("Compost / mulch", "L", 14.0),),
    ),
    "prune": _Rate(
        base_minutes=15, minutes_per_m3=4.0,
        tools=("Pruning shears",), tall_tool=("Pole saw", 3.0),
    ),
    "scout": _Rate(base_minutes=8, minutes_per_m3=0.8),
    "spray": _Rate(
        base_minutes=12, minutes_per_m3=3.0,
        consumables=(("Copper fungicide", "mL", 6.0),), tools=("Backpack sprayer",),
    ),
    "irrigation": _Rate(base_minutes=10, minutes_per_m3=0.0),
    "weed": _Rate(base_minutes=12, minutes_per_m3=1.5),
    "stake": _Rate(base_minutes=10, minutes_per_m3=0.0, tools=("Tree ties", "Stakes")),
    "soil_test": _Rate(base_minutes=18, minutes_per_m3=0.0, tools=("Soil test kit",)),
    "other": _Rate(base_minutes=15, minutes_per_m3=0.0),
}


def _round_minutes(value: float) -> int:
    return max(5, int(round(value / 5.0)) * 5)


def scale(
    category: str,
    rate_class: str,
    *,
    height_m: float | None,
    spread_m: float | None,
    fallback_minutes: int | None = None,
) -> ScaledTask:
    """Scale one care task to a tree's size."""
    rate = _RATES.get(category, _RATES["other"])  # type: ignore[arg-type]
    mult = _RATE_MULT.get(rate_class, 1.0)  # type: ignore[arg-type]
    volume = canopy_volume_m3(height_m, spread_m)

    minutes = rate.base_minutes + rate.minutes_per_m3 * volume * (0.5 + 0.5 * mult)
    if category == "other" and fallback_minutes:
        minutes = float(fallback_minutes)

    lines: list[ResourceLine] = [
        ResourceLine(name=name, quantity=per_m3 * volume * mult, unit=unit)
        for name, unit, per_m3 in rate.consumables
    ]
    tools = list(rate.tools)
    if rate.tall_tool and (height_m or _DEFAULT_HEIGHT_M) >= rate.tall_tool[1]:
        tools.append(rate.tall_tool[0])
    lines.extend(ResourceLine(name=t, quantity=1, unit="ea") for t in tools)

    return ScaledTask(estimated_minutes=_round_minutes(minutes), resource_plan=lines)
