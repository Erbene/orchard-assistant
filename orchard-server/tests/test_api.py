"""End-to-end tests through the HTTP layer, exercising router -> service ->
repository against a throwaway SQLite file selected via dependency override."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import _initialized, get_settings_dep
from app.main import app

API = "/api/v1"


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(db_path=str(tmp_path / "test.db"))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    _initialized.discard(settings.db_path)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    _initialized.discard(settings.db_path)


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
    # stub echoes the last user message (streamed across chunks)
    assert "asked:" in body and "hello" in body


def test_zone_crud_freetext_and_autoincrement(client):
    # zone_id is auto-assigned; arbitrary free text is accepted verbatim
    a = client.post(
        f"{API}/zones",
        json={"name": "North block", "soil_drainage": "fast", "water_source": "well + drip"},
    )
    assert a.status_code == 201, a.text
    a_body = a.json()
    assert isinstance(a_body["zone_id"], int)
    assert a_body["soil_drainage"] == "fast"       # not coerced to a vocab term
    assert a_body["water_source"] == "well + drip"

    b = client.post(f"{API}/zones", json={"name": "South block", "soil_drainage": "heavy clay"})
    assert b.json()["zone_id"] == a_body["zone_id"] + 1   # increments

    zid = a_body["zone_id"]
    patched = client.patch(
        f"{API}/zones/{zid}", json={"soil_drainage": "  well   drained  ", "water_source": "  canal  "}
    )
    assert patched.json()["soil_drainage"] == "well drained"  # whitespace collapsed only
    assert patched.json()["water_source"] == "canal"

    assert client.get(f"{API}/zones/{zid}").json()["name"] == "North block"
    assert client.delete(f"{API}/zones/{zid}").status_code == 204
    assert client.get(f"{API}/zones/{zid}").status_code == 404


def test_tree_crud_age_and_fk(client):
    zid = client.post(f"{API}/zones", json={"name": "Zone 1"}).json()["zone_id"]

    r = client.post(
        f"{API}/trees",
        json={"species": "custard apple", "variety": "gefner", "zone_id": zid, "planted_date": "2020-01-01"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["tree_id"]
    assert body["species"] == "custard apple"     # stored as typed
    assert body["variety"] == "gefner"
    assert body["zone_id"] == zid
    assert body["age_days"] > 2000 and body["age_years"] >= 5

    # unknown zone -> 422 (referential check, not a vocabulary check)
    assert client.post(
        f"{API}/trees", json={"species": "mango", "variety": "x", "zone_id": 9999}
    ).status_code == 422

    r = client.patch(f"{API}/trees/{tid}", json={"variety": "nam doc mai", "notes": "grafted"})
    assert r.json()["variety"] == "nam doc mai"
    assert r.json()["notes"] == "grafted"

    assert len(client.get(f"{API}/trees", params={"zone_id": zid}).json()) == 1
    assert client.get(f"{API}/trees", params={"species": "sapodilla"}).json() == []

    # zone still referenced -> 409
    assert client.delete(f"{API}/zones/{zid}").status_code == 409
    assert client.delete(f"{API}/trees/{tid}").status_code == 204
    assert client.get(f"{API}/trees/{tid}").status_code == 404
