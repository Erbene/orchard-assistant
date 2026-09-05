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

from datetime import date, datetime, time, timezone

from ..agent.agronomist import generate_care_plan, rescale_template
from ..agent.schedule_solver import months_from_tree, next_due
from ..schemas.tree import _normalize_month_list
from ..repositories.task_repository import TaskRepository
from ..repositories.task_template_repository import TaskTemplateRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.care_plan import (
    BaselineAnswer,
    BaselineQuestion,
    CarePlan,
    TaskTemplateRead,
    TaskTemplateUpdate,
    TreePhenologyRead,
)
from ..schemas.task import TaskRead
from .exceptions import DomainValidationError, NotFoundError
from .source_service import SourceService

_RESCALE_TRIGGERS = {"category", "rate_class"}
_SCHEDULE_TRIGGERS = {
    "interval_days", "valid_months", "biological_anchor", "anchor_offset_days",
}


def _midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time(), tzinfo=timezone.utc)


def _phenology_read(tree: dict) -> TreePhenologyRead:
    return TreePhenologyRead.from_tree_row(tree)


def _schedule_from_template(
    template: dict, *, after: date, phenology
) -> datetime:
    outcome = next_due(
        after=after,
        interval_days=template["interval_days"],
        valid_months=template.get("valid_months") or [],
        biological_anchor=template.get("biological_anchor"),
        anchor_offset_days=template.get("anchor_offset_days"),
        phenology=phenology,
    )
    assert outcome.date is not None
    return _midnight_utc(outcome.date)


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
        tree = await self._require_tree(tree_id)
        rows = await self._templates.list_for_tree(tree_id)
        pending = await self._tasks.list(status="pending", tree_id=tree_id)
        pending_from_plan = [t for t in pending if t.get("template_id")]
        return CarePlan(
            tree_id=tree_id,
            templates=[TaskTemplateRead.model_validate(r) for r in rows],
            baseline_questions=self._questions(rows),
            pending_task_count=len(pending_from_plan),
            generated=bool(rows),
            phenology=_phenology_read(tree),
        )

    # -- generate (Agronomist) -----------------------------------

    async def generate(self, tree_id: int) -> CarePlan:
        tree = await self._require_tree(tree_id)
        if not await self._sources.allowed_source_ids(tree_id):
            raise DomainValidationError(
                "sources",
                "Link at least one knowledge source before generating a care plan.",
            )

        draft = await generate_care_plan(
            tree=tree, sources=self._sources, settings=self._settings
        )

        phenology_patch: dict = {}
        for plural, singular, key in (
            ("expected_flowering_months", "expected_flowering_month", "flowering_months"),
            ("expected_harvest_months", "expected_harvest_month", "harvest_months"),
            ("expected_dormancy_months", "expected_dormancy_month", "dormancy_months"),
        ):
            months = _normalize_month_list(draft.get(key) or [])
            if months:
                phenology_patch[plural] = months
                phenology_patch[singular] = months[0]
        if phenology_patch:
            tree = await self._trees.update(tree_id, phenology_patch) or tree

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
            if _SCHEDULE_TRIGGERS & fields.keys():
                tree = await self._trees.get(current["tree_id"]) or {}
                base = updated["anchor_date"] or date.today()
                task_patch["scheduled_date"] = _schedule_from_template(
                    updated, after=base, phenology=months_from_tree(tree)
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
        self,
        tree_id: int,
        answers: list[BaselineAnswer],
        *,
        flowering_month: int | None = None,
        harvest_month: int | None = None,
        dormancy_month: int | None = None,
        flowering_months: list[int] | None = None,
        harvest_months: list[int] | None = None,
        dormancy_months: list[int] | None = None,
    ) -> list[TaskRead]:
        """Turn "last done" answers into the first scheduled task per template.
        Re-runnable: a template that already has an open task is rescheduled
        (not duplicated) when its anchor changes."""
        tree = await self._require_tree(tree_id)
        resolved = {
            "flowering_months": _normalize_month_list(
                flowering_months
                or ([flowering_month] if flowering_month is not None else [])
            ),
            "harvest_months": _normalize_month_list(
                harvest_months
                or ([harvest_month] if harvest_month is not None else [])
            ),
            "dormancy_months": _normalize_month_list(
                dormancy_months
                or ([dormancy_month] if dormancy_month is not None else [])
            ),
        }
        phenology_patch: dict = {}
        for plural, singular, key in (
            ("expected_flowering_months", "expected_flowering_month", "flowering_months"),
            ("expected_harvest_months", "expected_harvest_month", "harvest_months"),
            ("expected_dormancy_months", "expected_dormancy_month", "dormancy_months"),
        ):
            months = resolved[key]
            if months:
                phenology_patch[plural] = months
                phenology_patch[singular] = months[0]
        if phenology_patch:
            tree = await self._trees.update(tree_id, phenology_patch) or tree

        phenology = months_from_tree(tree)
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

            due = _schedule_from_template(
                tmpl, after=anchor or date.today(), phenology=phenology
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
