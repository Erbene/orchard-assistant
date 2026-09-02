"""Server-owned conversation history: POST /chat persists the turn, the
/conversations endpoints read / rename / delete it, and a follow-up turn
resumes the same thread."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.main import app

from conftest import stack_settings
from tests.test_agent import fake_llm

API = "/api/v1"


@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _events(body: str) -> list[dict]:
    return [
        json.loads(line[5:])
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def _say(client, message, conversation_id=None, *, route="smalltalk", **llm):
    with fake_llm(route, **llm):
        r = client.post(
            f"{API}/chat",
            json={"message": message, "conversation_id": conversation_id},
        )
    assert r.status_code == 200
    return _events(r.text)


def test_first_turn_creates_a_conversation_and_persists_both_messages(client):
    events = _say(client, "hi there", route="smalltalk", reply="Hello! How can I help?")
    convo = next(e for e in events if e["type"] == "conversation")
    assert convo["new"] is True
    assert convo["title"] == "hi there"
    cid = convo["id"]

    listing = client.get(f"{API}/conversations").json()
    assert [c["id"] for c in listing] == [cid]

    detail = client.get(f"{API}/conversations/{cid}").json()
    roles = [(m["role"], m["content"]) for m in detail["messages"]]
    assert roles == [("user", "hi there"), ("assistant", "Hello! How can I help?")]
    assert detail["messages"][1]["meta"]["route"] == "smalltalk"


def test_follow_up_turn_resumes_the_same_thread(client):
    first = _say(client, "hi", route="smalltalk", reply="Hi!")
    cid = next(e for e in first if e["type"] == "conversation")["id"]

    events = _say(
        client, "what can you do?", conversation_id=cid,
        route="smalltalk", reply="I answer orchard questions.",
    )
    convo = next(e for e in events if e["type"] == "conversation")
    assert convo["id"] == cid and convo["new"] is False

    detail = client.get(f"{API}/conversations/{cid}").json()
    assert [m["content"] for m in detail["messages"]] == [
        "hi", "Hi!", "what can you do?", "I answer orchard questions.",
    ]
    assert len(client.get(f"{API}/conversations").json()) == 1


def test_tool_turn_records_meta(client):
    # need real tasks so mark_tasks_complete resolves - but the route only
    # checks the persisted meta, so an empty result is fine here.
    events = _say(
        client, "done with 3 and 5", route="complete",
        task_ids=[3, 5], reply="Got it.",
    )
    cid = next(e for e in events if e["type"] == "conversation")["id"]
    msg = client.get(f"{API}/conversations/{cid}").json()["messages"][1]
    assert msg["meta"]["tool_calls"][0]["tool"] == "mark_tasks_complete"


def test_rename_and_delete(client):
    cid = next(
        e for e in _say(client, "hello", reply="hi") if e["type"] == "conversation"
    )["id"]

    renamed = client.patch(
        f"{API}/conversations/{cid}", json={"title": "Watering questions"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Watering questions"

    assert client.delete(f"{API}/conversations/{cid}").status_code == 204
    assert client.get(f"{API}/conversations/{cid}").status_code == 404
    assert client.get(f"{API}/conversations").json() == []


def test_unknown_conversation_id_streams_an_error(client):
    events = _say(client, "hi", conversation_id=99999, reply="hi")
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "text-delta" for e in events)
