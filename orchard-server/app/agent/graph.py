"""The Orchestrator graph: classify a chat turn, then dispatch.

    START -> classify -> (route) -> { agronomist | schedule_handoff
                                    | complete | reply_only } -> END

`classify` is the one LLM call every turn makes; only `agronomist` makes a
second (retrieval + answer). The graph is async and stateless - `ChatService`
builds it per request with the request's services.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..services.source_service import SourceService
from ..services.task_service import TaskService
from .agronomist import run_agronomist
from .orchestrator import Route, classify, last_user_text
from .state import OrchestratorState

_SCHEDULE_REDIRECT = {"href": "/schedule", "label": "Open the scheduler"}


def build_graph(
    sources: SourceService, tasks: TaskService, settings: Settings
) -> Any:
    async def _classify(state: OrchestratorState) -> dict:
        c = await classify(state["messages"], settings=settings)
        return {"route": c["route"], "task_ids": c["task_ids"], "reply": c["reply"]}

    async def _agronomist(state: OrchestratorState) -> dict:
        result = await run_agronomist(
            last_user_text(state["messages"]),
            tree_id=state.get("active_tree_id"),
            sources=sources,
            settings=settings,
        )
        return {"answer": result["answer"], "tool_calls": []}

    async def _schedule_handoff(state: OrchestratorState) -> dict:
        return {
            "answer": state.get("reply") or "Let's plan a work session.",
            "redirect": _SCHEDULE_REDIRECT,
            "tool_calls": [],
        }

    async def _complete(state: OrchestratorState) -> dict:
        ids = state.get("task_ids") or []
        if not ids:
            # No number given - always ask, regardless of what the router put
            # in `reply` (it sometimes just acknowledges).
            return {
                "answer": "Which task number did you finish? Tell me the number "
                "and I'll mark it done.",
                "tool_calls": [],
            }
        done = await tasks.mark_many_complete(ids)
        done_ids = [t.id for t in done]
        missed = sorted(set(ids) - set(done_ids))
        ack = state.get("reply") or "Done."
        if done_ids and missed:
            answer = (
                f"{ack} Marked task(s) {done_ids} complete. "
                f"Couldn't find task(s) {missed} - double-check the number(s)?"
            )
        elif done_ids:
            answer = f"{ack} Marked task(s) {done_ids} complete."
        else:
            answer = f"Couldn't find task(s) {missed} - double-check the number(s)?"
        return {
            "answer": answer,
            "tool_calls": [
                {"tool": "mark_tasks_complete", "args": {"task_ids": ids}, "result": done_ids}
            ],
        }

    async def _reply_only(state: OrchestratorState) -> dict:
        return {"answer": state.get("reply") or "", "tool_calls": []}

    def _route(state: OrchestratorState) -> Route:
        return state["route"]

    g = StateGraph(OrchestratorState)
    g.add_node("classify", _classify)
    g.add_node("agronomist", _agronomist)
    g.add_node("schedule_handoff", _schedule_handoff)
    g.add_node("complete", _complete)
    g.add_node("reply_only", _reply_only)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        _route,
        {
            "agronomy": "agronomist",
            "schedule": "schedule_handoff",
            "complete": "complete",
            "refuse": "reply_only",
            "smalltalk": "reply_only",
        },
    )
    for node in ("agronomist", "schedule_handoff", "complete", "reply_only"):
        g.add_edge(node, END)
    return g.compile()
