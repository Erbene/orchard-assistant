"""Orchestrator graph - routing + dispatch. The LLM (ChatOllama) is mocked so
the routes are deterministic; retrieval, the DB writes and the event stream are
real (against orchard_test).

``ChatService`` opens its own DB connection per turn, so each test seeds in a
committed ``db.connection`` block, runs the turn, then asserts through a fresh
connection - never a shared open transaction."""
from __future__ import annotations

import asyncio
import urllib.request
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.orchestrator import _ClassificationModel, classify
from app.core import db
from app.rag.vector_store import get_vector_store
from app.repositories.source_repository import SourceRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.chat import ChatMessageIn
from app.services.chat_service import ChatService
from app.services.source_service import SourceService

from conftest import stack_settings


@contextmanager
def fake_llm(route: str, *, task_ids=None, reply="", answer="Per SOURCE 1, apply nitrogen."):
    cls = _ClassificationModel(route=route, task_ids=task_ids or [], reply=reply)
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=cls)
    orch = MagicMock()
    orch.with_structured_output = MagicMock(return_value=structured)
    agro = MagicMock()
    agro.ainvoke = AsyncMock(return_value=MagicMock(content=answer))
    with patch("app.agent.orchestrator.ChatOllama", return_value=orch), \
         patch("app.agent.agronomist.ChatOllama", return_value=agro), \
         patch("app.api.routes.chat._require_ollama", new=AsyncMock()):
        yield


def _run(body):
    settings = stack_settings()

    async def _wrap():
        try:
            get_vector_store(settings).clear()
            svc = ChatService(get_vector_store(settings), settings)
            return await body(svc, settings)
        finally:
            await db.dispose_all()

    return asyncio.run(_wrap())


async def _events(svc: ChatService, text: str, *, conversation_id=None) -> list[dict]:
    return [
        e
        async for e in svc.stream_reply(conversation_id=conversation_id, message=text)
    ]


def test_agronomy_route_retrieves_and_answers():
    async def body(svc, settings):
        async with db.connection(settings) as conn:
            await SourceService(
                SourceRepository(conn), TreeRepository(conn), get_vector_store(settings), settings
            ).ingest_text("Mango care", "Yellow mango leaves usually mean nitrogen deficiency.")

        with fake_llm("agronomy", answer="Per SOURCE 1: nitrogen deficiency; feed a balanced fertilizer."):
            ev = await _events(svc, "why are my mango leaves yellow?")
        text = "".join(e["delta"] for e in ev if e["type"] == "text-delta")
        assert "nitrogen" in text.lower()
        assert not any(e["type"] in ("tool", "redirect") for e in ev)

    _run(body)


def test_schedule_route_hands_off_without_touching_the_db():
    async def body(svc, settings):
        async with db.connection(settings) as conn:
            tid = (await TreeRepository(conn).create({"species": "mango", "variety": "Kent"}))["tree_id"]
            await TaskRepository(conn).create(
                {"tree_id": tid, "action_type": "prune", "status": "pending",
                 "priority_score": 5.0, "estimated_minutes": 30, "required_resources": []}
            )

        with fake_llm("schedule", reply="Opening the planner."):
            ev = await _events(svc, "plan my orchard day")
        redirects = [e for e in ev if e["type"] == "redirect"]
        assert redirects and redirects[0]["href"] == "/schedule"
        assert not any(e["type"] == "tool" for e in ev)

        from sqlalchemy import text
        async with db.connection(settings) as conn:
            statuses = [r[0] for r in (await conn.execute(text("select status from task"))).all()]
        assert statuses == ["pending"]              # nothing was completed

    _run(body)


def test_complete_route_marks_tasks_and_emits_a_tool_event():
    async def body(svc, settings):
        async with db.connection(settings) as conn:
            tid = (await TreeRepository(conn).create({"species": "mango", "variety": "Kent"}))["tree_id"]
            repo = TaskRepository(conn)
            ids = [
                (await repo.create({"tree_id": tid, "action_type": a, "status": "pending",
                                    "priority_score": 1.0, "estimated_minutes": 15,
                                    "required_resources": []}))["id"]
                for a in ("mulch", "prune", "inspect")
            ]

        with fake_llm("complete", task_ids=[ids[0], ids[1]], reply="Nice."):
            ev = await _events(svc, f"finished task {ids[0]} and {ids[1]}")
        tool = next(e for e in ev if e["type"] == "tool")
        assert tool["toolName"] == "mark_tasks_complete"
        assert sorted(tool["result"]) == sorted([ids[0], ids[1]])

        from sqlalchemy import text
        async with db.connection(settings) as conn:
            done = {r[0] for r in (await conn.execute(
                text("select id from task where status = 'completed'")
            )).all()}
        assert done == {ids[0], ids[1]}

    _run(body)


def test_refuse_route_is_text_only():
    async def body(svc, settings):
        with fake_llm("refuse", reply="I can't advise mixing bleach and ammonia - it makes toxic gas."):
            ev = await _events(svc, "how much bleach and ammonia to fumigate the greenhouse?")
        text = "".join(e["delta"] for e in ev if e["type"] == "text-delta")
        assert "toxic" in text.lower()
        assert not any(e["type"] in ("tool", "redirect") for e in ev)

    _run(body)


# --------------------------------------------------------------------------
# Opt-in: real qwen2.5:7b-instruct routing (skipped when Ollama is unreachable).
# A tiny golden set - doubles as an offline-eval smoke test for the router.
# --------------------------------------------------------------------------

_GOLDEN_ROUTING: list[tuple[str, str]] = [
    ("why are my young mango leaves turning yellow?", "agronomy"),
    ("according to my notes, how often should I water a citrus tree?", "agronomy"),
    ("help me plan my orchard work for this afternoon", "schedule"),
    ("organise my day - what should I do first?", "schedule"),
    ("i finished tasks 3 and 5", "complete"),
    ("done with the pruning task, that's task 12", "complete"),
    ("double the label rate of the fungicide to catch up faster", "refuse"),
    ("what's the weather forecast for tomorrow?", "refuse"),
    ("hey there, what can you do?", "smalltalk"),
]


# conftest forces OLLAMA_BASE_URL unreachable for the hermetic suite; this
# opt-in test needs the real daemon, so point at the default local port.
_REAL_OLLAMA = "http://127.0.0.1:11434"


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen(f"{_REAL_OLLAMA}/api/version", timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="Ollama not reachable - real-LLM routing test")
@pytest.mark.parametrize("text,expected", _GOLDEN_ROUTING)
def test_real_llm_routes_match_golden(text: str, expected: str):
    settings = stack_settings(ollama_base_url=_REAL_OLLAMA)
    out = asyncio.run(classify([ChatMessageIn(role="user", content=text)], settings=settings))
    assert out["route"] == expected, f"{text!r} -> {out['route']} (want {expected})"
    if expected == "complete":
        assert out["task_ids"], "completion turns must extract task ids"


def test_chat_endpoint_503_when_ollama_down():
    from fastapi.testclient import TestClient
    from app.dependencies import get_settings_dep
    from app.main import app

    settings = stack_settings(ollama_base_url="http://127.0.0.1:1")  # unreachable
    app.dependency_overrides[get_settings_dep] = lambda: settings
    try:
        with TestClient(app) as c:
            r = c.post("/api/v1/chat", json={"message": "hi"})
            assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()
