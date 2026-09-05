"""Phase 4 - Foreman engine + graph. Pure/deterministic; no DB, no Ollama
(OLLAMA_BASE_URL is unreachable in conftest -> template summary)."""
from __future__ import annotations

from datetime import date, timedelta

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.escalation import escalate, task_age_days
from app.agent.foreman import build_foreman_graph, pack, refit, resources_for
from app.agent.schedule_rules import Completion, apply_blocks


def _task(tid, action, score, minutes, resources=(), *, days_old=0):
    anchor = (date.today() - timedelta(days=days_old)).isoformat()
    return {
        "id": tid, "tree_id": 1, "action_type": action, "status": "pending",
        "priority_score": score, "estimated_minutes": minutes,
        "required_resources": list(resources),
        "scheduled_date": None, "created_at": anchor, "completed_at": None,
        "frequency_days": None,
    }


# -- escalation -----------------------------------------------------------

def test_escalation_rules_and_generic_fallback():
    tasks = [
        _task(1, "copper fungicide spray", 4.0, 30, days_old=11),   # rule: 7d -> 3.0x
        _task(2, "hand-weed the row", 5.0, 20, days_old=20),        # generic: 14d -> 2.0x
        _task(3, "structural prune", 6.0, 45, days_old=5),          # prune rule 21d, not late
    ]
    scored, escalations = escalate(tasks)
    by_id = {t["id"]: t for t in scored}
    assert by_id[1]["_effective_score"] == 12.0
    assert by_id[2]["_effective_score"] == 10.0
    assert by_id[3]["_effective_score"] == 6.0            # untouched
    ids = {e["task_id"]: e for e in escalations}
    assert set(ids) == {1, 2}
    assert ids[1]["multiplier"] == 3.0 and ids[1]["days_late"] == 11
    assert "overdue" in ids[1]["reason"]


def test_task_age_days_never_negative():
    assert task_age_days(_task(1, "x", 1, 10, days_old=0)) == 0
    future = {"id": 1, "scheduled_date": (date.today() + timedelta(days=3)).isoformat()}
    assert task_age_days(future) == 0


def test_escalation_window_closing():
    today = date.today()
    closing = (today + timedelta(days=7)).isoformat()
    tasks = [
        {
            **_task(1, "spring mulch", 5.0, 20),
            "window_closes_on": closing,
        },
        _task(2, "copper fungicide spray", 4.0, 30, days_old=11),
    ]
    scored, escalations = escalate(tasks, today=today)
    by_id = {t["id"]: t for t in scored}
    assert by_id[1]["_effective_score"] == 10.0
    assert by_id[2]["_effective_score"] == 12.0
    mults = {e["task_id"]: e["multiplier"] for e in escalations}
    assert mults[1] == 2.0
    assert mults[2] == 3.0


def test_escalation_window_closed_sinks_overdue():
    today = date.today()
    closed = (today - timedelta(days=1)).isoformat()
    tasks = [
        {
            **_task(1, "Nitrogen feed", 8.0, 30, days_old=20),
            "window_closes_on": closed,
        },
    ]
    scored, escalations = escalate(tasks, today=today)
    assert scored[0]["_effective_score"] == 2.0
    assert len(escalations) == 1
    esc = escalations[0]
    assert esc["multiplier"] == 0.25
    assert esc["days_late"] == 20
    assert "out of season" in esc["reason"]
    assert "window closed" in esc["reason"]


def test_escalation_window_closed_not_overdue():
    today = date.today()
    closed = (today - timedelta(days=3)).isoformat()
    future = (today + timedelta(days=5)).isoformat()
    tasks = [
        {
            **_task(1, "spring mulch", 6.0, 20, days_old=0),
            "scheduled_date": future,
            "window_closes_on": closed,
        },
    ]
    scored, escalations = escalate(tasks, today=today)
    assert scored[0]["_effective_score"] == 1.5
    assert escalations[0]["multiplier"] == 0.25


# -- knapsack + refit ---------------------------------------------------

def test_pack_respects_budget_and_prefers_value():
    tasks = [
        {**_task(1, "a", 10.0, 40), "_effective_score": 10.0},
        {**_task(2, "b", 9.0, 20), "_effective_score": 9.0},
        {**_task(3, "c", 1.0, 20), "_effective_score": 1.0},
    ]
    picked = pack(tasks, minutes=45)          # b (20) + c (20) fits; a (40) alone would too
    assert {t["id"] for t in picked} == {2, 3}
    assert sum(t["estimated_minutes"] for t in picked) <= 45


def test_pack_schedules_tasks_without_estimates():
    tasks = [{**_task(1, "a", 5.0, None), "_effective_score": 5.0}]
    assert pack(tasks, minutes=30) == tasks   # default 30 min -> fits


def test_refit_drops_blocked_tasks_and_backfills():
    prune = {**_task(1, "prune", 9.0, 40, ["Shears"]), "_effective_score": 9.0}
    spray = {**_task(2, "spray", 8.0, 30, ["Copper"]), "_effective_score": 8.0}
    mulch = {**_task(3, "mulch", 2.0, 20), "_effective_score": 2.0}
    inspect = {**_task(4, "inspect", 1.0, 15), "_effective_score": 1.0}
    proposed = [prune, spray]
    final, dropped = refit([prune, spray, mulch, inspect], proposed, ["Copper"], minutes=90)
    assert [t["id"] for t in dropped] == [2]
    assert dropped[0]["_drop_reason"] == "needs Copper"
    assert {t["id"] for t in final} == {1, 3, 4}          # prune kept, freed time -> mulch + inspect


def test_refit_excludes_blocked_ids_from_backfill():
    prune = {**_task(1, "prune", 9.0, 40, ["Shears"]), "_effective_score": 9.0}
    spray = {**_task(2, "spray", 8.0, 30, ["Copper"]), "_effective_score": 8.0}
    mulch = {**_task(3, "mulch", 2.0, 20), "_effective_score": 2.0}
    proposed = [spray]
    final, dropped = refit(
        [prune, spray, mulch], proposed, [], minutes=90, blocked_ids={1}
    )
    assert 1 not in {t["id"] for t in final}
    assert {t["id"] for t in final} == {2, 3}
    assert dropped == []


def test_apply_blocks_drops_cross_task_blocked():
    today = date.today()
    completions = [
        Completion(
            tree_id=1,
            category="spray",
            completed_on=today - timedelta(days=2),
            blocks=[{"category": "prune", "min_gap_days": 7}],
        )
    ]
    tasks = [
        {**_task(1, "prune sprouts", 8.0, 45, ["Pruning Shears"]), "template_category": "prune"},
        {**_task(2, "mulch ring", 3.0, 20), "template_category": "mulch"},
    ]
    eligible, blocked = apply_blocks(tasks, completions, today=today)
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-blocks"}}
    r = g.invoke(
        {
            "pending_tasks": tasks,
            "recent_completions": [
                {
                    "tree_id": 1,
                    "category": "spray",
                    "completed_on": (today - timedelta(days=2)).isoformat(),
                    "blocks": [{"category": "prune", "min_gap_days": 7}],
                }
            ],
            "available_minutes": 120,
        },
        cfg,
    )
    assert {t["id"] for t in eligible} == {2}
    assert blocked[0]["id"] == 1
    assert 1 in {t["id"] for t in r["dropped_tasks"]}
    assert {t["id"] for t in r["proposed_tasks"]} == {2}


# -- graph flow (MemorySaver) -----------------------------------------

def _graph():
    return build_foreman_graph(MemorySaver())


def test_graph_two_interrupt_negotiation():
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-1"}}
    tasks = [
        _task(1, "copper fungicide spray", 4.0, 30, ["Copper Fungicide"], days_old=15),
        _task(2, "prune sprouts", 8.0, 45, ["Pruning Shears"]),
        _task(3, "mulch ring", 3.0, 20),
    ]

    r = g.invoke({"pending_tasks": tasks, "available_minutes": None}, cfg)
    assert r["__interrupt__"][0].value == {"ask": "available_minutes"}

    r = g.invoke(Command(resume=90), cfg)
    itr = r["__interrupt__"][0].value
    assert itr["ask"] == "have_resources"
    assert itr["resources"] == ["Copper Fungicide", "Pruning Shears"]

    r = g.invoke(Command(resume=["Pruning Shears"]), cfg)   # no fungicide
    assert r.get("__interrupt__") is None
    assert 1 in {t["id"] for t in r["dropped_tasks"]}
    assert {t["id"] for t in r["proposed_tasks"]} == {2, 3}
    assert any("overdue" in w for w in r["warnings"])
    assert r["summary"]                                     # template fallback


def test_graph_skips_resource_interrupt_when_nothing_needed():
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-2"}}
    tasks = [_task(1, "mulch", 3.0, 20), _task(2, "inspect", 2.0, 15)]
    r = g.invoke({"pending_tasks": tasks, "available_minutes": 120}, cfg)
    assert r.get("__interrupt__") is None                   # no time interrupt, no resource interrupt
    assert {t["id"] for t in r["proposed_tasks"]} == {1, 2}


def test_refit_does_not_backfill_sibling_fertilize():
    nitrogen = {
        **_task(1, "Nitrogen feed", 8.0, 25, ["Balanced fertilizer (8-3-9)"]),
        "template_category": "fertilize",
        "_effective_score": 8.0,
    }
    potassium = {
        **_task(2, "Potassium feed", 6.0, 25, ["Balanced fertilizer (8-3-9)"]),
        "template_category": "fertilize",
        "_effective_score": 6.0,
    }
    mulch = {**_task(3, "mulch ring", 3.0, 20), "template_category": "mulch", "_effective_score": 3.0}
    final, dropped = refit([nitrogen, potassium, mulch], [nitrogen], [], minutes=90)
    assert dropped == []
    assert {t["id"] for t in final} == {1, 3}


def test_graph_one_fertilize_per_tree_per_session():
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-fert"}}
    tasks = [
        {
            **_task(1, "Nitrogen feed", 8.0, 25, ["Balanced fertilizer (8-3-9)"]),
            "template_category": "fertilize",
        },
        {
            **_task(2, "Potassium feed", 6.0, 25, ["Balanced fertilizer (8-3-9)"]),
            "template_category": "fertilize",
        },
        {**_task(3, "mulch ring", 3.0, 20), "template_category": "mulch"},
    ]
    r = g.invoke({"pending_tasks": tasks, "available_minutes": 120}, cfg)
    assert r["__interrupt__"][0].value["ask"] == "have_resources"
    r = g.invoke(Command(resume=["Balanced fertilizer (8-3-9)"]), cfg)
    assert r.get("__interrupt__") is None
    ids = {t["id"] for t in r["proposed_tasks"]}
    assert ids == {1, 3}
    dropped = next(t for t in r["dropped_tasks"] if t["id"] == 2)
    assert "one fertilize" in dropped["_drop_reason"]
    assert "Nitrogen" in r["summary"] or "fertilize" in r["summary"].lower() or "Left out" in r["summary"]


def test_graph_fertilize_on_two_trees_both_kept():
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-fert-2"}}
    tasks = [
        {
            **_task(1, "Nitrogen feed", 8.0, 20, ["Balanced fertilizer (8-3-9)"]),
            "template_category": "fertilize",
        },
        {
            **_task(2, "Nitrogen feed", 7.0, 20, ["Balanced fertilizer (8-3-9)"]),
            "tree_id": 2,
            "template_category": "fertilize",
        },
    ]
    r = g.invoke({"pending_tasks": tasks, "available_minutes": 120}, cfg)
    r = g.invoke(Command(resume=["Balanced fertilizer (8-3-9)"]), cfg)
    assert {t["id"] for t in r["proposed_tasks"]} == {1, 2}


def test_agronomist_review_drops_remaining_adversary(monkeypatch):
    from app.agent import foreman as fm

    def fake_review(tasks, settings):
        victim = next(t for t in tasks if t["id"] == 2)
        return [{**victim, "_drop_reason": "agronomist: two scouts same tree"}]

    monkeypatch.setattr(fm, "review_session_adversaries", fake_review)
    g = _graph()
    cfg = {"configurable": {"thread_id": "t-review"}}
    tasks = [
        {**_task(1, "scout pests", 5.0, 15), "template_category": "scout"},
        {**_task(2, "scout disease", 4.0, 15), "template_category": "scout"},
    ]
    r = g.invoke({"pending_tasks": tasks, "available_minutes": 120}, cfg)
    assert r.get("__interrupt__") is None
    assert {t["id"] for t in r["proposed_tasks"]} == {1}
    dropped = next(t for t in r["dropped_tasks"] if t["id"] == 2)
    assert "agronomist" in dropped["_drop_reason"]
