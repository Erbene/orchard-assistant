"""End-to-end CRUD tests using a throwaway database file."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORCHARD_DB_PATH", str(tmp_path / "test.db"))
    from api import db, main

    importlib.reload(db)
    importlib.reload(main)
    # Re-point already-imported router modules at the reloaded db module.
    from api.routers import trees, zones

    importlib.reload(zones)
    importlib.reload(trees)
    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_zone_crud(client):
    r = client.post("/zones", json={"zone_id": "north", "name": "North block"})
    assert r.status_code == 201, r.text
    assert r.json()["soil_drainage"] is None

    assert client.post("/zones", json={"zone_id": "north", "name": "dup"}).status_code == 409

    r = client.patch("/zones/north", json={"soil_drainage": "loamy"})
    assert r.json()["soil_drainage"] == "loamy"

    assert client.get("/zones/north").json()["name"] == "North block"
    assert len(client.get("/zones").json()) == 1

    assert client.delete("/zones/north").status_code == 204
    assert client.get("/zones/north").status_code == 404


def test_tree_crud_and_age(client):
    client.post("/zones", json={"zone_id": "z1", "name": "Zone 1"})

    r = client.post(
        "/trees",
        json={
            "species": "mango",
            "variety": "Kent",
            "zone_id": "z1",
            "planted_date": "2020-01-01",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["tree_id"]
    assert body["age_days"] > 2000
    assert body["age_years"] >= 5

    # unknown zone rejected
    assert client.post(
        "/trees", json={"species": "mango", "variety": "x", "zone_id": "nope"}
    ).status_code == 422

    # bad species rejected by validation
    assert client.post(
        "/trees", json={"species": "banana", "variety": "x"}
    ).status_code == 422

    r = client.patch(f"/trees/{tid}", json={"variety": "Haden", "notes": "grafted"})
    assert r.json()["variety"] == "Haden"
    assert r.json()["notes"] == "grafted"

    assert len(client.get("/trees", params={"species": "mango"}).json()) == 1
    assert client.get("/trees", params={"species": "sapodilla"}).json() == []

    # zone still referenced -> cannot delete
    assert client.delete("/zones/z1").status_code == 409

    assert client.delete(f"/trees/{tid}").status_code == 204
    assert client.get(f"/trees/{tid}").status_code == 404
