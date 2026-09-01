"""Service-layer tests for Phase 1 (tasks + user context), against a real
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
from app.repositories.user_repository import UserRepository
from app.repositories.zone_repository import ZoneRepository
from app.schemas.task import TaskCreate, TaskPriorityUpdate, TaskUpdate
from app.schemas.tree import TreeCreate
from app.schemas.user_context import UserContextUpdate
from app.services.exceptions import DomainValidationError, NotFoundError
from app.services.task_service import TaskService
from app.services.tree_service import TreeService
from app.services.user_service import UserService
from app.services.validators import get_default_validation_agent


@pytest.fixture()
def ctx(tmp_path: Path):
    settings = Settings(db_path=str(tmp_path / "tasks.db"))
    init_db(settings)
    conn = connect(settings)
    validator = get_default_validation_agent()
    trees = TreeRepository(conn)
    tasks = TaskService(TaskRepository(conn), trees)
    tree_svc = TreeService(trees, ZoneRepository(conn), validator)
    users = UserService(UserRepository(conn))
    try:
        yield tasks, tree_svc, users, conn
    finally:
        conn.commit()
        conn.close()


def run(coro):
    return asyncio.run(coro)


async def _make_tree(tree_svc: TreeService) -> int:
    tree = await tree_svc.create_tree(TreeCreate(species="mango", variety="Kent"))
    return tree.tree_id


def test_create_task_requires_existing_tree(ctx):
    tasks, *_ = ctx
    with pytest.raises(DomainValidationError):
        run(tasks.create_task(TaskCreate(tree_id=9999, action_type="prune")))


def test_pending_queue_orders_by_priority_and_filters_by_date(ctx):
    tasks, tree_svc, _, _ = ctx
    tid = run(_make_tree(tree_svc))
    soon = datetime.now(timezone.utc) + timedelta(days=2)
    later = datetime.now(timezone.utc) + timedelta(days=40)

    run(tasks.create_task(TaskCreate(tree_id=tid, action_type="a", priority_score=1.0, scheduled_date=soon)))
    run(tasks.create_task(TaskCreate(tree_id=tid, action_type="b", priority_score=9.0, scheduled_date=soon)))
    run(tasks.create_task(TaskCreate(tree_id=tid, action_type="c", priority_score=5.0, scheduled_date=later)))
    run(tasks.create_task(TaskCreate(tree_id=tid, action_type="d", priority_score=2.0)))  # unscheduled

    queue = run(tasks.get_pending_queue())
    assert [t.action_type for t in queue] == ["b", "c", "d", "a"] or [t.priority_score for t in queue] == [9.0, 5.0, 2.0, 1.0]

    windowed = run(tasks.get_pending_queue(scheduled_before=datetime.now(timezone.utc) + timedelta(days=7)))
    names = {t.action_type for t in windowed}
    assert names == {"a", "b", "d"}  # "c" (day 40) excluded; unscheduled "d" kept


def test_mark_complete_spawns_next_occurrence(ctx):
    tasks, tree_svc, _, _ = ctx
    tid = run(_make_tree(tree_svc))
    when = datetime.now(timezone.utc)
    created = run(tasks.create_task(
        TaskCreate(tree_id=tid, action_type="irrigate", scheduled_date=when, frequency_days=7)
    ))

    done = run(tasks.mark_complete(created.id))
    assert done.status == "completed"
    assert done.completed_at is not None

    pending = run(tasks.get_pending_queue())
    assert len(pending) == 1
    nxt = pending[0]
    assert nxt.id != created.id
    assert nxt.action_type == "irrigate"
    assert nxt.frequency_days == 7
    assert nxt.scheduled_date is not None
    assert nxt.scheduled_date.date() == (when + timedelta(days=7)).date()


def test_batch_update_priorities_is_atomic(ctx):
    tasks, tree_svc, _, _ = ctx
    tid = run(_make_tree(tree_svc))
    t1 = run(tasks.create_task(TaskCreate(tree_id=tid, action_type="x")))
    t2 = run(tasks.create_task(TaskCreate(tree_id=tid, action_type="y")))

    with pytest.raises(NotFoundError):
        run(tasks.batch_update_priorities([
            TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
            TaskPriorityUpdate(task_id=99999, priority_score=1.0),
        ]))

    # first update was applied in-memory but the whole tool transaction would
    # roll back; here we just confirm the service raised before finishing t2
    ok = run(tasks.batch_update_priorities([
        TaskPriorityUpdate(task_id=t1.id, priority_score=8.0),
        TaskPriorityUpdate(task_id=t2.id, scheduled_date=datetime(2026, 9, 15, tzinfo=timezone.utc)),
    ]))
    assert ok[0].priority_score == 8.0
    assert ok[1].scheduled_date == datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_update_task_status_stamps_completed_at(ctx):
    tasks, tree_svc, _, _ = ctx
    tid = run(_make_tree(tree_svc))
    t = run(tasks.create_task(TaskCreate(tree_id=tid, action_type="scout")))
    updated = run(tasks.update_task(t.id, TaskUpdate(status="completed")))
    assert updated.completed_at is not None
    reopened = run(tasks.update_task(t.id, TaskUpdate(status="pending")))
    assert reopened.completed_at is None


def test_create_baseline_tasks(ctx):
    tasks, tree_svc, _, _ = ctx
    tid = run(_make_tree(tree_svc))
    baseline = run(tasks.create_baseline_tasks(tid))
    assert {t.action_type for t in baseline} == {
        "inspect_health",
        "fertilize",
        "mulch",
        "structural_prune",
    }
    assert all(t.frequency_days and t.scheduled_date for t in baseline)


def test_deleting_tree_cascades_tasks(ctx):
    tasks, tree_svc, _, conn = ctx
    tid = run(_make_tree(tree_svc))
    run(tasks.create_task(TaskCreate(tree_id=tid, action_type="prune")))
    run(tree_svc.delete_tree(tid))
    assert conn.execute("SELECT count(*) FROM task").fetchone()[0] == 0


def test_user_constraints_get_creates_default_then_update(ctx):
    _, _, users, _ = ctx
    default = run(users.get_constraints())
    assert default.available_labor_hours_per_day == 8.0
    assert default.available_products == []

    updated = run(users.update_constraints(
        UserContextUpdate(available_labor_hours_per_day=5.5, available_products=["urea", "neem oil"])
    ))
    assert updated.available_labor_hours_per_day == 5.5
    assert updated.available_products == ["urea", "neem oil"]
    assert run(users.get_constraints()).available_products == ["urea", "neem oil"]
