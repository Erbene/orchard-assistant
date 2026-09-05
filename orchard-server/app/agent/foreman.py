"""Phase 4 - the Foreman agent: an interactive Just-In-Time scheduling loop.

A two-interrupt LangGraph negotiation:

    time_check --(interrupt: available_minutes)--> propose
    propose    --> resource_check --(interrupt: have_resources)--> finalize
    finalize   --> narrate --> END

The deterministic engine (``escalate`` / ``pack`` / ``resources_for`` /
``refit``) does the scheduling; a local Ollama model only writes the
human-readable session summary (with a template fallback so the flow always
completes offline). **No node mutates the database** - the schedule is a
proposal; tasks are only completed on an explicit user action (see
``mark_tasks_complete`` / ``/api/v1/schedule/complete``).

The graph is **synchronous** (psycopg's async mode can't run on the Windows
Proactor loop uvicorn uses). ``ForemanService`` invokes it via
``asyncio.to_thread`` from the async routes.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..config import Settings, get_settings
from ..core.logging import get_logger
from .escalation import Escalation, escalate
from .ollama import chat_model
from .schedule_rules import Completion, apply_blocks

_log = get_logger("app.foreman")

Task = dict[str, Any]

_DEFAULT_MINUTES = 30  # a task with no estimate still needs to be schedulable

FOREMAN_SYSTEM_PROMPT = (
    "You are the Orchard Foreman. You are given a JSON work plan the scheduler "
    "already computed for today's session: the time budget, the tasks that fit, "
    "the tasks that were dropped and why, and any overdue-risk escalations. "
    "Write a short, practical briefing (3-6 sentences) the grower can act on: "
    "what to do first, roughly how long it runs, what got left out. "
    "For EVERY escalation in the input, call it out explicitly by task id and "
    "by how many days overdue it is - these are time-critical. Plain ASCII "
    "text, no markdown headers, no emoji."
)


# --------------------------------------------------------------------------
# Deterministic engine (pure functions - unit-tested directly)
# --------------------------------------------------------------------------

def _minutes(task: Task) -> int:
    est = task.get("estimated_minutes")
    return int(est) if est else _DEFAULT_MINUTES


def _by_score(tasks: list[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: t.get("_effective_score", 0.0), reverse=True)


def pack(tasks: list[Task], minutes: int) -> list[Task]:
    """Greedy knapsack: take tasks by value density until the budget is spent."""
    ordered = sorted(
        tasks, key=lambda t: t.get("_effective_score", 0.0) / _minutes(t), reverse=True
    )
    picked: list[Task] = []
    used = 0
    for task in ordered:
        cost = _minutes(task)
        if used + cost <= minutes:
            picked.append(task)
            used += cost
    return _by_score(picked)


def resources_for(tasks: list[Task]) -> list[str]:
    """Sorted, de-duplicated union of every task's ``required_resources``."""
    seen: dict[str, str] = {}
    for task in tasks:
        for res in task.get("required_resources") or []:
            seen.setdefault(res.strip().lower(), res.strip())
    return [seen[k] for k in sorted(seen)]


def _needs_any(task: Task, resources_lower: set[str]) -> list[str]:
    return [r for r in (task.get("required_resources") or []) if r.strip().lower() in resources_lower]


def refit(
    all_tasks: list[Task],
    proposed: list[Task],
    missing_resources: list[str],
    minutes: int,
    *,
    blocked_ids: set[int] | None = None,
) -> tuple[list[Task], list[Task]]:
    """Drop proposed tasks that need a tool the user lacks, then backfill the
    freed minutes from the rest of the backlog (also tool-free). Returns
    ``(final, dropped)``; dropped tasks carry a ``_drop_reason``."""
    blocked_ids = blocked_ids or set()
    missing_lower = {m.strip().lower() for m in missing_resources}
    kept: list[Task] = []
    dropped: list[Task] = []
    for task in proposed:
        blockers = _needs_any(task, missing_lower)
        if blockers:
            dropped.append({**task, "_drop_reason": f"needs {', '.join(blockers)}"})
        else:
            kept.append(task)

    used = sum(_minutes(t) for t in kept)
    handled = {t["id"] for t in proposed}
    candidates = sorted(
        (
            t
            for t in all_tasks
            if t["id"] not in handled
            and t["id"] not in blocked_ids
            and not _needs_any(t, missing_lower)
        ),
        key=lambda t: t.get("_effective_score", 0.0) / _minutes(t),
        reverse=True,
    )
    for task in candidates:
        cost = _minutes(task)
        if used + cost <= minutes:
            kept.append(task)
            used += cost
    return _by_score(kept), dropped


# --------------------------------------------------------------------------
# LLM narration (optional - falls back to a template)
# --------------------------------------------------------------------------

def _template_summary(state: "ForemanState") -> str:
    picked = state.get("proposed_tasks", [])
    dropped = state.get("dropped_tasks", [])
    total = sum(_minutes(t) for t in picked)
    lines = [
        f"Session plan: {len(picked)} task(s), about {total} min of the "
        f"{state.get('available_minutes')} min you have."
    ]
    if picked:
        lines.append("Start with: " + ", ".join(
            f"#{t['id']} {t['action_type']}" for t in picked[:3]
        ) + ".")
    if dropped:
        lines.append(
            f"Left out: " + ", ".join(
                f"#{t['id']} {t['action_type']} ({t.get('_drop_reason', 'no time')})"
                for t in dropped
            ) + "."
        )
    for esc in state.get("escalations", []):
        lines.append(f"WARNING: {esc['reason']}.")
    return " ".join(lines)


def _narrate(
    state: "ForemanState", settings: Settings | None = None
) -> tuple[str, list[str]]:
    warnings = [e["reason"] for e in state.get("escalations", [])]
    settings = settings or get_settings()
    context = json.dumps(
        {
            "available_minutes": state.get("available_minutes"),
            "scheduled": [
                {
                    "id": t["id"],
                    "action_type": t["action_type"],
                    "tree_id": t.get("tree_id"),
                    "minutes": _minutes(t),
                    "priority": round(t.get("_effective_score", t.get("priority_score", 0.0)), 1),
                }
                for t in state.get("proposed_tasks", [])
            ],
            "dropped": [
                {"id": t["id"], "action_type": t["action_type"], "reason": t.get("_drop_reason")}
                for t in state.get("dropped_tasks", [])
            ],
            "escalations": state.get("escalations", []),
        },
        default=str,
    )
    try:
        llm = chat_model(
            settings,
            model=settings.foreman_model,
            temperature=0.2,
            num_predict=400,
            # a 14B model on CPU is slow; cap it and fall back to the template
            timeout=45.0,
        )
        msg = llm.invoke([SystemMessage(FOREMAN_SYSTEM_PROMPT), HumanMessage(context)])
        summary = (msg.content or "").strip()
        if summary:
            _log.info("foreman.narrate.llm", model=settings.foreman_model)
            return summary, warnings
    except Exception as exc:  # noqa: BLE001 - offline / model missing -> template
        _log.info("foreman.narrate.fallback", error=str(exc)[:160])
    return _template_summary(state), warnings


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

class ForemanState(TypedDict, total=False):
    pending_tasks: list[Task]
    recent_completions: list[dict]
    available_minutes: int | None
    proposed_tasks: list[Task]
    required_resources: list[str]
    confirmed_resources: list[str]
    dropped_tasks: list[Task]
    blocked_tasks: list[Task]
    blocked_task_ids: set[int]
    escalations: list[Escalation]
    summary: str
    warnings: list[str]


def _completions_from_state(raw: list[dict]) -> list[Completion]:
    out: list[Completion] = []
    for row in raw:
        completed_raw = row.get("completed_on")
        if not completed_raw:
            continue
        completed_on = (
            date.fromisoformat(completed_raw)
            if isinstance(completed_raw, str)
            else completed_raw
        )
        category = row.get("category")
        if not category:
            continue
        out.append(
            Completion(
                tree_id=int(row["tree_id"]),
                category=str(category),
                completed_on=completed_on,
                blocks=list(row.get("blocks") or []),
            )
        )
    return out


def _time_check(state: ForemanState) -> dict:
    if state.get("available_minutes") is None:
        answer = interrupt({"ask": "available_minutes"})
        return {"available_minutes": int(answer)}
    return {}


def _propose(state: ForemanState) -> dict:
    escalated, escalations = escalate(state.get("pending_tasks", []))
    completions = _completions_from_state(state.get("recent_completions", []))
    eligible, blocked = apply_blocks(escalated, completions, today=date.today())
    proposed = pack(eligible, int(state["available_minutes"]))
    return {
        "pending_tasks": escalated,
        "proposed_tasks": proposed,
        "blocked_tasks": blocked,
        "blocked_task_ids": {t["id"] for t in blocked},
        "dropped_tasks": blocked,
        "required_resources": resources_for(proposed),
        "escalations": escalations,
    }


def _resource_check(state: ForemanState) -> dict:
    needed = state.get("required_resources") or []
    if not needed:
        return {"confirmed_resources": []}
    answer = interrupt({"ask": "have_resources", "resources": needed})
    return {"confirmed_resources": [str(r) for r in (answer or [])]}


def _finalize(state: ForemanState) -> dict:
    confirmed = {r.strip().lower() for r in state.get("confirmed_resources", [])}
    missing = [r for r in state.get("required_resources", []) if r.strip().lower() not in confirmed]
    final, dropped = refit(
        state.get("pending_tasks", []),
        state.get("proposed_tasks", []),
        missing,
        int(state["available_minutes"]),
        blocked_ids=state.get("blocked_task_ids") or set(),
    )
    blocked = state.get("blocked_tasks") or []
    return {"proposed_tasks": final, "dropped_tasks": blocked + dropped}


def _narrate_node(state: ForemanState, settings: Settings | None = None) -> dict:
    summary, warnings = _narrate(state, settings)
    return {"summary": summary, "warnings": warnings}


def build_foreman_graph(checkpointer: Any, settings: Settings | None = None):
    """Compile the Foreman graph with an injected checkpointer (Postgres in the
    app, ``MemorySaver`` in tests)."""
    g = StateGraph(ForemanState)
    g.add_node("time_check", _time_check)
    g.add_node("propose", _propose)
    g.add_node("resource_check", _resource_check)
    g.add_node("finalize", _finalize)
    g.add_node("narrate", lambda state: _narrate_node(state, settings))
    g.add_edge(START, "time_check")
    g.add_edge("time_check", "propose")
    g.add_edge("propose", "resource_check")
    g.add_edge("resource_check", "finalize")
    g.add_edge("finalize", "narrate")
    g.add_edge("narrate", END)
    return g.compile(checkpointer=checkpointer)
