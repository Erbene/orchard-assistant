"""Agent graphs for the orchard.

* ``graph.py`` + ``orchestrator.py`` + ``agronomist.py`` - the **Orchestrator**:
  an LLM classifier that routes each chat turn to a KB-grounded agronomy
  answer, a task completion, a refusal, or a hand-off to the scheduler.
  Driven over SSE at ``/api/v1/chat`` (see ``app/services/chat_service.py``).
* ``foreman.py`` + ``escalation.py`` - **Phase 4**, the interactive JIT
  scheduler: a checkpointed two-interrupt LangGraph negotiation driven over
  REST at ``/api/v1/schedule/*`` (see ``app/services/foreman_service.py``).
"""
from .graph import build_graph
from .state import OrchestratorState

__all__ = ["build_graph", "OrchestratorState"]
