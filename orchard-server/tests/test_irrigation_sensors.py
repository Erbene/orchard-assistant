"""Irrigation Sensors board: snapshot is public; overrides require ORCHARD_DEMO."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.irrigation import demo, hardware, weather
from app.main import app

from conftest import stack_settings


@pytest.fixture(autouse=True)
def _reset_demo():
    demo.reset()
    yield
    demo.reset()


@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def demo_client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path), orchard_demo=True)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _add_tree(client: TestClient, zone_id: str = "z-1", species: str = "mango"):
    return client.post(
        "/api/v1/trees",
        json={"species": species, "variety": "Kent", "zone_id": zone_id},
    ).json()


def test_snapshot_available_when_demo_off(client):
    tree = _add_tree(client)
    r = client.get("/api/v1/irrigation/sensors")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_enabled"] is False
    assert body["rain_overridden"] is False
    assert body["forecast_overridden"] is False
    assert body["zones"][0]["zone_id"] == "z-1"
    trees = body["zones"][0]["trees"]
    assert trees[0]["tree_id"] == tree["tree_id"]
    assert trees[0]["current_vwc"] is None
    assert trees[0]["sensors"] == []

    assert client.put("/api/v1/irrigation/sensors/overrides", json={"rain_24h_mm": 5}).status_code == 404
    assert client.post("/api/v1/irrigation/demo/reset").status_code == 404


def test_demo_overrides_pin_supervisor_inputs(demo_client):
    mango = _add_tree(demo_client, "z-mix", "mango")
    avocado = _add_tree(demo_client, "z-mix", "avocado")

    r = demo_client.put(
        "/api/v1/irrigation/sensors/overrides",
        json={
            "rain_24h_mm": 4.5,
            "forecast_rain_24h_mm": 12.0,
            "for_date": "2026-05-15",
            "last_watered": [{"zone_id": "z-mix", "last_watered_date": "2026-05-10"}],
            "moisture": [
                {"tree_id": mango["tree_id"], "vwc_pct": 24.0},
                {"tree_id": avocado["tree_id"], "vwc_pct": 16.0},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo_enabled"] is True
    assert body["for_date"] == "2026-05-15"
    assert body["rain_24h_mm"] == pytest.approx(4.5)
    assert body["rain_overridden"] is True
    assert body["forecast_rain_24h_mm"] == pytest.approx(12.0)
    assert body["forecast_overridden"] is True
    assert body["active_scenario_id"] is None
    assert body["pins_active"] is True

    zone = body["zones"][0]
    assert zone["last_watered_date"] == "2026-05-10"
    assert zone["last_watered_source"] == "demo"
    by_id = {t["tree_id"]: t for t in zone["trees"]}
    assert by_id[mango["tree_id"]]["current_vwc"] == pytest.approx(24.0)
    assert by_id[avocado["tree_id"]]["current_vwc"] == pytest.approx(16.0)
    assert by_id[mango["tree_id"]]["sensors"][0]["overridden"] is True
    assert by_id[mango["tree_id"]]["moisture_resolved_via"] == "tree"

    assert hardware.get_rain_bucket_24h() == pytest.approx(4.5)
    assert hardware.get_moisture(f"demo-{mango['tree_id']}") == pytest.approx(24.0)
    assert demo.overlay_on_date() == date(2026, 5, 15)
    assert demo.overlay_last_watered("z-mix") == date(2026, 5, 10)


def test_demo_reset_clears_sensor_pins(demo_client):
    tree = _add_tree(demo_client)
    demo_client.put(
        "/api/v1/irrigation/sensors/overrides",
        json={"rain_24h_mm": 9, "moisture": [{"tree_id": tree["tree_id"], "vwc_pct": 11}]},
    )
    assert hardware.rain_is_overridden()
    assert hardware.moisture_is_overridden(f"demo-{tree['tree_id']}")

    r = demo_client.post("/api/v1/irrigation/demo/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["rain_overridden"] is False
    assert body["forecast_overridden"] is False
    assert body["pins_active"] is False
    assert hardware.rain_is_overridden() is False
    assert demo.overlay_on_date() is None


def test_named_scenario_then_custom_edit_drops_scenario_label(demo_client):
    tree = _add_tree(demo_client, "z-rain")
    demo_client.post("/api/v1/irrigation/demo/rain-skip/apply")
    snap = demo_client.get("/api/v1/irrigation/sensors").json()
    assert snap["active_scenario_id"] == "rain-skip"
    assert snap["zones"][0]["trees"][0]["current_vwc"] == pytest.approx(30.0)

    edited = demo_client.put(
        "/api/v1/irrigation/sensors/overrides",
        json={"moisture": [{"tree_id": tree["tree_id"], "vwc_pct": 18.0}]},
    ).json()
    assert edited["active_scenario_id"] is None
    assert edited["zones"][0]["trees"][0]["current_vwc"] == pytest.approx(18.0)
    # rain-skip's forecast pin is left in place (partial update)
    assert weather.forecast_is_overridden() is True
