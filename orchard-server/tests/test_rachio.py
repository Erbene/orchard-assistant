"""RachioService — fully mocked (respx). Never touches the real Rachio API."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from app.config import Settings
from app.services import rachio
from app.services.exceptions import RachioError, RachioNotConfigured
from app.services.rachio import RachioService

BASE = "https://api.rach.io/1/public"

PERSON = {"id": "person-1"}
ACCOUNT = {
    "id": "person-1",
    "devices": [
        {
            "id": "dev-1",
            "name": "Backyard Controller",
            "status": "ONLINE",
            "model": "GENERATION3_16ZONE",
            "zones": [
                {
                    "id": "z-1", "name": "Front Lawn", "enabled": True, "zoneNumber": 1,
                    "customSoil": {"name": "Clay Loam"},
                    "customCrop": {"name": "Cool Season Grass"},
                    "customNozzle": {"name": "Fixed Spray Head"},
                },
                {"id": "z-2", "name": "Flower Beds", "enabled": False, "zoneNumber": 2},
            ],
        }
    ],
}


def cfg(key: str = "test-key") -> Settings:
    return Settings(rachio_api_key=key)


def test_rachio_parses_devices_and_zones_and_caches():
    @respx.mock
    async def go():
        respx.get(f"{BASE}/person/info").mock(return_value=httpx.Response(200, json=PERSON))
        account = respx.get(f"{BASE}/person/person-1").mock(
            return_value=httpx.Response(200, json=ACCOUNT)
        )
        svc = RachioService(cfg())
        try:
            devices = await svc.get_devices_and_zones()
            assert [d.id for d in devices] == ["dev-1"]
            z1, z2 = devices[0].zones
            assert (z1.id, z1.name, z1.zone_number) == ("z-1", "Front Lawn", 1)
            assert z1.custom_soil == {"name": "Clay Loam"}
            assert z1.custom_crop == {"name": "Cool Season Grass"}
            assert z2.enabled is False

            # 10-minute cache: a second call hits neither endpoint again
            await svc.get_devices_and_zones()
            assert account.call_count == 1

            device, zone = await svc.get_zone("z-2")
            assert device.id == "dev-1" and zone.name == "Flower Beds"

            with pytest.raises(Exception):  # NotFoundError
                await svc.get_zone("nope")
        finally:
            await svc.aclose()

    asyncio.run(go())


def test_rachio_cache_expires_after_ttl(monkeypatch):
    clock = {"t": 1_000.0}
    monkeypatch.setattr(rachio, "_monotonic", lambda: clock["t"])

    @respx.mock
    async def go():
        respx.get(f"{BASE}/person/info").mock(return_value=httpx.Response(200, json=PERSON))
        account = respx.get(f"{BASE}/person/person-1").mock(
            return_value=httpx.Response(200, json=ACCOUNT)
        )
        svc = RachioService(cfg())
        try:
            await svc.get_devices_and_zones()
            clock["t"] += rachio._CACHE_TTL + 1
            await svc.get_devices_and_zones()
            assert account.call_count == 2
        finally:
            await svc.aclose()

    asyncio.run(go())


def test_start_zone_watering_body_and_clamp():
    @respx.mock
    async def go():
        route = respx.put(f"{BASE}/zone/start").mock(return_value=httpx.Response(204))
        svc = RachioService(cfg())
        try:
            await svc.start_zone_watering("z-1", 120)
            assert json.loads(route.calls.last.request.content) == {"id": "z-1", "duration": 120}

            await svc.start_zone_watering("z-1", 999_999)          # clamp high
            assert json.loads(route.calls.last.request.content)["duration"] == 10_800

            await svc.start_zone_watering("z-1", 0)                 # clamp low
            assert json.loads(route.calls.last.request.content)["duration"] == 1
        finally:
            await svc.aclose()

    asyncio.run(go())


def test_rachio_not_configured_raises_before_any_request():
    async def go():
        svc = RachioService(cfg(key=""))
        for coro in (
            svc.get_person_info(),
            svc.get_devices_and_zones(),
            svc.get_zone("z-1"),
            svc.start_zone_watering("z-1", 60),
        ):
            with pytest.raises(RachioNotConfigured):
                await coro
        await svc.aclose()

    asyncio.run(go())


def test_rachio_http_error_wrapped():
    @respx.mock
    async def go():
        respx.get(f"{BASE}/person/info").mock(return_value=httpx.Response(401, json={}))
        svc = RachioService(cfg())
        try:
            with pytest.raises(RachioError):
                await svc.get_person_info()
        finally:
            await svc.aclose()

    asyncio.run(go())
