"""LangGraph skeleton: Orchestrator -> {Agronomist, Foreman} with a JIT
multi-turn interrupt in the Foreman node.

Nodes are STUBS. Where a real implementation would call an LLM (bound to the
MCP tools from ``client.load_orchard_tools``) there is a comment plus a
deterministic placeholder, so the graph compiles and runs today.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from .agronomist import AGRONOMIST_SYSTEM_PROMPT, format_priority_context
from .state import AgentState

_KNOWLEDGE_HINTS = ("why", "how", "what", "when", "disease", "pest", "deficien")


def _last_human_text(state: AgentState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return str(message.content).lower()
    return ""


# --------------------------------------------------------------------------
# Nodes (stubs)
# --------------------------------------------------------------------------

def orchestrator(state: AgentState) -> dict:
    """Classify the user's latest turn.

    Real version: an LLM call that reads ``state['messages']``, decides
    agronomy-question vs. scheduling-ask, and extracts ``active_tree_id``.
    Routing itself is done by ``route_from_orchestrator`` off the same signal.
    """
    return {"messages": [AIMessage("[orchestrator] routing…", name="orchestrator")]}


async def agronomist_agent(state: AgentState) -> dict:
    """Answer horticultural questions grounded in the knowledge base, respecting
    the grower's source authority order.

    Real version::

        groups  = await svc.sources.search(query, source_ids=svc.sources
                      .allowed_source_ids(state["active_tree_id"]))   # rank order
        context = format_priority_context(groups)                     # [PRIORITY n ...]
        answer  = await llm.ainvoke([
            SystemMessage(AGRONOMIST_SYSTEM_PROMPT),
            *state["messages"],
            SystemMessage(f"Retrieved sources:\\n\\n{context}"),
        ])   # conflicts resolved Priority 1 > Priority 2 per the system prompt
    """
    _ = (AGRONOMIST_SYSTEM_PROMPT, format_priority_context)  # wired; used by the real impl
    return {
        "messages": [
            AIMessage(
                "[agronomist] (stub) would call search_knowledge, render the "
                "results as [PRIORITY n SOURCE ...] blocks, and resolve any "
                "conflicts in favour of the higher-ranked source.",
                name="agronomist",
            )
        ]
    }


async def foreman_agent(state: AgentState) -> dict:
    """Fit the pending task queue into the time the user has *right now*.

    JIT multi-turn check
    --------------------
    ::

        if state["available_minutes"] is None:
            # Cannot schedule without a time budget. Ask, and end this turn so
            # the user can answer; the caller re-invokes with the answer
            # merged into state (available_minutes now set).
            return {"messages": [AIMessage(
                "How many minutes do you have to work right now?")]}

        tools = await load_orchard_tools()
        queue = await call_tool(tools, "get_pending_tasks")           # backlog
        plan  = llm.plan(queue,
                         minutes=state["available_minutes"],
                         resources=state["confirmed_resources"])      # fit
        await call_tool(tools, "batch_update_task_priorities", plan)  # commit
        # for an irrigation item due now, execute it directly on the hardware:
        await call_tool(tools, "trigger_rachio_watering",
                        {"zone_id": zone_id, "duration_minutes": minutes})
    """
    if state.get("available_minutes") is None:
        return {
            "messages": [
                AIMessage(
                    "How many minutes do you have to work in the orchard right now?",
                    name="foreman",
                )
            ]
        }

    minutes = state["available_minutes"]
    resources = state.get("confirmed_resources", [])
    return {
        "messages": [
            AIMessage(
                f"[foreman] (stub) would pull get_pending_tasks, fit ~{minutes} "
                f"min of work given resources {resources}, then commit the plan "
                f"via batch_update_task_priorities.",
                name="foreman",
            )
        ]
    }


# --------------------------------------------------------------------------
# Conditional routing
# --------------------------------------------------------------------------

def route_from_orchestrator(state: AgentState) -> Literal["agronomist", "foreman"]:
    text = _last_human_text(state)
    return "agronomist" if any(h in text for h in _KNOWLEDGE_HINTS) else "foreman"


def route_from_foreman(state: AgentState) -> Literal["ask_user", "done"]:
    # The JIT pause: no time budget yet -> the foreman asked a question, stop.
    return "ask_user" if state.get("available_minutes") is None else "done"


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("agronomist", agronomist_agent)
    graph.add_node("foreman", foreman_agent)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {"agronomist": "agronomist", "foreman": "foreman"},
    )
    graph.add_edge("agronomist", "foreman")
    graph.add_conditional_edges(
        "foreman",
        route_from_foreman,
        # both terminate the run; "ask_user" is the JIT pause - the caller
        # re-invokes with the user's answer merged into state.
        {"ask_user": END, "done": END},
    )
    return graph.compile()


graph = build_graph()
