"""Deterministic irrigation spacing rules (no LLM)."""
from __future__ import annotations

from datetime import date, timedelta

WATERING_ACTIONS = frozenset({"adjust_duration", "start_zone_watering", "pass_no_action"})


def consecutive_water_blocked(last_watered: date | None, for_date: date) -> bool:
    """True when Rachio last watered on ``for_date`` or the prior calendar day."""
    if last_watered is None:
        return False
    return last_watered >= for_date - timedelta(days=1)


def spacing_skip_summary(last_watered: date, for_date: date) -> str:
    if last_watered == for_date:
        return (
            "Zone watered today (Rachio lastWateredDate) — skipping to keep a 2-day gap."
        )
    return (
        "Zone watered yesterday (Rachio lastWateredDate) — skipping today to keep a 2-day gap."
    )
