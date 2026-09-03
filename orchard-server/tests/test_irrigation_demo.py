"""ORCHARD_DEMO: catalog, apply pins, and overlay helpers (no LLM)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_settings_dep
from app.irrigation import demo, hardware
from app.main import app

from conftest import stack_settings

SCENARIO_IDS = {"rain-skip", "mixed-zone-tot", "drought-emergency"}


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


def test_demo_off_returns_404(client):
    assert client.get("/api/v1/irrigation/demo").status_code == 404
    ov = client.get("/api/v1/irrigation/overview").json()
    assert ov["demo_enabled"] is False


def test_demo_catalog_and_unknown_apply(demo_client):
    r = demo_client.get("/api/v1/irrigation/demo")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert {s["id"] for s in body["scenarios"]} == SCENARIO_IDS
    assert body["active_scenario_id"] is None

    ov = demo_client.get("/api/v1/irrigation/overview").json()
    assert ov["demo_enabled"] is True

    assert demo_client.post("/api/v1/irrigation/demo/nope/apply").status_code == 404


def test_apply_rain_skip_pins_readings(demo_client):
    zone_id = "z-rain"
    tree = demo_client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "zone_id": zone_id},
    ).json()

    res = demo_client.post("/api/v1/irrigation/demo/rain-skip/apply").json()
    assert res["scenario_id"] == "rain-skip"
    assert res["on_date"] == "2026-06-15"
    assert res["zone_ids"] == [zone_id]

    catalog = demo_client.get("/api/v1/irrigation/demo").json()
    assert catalog["active_scenario_id"] == "rain-skip"

    assert demo.overlay_on_date() == date(2026, 6, 15)
    assert demo.overlay_last_watered(zone_id) == date(2026, 6, 10)

    sensor_id = f"demo-{tree['tree_id']}"
    assert hardware.get_moisture(sensor_id) == pytest.approx(30.0)


def test_apply_drought_emergency_pins_readings(demo_client):
    zone_id = "z-dry"
    tree = demo_client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "zone_id": zone_id},
    ).json()

    res = demo_client.post("/api/v1/irrigation/demo/drought-emergency/apply").json()
    assert res["scenario_id"] == "drought-emergency"
    assert res["on_date"] == "2026-03-15"

    assert demo.overlay_on_date() == date(2026, 3, 15)
    last = demo.overlay_last_watered(zone_id)
    assert last == date(2026, 3, 10)
    assert last != date(2026, 3, 15) - timedelta(days=1)

    sensor_id = f"demo-{tree['tree_id']}"
    assert hardware.get_moisture(sensor_id) == pytest.approx(12.0)


def test_demo_reset_clears_pins(demo_client):
    demo_client.post(
        "/api/v1/trees",
        json={"species": "mango", "variety": "Kent", "zone_id": "z-1"},
    )
    demo_client.post("/api/v1/irrigation/demo/rain-skip/apply")
    assert demo.active_scenario_id() == "rain-skip"
    assert demo.overlay_on_date() is not None

    demo.reset()
    assert demo.active_scenario_id() is None
    assert demo.overlay_on_date() is None
    assert demo.overlay_zone_ids() == []
    assert demo.overlay_last_watered("z-1") is None
