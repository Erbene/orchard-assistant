"""Irrigation Phase 2: the deterministic water-balance calculator, the stub
action tools, and the LangGraph supervisor node (LLM mocked; one opt-in
real-LLM smoke)."""
from __future__ import annotations

import asyncio
import urllib.request
from contextlib import contextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.irrigation_supervisor import (
    IrrigationSupervisorService,
    _DecisionModel,
    build_irrigation_graph,
)
from app.core import db
from app.irrigation import hardware, weather
from app.irrigation.phenology import growth_stage, target_vwc_for_stage
from app.irrigation.sensors import MoistureSensorService
from app.repositories.moisture_sensor_repository import MoistureSensorRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.irrigation import (
    DailyForecast,
    MoistureSensorCreate,
    WeatherForecast,
)
from app.services.water_balance import WaterBalanceService
from app.tools import irrigation as tools

from conftest import stack_settings

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def _reset():
    hardware.reset()
    weather.clear_cache()
    yield
    hardware.reset()
    weather.clear_cache()


def _forecast(qpf_today: float) -> WeatherForecast:
    return WeatherForecast(
        available=True, daily=[DailyForecast(date=TODAY, qpf_mm=qpf_today)]
    )


# --------------------------------------------------------------------------
# 1. phenology
# --------------------------------------------------------------------------

def test_phenology_stage_and_targets():
    assert growth_stage("apple", date(2026, 1, 5)) == "dormancy"
    assert growth_stage("apple", date(2026, 4, 5)) == "flowering"
    assert growth_stage("mango", date(2026, 1, 5)) == "flowering"       # evergreen override
    # southern hemisphere: shifted 6 months
    assert growth_stage("apple", date(2026, 7, 5), hemisphere="S") == "dormancy"
    assert target_vwc_for_stage("flowering") > target_vwc_for_stage("dormancy")
    assert target_vwc_for_stage("nonsense", fallback=21.0) == 21.0


# --------------------------------------------------------------------------
# 2. water-balance calculator (deterministic)
# --------------------------------------------------------------------------

def _run(body):
    settings = stack_settings(irrigation_target_vwc=25.0)

    async def _wrap():
        try:
            async with db.connection(settings) as conn:
                trees = TreeRepository(conn)
                sensors = MoistureSensorService(MoistureSensorRepository(conn), trees)
                water = WaterBalanceService(sensors, trees, settings)
                return await body(conn, trees, sensors, water, settings)
        finally:
            await db.dispose_all()

    return asyncio.run(_wrap())


def test_deficit_score_is_the_literal_formula():
    async def body(conn, trees, sensors, water, settings):
        tid = (await trees.create({"species": "apple", "variety": "Fuji", "zone_id": "z-1"}))["tree_id"]
        await sensors.create(MoistureSensorCreate(id="s1", tree_id=tid))
        hardware.set_moisture("s1", 18.0)      # current VWC
        hardware.set_rain_bucket_24h(2.0)      # rain last 24h

        with patch("app.irrigation.weather.forecast", AsyncMock(return_value=_forecast(3.0))):
            wb = await water.for_tree(tid, on_date=TODAY)

        # June -> fruit_development -> target 27.0
        assert wb.growth_stage == "fruit_development" and wb.target_vwc == 27.0
        assert wb.current_vwc == 18.0
        assert wb.moisture_gap == 9.0                      # 27 - 18
        assert wb.rain_24h_mm == 2.0 and wb.forecast_rain_24h_mm == 3.0
        assert wb.deficit_score == 4.0                     # 9 - 2 - 3
        assert not wb.notes

    _run(body)


def test_no_sensor_gives_zero_gap_and_a_note():
    async def body(conn, trees, sensors, water, settings):
        tid = (await trees.create({"species": "apple", "variety": "Fuji", "zone_id": "z-9"}))["tree_id"]
        hardware.set_rain_bucket_24h(6.0)
        with patch("app.irrigation.weather.forecast", AsyncMock(return_value=_forecast(0.0))):
            wb = await water.for_tree(tid, on_date=TODAY)
        assert wb.current_vwc is None and wb.moisture_gap == 0.0
        assert wb.deficit_score == -6.0                    # 0 - 6 - 0
        assert any("no moisture sensor" in n for n in wb.notes)

    _run(body)


def test_zone_balance_takes_the_driest_tree():
    async def body(conn, trees, sensors, water, settings):
        z = "z-block"
        t1 = (await trees.create({"species": "apple", "variety": "A", "zone_id": z}))["tree_id"]
        t2 = (await trees.create({"species": "apple", "variety": "B", "zone_id": z}))["tree_id"]
        await sensors.create(MoistureSensorCreate(id="a", tree_id=t1))
        await sensors.create(MoistureSensorCreate(id="b", tree_id=t2))
        hardware.set_moisture("a", 24.0)      # gap 3
        hardware.set_moisture("b", 12.0)      # gap 15  <- driest
        hardware.set_rain_bucket_24h(0.0)

        with patch("app.irrigation.weather.forecast", AsyncMock(return_value=_forecast(0.0))):
            zwb = await water.for_zone(z, on_date=TODAY)

        assert len(zwb.trees) == 2
        assert zwb.deficit_score == max(t.deficit_score for t in zwb.trees) == 15.0

    _run(body)


# --------------------------------------------------------------------------
# 3. action tools (stubbed)
# --------------------------------------------------------------------------

def test_tools_clamp_and_report_dry_run(capsys):
    r = tools.rachio_skip_schedule("z-1", 99)
    assert r.action == "skip_schedule" and r.params["days"] == 14 and r.dry_run
    r = tools.start_zone_watering("z-1", 0)
    assert r.params["duration_minutes"] == 1                # clamped up from 0
    r = tools.pass_no_action("z-1")
    assert r.action == "pass_no_action" and r.params == {}
    assert "[IRRIGATION STUB]" in capsys.readouterr().out
    assert tools.dispatch("weird", "z-1").action == "pass_no_action"   # unknown -> safe default


# --------------------------------------------------------------------------
# 4. supervisor node (LLM mocked)
# --------------------------------------------------------------------------

@contextmanager
def fake_llm(action: str, *, days=0, duration_minutes=0, reason="ok", down=False):
    structured = MagicMock()
    if down:
        structured.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))
    else:
        structured.ainvoke = AsyncMock(
            return_value=_DecisionModel(
                action=action, days=days, duration_minutes=duration_minutes, reason=reason
            )
        )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    with patch("app.agent.irrigation_supervisor.ChatOllama", return_value=llm):
        yield


def test_graph_deliberates_then_executes():
    g = build_irrigation_graph(stack_settings())
    state = {
        "zone_id": "z-1",
        "deficit_score": 12.0,
        "rain_24h_mm": 0.0,
        "forecast_rain_24h_mm": 0.0,
        "forecast_available": True,
        "trees": [{"tree_id": 1, "species": "apple", "growth_stage": "fruit_set",
                   "target_vwc": 30.0, "current_vwc": 15.0, "deficit_score": 12.0}],
    }
    with fake_llm("start_zone_watering", duration_minutes=20, reason="fruit set, dry, no rain"):
        out = asyncio.run(g.ainvoke(state))
    assert out["decision"]["action"] == "start_zone_watering"
    assert out["result"]["params"]["duration_minutes"] == 20
    assert out["result"]["dry_run"] is True
    assert out["llm_available"] is True


def test_graph_defers_to_baseline_when_llm_down():
    g = build_irrigation_graph(stack_settings())
    with fake_llm("", down=True):
        out = asyncio.run(g.ainvoke({"zone_id": "z-2", "deficit_score": 5.0, "trees": []}))
    assert out["decision"]["action"] == "pass_no_action"
    assert out["llm_available"] is False
    assert out["result"]["action"] == "pass_no_action"


def test_supervisor_service_run_for_zone_and_daily():
    async def body(conn, trees, sensors, water, settings):
        for z in ("z-a", "z-b"):
            tid = (await trees.create({"species": "apple", "variety": z, "zone_id": z}))["tree_id"]
            await sensors.create(MoistureSensorCreate(id=f"s-{z}", tree_id=tid))
            hardware.set_moisture(f"s-{z}", 10.0)
        hardware.set_rain_bucket_24h(0.0)

        svc = IrrigationSupervisorService(water, trees, settings)
        with patch("app.irrigation.weather.forecast", AsyncMock(return_value=_forecast(0.0))), \
             fake_llm("skip_schedule", days=2, reason="rain due"):
            run = await svc.run_for_zone("z-a", on_date=TODAY)
            assert run.zone_id == "z-a" and run.decision.action == "skip_schedule"
            assert run.decision.days == 2 and run.executed["params"]["days"] == 2
            assert run.growth_stages == ["fruit_development"]

            runs = await svc.run_daily(on_date=TODAY)
            assert {r.zone_id for r in runs} == {"z-a", "z-b"}

    _run(body)


# --------------------------------------------------------------------------
# 5. opt-in real-LLM smoke (skipped when Ollama is unreachable)
# --------------------------------------------------------------------------

_REAL_OLLAMA = "http://127.0.0.1:11434"


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen(f"{_REAL_OLLAMA}/api/version", timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="Ollama not reachable")
@pytest.mark.parametrize(
    "deficit,stage,forecast_mm,acceptable",
    [
        (-12.0, "fruit_development", 15.0, {"skip_schedule"}),                 # soaked -> skip
        (2.0, "vegetative", 0.0, {"pass_no_action", "skip_schedule"}),         # unremarkable
        (14.0, "fruit_set", 0.0, {"start_zone_watering", "pass_no_action"}),   # dry + critical
    ],
)
def test_real_llm_supervisor_picks_a_sane_action(deficit, stage, forecast_mm, acceptable):
    from app.agent.irrigation_supervisor import build_irrigation_graph

    g = build_irrigation_graph(stack_settings(ollama_base_url=_REAL_OLLAMA))
    state = {
        "zone_id": "z-test",
        "deficit_score": deficit,
        "rain_24h_mm": 0.0,
        "forecast_rain_24h_mm": forecast_mm,
        "forecast_available": True,
        "trees": [{"tree_id": 1, "species": "mango", "growth_stage": stage,
                   "target_vwc": 30.0, "current_vwc": 30.0 - max(deficit, 0),
                   "deficit_score": deficit}],
    }
    out = asyncio.run(g.ainvoke(state))
    assert out["decision"]["action"] in acceptable, (
        f"deficit={deficit} stage={stage} -> {out['decision']}"
    )
