"""Pure scheduling math for Care Plan recurrence.

No DB, no LLM. ``next_due`` applies in-window cadence (``interval_days``),
``valid_months`` preference clamping, and biological safety nets
(``biological_anchor`` + ``anchor_offset_days`` + tree phenology).
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta

BIOLOGICAL_ANCHORS = ("flowering", "harvest", "dormancy")


@dataclass(frozen=True)
class TreePhenology:
    flowering_months: tuple[int, ...] = ()
    harvest_months: tuple[int, ...] = ()
    dormancy_months: tuple[int, ...] = ()


@dataclass(frozen=True)
class ScheduleOutcome:
    date: date | None           # next actionable due date
    skipped: bool               # True if the naive candidate hit the safety net
    reason: str | None
    window_closes_on: date | None  # last day of the valid-months window containing date


def _months_from_value(
    plural: list | tuple | str | None, singular: int | None
) -> tuple[int, ...]:
    if isinstance(plural, str):
        try:
            plural = json.loads(plural)
        except json.JSONDecodeError:
            plural = []
    if plural:
        return tuple(m for m in plural if isinstance(m, int) and 1 <= m <= 12)
    if singular is not None and 1 <= singular <= 12:
        return (singular,)
    return ()


def months_from_tree(tree: dict) -> TreePhenology:
    """Prefer JSONB month lists; fall back to singular SMALLINT columns."""
    return TreePhenology(
        flowering_months=_months_from_value(
            tree.get("expected_flowering_months"), tree.get("expected_flowering_month")
        ),
        harvest_months=_months_from_value(
            tree.get("expected_harvest_months"), tree.get("expected_harvest_month")
        ),
        dormancy_months=_months_from_value(
            tree.get("expected_dormancy_months"), tree.get("expected_dormancy_month")
        ),
    )


def _month_set(valid_months: list[int] | None) -> set[int] | None:
    if not valid_months:
        return None
    return {m for m in valid_months if 1 <= m <= 12}


def _clamp_to_valid_months(candidate: date, valid_months: list[int] | None) -> date:
    months = _month_set(valid_months)
    if not months or candidate.month in months:
        return candidate
    year, month = candidate.year, candidate.month
    for _ in range(24):
        month += 1
        if month > 12:
            month = 1
            year += 1
        if month in months:
            return date(year, month, 1)
    return candidate


def _add_months(d: date, months: int) -> date:
    y, m = d.year, d.month + months
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1)


def _phenology_months(phenology: TreePhenology, anchor: str) -> tuple[int, ...]:
    if anchor == "flowering":
        return phenology.flowering_months
    if anchor == "harvest":
        return phenology.harvest_months
    if anchor == "dormancy":
        return phenology.dormancy_months
    return ()


def _resume_after_harvest(cutoff: date, harvest_months: tuple[int, ...]) -> date:
    """Earliest harvest-month 1st strictly after ``cutoff`` (this year, then next)."""
    candidates: list[date] = []
    for year in (cutoff.year, cutoff.year + 1):
        for hm in sorted(harvest_months):
            resume = date(year, hm, 1)
            if resume > cutoff:
                candidates.append(resume)
    return min(candidates)


def compute_window_closes_on(due: date, valid_months: list[int] | None) -> date | None:
    """Last calendar day of the contiguous valid-month run containing ``due.month``."""
    months = _month_set(valid_months)
    if not months or due.month not in months:
        return None
    sorted_months = sorted(months)
    # locate the contiguous block containing due.month
    start = end = due.month
    i = sorted_months.index(due.month)
    j = i
    while j > 0 and sorted_months[j - 1] == sorted_months[j] - 1:
        j -= 1
    start = sorted_months[j]
    while i + 1 < len(sorted_months) and sorted_months[i + 1] == sorted_months[i] + 1:
        i += 1
    end = sorted_months[i]
    last_day = calendar.monthrange(due.year, end)[1]
    return date(due.year, end, last_day)


# spec alias
window_closes_on = compute_window_closes_on


def next_due(
    *,
    after: date,
    interval_days: int,
    valid_months: list[int] | None,
    biological_anchor: str | None,
    anchor_offset_days: int | None,
    phenology: TreePhenology,
) -> ScheduleOutcome:
    """Compute the next due date after ``after`` with biological constraints."""
    candidate = after + timedelta(days=interval_days)
    skipped = False
    reason: str | None = None

    candidate = _clamp_to_valid_months(candidate, valid_months)

    if (
        biological_anchor in BIOLOGICAL_ANCHORS
        and anchor_offset_days is not None
    ):
        event_months = _phenology_months(phenology, biological_anchor)
        if event_months:
            harvest_months = phenology.harvest_months
            earliest_resume: date | None = None

            for year in (candidate.year, candidate.year + 1):
                for anchor_month in event_months:
                    event = date(year, anchor_month, 1)
                    cutoff = event + timedelta(days=anchor_offset_days)
                    if harvest_months:
                        resume = _resume_after_harvest(cutoff, harvest_months)
                    else:
                        resume = _add_months(event, 1)

                    if cutoff <= candidate < resume:
                        if earliest_resume is None or resume < earliest_resume:
                            earliest_resume = resume

            if earliest_resume is not None:
                skipped = True
                offset_abs = abs(anchor_offset_days)
                reason = (
                    f"safety cutoff {offset_abs}d before {biological_anchor}; "
                    f"resume after harvest"
                    if harvest_months
                    else f"safety cutoff {offset_abs}d before {biological_anchor}; "
                    f"resume after event window"
                )
                candidate = earliest_resume
                candidate = _clamp_to_valid_months(candidate, valid_months)

    closes = compute_window_closes_on(candidate, valid_months)
    return ScheduleOutcome(
        date=candidate,
        skipped=skipped,
        reason=reason,
        window_closes_on=closes,
    )
