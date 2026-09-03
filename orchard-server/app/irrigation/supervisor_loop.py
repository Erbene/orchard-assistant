"""In-process asyncio supervisor loop.

While the API process is running, ticks on ``supervisor_frequency_hours`` from
the DB and calls ``IrrigationSupervisorService.run`` — the same path as the
manual **Run Supervision Task** button. Disabled when ``ORCHARD_SUPERVISOR_LOOP``
is ``0`` / ``false`` / ``off`` (tests set this in ``conftest.py``).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from ..agent.checkpointer import ensure_irrigation_graph
from ..config import Settings
from ..core import db
from ..core.logging import get_logger
from ..irrigation.sensors import MoistureSensorService
from ..repositories.irrigation_config_repository import IrrigationConfigRepository
from ..repositories.irrigation_proposal_repository import IrrigationProposalRepository
from ..repositories.moisture_sensor_repository import MoistureSensorRepository
from ..repositories.tree_repository import TreeRepository
from ..services.irrigation_service import IrrigationSupervisorService
from ..services.water_balance import WaterBalanceService

_log = get_logger("irrigation.supervisor.loop")


def seconds_until_due(
    last_run: datetime | None, frequency_hours: int, now: datetime
) -> float:
    """Seconds until the next supervisor run is due (0 = due now)."""
    frequency_hours = max(1, frequency_hours)
    if last_run is None:
        return 0.0
    due_at = last_run + timedelta(hours=frequency_hours)
    return max(0.0, (due_at - now).total_seconds())


def is_due(last_run: datetime | None, frequency_hours: int, now: datetime) -> bool:
    return seconds_until_due(last_run, frequency_hours, now) == 0.0


def _loop_enabled() -> bool:
    raw = os.environ.get("ORCHARD_SUPERVISOR_LOOP")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "off"}


class SupervisorLoop:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_run: datetime | None = None
        self._in_flight = False

    async def run_forever(self) -> None:
        _log.info("irrigation.supervisor.loop.start")
        try:
            while True:
                await self._tick()
        except asyncio.CancelledError:
            _log.info("irrigation.supervisor.loop.stop")
            raise

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            frequency_hours = await self._read_frequency_hours()
            due = is_due(self._last_run, frequency_hours, now)
            wait = seconds_until_due(self._last_run, frequency_hours, now)
            _log.info(
                "irrigation.supervisor.loop.tick",
                due=due,
                seconds_until_due=wait,
                frequency_hours=frequency_hours,
            )

            if due:
                if self._in_flight:
                    _log.info("irrigation.supervisor.loop.busy")
                else:
                    self._in_flight = True
                    try:
                        await self._run_supervisor()
                        self._last_run = now
                        _log.info("irrigation.supervisor.loop.ran")
                    finally:
                        self._in_flight = False

            sleep_for = min(
                seconds_until_due(
                    self._last_run,
                    frequency_hours,
                    datetime.now(timezone.utc),
                ),
                60.0,
            )
            if sleep_for <= 0:
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(sleep_for)
        except Exception:  # noqa: BLE001 - loop must survive tick failures
            _log.warning("irrigation.supervisor.loop.error", exc_info=True)
            await asyncio.sleep(60.0)

    async def _read_frequency_hours(self) -> int:
        async with db.connection(self._settings) as conn:
            repo = IrrigationConfigRepository(conn)
            row = await repo.get_supervisor()
            return int(row["supervisor_frequency_hours"])

    async def _run_supervisor(self) -> None:
        settings = self._settings
        graph = await ensure_irrigation_graph(settings)
        async with db.connection(settings) as conn:
            trees = TreeRepository(conn)
            sensors = MoistureSensorService(MoistureSensorRepository(conn), trees)
            water = WaterBalanceService(sensors, trees, settings)
            cfg_repo = IrrigationConfigRepository(conn)
            prop_repo = IrrigationProposalRepository(conn)
            svc = IrrigationSupervisorService(
                water, trees, cfg_repo, prop_repo, graph, settings
            )
            await svc.run()


async def start_supervisor_loop(settings: Settings) -> asyncio.Task[None] | None:
    if not _loop_enabled():
        return None
    loop = SupervisorLoop(settings)
    return asyncio.create_task(loop.run_forever(), name="irrigation-supervisor-loop")


async def stop_supervisor_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
