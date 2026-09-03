"""Stubbed hardware reads for the deliberation engine, built before the
physical sensors exist.

- ``get_moisture(sensor_id)`` -> a plausible, **stable-per-sensor** volumetric
  water content (VWC) %. Two sensors read differently; the same sensor reads
  the same across a process (reproducible), with slow seasonal drift so a
  moisture *trend* is still observable.
- ``get_rain_bucket_24h()`` -> a 24h rain-gauge total in mm (0.0 by default).

An in-process override registry lets tests / the Phase 2 harness pin exact
readings: ``set_moisture("s1", 12.0)`` / ``set_rain_bucket_24h(4.0)`` /
``reset()``.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date

# VWC band for the deterministic stub. Wilting point ~10-15%, field capacity
# ~30-40% for most soils - keep the stub inside the decision-relevant range.
_VWC_MIN = 14.0
_VWC_SPAN = 20.0            # -> 14.0 .. 34.0
_DRIFT_AMPLITUDE = 3.0      # +/- % seasonal drift

_moisture_overrides: dict[str, float] = {}
_rain_override: float | None = None


def _seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def get_moisture(sensor_id: str) -> float:
    """Current VWC % for a sensor. Deterministic per id, with slow seasonal
    drift; overridable via :func:`set_moisture`."""
    if sensor_id in _moisture_overrides:
        return _moisture_overrides[sensor_id]

    base = _VWC_MIN + (_seed(sensor_id) % 1000) / 1000.0 * _VWC_SPAN
    doy = date.today().timetuple().tm_yday
    phase = (_seed("phase:" + sensor_id) % 360) * math.pi / 180.0
    drift = _DRIFT_AMPLITUDE * math.sin(2 * math.pi * doy / 365.0 + phase)
    return round(max(0.0, min(100.0, base + drift)), 1)


def get_rain_bucket_24h() -> float:
    """Rain-gauge 24h total in mm. Stub returns 0.0 unless overridden."""
    return _rain_override if _rain_override is not None else 0.0


# -- override registry (tests / dev / Phase 2 harness) --------------

def set_moisture(sensor_id: str, vwc_pct: float) -> None:
    _moisture_overrides[sensor_id] = float(vwc_pct)


def set_rain_bucket_24h(mm: float | None) -> None:
    global _rain_override
    _rain_override = None if mm is None else float(mm)


def reset() -> None:
    _moisture_overrides.clear()
    set_rain_bucket_24h(None)


__all__ = [
    "get_moisture",
    "get_rain_bucket_24h",
    "set_moisture",
    "set_rain_bucket_24h",
    "reset",
]
