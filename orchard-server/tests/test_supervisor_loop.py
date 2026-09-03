"""Unit tests for the in-process irrigation supervisor loop."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.irrigation.supervisor_loop import (
    SupervisorLoop,
    is_due,
    seconds_until_due,
    start_supervisor_loop,
)
from conftest import stack_settings

UTC = timezone.utc
BASE = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def test_seconds_until_due_none_last_run_is_immediate():
    assert seconds_until_due(None, 24, BASE) == 0.0
    assert is_due(None, 24, BASE) is True


def test_seconds_until_due_one_hour_ago_not_due():
    last = BASE - timedelta(hours=1)
    assert seconds_until_due(last, 24, BASE) == 23 * 3600
    assert is_due(last, 24, BASE) is False


def test_seconds_until_due_twenty_five_hours_ago_is_due():
    last = BASE - timedelta(hours=25)
    assert seconds_until_due(last, 24, BASE) == 0.0
    assert is_due(last, 24, BASE) is True


def test_seconds_until_due_exactly_frequency_ago_is_due():
    last = BASE - timedelta(hours=24)
    assert seconds_until_due(last, 24, BASE) == 0.0
    assert is_due(last, 24, BASE) is True


def test_seconds_until_due_clamps_frequency_hours():
    last = BASE - timedelta(minutes=30)
    assert seconds_until_due(last, 0, BASE) == 30 * 60
    assert is_due(last, -5, BASE) is False


def test_tick_skips_when_in_flight():
    settings = stack_settings()
    loop = SupervisorLoop(settings)
    loop._in_flight = True

    async def _go():
        with patch.object(loop, "_read_frequency_hours", new=AsyncMock(return_value=24)):
            with patch.object(loop, "_run_supervisor", new=AsyncMock()) as run_mock:
                with patch("asyncio.sleep", new=AsyncMock()):
                    await loop._tick()
        run_mock.assert_not_called()

    asyncio.run(_go())


def test_tick_runs_when_due_and_not_busy():
    settings = stack_settings()
    loop = SupervisorLoop(settings)

    async def _go():
        with patch.object(loop, "_read_frequency_hours", new=AsyncMock(return_value=24)):
            with patch.object(loop, "_run_supervisor", new=AsyncMock()) as run_mock:
                with patch("asyncio.sleep", new=AsyncMock()):
                    await loop._tick()
        run_mock.assert_called_once()
        assert loop._last_run is not None

    asyncio.run(_go())


def test_start_supervisor_loop_disabled():
    settings = stack_settings()

    async def _go():
        with patch.dict(os.environ, {"ORCHARD_SUPERVISOR_LOOP": "0"}, clear=False):
            return await start_supervisor_loop(settings)

    assert asyncio.run(_go()) is None


def test_start_supervisor_loop_disabled_off():
    settings = stack_settings()

    async def _go():
        with patch.dict(os.environ, {"ORCHARD_SUPERVISOR_LOOP": "off"}, clear=False):
            return await start_supervisor_loop(settings)

    assert asyncio.run(_go()) is None


def test_start_supervisor_loop_enabled():
    settings = stack_settings()

    async def _go():
        with patch.dict(os.environ, {"ORCHARD_SUPERVISOR_LOOP": "1"}, clear=False):
            with patch.object(SupervisorLoop, "run_forever", new=AsyncMock()):
                task = await start_supervisor_loop(settings)
        assert task is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_go())
