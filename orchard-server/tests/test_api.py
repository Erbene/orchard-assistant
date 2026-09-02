"""End-to-end tests through the HTTP layer, exercising router -> service ->
repository against the disposable ``orchard_test`` Postgres database
(selected via a dependency override; tables are truncated between tests by
the autouse fixture in conftest.py). Rachio is always mocked with respx."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core import db
from app.dependencies import get_settings_dep
from app.main import app
from app.repositories.task_repository import TaskRepository
from app.repositories.tree_repository import TreeRepository
from app.services.rachio import get_rachio_service

from conftest import stack_settings

API = "/api/v1"
RACHIO = "https://api.rach.io/1/public"

_PERSON = {"id": "p1"}
_ACCOUNT = {
    "id": "p1",
    "devices": [
        {
            "id": "dev-1", "name": "Backyard", "status": "ONLINE", "model": "GEN3",
            "zones": [
                {"id": "rz-1", "name": "Row A", "enabled": True, "zoneNumber": 1,
                 "customSoil": {"name": "Sand"}},
                {"id": "rz-2", "name": "Row B", "enabled": True, "zoneNumber": 2},
            ],
        }
    ],
}


def _mock_rachio() -> None:
    respx.get(f"{RACHIO}/person/info").mock(return_value=httpx.Response(200, json=_PERSON))
    respx.get(f"{RACHIO}/person/p1").mock(return_value=httpx.Response(200, json=_ACCOUNT))
    respx.put(f"{RACHIO}/zone/start").mock(return_value=httpx.Response(204))


@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    get_rachio_service.cache_clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_rachio_service.cache_clear()


@pytest.fixture()
def rachio_client(tmp_path: Path):
    """A client whose Settings carry a (fake) RACHIO_API_KEY."""
    settings = stack_settings(uploads_dir=str(tmp_path), rachio_api_key="test-key")
    app.dependency_overrides[get_settings_dep] = lambda: settings
    get_rachio_service.cache_clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_rachio_service.cache_clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_streams_a_routed_reply(client):
    # LLM mocked: classify -> "smalltalk", ChatService streams the canned reply.
    from tests.test_agent import fake_llm

    with fake_llm("smalltalk", reply="I help with orchard tasks and your notes."):
        r = client.post(
            f"{API}/chat", json={"messages": [{"role": "user", "content": "hi there"}]}
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert '"type":"start"' in body and '"type":"text-delta"' in body
    assert '"finishReason":"ok"' in body
    # text streams one word per delta frame - reconstruct it
    import json as _json

    deltas = [
        _json.loads(line[5:])["delta"]
        for line in body.splitlines()
        if line.startswith("data:") and '"text-delta"' in line
    ]
    assert "orchard tasks" in "".join(deltas)


def test_zones_require_rachio_key(client):
    # no RACHIO_API_KEY -> graceful 503, app otherwise fine
    assert client.get(f"{API}/zones").status_code == 503
    assert client.post(f"{API}/zones/rz-1/water", json={"duration_minutes": 5}).status_code == 503


@respx.mock
def test_zones_are_read_only_from_rachio(rachio_client):
    _mock_rachio()

    devices = rachio_client.get(f"{API}/zones").json()
    assert [d["id"] for d in devices] == ["dev-1"]
    assert [z["id"] for z in devices[0]["zones"]] == ["rz-1", "rz-2"]
    assert devices[0]["zones"][0]["custom_soil"] == {"name": "Sand"}

    detail = rachio_client.get(f"{API}/zones/rz-1")
    assert detail.status_code == 200
    assert detail.json()["device_name"] == "Backyard"
    assert detail.json()["zone"]["name"] == "Row A"
    assert rachio_client.get(f"{API}/zones/nope").status_code == 404

    started = rachio_client.post(f"{API}/zones/rz-1/water", json={"duration_minutes": 3})
    assert started.status_code == 202
    assert respx.calls.last.request.url.path == "/1/public/zone/start"

    # there are NO zone-config mutation routes
    assert rachio_client.post(f"{API}/zones", json={"name": "x"}).status_code == 405
    assert rachio_client.patch(f"{API}/zones/rz-1", json={"name": "x"}).status_code == 405
    assert rachio_client.delete(f"{API}/zones/rz-1").status_code == 405


def test_tree_crud_age_and_freetext_zone(client):
    # zone_id is a free-text Rachio zone id - any string, never validated
    r = client.post(
        f"{API}/trees",
        json={"species": "custard apple", "variety": "gefner",
              "zone_id": "rz-999-unknown", "planted_date": "2020-01-01"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["tree_id"]
    assert body["species"] == "custard apple"
    assert body["zone_id"] == "rz-999-unknown"       # stored verbatim, no 422
    assert body["age_days"] > 2000 and body["age_years"] >= 5

    r = client.patch(f"{API}/trees/{tid}", json={"variety": "nam doc mai", "zone_id": "rz-1"})
    assert r.json()["variety"] == "nam doc mai"
    assert r.json()["zone_id"] == "rz-1"

    assert len(client.get(f"{API}/trees", params={"zone_id": "rz-1"}).json()) == 1
    assert client.get(f"{API}/trees", params={"zone_id": "rz-1"}).json()[0]["tree_id"] == tid
    assert client.get(f"{API}/trees", params={"species": "sapodilla"}).json() == []

    assert client.delete(f"{API}/trees/{tid}").status_code == 204
    assert client.get(f"{API}/trees/{tid}").status_code == 404


# --------------------------------------------------------------------------
# Phase 4 - Foreman JIT scheduling loop
# --------------------------------------------------------------------------

async def _seed_schedule_tasks(settings) -> None:
    """One tree + a backlog with an overdue fungicide task and tool-free work."""
    late = datetime.now(timezone.utc) - timedelta(days=12)
    async with db.connection(settings) as conn:
        tree_id = (await TreeRepository(conn).create(
            {"species": "mango", "variety": "Kent"}
        ))["tree_id"]
        repo = TaskRepository(conn)
        await repo.create({
            "tree_id": tree_id, "action_type": "copper fungicide spray", "status": "pending",
            "priority_score": 4.0, "scheduled_date": late, "estimated_minutes": 30,
            "required_resources": ["Copper Fungicide", "Sprayer"],
        })
        await repo.create({
            "tree_id": tree_id, "action_type": "prune sprouts", "status": "pending",
            "priority_score": 8.0, "estimated_minutes": 45, "required_resources": ["Pruning Shears"],
        })
        for name, score, mins in [("mulch ring", 3.0, 20), ("inspect for pests", 2.0, 15)]:
            await repo.create({
                "tree_id": tree_id, "action_type": name, "status": "pending",
                "priority_score": score, "estimated_minutes": mins, "required_resources": [],
            })
    # this ran in its own asyncio.run loop; drop the engine so TestClient rebuilds
    await db.dispose_all()


def test_schedule_jit_negotiation_and_completion(client):
    settings = stack_settings()
    asyncio.run(_seed_schedule_tasks(settings))

    # step 1: no time budget -> interrupt asks for it
    s = client.post(f"{API}/schedule/plan", json={}).json()
    assert s["step"] == "need_time"
    thread = s["thread_id"]

    # step 2: resume with minutes -> interrupt asks which tools you have
    s = client.post(f"{API}/schedule/resume",
                    json={"thread_id": thread, "available_minutes": 90}).json()
    assert s["step"] == "need_resources"
    assert "Copper Fungicide" in s["required_resources"]

    # step 3: you have shears but not the fungicide -> that task drops, backfill
    s = client.post(f"{API}/schedule/resume",
                    json={"thread_id": thread, "have_resources": ["Pruning Shears"]}).json()
    assert s["step"] == "done"
    dropped = {t["id"]: t for t in s["dropped_tasks"]}
    assert dropped and all(t["drop_reason"] for t in dropped.values())
    assert any(t["escalated"] for t in dropped.values())          # the overdue fungicide
    assert any("overdue" in w for w in s["warnings"])
    assert s["summary"]
    picked = [t["id"] for t in s["proposed_tasks"]]
    assert picked and not (set(picked) & set(dropped))

    # UI "Mark Complete"
    first = picked[0]
    done = client.post(f"{API}/schedule/complete", json={"task_ids": [first]}).json()
    assert done[0]["id"] == first and done[0]["status"] == "completed"

    # natural-language completion ("finished task N")
    second = picked[1]
    r = client.post(f"{API}/schedule/report",
                    json={"thread_id": thread, "text": f"also finished task {second}"}).json()
    assert second in r["marked"]


def test_schedule_resume_needs_a_value(client):
    s = client.post(f"{API}/schedule/plan", json={}).json()
    r = client.post(f"{API}/schedule/resume", json={"thread_id": s["thread_id"]})
    assert r.status_code == 422
