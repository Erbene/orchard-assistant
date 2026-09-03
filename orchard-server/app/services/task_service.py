"""Task business logic: state transitions, recurring-task spawning, batch
priority updates, and (LLM-driven) baseline task generation.

HTTP-agnostic. Every method returns pure Pydantic models and raises
framework-neutral ``DomainError`` subclasses.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone

from ..agent.schedule_rules import Completion, ready_on
from ..agent.schedule_solver import compute_window_closes_on, months_from_tree, next_due
from ..repositories.task_repository import TaskRepository
from ..repositories.task_template_repository import TaskTemplateRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.task import (
    InboxTaskRead,
    TaskBaselineItem,
    TaskCreate,
    TaskPriorityUpdate,
    TaskRead,
    TaskUpdate,
)
from .exceptions import DomainValidationError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _phenology_from_tree(tree: dict):
    return months_from_tree(tree)


def _window_closes_on_row(row: dict) -> date | None:
    scheduled = _as_date(row.get("scheduled_date"))
    if scheduled is None:
        return None
    valid_months = row.get("template_valid_months")
    if isinstance(valid_months, str):
        valid_months = json.loads(valid_months)
    if not valid_months:
        return None
    return compute_window_closes_on(scheduled, valid_months)


def _enrich_window_fields(row: dict, *, today: date | None = None) -> dict:
    d = dict(row)
    closes = _window_closes_on_row(d)
    d["window_closes_on"] = closes
    today = today or date.today()
    d["out_of_season"] = closes is not None and closes < today
    return d


class TaskService:
    def __init__(
        self,
        tasks: TaskRepository,
        trees: TreeRepository,
        templates: TaskTemplateRepository | None = None,
    ) -> None:
        self._tasks = tasks
        self._trees = trees
        self._templates = templates

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
        rows = await self._heal_blocked_schedules(rows)
        enriched = [_enrich_window_fields(row) for row in rows]
        return [TaskRead.model_validate(r) for r in enriched]

    async def inbox(self) -> list[InboxTaskRead]:
        """The schedule inbox: pending tasks + template/tree labels + amounts,
        priority-then-date ordered."""
        rows = await self._heal_blocked_schedules(await self._tasks.inbox())
        rows = [_enrich_window_fields(row) for row in rows]
        rows.sort(key=lambda r: r.get("out_of_season", False))
        return [InboxTaskRead.model_validate(r) for r in rows]

    async def recent_completions_for_scheduling(self) -> list[dict]:
        """Completed care-plan tasks within 90 days, for cross-task block rules."""
        out: list[dict] = []
        for row in await self._tasks.list_recent_completions(within_days=90):
            completed = _as_date(row.get("completed_at"))
            if completed is None:
                continue
            blocks = row.get("template_blocks") or []
            if isinstance(blocks, str):
                blocks = json.loads(blocks)
            out.append(
                {
                    "tree_id": row["tree_id"],
                    "category": row["template_category"],
                    "completed_on": completed.isoformat(),
                    "blocks": blocks,
                }
            )
        return out

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
        """Mark a task ``completed``, then spawn the next occurrence if it
        belongs to a Care Plan template (or has a bare ``frequency_days``)."""
        return await self._close_and_respawn(task_id, "completed")

    async def skip_task(self, task_id: int) -> TaskRead:
        """Mark a task ``skipped`` (done nothing, don't do it) and still advance
        the recurrence so the plan keeps rolling."""
        return await self._close_and_respawn(task_id, "skipped")

    async def _close_and_respawn(self, task_id: int, status: str) -> TaskRead:
        current = await self._tasks.get(task_id)
        if current is None:
            raise NotFoundError(f"task {task_id} not found")
        if current["status"] in ("completed", "skipped"):
            return TaskRead.model_validate(current)

        patch: dict[str, object] = {"status": status}
        if status == "completed":
            patch["completed_at"] = _now()
        closed = TaskRead.model_validate(await self._tasks.update(task_id, patch))

        if status == "completed":
            after = _as_date(closed.completed_at) or date.today()
        else:
            after = date.today()
        template = None
        if closed.template_id and self._templates is not None:
            template = await self._templates.get(closed.template_id)

        if template is not None:
            tree = await self._trees.get(closed.tree_id) or {}
            outcome = next_due(
                after=after,
                interval_days=template["interval_days"],
                valid_months=template.get("valid_months") or [],
                biological_anchor=template.get("biological_anchor"),
                anchor_offset_days=template.get("anchor_offset_days"),
                phenology=_phenology_from_tree(tree),
            )
            next_date = outcome.date or after
            await self._tasks.create(
                {
                    "tree_id": closed.tree_id,
                    "template_id": template["id"],
                    "action_type": template["name"],
                    "status": "pending",
                    "priority_score": template["priority_score"],
                    "scheduled_date": datetime.combine(
                        next_date, datetime.min.time(), tzinfo=timezone.utc
                    ),
                    "estimated_minutes": template["estimated_minutes"],
                    "required_resources": template["required_resources"],
                }
            )
        elif closed.frequency_days:
            await self._tasks.create(
                {
                    "tree_id": closed.tree_id,
                    "action_type": closed.action_type,
                    "status": "pending",
                    "priority_score": closed.priority_score,
                    "scheduled_date": datetime.combine(
                        after + timedelta(days=closed.frequency_days),
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ),
                    "frequency_days": closed.frequency_days,
                    "estimated_minutes": closed.estimated_minutes,
                    "required_resources": closed.required_resources,
                }
            )
        return closed

    async def mark_many_complete(self, task_ids: Sequence[int]) -> list[TaskRead]:
        """Complete several tasks at once (the Foreman's write path). Unknown or
        already-completed ids are skipped; returns the tasks actually touched."""
        done: list[TaskRead] = []
        for task_id in dict.fromkeys(task_ids):  # de-dupe, keep order
            try:
                done.append(await self.mark_complete(int(task_id)))
            except NotFoundError:
                continue
        return done

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

    async def _load_completions(self) -> list[Completion]:
        completions: list[Completion] = []
        for row in await self._tasks.list_recent_completions(within_days=90):
            completed = _as_date(row.get("completed_at"))
            category = row.get("template_category")
            if completed is None or not category:
                continue
            blocks = row.get("template_blocks") or []
            if isinstance(blocks, str):
                blocks = json.loads(blocks)
            completions.append(
                Completion(
                    tree_id=row["tree_id"],
                    category=category,
                    completed_on=completed,
                    blocks=blocks,
                )
            )
        return completions

    async def _heal_blocked_schedules(
        self, rows: list[dict], *, today: date | None = None
    ) -> list[dict]:
        """Push blocked pending tasks forward to their first legal date (same row)."""
        today = today or date.today()
        completions = await self._load_completions()
        healed: list[dict] = []
        for row in rows:
            category = row.get("template_category")
            if not category:
                healed.append(row)
                continue
            ready, _ = ready_on(category, row["tree_id"], completions, today=today)
            if ready is None:
                healed.append(row)
                continue
            current = _as_date(row.get("scheduled_date"))
            if current is None or current < today or ready > current:
                new_dt = datetime.combine(
                    ready, datetime.min.time(), tzinfo=timezone.utc
                )
                updated = await self._tasks.update(row["id"], {"scheduled_date": new_dt})
                healed.append(updated if updated is not None else {**row, "scheduled_date": new_dt})
            else:
                healed.append(row)
        return healed
