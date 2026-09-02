"""Offline evaluation harness for the orchard assistant.

Not part of the pytest suite - it needs a reachable Ollama and takes a few
minutes. Run it by hand::

    cd orchard-server
    ./.venv/Scripts/python -m eval            # whole dataset
    ./.venv/Scripts/python -m eval --only chat
    ./.venv/Scripts/python -m eval --id chat-refusal-01

It exercises the real Orchestrator graph (routing + retrieval + Agronomist)
and the real Foreman scheduling negotiation against a disposable
``orchard_eval`` database / ``orchard_knowledge_eval`` Chroma collection - never
the real ``orchard`` data. Results are written to ``eval/results/``.
"""
