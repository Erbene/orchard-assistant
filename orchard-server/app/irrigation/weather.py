"""Real NWS (api.weather.gov) client for the Irrigation workflow.

- ``forecast(settings)`` -> the next ~7 days of **quantitative** precipitation
  (mm), probability of precip, and temps, from the NWS *gridpoint* product
  (the plain ``/forecast`` product has no mm amounts).
- ``observed_rain_mm(settings, day)`` -> observed rainfall total (mm) for a
  calendar day, summed from the nearest station's hourly/6-hourly obs. NWS obs
  precip is frequently null -> returns ``None`` when nothing usable is found.
- ``get_weather_forecast()`` -> the prompt's no-arg ``-> dict`` signature.

NWS requires a ``User-Agent`` header (``settings.nws_user_agent``). The
``/points`` -> gridpoint lookup is cached forever (stable for a lat/lon); the
forecast itself is cached ~1h.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import Settings, get_settings
from ..core.logging import get_logger
from ..schemas.irrigation import DailyForecast, WeatherForecast

_log = get_logger("app.irrigation.weather")

_POINTS_TTL = None          # never expires
_FORECAST_TTL = 3600.0      # seconds
_HTTP_TIMEOUT = 15.0

# keyed by "lat,lon"
_points_cache: dict[str, dict] = {}
_forecast_cache: dict[str, tuple[float, WeatherForecast]] = {}

# In-process override for tests / the eval harness - when set, `forecast()`
# returns it verbatim and never touches the network (mirrors hardware.py).
_forecast_override: WeatherForecast | None = None


def set_forecast(fc: WeatherForecast | None) -> None:
    global _forecast_override
    _forecast_override = fc


def forecast_is_overridden() -> bool:
    return _forecast_override is not None


def clear_cache() -> None:
    _points_cache.clear()
    _forecast_cache.clear()


def reset() -> None:
    """Drop caches and any test override."""
    clear_cache()
    set_forecast(None)


def _key(settings: Settings) -> str:
    return f"{settings.orchard_lat},{settings.orchard_lon}"


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.nws_user_agent,
        "Accept": "application/geo+json",
    }


_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?")


def _parse_interval(valid_time: str) -> tuple[datetime, timedelta]:
    """NWS ``validTime`` is ``<iso-start>/<iso8601-duration>``."""
    start_s, _, dur_s = valid_time.partition("/")
    start = datetime.fromisoformat(start_s)
    m = _DURATION.fullmatch(dur_s) if dur_s else None
    days = int(m.group(1)) if m and m.group(1) else 0
    hours = int(m.group(2)) if m and m.group(2) else 0
    mins = int(m.group(3)) if m and m.group(3) else 0
    return start, timedelta(days=days, hours=hours, minutes=mins) or timedelta(hours=1)


def _daily_from_series(
    qpf: list[dict], pop: list[dict], tmax: list[dict], tmin: list[dict]
) -> list[DailyForecast]:
    def by_day(values: list[dict], reduce: str) -> dict[date, float]:
        acc: dict[date, list[float]] = {}
        for entry in values or []:
            if entry.get("value") is None:
                continue
            start, _dur = _parse_interval(entry["validTime"])
            acc.setdefault(start.date(), []).append(float(entry["value"]))
        if reduce == "sum":
            return {d: round(sum(v), 2) for d, v in acc.items()}
        if reduce == "max":
            return {d: round(max(v), 1) for d, v in acc.items()}
        return {d: round(min(v), 1) for d, v in acc.items()}

    qpf_by = by_day(qpf, "sum")
    pop_by = by_day(pop, "max")
    tmax_by = by_day(tmax, "max")
    tmin_by = by_day(tmin, "min")

    days = sorted(set(qpf_by) | set(pop_by) | set(tmax_by) | set(tmin_by))
    return [
        DailyForecast(
            date=d,
            qpf_mm=qpf_by.get(d, 0.0),
            pop_pct=pop_by.get(d),
            temp_high_c=tmax_by.get(d),
            temp_low_c=tmin_by.get(d),
        )
        for d in days
    ]


async def _points(settings: Settings, client: httpx.AsyncClient) -> dict:
    key = _key(settings)
    if key in _points_cache:
        return _points_cache[key]
    resp = await client.get(
        f"{settings.nws_base_url}/points/{settings.orchard_lat},{settings.orchard_lon}"
    )
    resp.raise_for_status()
    props = resp.json()["properties"]
    _points_cache[key] = props
    return props


async def forecast(settings: Settings) -> WeatherForecast:
    """Next ~7 days of quantitative precip + PoP + temps from NWS."""
    if _forecast_override is not None:
        return _forecast_override
    if settings.orchard_lat is None or settings.orchard_lon is None:
        return WeatherForecast(available=False, error="ORCHARD_LAT / ORCHARD_LON not set")

    key = _key(settings)
    cached = _forecast_cache.get(key)
    if cached is not None and (time.monotonic() - cached[0]) < _FORECAST_TTL:
        return cached[1]

    try:
        async with httpx.AsyncClient(
            headers=_headers(settings), timeout=_HTTP_TIMEOUT
        ) as client:
            props = await _points(settings, client)
            grid_resp = await client.get(props["forecastGridData"])
            grid_resp.raise_for_status()
            g = grid_resp.json()["properties"]
            rel = props.get("relativeLocation", {}).get("properties", {})
    except Exception as exc:  # noqa: BLE001 - NWS is flaky; degrade, don't crash
        _log.warning("weather.forecast.failed", error=str(exc)[:200])
        return WeatherForecast(available=False, error=str(exc)[:200])

    daily = _daily_from_series(
        g.get("quantitativePrecipitation", {}).get("values", []),
        g.get("probabilityOfPrecipitation", {}).get("values", []),
        g.get("maxTemperature", {}).get("values", []),
        g.get("minTemperature", {}).get("values", []),
    )
    out = WeatherForecast(
        available=True,
        fetched_at=datetime.now(timezone.utc),
        location=(
            f"{rel.get('city')}, {rel.get('state')}"
            if rel.get("city")
            else _key(settings)
        ),
        daily=daily,
    )
    _forecast_cache[key] = (time.monotonic(), out)
    return out


async def observed_rain_mm(settings: Settings, day: date) -> float | None:
    """Observed rainfall total (mm) for ``day`` from the nearest NWS station.
    ``None`` when the station reported no usable precip data."""
    if settings.orchard_lat is None or settings.orchard_lon is None:
        return None

    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    try:
        async with httpx.AsyncClient(
            headers=_headers(settings), timeout=_HTTP_TIMEOUT
        ) as client:
            props = await _points(settings, client)
            st_resp = await client.get(props["observationStations"])
            st_resp.raise_for_status()
            stations = st_resp.json().get("features", [])
            if not stations:
                return None
            station_id = stations[0]["properties"]["stationIdentifier"]
            obs_resp = await client.get(
                f"{settings.nws_base_url}/stations/{station_id}/observations",
                params={
                    "start": start.isoformat().replace("+00:00", "Z"),
                    "end": end.isoformat().replace("+00:00", "Z"),
                },
            )
            obs_resp.raise_for_status()
            features = obs_resp.json().get("features", [])
    except Exception as exc:  # noqa: BLE001
        _log.warning("weather.observed.failed", day=str(day), error=str(exc)[:200])
        return None

    # prefer the 6-hour accumulators (fewer, non-overlapping); fall back to 1h.
    six = [
        f["properties"]["precipitationLast6Hours"].get("value")
        for f in features
        if f["properties"].get("precipitationLast6Hours")
    ]
    six = [v for v in six if v is not None]
    if six:
        return round(sum(six), 2)

    one = [
        f["properties"]["precipitationLastHour"].get("value")
        for f in features
        if f["properties"].get("precipitationLastHour")
    ]
    one = [v for v in one if v is not None]
    return round(sum(one), 2) if one else None


async def get_weather_forecast() -> dict:
    """The prompt's no-arg signature: current forecast as a plain dict."""
    return (await forecast(get_settings())).model_dump(mode="json")
