"""Pure cross-task scheduling rules (no DB, no LLM).

After a task in category X completes, its template ``blocks`` list may forbid
other categories on the same tree until ``min_gap_days`` have elapsed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

Task = dict[str, Any]


@dataclass(frozen=True)
class Completion:
    tree_id: int
    category: str          # template category of the completed task
    completed_on: date
    blocks: list[dict]     # that template's blocks


def _task_category(task: Task) -> str | None:
    cat = task.get("template_category") or task.get("category")
    return str(cat).strip() if cat else None


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
