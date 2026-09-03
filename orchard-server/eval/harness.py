"""Stack setup + the two run drivers (chat turn / schedule negotiation).

Disposable slice of the same containers the app and tests use:
``orchard_eval`` Postgres DB + ``orchard_knowledge_eval`` Chroma collection.
Provisioned once, truncated between scenarios. Deliberately does **not**
import ``tests.conftest`` - that module force-points Ollama at an unreachable
port on import, and the eval needs the real daemon.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import asyncpg
from sqlalchemy import text

from app.agent.checkpointer import (
    close_checkpointers,
    ensure_foreman_graph,
    ensure_irrigation_graph,
)
from app.agent.graph import build_graph
from app.config import Settings, get_settings
from app.core import db
from app.irrigation import hardware, weather
from app.irrigation.sensors import MoistureSensorService
from app.rag.vector_store import get_vector_store
from app.repositories.irrigation_config_repository import IrrigationConfigRepository
from app.repositories.irrigation_proposal_repository import IrrigationProposalRepository
from app.repositories.moisture_sensor_repository import MoistureSensorRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.chat import ChatMessageIn
from app.schemas.irrigation import DailyForecast, WeatherForecast
from app.services.foreman_service import ForemanService
from app.services.irrigation_service import IrrigationSupervisorService
from app.services.source_service import SourceService
from app.services.task_service import TaskService
from app.services.water_balance import WaterBalanceService

EVAL_DB = "orchard_eval"
EVAL_COLLECTION = "orchard_knowledge_eval"
REAL_OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

_INIT_SQL = Path(__file__).resolve().parent.parent / "docker" / "postgres" / "init.sql"


def eval_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "postgres_db": EVAL_DB,
        "chroma_collection": EVAL_COLLECTION,
        "ollama_base_url": REAL_OLLAMA,
    }
    base.update(overrides)
    return Settings(**base)


def _admin_dsn(dbname: str) -> str:
    s = get_settings()
    return (
        f"postgresql://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/{dbname}"
    )


async def provision() -> None:
    """Create ``orchard_eval`` if missing and (re)apply the schema. Idempotent."""
    admin = await asyncpg.connect(_admin_dsn(get_settings().postgres_db))
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", EVAL_DB
        )
        if not exists:
            await admin.execute(f'CREATE DATABASE "{EVAL_DB}"')
    finally:
        await admin.close()

    from app.core.db import _STARTUP_DDL

    conn = await asyncpg.connect(_admin_dsn(EVAL_DB))
    try:
        await conn.execute(_INIT_SQL.read_text(encoding="utf-8"))
        for stmt in _STARTUP_DDL:
            await conn.execute(stmt)
    finally:
        await conn.close()


_RESET_TABLES = (
    "source_chunks", "tree_sources", "task", "task_templates",
    "moisture_sensor", "rainfall_forecast_log",
    "irrigation_zone_config", "irrigation_proposal", "irrigation_config",
    "sources", "tree",
    "chat_message", "conversation",
    "checkpoint_writes", "checkpoint_blobs", "checkpoints",
)


async def reset(settings: Settings) -> None:
    conn = await asyncpg.connect(_admin_dsn(EVAL_DB))
    try:
        present = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        targets = [t for t in _RESET_TABLES if t in present]
        if targets:
            await conn.execute(f"TRUNCATE {', '.join(targets)} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    try:
        get_vector_store(settings).clear()
    except Exception:  # noqa: BLE001
        pass
    hardware.reset()       # stub moisture / rain-bucket overrides
    weather.reset()        # forecast cache + eval override


def ollama_up() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{REAL_OLLAMA}/api/version", timeout=3):
            return True
    except Exception:  # noqa: BLE001
        return False


async def teardown() -> None:
    await close_checkpointers()
    await db.dispose_all()


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

async def seed(settings: Settings, spec: dict[str, Any]) -> dict[str, int]:
    """Create trees / tasks / sources for one scenario (committed).

    Returns ``{action_type: task_id}`` for the tasks it created, so a scenario
    can refer to tasks by name and the grader can resolve ids.
    """
    from datetime import date, datetime, timedelta, timezone

    task_ids: dict[str, int] = {}
    async with db.connection(settings) as conn:
        trees = TreeRepository(conn)
        tasks = TaskRepository(conn)
        probes = MoistureSensorRepository(conn)
        irr_cfg = IrrigationConfigRepository(conn)
        sources = SourceService(
            SourceRepository(conn), trees, get_vector_store(settings), settings
        )

        default_tree_id: int | None = None
        for t in spec.get("trees", []):
            row = await trees.create(
                {
                    "species": t.get("species", "mango"),
                    "variety": t.get("variety", "Kent"),
                    "zone_id": t.get("zone_id"),
                    "height_m": t.get("height_m"),
                    "canopy_spread_m": t.get("canopy_spread_m"),
                    "estimated_gph": t.get("estimated_gph"),
                    "wetted_area_m2": t.get("wetted_area_m2"),
                }
            )
            default_tree_id = row["tree_id"]
            if t.get("current_vwc") is not None:
                sid = f"eval-s{row['tree_id']}"
                await probes.create({"id": sid, "label": "eval", "tree_id": row["tree_id"]})
                hardware.set_moisture(sid, float(t["current_vwc"]))
        if spec.get("tasks") and default_tree_id is None:
            default_tree_id = (await trees.create({"species": "mango", "variety": "Kent"}))["tree_id"]

        for k in range(spec.get("n_tasks", 0)):
            row = await tasks.create(
                {
                    "tree_id": default_tree_id
                    or (await trees.create({"species": "mango", "variety": "Kent"}))["tree_id"],
                    "action_type": f"task {k + 1}",
                    "status": "pending",
                    "priority_score": 1.0,
                    "estimated_minutes": 15,
                    "required_resources": [],
                }
            )
            default_tree_id = row["tree_id"]
            task_ids[f"task {k + 1}"] = row["id"]

        for spec_task in spec.get("tasks", []):
            scheduled = None
            if "days_old" in spec_task:
                scheduled = datetime.now(timezone.utc) - timedelta(days=spec_task["days_old"])
            row = await tasks.create(
                {
                    "tree_id": spec_task.get("tree_id", default_tree_id),
                    "action_type": spec_task["action_type"],
                    "status": "pending",
                    "priority_score": float(spec_task.get("priority_score", 1.0)),
                    "estimated_minutes": spec_task.get("estimated_minutes"),
                    "required_resources": spec_task.get("required_resources", []),
                    "scheduled_date": scheduled,
                }
            )
            task_ids[spec_task["action_type"]] = row["id"]

        for s in spec.get("sources", []):
            await sources.ingest_text(s["name"], s["text"])

        # -- irrigation scenario setup -----------------------------------
        zone = spec.get("zone")
        if zone:
            await irr_cfg.upsert_zone(
                zone["zone_id"],
                {
                    k: zone[k]
                    for k in ("baseline_minutes", "baseline_frequency_days", "supervised")
                    if k in zone
                },
            )
        if "auto_approve_skips" in spec:
            await irr_cfg.update_supervisor(
                {"auto_approve_skips": bool(spec["auto_approve_skips"])}
            )

    if "rain_bucket_mm" in spec:
        hardware.set_rain_bucket_24h(float(spec["rain_bucket_mm"]))

    fc = spec.get("forecast")
    if fc is not None:
        if fc.get("available") is False:
            weather.set_forecast(
                WeatherForecast(available=False, error="eval: forecast unavailable")
            )
        else:
            on = date.fromisoformat(spec["on_date"])
            weather.set_forecast(
                WeatherForecast(
                    available=True,
                    fetched_at=datetime.now(timezone.utc),
                    source="eval",
                    daily=[
                        DailyForecast(
                            date=on,
                            qpf_mm=float(fc.get("qpf_mm", 0.0)),
                            pop_pct=fc.get("pop_pct"),
                        )
                    ],
                )
            )

    return task_ids


# --------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------

async def run_chat(settings: Settings, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Run one chat turn through the real Orchestrator graph.

    Mirrors ``ChatService.stream_reply`` but returns the raw end state so the
    grader can see the route, not just the streamed events.
    """
    async with db.connection(settings) as conn:
        sources = SourceService(
            SourceRepository(conn), TreeRepository(conn), get_vector_store(settings), settings
        )
        tasks = TaskService(TaskRepository(conn), TreeRepository(conn))
        graph = build_graph(sources, tasks, settings)
        result = await graph.ainvoke(
            {"messages": [ChatMessageIn(role=m["role"], content=m["content"]) for m in messages]}
        )
    return {
        "route": result.get("route"),
        "answer": result.get("answer", "") or "",
        "tool_calls": result.get("tool_calls", []) or [],
        "redirect": result.get("redirect"),
        "task_ids": result.get("task_ids", []) or [],
        # Agronomist retrieval provenance (only the "agronomy" route sets it) -
        # used by eval/grounding.py's advisory groundedness check.
        "retrieved": result.get("retrieved") or [],
    }


async def run_schedule(
    settings: Settings, row: dict[str, Any], task_ids: dict[str, int]
) -> dict[str, Any]:
    """Drive the Foreman negotiation for one scenario.

    ``row["start"]`` -> ``ForemanService.start``; each ``row["resumes"]`` entry
    carries exactly one of ``available_minutes`` / ``have_resources`` /
    ``report`` / ``complete`` (the last two resolve action-type names to ids).
    Returns every ``ScheduleState`` seen plus the final task statuses.
    """
    graph = await ensure_foreman_graph(settings)
    states: list[Any] = []
    reports: list[tuple[list[int], str]] = []

    async with db.connection(settings) as conn:
        fs = ForemanService(
            TaskService(TaskRepository(conn), TreeRepository(conn)), graph
        )
        state = await fs.start((row.get("start") or {}).get("available_minutes"))
        states.append(state)

        for step in row.get("resumes", []):
            if "available_minutes" in step:
                state = await fs.resume(state.thread_id, step["available_minutes"])
                states.append(state)
            elif "have_resources" in step:
                state = await fs.resume(state.thread_id, step["have_resources"])
                states.append(state)
            elif "report" in step:
                reports.append(await fs.report(step["report"]))
            elif "report_task" in step:
                tid = task_ids[step["report_task"]]
                reports.append(await fs.report(f"finished task {tid}"))
            elif "complete" in step:
                ids = [task_ids[a] for a in step["complete"]]
                marked = await fs.complete(ids)
                reports.append(([t.id for t in marked], "complete"))

        final = {
            r["action_type"]: r["status"]
            for r in (await conn.execute(text("SELECT action_type, status FROM task"))).mappings()
        }

    return {"states": states, "reports": reports, "final_status": final}


async def run_irrigation(settings: Settings, row: dict[str, Any]) -> dict[str, Any]:
    """Drive the real irrigation supervisor for one zone.

    ``seed`` has already created the zone config, trees, sensors, and pinned the
    stub moisture / rain-bucket / NWS forecast. Runs
    ``IrrigationSupervisorService.run`` and returns the resulting proposal (the
    HITL queue row) plus the pre-LLM zone water balance for observability.
    """
    from datetime import date

    seed = row.get("seed", {})
    zone_id = seed["zone"]["zone_id"]
    on_date = date.fromisoformat(seed["on_date"]) if seed.get("on_date") else None

    graph = await ensure_irrigation_graph(settings)
    async with db.connection(settings) as conn:
        trees = TreeRepository(conn)
        sensors = MoistureSensorService(MoistureSensorRepository(conn), trees)
        water = WaterBalanceService(sensors, trees, settings)
        cfg = IrrigationConfigRepository(conn)
        proposals = IrrigationProposalRepository(conn)
        svc = IrrigationSupervisorService(
            water, trees, cfg, proposals, graph, settings
        )

        balance = await water.for_zone(zone_id, on_date=on_date)
        result = await svc.run(zone_ids=[zone_id], on_date=on_date)

    proposal = result.proposals[0] if result.proposals else None
    return {
        "proposal": proposal.model_dump(mode="json") if proposal else None,
        "balance": balance.model_dump(mode="json"),
    }
