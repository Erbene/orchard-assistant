"""Unit tests for cross-task schedule rules (no DB)."""
from __future__ import annotations

from datetime import date, timedelta

from app.agent.schedule_rules import (
    Completion,
    apply_blocks,
    apply_session_conflicts,
    ready_on,
    session_conflict_reason,
)


def _task(tid: int, *, tree_id: int = 1, category: str = "prune") -> dict:
    return {
        "id": tid,
        "tree_id": tree_id,
        "template_category": category,
        "action_type": category,
        "status": "pending",
    }


def test_spray_blocks_prune_for_seven_days():
    today = date(2026, 6, 1)
    completions = [
        Completion(
            tree_id=1,
            category="spray",
            completed_on=today - timedelta(days=4),
            blocks=[{"category": "prune", "min_gap_days": 7}],
        )
    ]
    ready, reason = ready_on("prune", 1, completions, today=today)
    assert ready == date(2026, 6, 4)
    assert reason is not None and "prune blocked 7d after spray" in reason


def test_different_tree_not_blocked():
    today = date(2026, 6, 1)
    completions = [
        Completion(
            tree_id=2,
            category="spray",
            completed_on=today - timedelta(days=1),
            blocks=[{"category": "prune", "min_gap_days": 7}],
        )
    ]
    ready, reason = ready_on("prune", 1, completions, today=today)
    assert ready is None and reason is None


def test_empty_blocks_no_block():
    today = date(2026, 6, 1)
    completions = [
        Completion(
            tree_id=1,
            category="spray",
            completed_on=today - timedelta(days=1),
            blocks=[],
        )
    ]
    ready, reason = ready_on("prune", 1, completions, today=today)
    assert ready is None and reason is None


def test_two_completions_take_later_ready_on():
    today = date(2026, 6, 1)
    completions = [
        Completion(
            tree_id=1,
            category="spray",
            completed_on=date(2026, 5, 20),
            blocks=[{"category": "prune", "min_gap_days": 7}],
        ),
        Completion(
            tree_id=1,
            category="fertilize",
            completed_on=date(2026, 5, 25),
            blocks=[{"category": "prune", "min_gap_days": 14}],
        ),
    ]
    ready, _ = ready_on("prune", 1, completions, today=today)
    assert ready == date(2026, 6, 8)


def test_apply_blocks_splits_and_tags_reason():
    today = date(2026, 6, 1)
    completions = [
        Completion(
            tree_id=1,
            category="spray",
            completed_on=today - timedelta(days=2),
            blocks=[{"category": "prune", "min_gap_days": 7}],
        )
    ]
    tasks = [_task(1, category="prune"), _task(2, category="scout")]
    eligible, blocked = apply_blocks(tasks, completions, today=today)
    assert [t["id"] for t in eligible] == [2]
    assert len(blocked) == 1
    assert blocked[0]["_drop_reason"] and "prune blocked" in blocked[0]["_drop_reason"]


def test_session_conflict_two_fertilize_same_tree():
    nitrogen = _task(1, category="fertilize")
    nitrogen["action_type"] = "Nitrogen feed"
    nitrogen["_effective_score"] = 8.0
    potassium = _task(2, category="fertilize")
    potassium["action_type"] = "Potassium feed"
    potassium["_effective_score"] = 6.0
    kept, dropped = apply_session_conflicts([nitrogen, potassium])
    assert [t["id"] for t in kept] == [1]
    assert dropped[0]["id"] == 2
    assert "one fertilize" in dropped[0]["_drop_reason"]
    assert session_conflict_reason(potassium, nitrogen) is not None


def test_session_conflict_allows_fertilize_on_different_trees():
    a = {**_task(1, tree_id=1, category="fertilize"), "_effective_score": 8.0}
    b = {**_task(2, tree_id=2, category="fertilize"), "_effective_score": 7.0}
    kept, dropped = apply_session_conflicts([a, b])
    assert {t["id"] for t in kept} == {1, 2}
    assert dropped == []


def test_session_conflict_prospective_blocks():
    spray = _task(1, category="spray")
    spray["action_type"] = "copper spray"
    spray["template_blocks"] = [{"category": "prune", "min_gap_days": 7}]
    spray["_effective_score"] = 9.0
    prune = {**_task(2, category="prune"), "_effective_score": 4.0}
    kept, dropped = apply_session_conflicts([spray, prune])
    assert [t["id"] for t in kept] == [1]
    assert dropped[0]["id"] == 2
    assert "cannot run the same day" in dropped[0]["_drop_reason"]


def test_session_conflict_two_prunes_ok():
    a = {**_task(1, category="prune"), "action_type": "structural prune", "_effective_score": 5.0}
    b = {**_task(2, category="prune"), "action_type": "sprout prune", "_effective_score": 4.0}
    kept, dropped = apply_session_conflicts([a, b])
    assert {t["id"] for t in kept} == {1, 2}
    assert dropped == []
