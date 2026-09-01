"""Task business logic: state transitions, recurring-task spawning, batch
priority updates, and baseline task generation.

HTTP-agnostic. Every method returns pure Pydantic models (``TaskRead`` /
``list[TaskRead]``) and raises framework-neutral ``DomainError`` subclasses.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from ..repositories.task_repository import TaskRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.task import (
    TaskCreate,
    TaskPriorityUpdate,
    TaskRead,
    TaskUpdate,
)
from .exceptions import DomainValidationError, NotFoundError

# Standard starter task set for a newly planted tree. First occurrence is
# scheduled ``frequency_days`` out; the Foreman agent redistributes from there.
_BASELINE_TASKS: tuple[dict[str, float | str | int], ...] = (
    {"action_type": "inspect_health", "priority_score": 5.0, "frequency_days": 30},
    {"action_type": "fertilize", "priority_score": 6.0, "frequency_days": 90},
    {"action_type": "mulch", "priority_score": 3.0, "frequency_days": 180},
    {"action_type": "structural_prune", "priority_score": 4.0, "frequency_days": 365},
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskService:
    def __init__(self, tasks: TaskRepository, trees: TreeRepository) -> None:
        self._tasks = tasks
        self._trees = trees

    # -- reads --------------------------------------------------------

    async def list_tasks(
        self, *, status: str | None = None, tree_id: int | None = None
    ) -> list[TaskRead]:
        rows = self._tasks.list(status=status, tree_id=tree_id)
        return [TaskRead.model_validate(r) for r in rows]

    async def get_task(self, task_id: int) -> TaskRead:
        row = self._tasks.get(task_id)
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return TaskRead.model_validate(row)

    async def get_pending_queue(
        self, *, scheduled_before: datetime | None = None
    ) -> list[TaskRead]:
        """Pending tasks, highest priority first (see ``TaskRepository.list_pending``)."""
        rows = self._tasks.list_pending(scheduled_before=_iso(scheduled_before))
        return [TaskRead.model_validate(r) for r in rows]

    # -- writes -----------------------------------------------------

    async def create_task(self, payload: TaskCreate) -> TaskRead:
        self._require_tree(payload.tree_id)
        row = self._tasks.create(
            {
                "tree_id": payload.tree_id,
                "action_type": payload.action_type.strip(),
                "status": payload.status,
                "priority_score": payload.priority_score,
                "scheduled_date": _iso(payload.scheduled_date),
                "frequency_days": payload.frequency_days,
            }
        )
        return TaskRead.model_validate(row)

    async def update_task(self, task_id: int, payload: TaskUpdate) -> TaskRead:
        current = self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")

        patch = payload.model_dump(exclude_unset=True)
        if "scheduled_date" in patch:
            patch["scheduled_date"] = _iso(payload.scheduled_date)
        if "action_type" in patch and patch["action_type"] is not None:
            patch["action_type"] = patch["action_type"].strip()

        # keep completed_at consistent with any status change
        if "status" in patch:
            was_completed = current["status"] == "completed"
            now_completed = patch["status"] == "completed"
            if now_completed and not was_completed:
                patch["completed_at"] = _now_iso()
            elif was_completed and not now_completed:
                patch["completed_at"] = None

        row = self._tasks.update(task_id, patch)
        return TaskRead.model_validate(row)

    async def delete_task(self, task_id: int) -> None:
        if not self._tasks.delete(task_id):
            raise NotFoundError(f"task {task_id} not found")

    async def mark_complete(self, task_id: int) -> TaskRead:
        """Mark a task ``completed``. If it recurs, spawn the next occurrence."""
        current = self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")
        if current["status"] == "completed":
            return TaskRead.model_validate(current)

        row = self._tasks.update(
            task_id, {"status": "completed", "completed_at": _now_iso()}
        )
        completed = TaskRead.model_validate(row)

        if completed.frequency_days:
            anchor = completed.scheduled_date or datetime.now(timezone.utc)
            self._tasks.create(
                {
                    "tree_id": completed.tree_id,
                    "action_type": completed.action_type,
                    "status": "pending",
                    "priority_score": completed.priority_score,
                    "scheduled_date": _iso(
                        anchor + timedelta(days=completed.frequency_days)
                    ),
                    "frequency_days": completed.frequency_days,
                }
            )
        return completed

    async def defer_task(
        self, task_id: int, *, until: datetime | None = None
    ) -> TaskRead:
        current = self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")
        patch: dict[str, object] = {"status": "deferred"}
        if until is not None:
            patch["scheduled_date"] = _iso(until)
        row = self._tasks.update(task_id, patch)
        return TaskRead.model_validate(row)

    async def batch_update_priorities(
        self, updates: Sequence[TaskPriorityUpdate]
    ) -> list[TaskRead]:
        """Apply ``priority_score`` / ``scheduled_date`` changes to many tasks
        in one transaction. Fails fast (whole batch rolls back) if any
        ``task_id`` is unknown."""
        results: list[TaskRead] = []
        for change in updates:
            patch: dict[str, object] = {}
            if change.priority_score is not None:
                patch["priority_score"] = change.priority_score
            if change.scheduled_date is not None:
                patch["scheduled_date"] = _iso(change.scheduled_date)

            row = (
                self._tasks.update(change.task_id, patch)
                if patch
                else self._tasks.get(change.task_id)
            )
            if row is None:
                raise NotFoundError(f"task {change.task_id} not found")
            results.append(TaskRead.model_validate(row))
        return results

    async def create_baseline_tasks(
        self, tree_id: int, *, start_date: datetime | None = None
    ) -> list[TaskRead]:
        """Create the standard recurring care tasks for a (newly planted) tree."""
        self._require_tree(tree_id)
        start = start_date or datetime.now(timezone.utc)
        created: list[TaskRead] = []
        for template in _BASELINE_TASKS:
            frequency = int(template["frequency_days"])
            row = self._tasks.create(
                {
                    "tree_id": tree_id,
                    "action_type": str(template["action_type"]),
                    "status": "pending",
                    "priority_score": float(template["priority_score"]),
                    "scheduled_date": _iso(start + timedelta(days=frequency)),
                    "frequency_days": frequency,
                }
            )
            created.append(TaskRead.model_validate(row))
        return created

    # -- helpers ---------------------------------------------------

    def _require_tree(self, tree_id: int) -> None:
        if self._trees.get(tree_id) is None:
            raise DomainValidationError("tree_id", f"tree {tree_id} does not exist")
