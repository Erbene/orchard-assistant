"""Irrigation Phase 3: the Tree-of-Thoughts zone solver, the HITL supervisor
graph (sync + interrupt_before), and the run / approve / reject service flow."""
from __future__ import annotations

import asyncio
import urllib.request
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent import zone_solver as zs
from app.agent.irrigation_supervisor import _DecisionModel, build_irrigation_graph
from app.core import db
from app.dependencies import get_settings_dep
from app.irrigation import hardware, weather
from app.irrigation.phenology import growth_stage, target_vwc_for_stage
from app.irrigation.sensors import MoistureSensorService
from app.main import app
from app.repositories.irrigation_config_repository import IrrigationConfigRepository
from app.repositories.irrigation_proposal_repository import IrrigationProposalRepository
from app.repositories.moisture_sensor_repository import MoistureSensorRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.irrigation import (
    DailyForecast,
    MoistureSensorCreate,
    SupervisorConfigUpdate,
    WeatherForecast,
    ZoneConfigUpdate,
)
from app.services.irrigation_service import (
    IrrigationConfigService,
    IrrigationSupervisorService,
)
from app.services.water_balance import WaterBalanceService

from conftest import stack_settings

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def _reset():
    hardware.reset()
    weather.clear_cache()
    yield
    hardware.reset()
    weather.clear_cache()


def _forecast(qpf: float) -> WeatherForecast:
    return WeatherForecast(available=True, daily=[DailyForecast(date=TODAY, qpf_mm=qpf)])


# --------------------------------------------------------------------------
# 1. phenology + water-balance (Phase 2 carry-over)
# --------------------------------------------------------------------------

def test_phenology_targets_track_stage():
    assert growth_stage("mango", date(2026, 1, 5)) == "flowering"
    assert target_vwc_for_stage("flowering") > target_vwc_for_stage("dormancy")


# --------------------------------------------------------------------------
# 2. Zone Contention Solver (ToT + beam search)
# --------------------------------------------------------------------------

def _hydro(species, vwc, gph=8.0, wetted_area=None, spread=3.0):
    return zs.TreeHydro(hash(species) & 0xFFFF, species, vwc, spread, gph, wetted_area)


def test_volume_math_matches_the_spec_formula():
    t = _hydro("mango", 25.0, gph=12.0)
    assert zs.delivered_gallons(t, 30) == pytest.approx((30 / 60) * 12.0)   # 6.0 gal


def test_solver_prefers_less_water_on_a_tie():
    trees = [_hydro("mango", 26.0), _hydro("citrus", 27.0)]        # both comfortable
    sol = zs.solve(trees, baseline_minutes=40)
    assert sol.recommended_minutes < 40 and sol.delta_minutes < 0
    assert sol.total_penalty == pytest.approx(min(
        zs.evaluate(trees, zs.Candidate(sol.recommended_minutes),
                    rain_24h_mm=0, forecast_rain_24h_mm=0).total_penalty,
        sol.total_penalty,
    ))


def test_solver_resolves_heterogeneous_contention():
    # Mango (low over-water tolerance) sharing a zone with Jaboticaba (thirsty)
    trees = [_hydro("Kent mango", 27.0), _hydro("jaboticaba", 19.0)]
    sol = zs.solve(trees, baseline_minutes=30)
    posts = {o.species: o.post_vwc for o in sol.per_tree}
    # the winning strategy is a compromise: it doesn't drown the mango...
    assert posts["Kent mango"] <= zs.profile_for("mango").sat_vwc + 3
    # ...while giving the jaboticaba more than a minimal run would
    minimal = zs.evaluate(trees, zs.Candidate(7), rain_24h_mm=0, forecast_rain_24h_mm=0)
    assert sol.recommended_minutes > 7
    assert sol.candidates_considered >= 10          # coarse ToT + beam fine-search
    assert sol.thoughts and "penalty" in sol.thoughts[0]


def test_solver_skips_when_rain_is_coming():
    trees = [_hydro("mango", 24.0), _hydro("jaboticaba", 25.0)]
    sol = zs.solve(trees, baseline_minutes=30, forecast_rain_24h_mm=25.0)
    assert sol.recommended_minutes <= 10 and sol.delta_minutes < 0


# --------------------------------------------------------------------------
# 3. the HITL graph (LLM mocked)
# --------------------------------------------------------------------------

@contextmanager
def fake_llm(action: str, *, days=0, reason="deficit warrants it", summary="Because deficit.", down=False):
    structured = MagicMock()
    if down:
        structured.invoke = MagicMock(side_effect=RuntimeError("connection refused"))
    else:
        structured.invoke = MagicMock(
            return_value=_DecisionModel(action=action, days=days, reason=reason)
        )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)
    llm.invoke = MagicMock(return_value=MagicMock(content=summary))
    with patch("app.agent.irrigation_supervisor.ChatOllama", return_value=llm):
        yield


def _state(action_hint="dry"):
    return {
        "zone_id": "z-1",
        "for_date": TODAY.isoformat(),
        "baseline_minutes": 30,
        "deficit_score": 10.0 if action_hint == "dry" else -10.0,
        "rain_24h_mm": 0.0,
        "forecast_rain_24h_mm": 0.0,
        "forecast_available": True,
        "trees": [
            {"tree_id": 1, "species": "mango", "growth_stage": "fruit_set",
             "target_vwc": 30.0, "current_vwc": 18.0, "deficit_score": 10.0,
             "canopy_spread_m": 3.0, "estimated_gph": 8.0, "wetted_area_m2": None},
        ],
    }


def test_pass_no_action_finishes_without_an_interrupt():
    g = build_irrigation_graph(stack_settings(), MemorySaver())
    cfg = {"configurable": {"thread_id": "t-pass"}}
    with fake_llm("pass_no_action"):
        g.invoke(_state("wet"), cfg)
    snap = g.get_state(cfg)
    assert snap.next == ()                       # ran to END
    assert snap.values["decision"]["action"] == "pass_no_action"
    assert "result" not in snap.values           # execute_rachio_action never ran


def test_watering_action_interrupts_before_execute_with_a_summary():
    g = build_irrigation_graph(stack_settings(), MemorySaver())
    cfg = {"configurable": {"thread_id": "t-skip"}}
    with fake_llm("skip_schedule", days=2, summary="2-day skip proposed to save water."):
        g.invoke(_state("wet"), cfg)
    snap = g.get_state(cfg)
    assert snap.next == ("execute_rachio_action",)             # paused for HITL
    assert snap.values["decision"]["action"] == "skip_schedule"
    assert snap.values["solution"]["recommended_minutes"] > 0  # solver ran
    assert snap.values["summary"]
    assert "result" not in snap.values

    g.invoke(None, cfg)                                        # approve -> resume
    assert g.get_state(cfg).values["result"]["action"] == "skip_schedule"


def test_llm_down_defers_to_baseline():
    g = build_irrigation_graph(stack_settings(), MemorySaver())
    cfg = {"configurable": {"thread_id": "t-down"}}
    with fake_llm("", down=True):
        g.invoke(_state("dry"), cfg)
    snap = g.get_state(cfg)
    assert snap.values["decision"]["action"] == "pass_no_action"
    assert snap.values["llm_available"] is False


# --------------------------------------------------------------------------
# 4. supervisor service - run / approve / reject (DB + MemorySaver graph)
# --------------------------------------------------------------------------

def _run(body, *, llm_action="skip_schedule", auto_skip=False):
    settings = stack_settings()

    async def _wrap():
        try:
            async with db.connection(settings) as conn:
                trees = TreeRepository(conn)
                sensors = MoistureSensorService(MoistureSensorRepository(conn), trees)
                water = WaterBalanceService(sensors, trees, settings)
                cfg_repo = IrrigationConfigRepository(conn)
                prop_repo = IrrigationProposalRepository(conn)
                graph = build_irrigation_graph(settings, MemorySaver())
                svc = IrrigationSupervisorService(
                    water, trees, cfg_repo, prop_repo, graph, settings
                )
                cfg_svc = IrrigationConfigService(cfg_repo, trees, prop_repo)
                if auto_skip:
                    await cfg_repo.update_supervisor({"auto_approve_skips": True})
                with patch("app.irrigation.weather.forecast",
                           new=_amock(_forecast(0.0))), fake_llm(llm_action):
                    return await body(conn, trees, sensors, svc, cfg_svc)
        finally:
            await db.dispose_all()

    return asyncio.run(_wrap())


def _amock(value):
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)


def test_run_produces_a_pending_proposal_then_approve_executes():
    async def body(conn, trees, sensors, svc, cfg_svc):
        tid = (await trees.create({
            "species": "jaboticaba", "variety": "Sabara", "zone_id": "z-1",
            "canopy_spread_m": 2.5, "estimated_gph": 10.0,
        }))["tree_id"]
        await sensors.create(MoistureSensorCreate(id="s1", tree_id=tid))
        hardware.set_moisture("s1", 12.0)

        run = await svc.run(on_date=TODAY)
        assert len(run.proposals) == 1
        p = run.proposals[0]
        assert p.status == "pending" and p.action == "skip_schedule"
        assert p.summary and p.solution is not None and p.decision is not None

        approved = await svc.approve(p.thread_id)
        assert approved.status == "executed"
        assert approved.result["action"] == "skip_schedule" and approved.result["dry_run"]

        # re-approving a resolved proposal is rejected
        with pytest.raises(Exception):
            await svc.approve(p.thread_id)

    _run(body)


def test_reject_leaves_the_action_unexecuted():
    async def body(conn, trees, sensors, svc, cfg_svc):
        await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-1"})
        run = await svc.run(on_date=TODAY)
        p = run.proposals[0]
        rejected = await svc.reject(p.thread_id)
        assert rejected.status == "rejected" and rejected.result is None
        assert [x.status for x in await svc.list_proposals(status="rejected")] == ["rejected"]

    _run(body)


def test_pass_no_action_is_auto_recorded():
    async def body(conn, trees, sensors, svc, cfg_svc):
        await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-1"})
        run = await svc.run(on_date=TODAY)
        assert run.proposals[0].status == "no_action"

    _run(body, llm_action="pass_no_action")


def test_auto_approve_skips_executes_without_hitl():
    async def body(conn, trees, sensors, svc, cfg_svc):
        await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-1"})
        run = await svc.run(on_date=TODAY)
        assert run.proposals[0].status == "executed"

    _run(body, llm_action="skip_schedule", auto_skip=True)


def test_config_overview_and_updates():
    async def body(conn, trees, sensors, svc, cfg_svc):
        await trees.create({"species": "mango", "variety": "Kent", "zone_id": "z-a"})
        await trees.create({"species": "citrus", "variety": "Meyer", "zone_id": "z-b"})

        ov = await cfg_svc.overview()
        assert {z.zone_id for z in ov.zones} == {"z-a", "z-b"}
        assert all(z.baseline_minutes == 20 for z in ov.zones)   # defaults

        z = await cfg_svc.update_zone("z-a", ZoneConfigUpdate(baseline_minutes=45, supervised=False))
        assert z.baseline_minutes == 45 and z.supervised is False

        s = await cfg_svc.update_supervisor(SupervisorConfigUpdate(auto_approve_skips=True))
        assert s.auto_approve_skips is True

        # an unsupervised zone is skipped by run()
        # (mock LLM would pass anyway, but z-a must not appear)
        with patch("app.irrigation.weather.forecast", new=_amock(_forecast(0.0))), fake_llm("pass_no_action"):
            run = await (
                IrrigationSupervisorService(
                    svc._water, trees, svc._config, svc._proposals, svc._graph, svc._settings
                ).run(on_date=TODAY)
            )
        assert {p.zone_id for p in run.proposals} == {"z-b"}

    _run(body)


# --------------------------------------------------------------------------
# 5. HTTP surface
# --------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_irrigation_http_overview_and_config(client):
    client.post("/api/v1/trees", json={"species": "mango", "variety": "Kent", "zone_id": "z-1"})
    ov = client.get("/api/v1/irrigation/overview").json()
    assert ov["zones"][0]["zone_id"] == "z-1"
    assert ov["supervisor"]["supervisor_frequency_hours"] == 24

    r = client.put("/api/v1/irrigation/config/zones/z-1", json={"baseline_minutes": 35})
    assert r.status_code == 200 and r.json()["baseline_minutes"] == 35
    r = client.put("/api/v1/irrigation/config/supervisor", json={"auto_approve_skips": True})
    assert r.json()["auto_approve_skips"] is True


# --------------------------------------------------------------------------
# 6. opt-in real-LLM smoke
# --------------------------------------------------------------------------

def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="Ollama not reachable")
def test_real_llm_graph_end_to_end():
    g = build_irrigation_graph(
        stack_settings(ollama_base_url="http://127.0.0.1:11434"), MemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t-real"}}
    state = _state("wet")
    state["deficit_score"] = -14.0
    state["forecast_rain_24h_mm"] = 20.0
    g.invoke(state, cfg)
    snap = g.get_state(cfg)
    assert snap.values["decision"]["action"] in {
        "skip_schedule", "pass_no_action", "adjust_duration"
    }
    if snap.next:
        assert snap.values["summary"]
