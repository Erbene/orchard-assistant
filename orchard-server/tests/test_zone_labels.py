"""Local zone labels overlay Rachio zone numbers in API responses."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.main import app
from app.services.rachio import get_rachio_service
from app.services.zone_service import zone_display_name

from conftest import stack_settings

API = "/api/v1"
RACHIO = "https://api.rach.io/1/public"

_PERSON = {"id": "p1"}
_ACCOUNT = {
    "id": "p1",
    "devices": [
        {
            "id": "dev-1",
            "name": "Backyard",
            "status": "ONLINE",
            "model": "GEN3",
            "zones": [
                {"id": "rz-1", "name": "Row A", "enabled": True, "zoneNumber": 1},
                {"id": "rz-2", "name": "Row B", "enabled": True, "zoneNumber": 2},
            ],
        }
    ],
}


def _mock_rachio() -> None:
    respx.get(f"{RACHIO}/person/info").mock(return_value=httpx.Response(200, json=_PERSON))
    respx.get(f"{RACHIO}/person/p1").mock(return_value=httpx.Response(200, json=_ACCOUNT))


@pytest.fixture()
def rachio_client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path), rachio_api_key="test-key")
    app.dependency_overrides[get_settings_dep] = lambda: settings
    get_rachio_service.cache_clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_rachio_service.cache_clear()


def test_zone_display_name_prefers_label_then_number():
    assert zone_display_name("North mango", 3, "abc") == "North mango"
    assert zone_display_name("  ", 3, "abc") == "Zone 3"
    assert zone_display_name(None, 3, "abc") == "Zone 3"
    assert zone_display_name(None, None, "abc") == "Zone abc"


@respx.mock
def test_zones_list_falls_back_to_rachio_number(rachio_client):
    _mock_rachio()
    devices = rachio_client.get(f"{API}/zones").json()
    z1 = devices[0]["zones"][0]
    assert z1["id"] == "rz-1"
    assert z1["label"] is None
    assert z1["display_name"] == "Zone 1"
    assert z1["name"] == "Row A"


@respx.mock
def test_set_label_overlays_everywhere(rachio_client):
    _mock_rachio()
    saved = rachio_client.put(
        f"{API}/zones/rz-1/label", json={"label": "North mango row"}
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["label"] == "North mango row"
    assert body["display_name"] == "North mango row"
    assert body["zone_number"] == 1

    devices = rachio_client.get(f"{API}/zones").json()
    z1 = next(z for z in devices[0]["zones"] if z["id"] == "rz-1")
    z2 = next(z for z in devices[0]["zones"] if z["id"] == "rz-2")
    assert z1["display_name"] == "North mango row"
    assert z2["display_name"] == "Zone 2"

    tree = rachio_client.post(
        f"{API}/trees",
        json={"species": "mango", "variety": "Kent", "zone_id": "rz-1"},
    ).json()
    assert tree["zone_label"] == "North mango row"
    assert tree["zone_display_name"] == "North mango row"

    cleared = rachio_client.put(f"{API}/zones/rz-1/label", json={"label": ""})
    assert cleared.status_code == 200
    assert cleared.json()["label"] is None
    assert cleared.json()["display_name"] == "Zone 1"


@respx.mock
def test_unused_zone_stays_listed_but_flagged(rachio_client):
    _mock_rachio()
    marked = rachio_client.put(f"{API}/zones/rz-1/in-use", json={"in_use": False})
    assert marked.status_code == 200, marked.text
    assert marked.json()["in_use"] is False

    devices = rachio_client.get(f"{API}/zones").json()
    z1 = next(z for z in devices[0]["zones"] if z["id"] == "rz-1")
    z2 = next(z for z in devices[0]["zones"] if z["id"] == "rz-2")
    assert z1["in_use"] is False
    assert z2["in_use"] is True

    restored = rachio_client.put(f"{API}/zones/rz-1/in-use", json={"in_use": True})
    assert restored.json()["in_use"] is True
    devices = rachio_client.get(f"{API}/zones").json()
    z1 = next(z for z in devices[0]["zones"] if z["id"] == "rz-1")
    assert z1["in_use"] is True
