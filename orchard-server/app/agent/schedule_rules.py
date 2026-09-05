"""Pure cross-task scheduling rules (no DB, no LLM).

After a task in category X completes, its template ``blocks`` list may forbid
other categories on the same tree until ``min_gap_days`` have elapsed.

Same-session rules also apply *before* work is done: two fertilize (or spray,
or mulch) jobs on one tree cannot share a plan, and a task whose template
``blocks`` the other's category cannot run the same day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

Task = dict[str, Any]

# One of these per tree per session — two nitrogen/potassium feeds is wrong.
_EXCLUSIVE_CATEGORIES = frozenset({"fertilize", "spray", "mulch"})


@dataclass(frozen=True)
class Completion:
    tree_id: int
    category: str          # template category of the completed task
    completed_on: date
    blocks: list[dict]     # that template's blocks


def _task_category(task: Task) -> str | None:
    cat = task.get("template_category") or task.get("category")
    return str(cat).strip() if cat else None


def _task_blocks(task: Task) -> list[dict]:
    raw = task.get("template_blocks")
    if raw is None:
        raw = task.get("blocks")
    return list(raw or [])


def _score(task: Task) -> float:
    value = task.get("_effective_score", task.get("priority_score", 0.0))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _label(task: Task) -> str:
    action = str(task.get("action_type") or _task_category(task) or "task")
    return f"#{task.get('id')} {action}"


def _blocks_category(task: Task, category: str | None) -> bool:
    if not category:
        return False
    for block in _task_blocks(task):
        if block.get("category") != category:
            continue
        if int(block.get("min_gap_days") or 0) >= 1:
            return True
    return False


def session_conflict_reason(a: Task, b: Task) -> str | None:
    """Why ``a`` and ``b`` cannot share a work session, or ``None`` if they can."""
    if a.get("id") is not None and a.get("id") == b.get("id"):
        return None
    if a.get("tree_id") != b.get("tree_id"):
        return None
    ca, cb = _task_category(a), _task_category(b)
    if ca and ca == cb and ca in _EXCLUSIVE_CATEGORIES:
        return (
            f"conflicts with {_label(b)} "
            f"(same tree, one {ca} job per session)"
        )
    if ca and _blocks_category(b, ca):
        return (
            f"blocked by {_label(b)} "
            f"({ca} cannot run the same day)"
        )
    if cb and _blocks_category(a, cb):
        return (
            f"would block {_label(b)} "
            f"(cannot share a session)"
        )
    return None


def apply_session_conflicts(tasks: list[Task]) -> tuple[list[Task], list[Task]]:
    """Keep the highest-scoring task in each same-session conflict group.

    Greedy: sort by effective score, keep a task only when it does not conflict
    with anything already kept. Dropped rows carry ``_drop_reason``.
    """
    ordered = sorted(
        tasks,
        key=lambda t: (_score(t), -int(t.get("id") or 0)),
        reverse=True,
    )
    kept: list[Task] = []
    dropped: list[Task] = []
    for task in ordered:
        reason = None
        for other in kept:
            reason = session_conflict_reason(task, other)
            if reason:
                break
        if reason:
            dropped.append({**task, "_drop_reason": reason})
        else:
            kept.append(task)
    return kept, dropped


def ready_on(
    candidate_category: str,
    tree_id: int,
    completions: list[Completion],
    *,
    today: date,
) -> tuple[date | None, str | None]:
    """If blocked, return (first legal date, reason); else (None, None)."""
    latest: date | None = None
    reason: str | None = None
    for comp in completions:
        if comp.tree_id != tree_id:
            continue
        for block in comp.blocks or []:
            if block.get("category") != candidate_category:
                continue
            gap = int(block.get("min_gap_days") or 0)
            if gap <= 0:
                continue
            ready = comp.completed_on + timedelta(days=gap)
            if ready <= today:
                continue
            if latest is None or ready > latest:
                latest = ready
                reason = (
                    f"{candidate_category} blocked {gap}d after {comp.category} "
                    f"(ready {ready.isoformat()})"
                )
    return latest, reason


def apply_blocks(
    pending_tasks: list[Task],
    completions: list[Completion],
    *,
    today: date,
) -> tuple[list[Task], list[Task]]:
    """Split pending tasks into eligible vs blocked (blocked carry ``_drop_reason``)."""
    eligible: list[Task] = []
    blocked: list[Task] = []
    for task in pending_tasks:
        category = _task_category(task)
        if not category:
            eligible.append(task)
            continue
        ready, reason = ready_on(category, task["tree_id"], completions, today=today)
        if ready is None:
            eligible.append(task)
        else:
            blocked.append({**task, "_drop_reason": reason})
    return eligible, blocked
