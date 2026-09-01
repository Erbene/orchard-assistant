"""Service-layer tests for tasks (JIT scheduling model), against a real
throwaway SQLite database."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db
from app.repositories.task_repository import TaskRepository
from app.repositories.tree_repository import TreeRepository
from app.repositories.zone_repository import ZoneRepository
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


@pytest.fixture()
def ctx(tmp_path: Path):
    settings = Settings(db_path=str(tmp_path / "tasks.db"))
    init_db(settings)
    conn = connect(settings)
    trees = TreeRepository(conn)
    tasks = TaskService(TaskRepository(conn), trees)
    tree_svc = TreeService(trees, ZoneRepository(conn), get_default_validation_agent())
    try:
        yield tasks, tree_svc, conn
    finally:
        conn.commit()
        conn.close()


def run(coro):
    return asyncio.run(coro)


async def _make_tree(tree_svc: TreeService) -> int:
    tree = await tree_svc.create_tree(TreeCreate(species="mango", variety="Kent"))
    return tree.tree_id


def _task(tid: int, action: str, **kw) -> TaskCreate:
    return TaskCreate(tree_id=tid, action_type=action, **kw)


def test_create_task_requires_existing_tree(ctx):
    tasks, *_ = ctx
    with pytest.raises(DomainValidationError):
        run(tasks.create_task(_task(9999, "prune")))


def test_estimated_minutes_and_resources_round_trip(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    created = run(tasks.create_task(
        _task(tid, "spray", estimated_minutes=45, required_resources=["neem oil", "sprayer"])
    ))
    assert created.estimated_minutes == 45
    assert created.required_resources == ["neem oil", "sprayer"]
    assert run(tasks.get_task(created.id)).required_resources == ["neem oil", "sprayer"]


def test_pending_queue_orders_by_priority_and_filters_by_date(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    soon = datetime.now(timezone.utc) + timedelta(days=2)
    later = datetime.now(timezone.utc) + timedelta(days=40)

    run(tasks.create_task(_task(tid, "a", priority_score=1.0, scheduled_date=soon)))
    run(tasks.create_task(_task(tid, "b", priority_score=9.0, scheduled_date=soon)))
    run(tasks.create_task(_task(tid, "c", priority_score=5.0, scheduled_date=later)))
    run(tasks.create_task(_task(tid, "d", priority_score=2.0)))  # unscheduled

    queue = run(tasks.get_pending_queue())
    assert [t.priority_score for t in queue] == [9.0, 5.0, 2.0, 1.0]

    windowed = run(tasks.get_pending_queue(
        scheduled_before=datetime.now(timezone.utc) + timedelta(days=7)
    ))
    assert {t.action_type for t in windowed} == {"a", "b", "d"}  # "c" future; "d" unscheduled kept


def test_mark_complete_spawns_next_occurrence(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    when = datetime.now(timezone.utc)
    created = run(tasks.create_task(
        _task(tid, "irrigate", scheduled_date=when, frequency_days=7,
              estimated_minutes=20, required_resources=["hose"])
    ))

    done = run(tasks.mark_complete(created.id))
    assert done.status == "completed" and done.completed_at is not None

    pending = run(tasks.get_pending_queue())
    assert len(pending) == 1
    nxt = pending[0]
    assert nxt.id != created.id
    assert nxt.action_type == "irrigate"
    assert nxt.required_resources == ["hose"]        # carried forward
    assert nxt.scheduled_date.date() == (when + timedelta(days=7)).date()


def test_batch_update_priorities_fails_fast_on_unknown_id(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    t1 = run(tasks.create_task(_task(tid, "x")))
    t2 = run(tasks.create_task(_task(tid, "y")))

    with pytest.raises(NotFoundError):
        run(tasks.batch_update_priorities([
            TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
            TaskPriorityUpdate(task_id=99999, priority_score=1.0),
        ]))

    ok = run(tasks.batch_update_priorities([
        TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
        TaskPriorityUpdate(task_id=t2.id,
                           scheduled_date=datetime(2026, 9, 15, tzinfo=timezone.utc)),
    ]))
    assert ok[0].priority_score == 8.0
    assert ok[1].scheduled_date == datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_update_task_status_stamps_completed_at(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    t = run(tasks.create_task(_task(tid, "scout")))
    assert run(tasks.update_task(t.id, TaskUpdate(status="completed"))).completed_at is not None
    assert run(tasks.update_task(t.id, TaskUpdate(status="pending"))).completed_at is None


def test_create_baseline_tasks_uses_llm_supplied_items(ctx):
    tasks, tree_svc, _ = ctx
    tid = run(_make_tree(tree_svc))
    items = [
        TaskBaselineItem(action_type="inspect_health", estimated_minutes=15,
                         required_resources=[], frequency_days=30),
        TaskBaselineItem(action_type="fertilize", estimated_minutes=40,
                         required_resources=["10-10-10 fertilizer"], frequency_days=90),
    ]
    baseline = run(tasks.create_baseline_tasks(tid, items))
    assert {t.action_type for t in baseline} == {"inspect_health", "fertilize"}
    assert all(t.estimated_minutes and t.estimated_minutes > 0 for t in baseline)
    fert = next(t for t in baseline if t.action_type == "fertilize")
    assert fert.required_resources == ["10-10-10 fertilizer"]

    with pytest.raises(DomainValidationError):
        run(tasks.create_baseline_tasks(tid, []))


def test_deleting_tree_cascades_tasks(ctx):
    tasks, tree_svc, conn = ctx
    tid = run(_make_tree(tree_svc))
    run(tasks.create_task(_task(tid, "prune")))
    run(tree_svc.delete_tree(tid))
    assert conn.execute("SELECT count(*) FROM task").fetchone()[0] == 0
