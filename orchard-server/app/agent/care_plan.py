"""Deterministic size-scaling for the Care Plan engine.

The Agronomist LLM picks *which* routine tasks a tree needs, a ``category``,
a ``rate_class``, and an optional recommended ``product``. Everything numeric
— labour minutes and product quantities — is computed here from the tree's
canopy volume, so a plan is reproducible and auditable (the eval log flags
qwen2.5:7b as unreliable at dosing math). Templates that recommend the same
product (same bag / same NPK analysis) are merged; distinct products stay
separate.

All constants are tunable; they are rough field estimates, not label rates.
Nothing here calls a model or touches the DB.
"""
from __future__ import annotations

import math
import re
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


_NPK = re.compile(r"\b(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\b")


def _normalize_product(name: str) -> str:
    """Same bag / same analysis → same key ('8-3-9' == 'Balanced fertilizer (8-3-9)')."""
    text = " ".join(name.strip().lower().split())
    match = _NPK.search(text)
    if match:
        return f"{int(match.group(1))}-{int(match.group(2))}-{int(match.group(3))}"
    return text


def scale(
    category: str,
    rate_class: str,
    *,
    height_m: float | None,
    spread_m: float | None,
    fallback_minutes: int | None = None,
    product: str | None = None,
) -> ScaledTask:
    """Scale one care task to a tree's size.

    ``product`` replaces the default consumable name when the agronomist
    recommended a specific fertilizer or spray; quantities still come from
    the category rate table.
    """
    rate = _RATES.get(category, _RATES["other"])  # type: ignore[arg-type]
    mult = _RATE_MULT.get(rate_class, 1.0)  # type: ignore[arg-type]
    volume = canopy_volume_m3(height_m, spread_m)

    minutes = rate.base_minutes + rate.minutes_per_m3 * volume * (0.5 + 0.5 * mult)
    if category == "other" and fallback_minutes:
        minutes = float(fallback_minutes)

    override = (product or "").strip()
    lines: list[ResourceLine] = []
    for name, unit, per_m3 in rate.consumables:
        lines.append(
            ResourceLine(
                name=override or name,
                quantity=per_m3 * volume * mult,
                unit=unit,
            )
        )
        override = ""  # only the first consumable takes the recommended name
    tools = list(rate.tools)
    if rate.tall_tool and (height_m or _DEFAULT_HEIGHT_M) >= rate.tall_tool[1]:
        tools.append(rate.tall_tool[0])
    lines.extend(ResourceLine(name=t, quantity=1, unit="ea") for t in tools)

    return ScaledTask(estimated_minutes=_round_minutes(minutes), resource_plan=lines)


def _product_key(template: dict) -> tuple[str, str, str] | None:
    """Category + first dosed product (skip ``ea`` tools). ``None`` = do not merge."""
    category = str(template.get("category") or "").strip()
    if not category:
        return None
    for line in template.get("resource_plan") or []:
        if isinstance(line, ResourceLine):
            name, unit = line.name, line.unit
        else:
            name = str(line.get("name") or "")
            unit = str(line.get("unit") or "")
        if unit.strip().lower() == "ea":
            continue
        name = name.strip()
        if not name:
            continue
        return (category, _normalize_product(name), unit.strip().lower())
    return None


def _union_blocks(left: list | None, right: list | None) -> list[dict]:
    by_cat: dict[str, int] = {}
    for block in list(left or []) + list(right or []):
        cat = str(block.get("category") or "")
        if not cat:
            continue
        gap = int(block.get("min_gap_days") or 0)
        by_cat[cat] = max(by_cat.get(cat, 0), gap)
    return [{"category": cat, "min_gap_days": gap} for cat, gap in by_cat.items() if gap >= 1]


def _merge_product_pair(keep: dict, other: dict) -> dict:
    names: list[str] = []
    for name in (keep.get("name"), other.get("name")):
        label = str(name or "").strip()
        if label and label not in names:
            names.append(label)
    rank = {"light": 0, "standard": 1, "heavy": 2}
    numeric = keep
    if rank.get(other.get("rate_class"), 1) > rank.get(keep.get("rate_class"), 1):
        numeric = other
    months = sorted(
        {int(m) for m in (keep.get("valid_months") or []) + (other.get("valid_months") or [])}
    )
    return {
        **numeric,
        "name": " / ".join(names) if names else str(numeric.get("name") or "Feed"),
        "priority_score": max(
            float(keep.get("priority_score") or 0.0),
            float(other.get("priority_score") or 0.0),
        ),
        "interval_days": min(
            int(keep.get("interval_days") or 365),
            int(other.get("interval_days") or 365),
        ),
        "blocks": _union_blocks(keep.get("blocks"), other.get("blocks")),
        "valid_months": months,
        "baseline_question": keep.get("baseline_question") or other.get("baseline_question"),
    }


def merge_duplicate_product_templates(templates: list[dict]) -> list[dict]:
    """Collapse tasks that recommend the same dosed product in one category.

    Two feeds that both apply 8-3-9 become one template. A 22-0-0 feed and an
    8-3-9 feed stay separate. Tasks with only tools (``ea``) are never merged.
    """
    merged_at: dict[tuple[str, str, str], int] = {}
    out: list[dict] = []
    for template in templates:
        key = _product_key(template)
        if key is None:
            out.append(template)
            continue
        idx = merged_at.get(key)
        if idx is None:
            merged_at[key] = len(out)
            out.append(dict(template))
            continue
        out[idx] = _merge_product_pair(out[idx], template)
    return out
