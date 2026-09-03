"""Risk Escalation Engine.

A pending task that is dangerously overdue gets its ``priority_score``
inflated *before* the Foreman's knapsack packing, so time-critical work
(fungicide, irrigation) jumps the queue. Rules are keyed off ``action_type``
with a generic catch-all; every escalated task carries a human reason string
that the Foreman LLM turns into an explicit warning.

Tasks with a closing biological window (``window_closes_on`` within 14 days)
also get inflated; when both an overdue rule and a window rule apply, the
**max** multiplier wins (they do not compound).

When the window is already closed (``window_closes_on`` in the past), the
task sinks to x0.25 for knapsack packing only — **closed wins over overdue**,
so missing the season does not amplify priority. The stored ``priority_score``
is never rewritten.

Operates on plain task dicts (``TaskRead.model_dump(mode="json")`` shape:
``id``, ``action_type``, ``priority_score``, ``scheduled_date`` /
``created_at`` as ISO strings, optional ``window_closes_on``).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, TypedDict

Task = dict[str, Any]


class Escalation(TypedDict):
    task_id: int
    action_type: str
    days_late: int
    multiplier: float
    reason: str


# (action_type pattern, days-late threshold, priority multiplier)
_RULES: list[tuple[re.Pattern[str], int, float]] = [
    (re.compile(r"fung|spray|copper|mildew|blight|anthracnose", re.I), 7, 3.0),
    (re.compile(r"irrigat|water", re.I), 3, 2.5),
    (re.compile(r"fertil|feed|nutrient|amend", re.I), 10, 2.0),
    (re.compile(r"prune|prun|thin|train", re.I), 21, 1.5),
]
_GENERIC_DAYS, _GENERIC_MULT = 14, 2.0
_WINDOW_CLOSING_DAYS, _WINDOW_CLOSING_MULT = 14, 2.0
_WINDOW_CLOSED_MULT = 0.25


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def task_age_days(task: Task, *, today: date | None = None) -> int:
    """Days since the task was due (``scheduled_date``) or, failing that,
    created. Never negative."""
    today = today or date.today()
    anchor = _as_date(task.get("scheduled_date")) or _as_date(task.get("created_at"))
    if anchor is None:
        return 0
    return max(0, (today - anchor).days)


def _days_until_window_closes(task: Task, *, today: date | None = None) -> int | None:
    today = today or date.today()
    closes = _as_date(task.get("window_closes_on"))
    if closes is None:
        return None
    return (closes - today).days


def _match(action_type: str, days_late: int) -> tuple[int, float] | None:
    for pattern, threshold, mult in _RULES:
        if pattern.search(action_type or ""):
            return (threshold, mult) if days_late >= threshold else None
    if days_late >= _GENERIC_DAYS:
        return _GENERIC_DAYS, _GENERIC_MULT
    return None


def _window_closing_hit(task: Task, *, today: date | None = None) -> tuple[float, str] | None:
    days_until = _days_until_window_closes(task, today=today)
    if days_until is None:
        return None
    if 0 <= days_until < _WINDOW_CLOSING_DAYS:
        closes = _as_date(task.get("window_closes_on"))
        label = closes.isoformat() if closes else "soon"
        return (
            _WINDOW_CLOSING_MULT,
            f"{task.get('action_type', 'task')} window closes {label} "
            f"({days_until}d) - priority x{_WINDOW_CLOSING_MULT:g}",
        )
    return None


def _window_closed_hit(task: Task, *, today: date | None = None) -> tuple[float, str] | None:
    days_until = _days_until_window_closes(task, today=today)
    if days_until is None:
        return None
    if days_until < 0:
        closes = _as_date(task.get("window_closes_on"))
        label = closes.isoformat() if closes else "past"
        return (
            _WINDOW_CLOSED_MULT,
            f"{task.get('action_type', 'task')} window closed {label} "
            f"- out of season, priority x{_WINDOW_CLOSED_MULT:g}",
        )
    return None


def escalate(
    tasks: list[Task], *, today: date | None = None
) -> tuple[list[Task], list[Escalation]]:
    """Return ``(tasks, escalations)`` where each task gains an
    ``_effective_score`` (= ``priority_score`` x multiplier, or x1) and every
    task that tripped a threshold has an :class:`Escalation` record."""
    out: list[Task] = []
    escalations: list[Escalation] = []
    for task in tasks:
        t = dict(task)
        base = float(t.get("priority_score") or 0.0)
        days_late = task_age_days(t, today=today)
        closed = _window_closed_hit(t, today=today)
        overdue = _match(str(t.get("action_type", "")), days_late)
        window = _window_closing_hit(t, today=today)

        mult = 1.0
        reason: str | None = None
        if closed is not None:
            mult, reason = closed
        elif overdue is not None and window is not None:
            _, overdue_mult = overdue
            window_mult, window_reason = window
            if overdue_mult >= window_mult:
                _, mult = overdue
                reason = (
                    f"{t.get('action_type', 'task')} is {days_late} days overdue "
                    f"(threshold {overdue[0]}d) - priority x{mult:g}"
                )
            else:
                mult = window_mult
                reason = window_reason
        elif overdue is not None:
            _, mult = overdue
            reason = (
                f"{t.get('action_type', 'task')} is {days_late} days overdue "
                f"(threshold {overdue[0]}d) - priority x{mult:g}"
            )
        elif window is not None:
            mult, reason = window

        if mult != 1.0 and reason:
            t["_effective_score"] = base * mult
            escalations.append(
                Escalation(
                    task_id=int(t["id"]),
                    action_type=str(t.get("action_type", "")),
                    days_late=days_late,
                    multiplier=mult,
                    reason=reason,
                )
            )
        else:
            t["_effective_score"] = base
        out.append(t)
    return out, escalations
