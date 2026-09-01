"""LangGraph skeleton: routing + the JIT multi-turn interrupt."""
from __future__ import annotations

import asyncio

from langchain_core.messages import HumanMessage

from app.agent.graph import graph
from app.agent.state import AgentState


def _state(text: str, **over) -> AgentState:
    base: AgentState = {
        "messages": [HumanMessage(text)],
        "active_tree_id": None,
        "available_minutes": None,
        "confirmed_resources": [],
    }
    base.update(over)  # type: ignore[typeddict-item]
    return base


def test_foreman_asks_for_time_budget_when_missing():
    out = asyncio.run(graph.ainvoke(_state("schedule my orchard work")))
    assert "minutes" in out["messages"][-1].content.lower()


def test_foreman_proceeds_once_minutes_known():
    out = asyncio.run(graph.ainvoke(_state("plan my day", available_minutes=90)))
    assert "90 min" in out["messages"][-1].content


def test_knowledge_question_routes_through_agronomist():
    out = asyncio.run(
        graph.ainvoke(_state("why are the mango leaves yellowing?", available_minutes=30))
    )
    names = [m.name for m in out["messages"] if getattr(m, "name", None)]
    assert names == ["orchestrator", "agronomist", "foreman"]
