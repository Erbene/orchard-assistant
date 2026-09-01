"""End-to-end tests through the HTTP layer, exercising router -> service ->
repository against the disposable ``orchard_test`` Postgres database
(selected via a dependency override; tables are truncated between tests by
the autouse fixture in conftest.py). Rachio is always mocked with respx."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.main import app
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


def test_chat_streams_stub_reply(client):
    r = client.post(
        f"{API}/chat", json={"messages": [{"role": "user", "content": "hello there"}]}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert '"type":"start"' in body
    assert '"type":"text-delta"' in body
    assert '"finishReason":"stub"' in body
    assert "asked:" in body and "hello" in body


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
