"""Phase 4 - Foreman engine + graph. Pure/deterministic; no DB, no Ollama
(OLLAMA_BASE_URL is unreachable in conftest -> template summary)."""
from __future__ import annotations

from datetime import date, timedelta

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.escalation import escalate, task_age_days
from app.agent.foreman import build_foreman_graph, pack, refit, resources_for


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
