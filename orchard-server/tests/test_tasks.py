"""Service-layer tests for tasks (JIT scheduling model), against the
disposable ``orchard_test`` Postgres database.

An ``AsyncConnection`` is loop-bound, so each test body is a single async
function run once via ``asyncio.run`` - the ``orchard`` fixture opens the
connection, wires the services, and hands them to the body.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import db
from app.repositories.task_repository import TaskRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.task import (
    TaskBaselineItem,
    TaskCreate,
    TaskPriorityUpdate,
    TaskUpdate,
)
from app.schemas.tree import TreeCreate
from app.services.exceptions import DomainValidationError, NotFoundError
from app.services.task_service import TaskService
from app.services.tree_service import TreeService
from app.services.validators import get_default_validation_agent

from conftest import stack_settings


@dataclass
class Ctx:
    tasks: TaskService
    trees: TreeService
    conn: AsyncConnection


@pytest.fixture()
def orchard(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))

    def run(body):
        async def _wrap():
            try:
                async with db.connection(settings) as conn:
                    tree_repo = TreeRepository(conn)
                    ctx = Ctx(
                        tasks=TaskService(TaskRepository(conn), tree_repo),
                        trees=TreeService(tree_repo, get_default_validation_agent()),
                        conn=conn,
                    )
                    return await body(ctx)
            finally:
                # asyncpg connections are loop-bound; each test gets its own
                # asyncio.run() loop, so the cached engine must not outlive it.
                await db.dispose_all()

        return asyncio.run(_wrap())

    return run


async def _make_tree(tree_svc: TreeService) -> int:
    tree = await tree_svc.create_tree(TreeCreate(species="mango", variety="Kent"))
    return tree.tree_id


def _task(tid: int, action: str, **kw) -> TaskCreate:
    return TaskCreate(tree_id=tid, action_type=action, **kw)


def test_create_task_requires_existing_tree(orchard):
    async def body(c: Ctx):
        with pytest.raises(DomainValidationError):
            await c.tasks.create_task(_task(9999, "prune"))

    orchard(body)


def test_estimated_minutes_and_resources_round_trip(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        created = await c.tasks.create_task(
            _task(tid, "spray", estimated_minutes=45,
                  required_resources=["neem oil", "sprayer"])
        )
        assert created.estimated_minutes == 45
        assert created.required_resources == ["neem oil", "sprayer"]
        got = await c.tasks.get_task(created.id)
        assert got.required_resources == ["neem oil", "sprayer"]

    orchard(body)


def test_pending_queue_orders_by_priority_and_filters_by_date(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        soon = datetime.now(timezone.utc) + timedelta(days=2)
        later = datetime.now(timezone.utc) + timedelta(days=40)

        await c.tasks.create_task(_task(tid, "a", priority_score=1.0, scheduled_date=soon))
        await c.tasks.create_task(_task(tid, "b", priority_score=9.0, scheduled_date=soon))
        await c.tasks.create_task(_task(tid, "c", priority_score=5.0, scheduled_date=later))
        await c.tasks.create_task(_task(tid, "d", priority_score=2.0))  # unscheduled

        queue = await c.tasks.get_pending_queue()
        assert [t.priority_score for t in queue] == [9.0, 5.0, 2.0, 1.0]

        windowed = await c.tasks.get_pending_queue(
            scheduled_before=datetime.now(timezone.utc) + timedelta(days=7)
        )
        assert {t.action_type for t in windowed} == {"a", "b", "d"}

    orchard(body)


def test_mark_complete_spawns_next_occurrence(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        when = datetime.now(timezone.utc)
        created = await c.tasks.create_task(
            _task(tid, "irrigate", scheduled_date=when, frequency_days=7,
                  estimated_minutes=20, required_resources=["hose"])
        )

        done = await c.tasks.mark_complete(created.id)
        assert done.status == "completed" and done.completed_at is not None

        pending = await c.tasks.get_pending_queue()
        assert len(pending) == 1
        nxt = pending[0]
        assert nxt.id != created.id
        assert nxt.action_type == "irrigate"
        assert nxt.required_resources == ["hose"]
        assert nxt.scheduled_date.date() == (when + timedelta(days=7)).date()

    orchard(body)


def test_batch_update_priorities_fails_fast_on_unknown_id(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        t1 = await c.tasks.create_task(_task(tid, "x"))
        t2 = await c.tasks.create_task(_task(tid, "y"))

        with pytest.raises(NotFoundError):
            await c.tasks.batch_update_priorities([
                TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
                TaskPriorityUpdate(task_id=99999, priority_score=1.0),
            ])

        ok = await c.tasks.batch_update_priorities([
            TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
            TaskPriorityUpdate(task_id=t2.id,
                               scheduled_date=datetime(2026, 9, 15, tzinfo=timezone.utc)),
        ])
        assert ok[0].priority_score == 8.0
        assert ok[1].scheduled_date == datetime(2026, 9, 15, tzinfo=timezone.utc)

    orchard(body)


def test_update_task_status_stamps_completed_at(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        t = await c.tasks.create_task(_task(tid, "scout"))
        done = await c.tasks.update_task(t.id, TaskUpdate(status="completed"))
        assert done.completed_at is not None
        reopened = await c.tasks.update_task(t.id, TaskUpdate(status="pending"))
        assert reopened.completed_at is None

    orchard(body)


def test_create_baseline_tasks_uses_llm_supplied_items(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        items = [
            TaskBaselineItem(action_type="inspect_health", estimated_minutes=15,
                             required_resources=[], frequency_days=30),
            TaskBaselineItem(action_type="fertilize", estimated_minutes=40,
                             required_resources=["10-10-10 fertilizer"], frequency_days=90),
        ]
        baseline = await c.tasks.create_baseline_tasks(tid, items)
        assert {t.action_type for t in baseline} == {"inspect_health", "fertilize"}
        assert all(t.estimated_minutes and t.estimated_minutes > 0 for t in baseline)
        fert = next(t for t in baseline if t.action_type == "fertilize")
        assert fert.required_resources == ["10-10-10 fertilizer"]

        with pytest.raises(DomainValidationError):
            await c.tasks.create_baseline_tasks(tid, [])

    orchard(body)


def test_deleting_tree_cascades_tasks(orchard):
    async def body(c: Ctx):
        tid = await _make_tree(c.trees)
        await c.tasks.create_task(_task(tid, "prune"))
        await c.trees.delete_tree(tid)
        count = await c.conn.execute(text("SELECT count(*) FROM task"))
        assert count.scalar_one() == 0

    orchard(body)
