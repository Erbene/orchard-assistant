"""Irrigation workflow - Phase 1: stub hardware, NWS client (respx), the
moisture-sensor map, and the rainfall forecast-accuracy log."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core import db
from app.dependencies import get_settings_dep
from app.irrigation import hardware, weather
from app.irrigation.forecast_log import RainfallForecastService
from app.irrigation.sensors import MoistureSensorService
from app.main import app
from app.repositories.moisture_sensor_repository import MoistureSensorRepository
from app.repositories.rainfall_forecast_repository import RainfallForecastRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.irrigation import (
    DailyForecast,
    MoistureSensorCreate,
    MoistureSensorUpdate,
    WeatherForecast,
)
from app.services.exceptions import ConflictError, DomainValidationError, NotFoundError

from conftest import stack_settings

NWS = "https://api.weather.gov"


@pytest.fixture(autouse=True)
def _reset_hardware():
    hardware.reset()
    weather.clear_cache()
    yield
    hardware.reset()
    weather.clear_cache()


# --------------------------------------------------------------------------
# 1. stub hardware
# --------------------------------------------------------------------------

def test_moisture_stub_is_stable_per_sensor_and_varies_across_sensors():
    a1, a2 = hardware.get_moisture("probe-a"), hardware.get_moisture("probe-a")
    assert a1 == a2                                    # reproducible
    assert hardware.get_moisture("probe-b") != a1      # sensor-specific
    assert 0.0 <= a1 <= 100.0


def test_hardware_overrides_and_reset():
    hardware.set_moisture("probe-a", 8.5)
    assert hardware.get_moisture("probe-a") == 8.5
    assert hardware.get_rain_bucket_24h() == 0.0
    hardware.set_rain_bucket_24h(6.2)
    assert hardware.get_rain_bucket_24h() == 6.2
    hardware.reset()
    assert hardware.get_rain_bucket_24h() == 0.0
    assert hardware.get_moisture("probe-a") != 8.5


# --------------------------------------------------------------------------
# 2. NWS weather client (respx)
# --------------------------------------------------------------------------

def _settings():
    return stack_settings(orchard_lat=27.5, orchard_lon=-82.5, nws_user_agent="test (t@e.st)")


_POINTS = {
    "properties": {
        "forecastGridData": f"{NWS}/gridpoints/TBW/50,60",
        "observationStations": f"{NWS}/gridpoints/TBW/50,60/stations",
        "relativeLocation": {"properties": {"city": "Testville", "state": "FL"}},
    }
}


def _grid(day: date) -> dict:
    d0 = day.isoformat()
    d2 = (day + timedelta(days=2)).isoformat()
    return {
        "properties": {
            "quantitativePrecipitation": {
                "uom": "wmoUnit:mm",
                "values": [
                    {"validTime": f"{d0}T00:00:00+00:00/PT6H", "value": 4.0},
                    {"validTime": f"{d0}T06:00:00+00:00/PT6H", "value": 2.0},
                    {"validTime": f"{d2}T00:00:00+00:00/PT12H", "value": 0.0},
                ],
            },
            "probabilityOfPrecipitation": {
                "values": [{"validTime": f"{d0}T00:00:00+00:00/PT12H", "value": 80}]
            },
            "maxTemperature": {
                "values": [{"validTime": f"{d0}T00:00:00+00:00/PT12H", "value": 31.0}]
            },
            "minTemperature": {
                "values": [{"validTime": f"{d0}T00:00:00+00:00/PT12H", "value": 23.0}]
            },
        }
    }


@respx.mock
def test_forecast_parses_gridpoint_qpf_pop_temps():
    today = date.today()
    respx.get(f"{NWS}/points/27.5,-82.5").mock(return_value=httpx.Response(200, json=_POINTS))
    respx.get(f"{NWS}/gridpoints/TBW/50,60").mock(
        return_value=httpx.Response(200, json=_grid(today))
    )

    fc = asyncio.run(weather.forecast(_settings()))
    assert fc.available and fc.location == "Testville, FL"
    first = next(d for d in fc.daily if d.date == today)
    assert first.qpf_mm == 6.0            # 4 + 2 summed for the day
    assert first.pop_pct == 80
    assert first.temp_high_c == 31.0 and first.temp_low_c == 23.0


@respx.mock
def test_forecast_degrades_when_nws_errors():
    respx.get(f"{NWS}/points/27.5,-82.5").mock(return_value=httpx.Response(503))
    fc = asyncio.run(weather.forecast(_settings()))
    assert fc.available is False and fc.error


def test_forecast_unavailable_without_coordinates():
    fc = asyncio.run(weather.forecast(stack_settings()))
    assert fc.available is False and "ORCHARD_LAT" in fc.error


@respx.mock
def test_observed_rain_sums_the_6h_accumulators():
    day = date.today() - timedelta(days=1)
    respx.get(f"{NWS}/points/27.5,-82.5").mock(return_value=httpx.Response(200, json=_POINTS))
    respx.get(f"{NWS}/gridpoints/TBW/50,60/stations").mock(
        return_value=httpx.Response(
            200, json={"features": [{"properties": {"stationIdentifier": "KSRQ"}}]}
        )
    )
    respx.get(f"{NWS}/stations/KSRQ/observations").mock(
        return_value=httpx.Response(
            200,
            json={
                "features": [
                    {"properties": {"precipitationLast6Hours": {"value": 3.0}}},
                    {"properties": {"precipitationLast6Hours": {"value": 1.5}}},
                    {"properties": {"precipitationLast6Hours": {"value": None}}},
                ]
            },
        )
    )
    mm = asyncio.run(weather.observed_rain_mm(_settings(), day))
    assert mm == 4.5


# --------------------------------------------------------------------------
# 3. moisture-sensor map
# --------------------------------------------------------------------------

def _run(body):
    settings = stack_settings()

    async def _wrap():
        try:
            async with db.connection(settings) as conn:
                trees = TreeRepository(conn)
                svc = MoistureSensorService(MoistureSensorRepository(conn), trees)
                log = RainfallForecastService(
                    RainfallForecastRepository(conn),
                    _settings(),
                )
                return await body(conn, trees, svc, log)
        finally:
            await db.dispose_all()

    return asyncio.run(_wrap())


def test_sensor_crud_and_validation():
    async def body(conn, trees, svc, log):
        tid = (await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-1"}))["tree_id"]

        with pytest.raises(DomainValidationError):
            await svc.create(MoistureSensorCreate(id="s-orphan"))          # no tree, no zone
        with pytest.raises(DomainValidationError):
            await svc.create(MoistureSensorCreate(id="s-bad", tree_id=99999))

        made = await svc.create(MoistureSensorCreate(id="s-1", tree_id=tid, label="north probe"))
        assert made.tree_id == tid
        with pytest.raises(ConflictError):
            await svc.create(MoistureSensorCreate(id="s-1", zone_id="z-1"))

        moved = await svc.update("s-1", MoistureSensorUpdate(label="renamed"))
        assert moved.label == "renamed"
        await svc.delete("s-1")
        with pytest.raises(NotFoundError):
            await svc.get("s-1")

    _run(body)


def test_tree_moisture_resolves_own_sensors_then_zone_then_none():
    async def body(conn, trees, svc, log):
        tid = (await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-9"}))["tree_id"]

        # no sensors -> resolved_via none
        m = await svc.tree_moisture(tid)
        assert m.resolved_via == "none" and m.mean_vwc_pct is None

        # a zone sensor -> resolved via zone
        await svc.create(MoistureSensorCreate(id="zs", zone_id="z-9"))
        hardware.set_moisture("zs", 18.0)
        m = await svc.tree_moisture(tid)
        assert m.resolved_via == "zone" and m.mean_vwc_pct == 18.0

        # the tree's own sensor wins over the zone
        await svc.create(MoistureSensorCreate(id="ts1", tree_id=tid))
        await svc.create(MoistureSensorCreate(id="ts2", tree_id=tid))
        hardware.set_moisture("ts1", 10.0)
        hardware.set_moisture("ts2", 20.0)
        m = await svc.tree_moisture(tid)
        assert m.resolved_via == "tree" and m.mean_vwc_pct == 15.0
        assert {r.sensor_id for r in m.readings} == {"ts1", "ts2"}

    _run(body)


# --------------------------------------------------------------------------
# 4. rainfall forecast-accuracy log
# --------------------------------------------------------------------------

def _forecast_for(day0: date, mm_by_offset: dict[int, float]) -> WeatherForecast:
    return WeatherForecast(
        available=True,
        fetched_at=datetime.now(timezone.utc),
        daily=[
            DailyForecast(date=day0 + timedelta(days=k), qpf_mm=v)
            for k, v in mm_by_offset.items()
        ],
    )


def test_roll_writes_horizon_forecasts_and_backfills_actuals():
    async def body(conn, trees, svc, log):
        today = date(2026, 6, 10)
        fc = _forecast_for(today, {1: 0.0, 3: 8.0, 5: 2.0, 7: 1.0})
        hardware.set_rain_bucket_24h(5.5)

        with patch.object(weather, "forecast", AsyncMock(return_value=fc)), patch.object(
            weather, "observed_rain_mm", AsyncMock(return_value=7.1)
        ):
            res = await log.roll(today=today)

        assert res.forecasts_written == {"1d": 0.0, "3d": 8.0, "5d": 2.0}
        assert res.actuals_written == {"nws": 7.1, "gauge": 5.5}

        repo = RainfallForecastRepository(conn)
        assert (await repo.get(today + timedelta(days=3)))["forecast_3d_mm"] == 8.0
        y = await repo.get(today - timedelta(days=1))
        assert y["actual_nws_mm"] == 7.1 and y["actual_gauge_mm"] == 5.5

        # re-roll same day -> upsert, not duplicate/erase
        fc2 = _forecast_for(today, {3: 9.0})
        with patch.object(weather, "forecast", AsyncMock(return_value=fc2)), patch.object(
            weather, "observed_rain_mm", AsyncMock(return_value=None)
        ):
            await log.roll(today=today)
        assert (await repo.get(today + timedelta(days=3)))["forecast_3d_mm"] == 9.0

    _run(body)


def test_accuracy_scores_forecast_vs_actual_per_horizon():
    async def body(conn, trees, svc, log):
        repo = RainfallForecastRepository(conn)
        base = date(2026, 3, 1)
        # 3 scored days: forecast_3d vs actual_nws -> errors +2, -1, 0
        for k, (f3, act) in enumerate([(5.0, 3.0), (0.0, 1.0), (4.0, 4.0)]):
            d = base + timedelta(days=k)
            await repo.upsert(d, {"forecast_3d_mm": f3})
            await repo.upsert(d, {"actual_nws_mm": act})

        acc = await log.accuracy(since=base)
        h3 = next(h for h in acc.horizons if h.horizon == "3d")
        assert h3.n == 3
        assert h3.mae_mm == round((2 + 1 + 0) / 3, 2)
        assert h3.bias_mm == round((2 - 1 + 0) / 3, 2)
        # rain(>=1mm) call: (5,3)=hit, (0,1)=miss, (4,4)=hit -> 2/3
        assert h3.hit_rate == round(2 / 3, 3)
        assert next(h for h in acc.horizons if h.horizon == "1d").n == 0

    _run(body)


# --------------------------------------------------------------------------
# 5. tree.estimated_gph over the existing PATCH endpoint
# --------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_estimated_gph_persists_on_the_tree(client):
    tid = client.post(
        "/api/v1/trees", json={"species": "mango", "variety": "Kent", "estimated_gph": 12.5}
    ).json()["tree_id"]
    assert client.get(f"/api/v1/trees/{tid}").json()["estimated_gph"] == 12.5
    client.patch(f"/api/v1/trees/{tid}", json={"estimated_gph": 20.0})
    assert client.get(f"/api/v1/trees/{tid}").json()["estimated_gph"] == 20.0
