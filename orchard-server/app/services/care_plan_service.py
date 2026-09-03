"""Care Plan orchestration: generate templates from the Agronomist, keep them
editable, and materialise them into the recurring ``task`` stream.

Recurrence model: **one open task per template**. The first is scheduled from
the template's ``anchor_date`` (set by the baseline wizard) or today, plus the
interval; the next is spawned by ``TaskService`` when the current one is
completed or skipped.

Editing a template re-scales its numeric fields (via
``app.agent.agronomist.rescale_template``) and updates its single open pending
task; completed / skipped history is never touched.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from ..agent.agronomist import generate_care_plan, rescale_template
from ..repositories.task_repository import TaskRepository
from ..repositories.task_template_repository import TaskTemplateRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.care_plan import (
    BaselineAnswer,
    BaselineQuestion,
    CarePlan,
    TaskTemplateRead,
    TaskTemplateUpdate,
)
from ..schemas.task import TaskRead
from .exceptions import NotFoundError
from .source_service import SourceService

_RESCALE_TRIGGERS = {"category", "rate_class"}


def _midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time(), tzinfo=timezone.utc)


class CarePlanService:
    def __init__(
        self,
        templates: TaskTemplateRepository,
        tasks: TaskRepository,
        trees: TreeRepository,
        sources: SourceService,
        settings,
    ) -> None:
        self._templates = templates
        self._tasks = tasks
        self._trees = trees
        self._sources = sources
        self._settings = settings

    # -- read ------------------------------------------------------

    async def get_plan(self, tree_id: int) -> CarePlan:
        await self._require_tree(tree_id)
        rows = await self._templates.list_for_tree(tree_id)
        pending = await self._tasks.list(status="pending", tree_id=tree_id)
        pending_from_plan = [t for t in pending if t.get("template_id")]
        return CarePlan(
            tree_id=tree_id,
            templates=[TaskTemplateRead.model_validate(r) for r in rows],
            baseline_questions=self._questions(rows),
            pending_task_count=len(pending_from_plan),
            generated=bool(rows),
        )

    # -- generate (Agronomist) -----------------------------------

    async def generate(self, tree_id: int) -> CarePlan:
        tree = await self._require_tree(tree_id)

        draft = await generate_care_plan(
            tree=tree, sources=self._sources, settings=self._settings
        )

        # wipe the old plan's open tasks, then swap the templates
        for old in await self._templates.list_for_tree(tree_id):
            await self._tasks.delete_open_for_template(old["id"])
        await self._templates.replace_for_tree(tree_id, draft["templates"])

        return await self.get_plan(tree_id)

    # -- edit a template ---------------------------------------

    async def update_template(
        self, template_id: int, patch: TaskTemplateUpdate
    ) -> TaskTemplateRead:
        current = await self._templates.get(template_id)
        if current is None:
            raise NotFoundError(f"task template {template_id} not found")

        fields = patch.model_dump(exclude_unset=True)
        merged = {**current, **fields}

        if _RESCALE_TRIGGERS & fields.keys():
            tree = await self._trees.get(current["tree_id"])
            fields.update(rescale_template(merged, tree or {}))

        updated = await self._templates.update(template_id, fields)
        assert updated is not None

        # keep the single open task in sync (never touch closed history)
        open_task = await self._tasks.open_for_template(template_id)
        if open_task is not None:
            task_patch: dict = {
                "action_type": updated["name"],
                "priority_score": updated["priority_score"],
                "estimated_minutes": updated["estimated_minutes"],
                "required_resources": updated["required_resources"],
            }
            if "interval_days" in fields:
                base = updated["anchor_date"] or (open_task["created_at"].date())
                task_patch["scheduled_date"] = _midnight_utc(
                    base + timedelta(days=updated["interval_days"])
                )
            await self._tasks.update(open_task["id"], task_patch)

        return TaskTemplateRead.model_validate(updated)

    async def delete_template(self, template_id: int) -> None:
        current = await self._templates.get(template_id)
        if current is None:
            raise NotFoundError(f"task template {template_id} not found")
        await self._tasks.delete_open_for_template(template_id)
        await self._templates.delete(template_id)

    # -- baseline wizard -> first tasks ------------------------

    async def apply_baseline(
        self, tree_id: int, answers: list[BaselineAnswer]
    ) -> list[TaskRead]:
        """Turn "last done" answers into the first scheduled task per template.
        Re-runnable: a template that already has an open task is rescheduled
        (not duplicated) when its anchor changes."""
        await self._require_tree(tree_id)
        by_id = {a.template_id: a for a in answers}
        created: list[TaskRead] = []

        for tmpl in await self._templates.list_for_tree(tree_id):
            answer = by_id.get(tmpl["id"])
            if answer and answer.last_done is not None:
                await self._templates.update(
                    tmpl["id"], {"anchor_date": answer.last_done}
                )
                anchor = answer.last_done
            else:
                anchor = tmpl["anchor_date"]

            due = _midnight_utc(
                (anchor or date.today()) + timedelta(days=tmpl["interval_days"])
            )
            open_task = await self._tasks.open_for_template(tmpl["id"])
            if open_task is not None:
                if open_task["scheduled_date"] != due:
                    await self._tasks.update(
                        open_task["id"], {"scheduled_date": due}
                    )
                continue

            row = await self._tasks.create(
                {
                    "tree_id": tree_id,
                    "template_id": tmpl["id"],
                    "action_type": tmpl["name"],
                    "status": "pending",
                    "priority_score": tmpl["priority_score"],
                    "scheduled_date": due,
                    "estimated_minutes": tmpl["estimated_minutes"],
                    "required_resources": tmpl["required_resources"],
                }
            )
            created.append(TaskRead.model_validate(row))

        return created

    # -- helpers ----------------------------------------------

    async def _require_tree(self, tree_id: int) -> dict:
        row = await self._trees.get(tree_id)
        if row is None:
            raise NotFoundError(f"tree {tree_id} not found")
        return row

    @staticmethod
    def _questions(rows: list[dict]) -> list[BaselineQuestion]:
        return [
            BaselineQuestion(
                template_id=r["id"], name=r["name"], question=r["baseline_question"]
            )
            for r in rows
            if r.get("baseline_question")
        ]
