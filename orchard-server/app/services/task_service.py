"""Task business logic: state transitions, recurring-task spawning, batch
priority updates, and (LLM-driven) baseline task generation.

HTTP-agnostic. Every method returns pure Pydantic models and raises
framework-neutral ``DomainError`` subclasses.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from ..repositories.task_repository import TaskRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.task import (
    TaskBaselineItem,
    TaskCreate,
    TaskPriorityUpdate,
    TaskRead,
    TaskUpdate,
)
from .exceptions import DomainValidationError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskService:
    def __init__(self, tasks: TaskRepository, trees: TreeRepository) -> None:
        self._tasks = tasks
        self._trees = trees

    # -- reads --------------------------------------------------------

    async def list_tasks(
        self, *, status: str | None = None, tree_id: int | None = None
    ) -> list[TaskRead]:
        return [
            TaskRead.model_validate(r)
            for r in await self._tasks.list(status=status, tree_id=tree_id)
        ]

    async def get_task(self, task_id: int) -> TaskRead:
        row = await self._tasks.get(task_id)
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return TaskRead.model_validate(row)

    async def get_pending_queue(
        self, *, scheduled_before: datetime | None = None
    ) -> list[TaskRead]:
        rows = await self._tasks.list_pending(
            scheduled_before=scheduled_before.date() if scheduled_before else None
        )
        return [TaskRead.model_validate(r) for r in rows]

    # -- writes -----------------------------------------------------

    async def create_task(self, payload: TaskCreate) -> TaskRead:
        await self._require_tree(payload.tree_id)
        row = await self._tasks.create(
            {
                "tree_id": payload.tree_id,
                "action_type": payload.action_type.strip(),
                "status": payload.status,
                "priority_score": payload.priority_score,
                "scheduled_date": payload.scheduled_date,
                "frequency_days": payload.frequency_days,
                "estimated_minutes": payload.estimated_minutes,
                "required_resources": payload.required_resources,
            }
        )
        return TaskRead.model_validate(row)

    async def update_task(self, task_id: int, payload: TaskUpdate) -> TaskRead:
        current = await self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")

        patch = payload.model_dump(exclude_unset=True)
        if "scheduled_date" in patch:
            patch["scheduled_date"] = payload.scheduled_date
        if patch.get("action_type"):
            patch["action_type"] = patch["action_type"].strip()

        if "status" in patch:
            was_completed = current["status"] == "completed"
            now_completed = patch["status"] == "completed"
            if now_completed and not was_completed:
                patch["completed_at"] = _now()
            elif was_completed and not now_completed:
                patch["completed_at"] = None

        row = await self._tasks.update(task_id, patch)
        return TaskRead.model_validate(row)

    async def delete_task(self, task_id: int) -> None:
        if not await self._tasks.delete(task_id):
            raise NotFoundError(f"task {task_id} not found")

    async def mark_complete(self, task_id: int) -> TaskRead:
        """Mark a task ``completed``. If it recurs, spawn the next occurrence."""
        current = await self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")
        if current["status"] == "completed":
            return TaskRead.model_validate(current)

        row = await self._tasks.update(
            task_id, {"status": "completed", "completed_at": _now()}
        )
        completed = TaskRead.model_validate(row)

        if completed.frequency_days:
            anchor = completed.scheduled_date or datetime.now(timezone.utc)
            await self._tasks.create(
                {
                    "tree_id": completed.tree_id,
                    "action_type": completed.action_type,
                    "status": "pending",
                    "priority_score": completed.priority_score,
                    "scheduled_date": anchor + timedelta(days=completed.frequency_days),
                    "frequency_days": completed.frequency_days,
                    "estimated_minutes": completed.estimated_minutes,
                    "required_resources": completed.required_resources,
                }
            )
        return completed

    async def defer_task(
        self, task_id: int, *, until: datetime | None = None
    ) -> TaskRead:
        if await self._tasks.get(task_id) is None:
            raise NotFoundError(f"task {task_id} not found")
        patch: dict[str, object] = {"status": "deferred"}
        if until is not None:
            patch["scheduled_date"] = until
        return TaskRead.model_validate(await self._tasks.update(task_id, patch))

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
                patch["scheduled_date"] = change.scheduled_date
            row = (
                await self._tasks.update(change.task_id, patch)
                if patch
                else await self._tasks.get(change.task_id)
            )
            if row is None:
                raise NotFoundError(f"task {change.task_id} not found")
            results.append(TaskRead.model_validate(row))
        return results

    async def create_baseline_tasks(
        self, tree_id: int, items: Sequence[TaskBaselineItem]
    ) -> list[TaskRead]:
        """Create a starter task set for a tree from LLM-specified items.

        Each item must carry ``estimated_minutes`` and ``required_resources`` -
        the JIT scheduler needs them from the start.
        """
        await self._require_tree(tree_id)
        if not items:
            raise DomainValidationError("items", "at least one baseline task is required")

        created: list[TaskRead] = []
        for item in items:
            row = await self._tasks.create(
                {
                    "tree_id": tree_id,
                    "action_type": item.action_type.strip(),
                    "status": "pending",
                    "priority_score": item.priority_score,
                    "scheduled_date": item.scheduled_date,
                    "frequency_days": item.frequency_days,
                    "estimated_minutes": item.estimated_minutes,
                    "required_resources": item.required_resources,
                }
            )
            created.append(TaskRead.model_validate(row))
        return created

    # -- helpers ---------------------------------------------------

    async def _require_tree(self, tree_id: int) -> None:
        if await self._trees.get(tree_id) is None:
            raise DomainValidationError("tree_id", f"tree {tree_id} does not exist")
