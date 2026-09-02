"""Agent graphs for the orchard.

* ``graph.py`` - the orchestrator skeleton (routes agronomy vs. scheduling
  questions); nodes are still stubs.
* ``foreman.py`` + ``escalation.py`` - **Phase 4**, the real interactive JIT
  scheduler: a checkpointed two-interrupt LangGraph negotiation driven over
  REST at ``/api/v1/schedule/*`` (see ``app/services/foreman_service.py``).
"""
from .graph import build_graph
from .state import AgentState

__all__ = ["build_graph", "AgentState"]
