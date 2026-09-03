"""Optional LangSmith spans for the steps LangChain / LangGraph don't
auto-instrument - mainly the Chroma retrieval that otherwise leaves a gap
between the ``classify`` LLM call and the answer LLM call in a trace.

``@traced(name)`` wraps :func:`langsmith.traceable`: it drops ``self`` / ``cls``
from the logged inputs, and degrades to a plain no-op decorator if ``langsmith``
can't be imported. Spans are only actually sent when ``LANGCHAIN_TRACING_V2=true``
and ``LANGCHAIN_API_KEY`` is set - the test suite forces it off in conftest, so
this adds zero overhead there.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

try:  # langsmith ships as a langchain-core dependency; guard anyway
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover
    _traceable = None


# Never log these arg names - they are wiring (services, the DB connection) or
# carry secrets (Settings has the DB password / Rachio key). Only "data" args
# (query, question, messages, tree, …) reach LangSmith.
_SKIP_INPUTS = {
    "self", "cls", "settings", "sources", "tasks", "trees", "templates",
    "store", "conn", "repo", "svc", "service",
}


def _scrub_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in inputs.items() if k not in _SKIP_INPUTS}


def traced(name: str, *, run_type: str = "chain") -> Callable[[_F], _F]:
    """Decorator: emit a LangSmith span named ``name`` around the call.

    ``run_type`` is one of langsmith's kinds - use ``"retriever"`` for the KB
    search so its output renders as retrieved documents.
    """
    if _traceable is None:

        def _noop(fn: _F) -> _F:
            return fn

        return _noop

    return _traceable(name=name, run_type=run_type, process_inputs=_scrub_inputs)
