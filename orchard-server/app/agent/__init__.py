"""LangGraph orchestration skeleton for the JIT conversational scheduler.

Not wired to a real LLM yet - the nodes are stubs that demonstrate control
flow, the JIT multi-turn check, and MCP tool binding.
"""
from .graph import build_graph
from .state import AgentState

__all__ = ["build_graph", "AgentState"]
