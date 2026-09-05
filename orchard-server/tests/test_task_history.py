"""Executed-task log: write on complete/skip and GET /tasks/history."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.main import app

from conftest import stack_settings
from test_care_plan import _link_note_http, fake_plan_llm


@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _care_plan_inbox(client: TestClient) -> tuple[int, list[dict]]:
    tree = client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "height_m": 3.5},
    ).json()
    tid = tree["tree_id"]
    _link_note_http(client, tid)
    with fake_plan_llm():
        client.post(f"/api/v1/trees/{tid}/care-plan/generate")
    client.post(f"/api/v1/trees/{tid}/care-plan/baseline", json={"answers": []})
    inbox = client.get("/api/v1/tasks").json()
    return tid, inbox


def test_complete_writes_history_and_removes_from_inbox(client):
    tid, inbox = _care_plan_inbox(client)
    first = inbox[0]
    task_id = first["id"]
    action = first["action_type"]

    done = client.post(f"/api/v1/tasks/{task_id}/complete")
    assert done.status_code == 200

    history = client.get("/api/v1/tasks/history").json()
    assert len(history) == 1
    row = history[0]
    assert row["outcome"] == "completed"
    assert row["action_type"] == action
    assert row["tree_id"] == tid
    assert row["executed_at"] is not None
    assert row["tree_species"] == "mango"
    assert row["tree_variety"] == "Kent"

    inbox_ids = {t["id"] for t in client.get("/api/v1/tasks").json()}
    assert task_id not in inbox_ids


def test_skip_excluded_from_default_history(client):
    tid, inbox = _care_plan_inbox(client)
    task_id = inbox[0]["id"]

    skipped = client.post(f"/api/v1/tasks/{task_id}/skip")
    assert skipped.status_code == 200

    assert client.get("/api/v1/tasks/history").json() == []

    skipped_rows = client.get("/api/v1/tasks/history?outcome=skipped").json()
    assert len(skipped_rows) == 1
    assert skipped_rows[0]["outcome"] == "skipped"
    assert skipped_rows[0]["tree_id"] == tid


def test_history_survives_care_plan_regeneration(client):
    tid, inbox = _care_plan_inbox(client)
    first = inbox[0]
    client.post(f"/api/v1/tasks/{first['id']}/complete").raise_for_status()

    with fake_plan_llm():
        client.post(f"/api/v1/trees/{tid}/care-plan/generate").raise_for_status()

    history = client.get("/api/v1/tasks/history").json()
    assert len(history) == 1
    assert history[0]["action_type"] == first["action_type"]
    assert history[0]["outcome"] == "completed"


def test_history_empty_for_unknown_tree_filter(client):
    _tid, inbox = _care_plan_inbox(client)
    client.post(f"/api/v1/tasks/{inbox[0]['id']}/complete").raise_for_status()

    assert client.get("/api/v1/tasks/history?tree_id=99999").json() == []


def test_inbox_last_completed_from_baseline_then_history(client):
    tree = client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "height_m": 3.5},
    ).json()
    tid = tree["tree_id"]
    _link_note_http(client, tid)
    with fake_plan_llm():
        plan = client.post(f"/api/v1/trees/{tid}/care-plan/generate").json()
    feed = next(t for t in plan["templates"] if t["category"] == "fertilize")
    last = "2026-03-15"
    client.post(
        f"/api/v1/trees/{tid}/care-plan/baseline",
        json={"answers": [{"template_id": feed["id"], "last_done": last}]},
    ).raise_for_status()

    inbox = client.get("/api/v1/tasks").json()
    feed_task = next(t for t in inbox if t["template_id"] == feed["id"])
    assert feed_task["last_completed"] == last
    assert feed_task["tree_species"] == "mango"
    assert feed_task["tree_variety"] == "Kent"

    other = next(t for t in inbox if t["template_id"] != feed["id"])
    assert other["last_completed"] is None

    client.post(f"/api/v1/tasks/{feed_task['id']}/complete").raise_for_status()
    nxt = next(
        t
        for t in client.get("/api/v1/tasks").json()
        if t["template_id"] == feed["id"]
    )
    assert nxt["last_completed"] >= last
    assert nxt["id"] != feed_task["id"]


def test_complete_is_idempotent_no_duplicate_log(client):
    _, inbox = _care_plan_inbox(client)
    task_id = inbox[0]["id"]

    client.post(f"/api/v1/tasks/{task_id}/complete").raise_for_status()
    client.post(f"/api/v1/tasks/{task_id}/complete").raise_for_status()

    assert len(client.get("/api/v1/tasks/history").json()) == 1
