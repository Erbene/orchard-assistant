"""The rainfall forecast-accuracy log.

``roll(today)`` is the once-a-day job (Phase 2 wires the trigger):
- writes the 1/3/5-day-ahead QPF for ``today + {1,3,5}`` into
  ``rainfall_forecast_log``,
- backfills yesterday's actuals (observed NWS precip + the rain-bucket read).

``accuracy(since)`` scores forecast vs. actual per horizon (MAE, bias,
rain/no-rain hit rate).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..config import Settings
from ..core.logging import get_logger
from ..repositories.rainfall_forecast_repository import RainfallForecastRepository
from ..schemas.irrigation import (
    ForecastAccuracy,
    HorizonAccuracy,
    RainfallLogRow,
    RollResult,
)
from . import hardware, weather

_log = get_logger("app.irrigation.forecast_log")

_HORIZONS = (1, 3, 5)
_RAIN_THRESHOLD_MM = 1.0        # "did it rain?" cut for the hit-rate metric
_DEFAULT_LOOKBACK_DAYS = 90


class RainfallForecastService:
    def __init__(
        self, log: RainfallForecastRepository, settings: Settings
    ) -> None:
        self._log = log
        self._settings = settings

    async def roll(self, today: date | None = None) -> RollResult:
        today = today or datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)

        fc = await weather.forecast(self._settings)
        qpf_by_date = {d.date: d.qpf_mm for d in fc.daily}

        forecasts_written: dict[str, float | None] = {}
        for h in _HORIZONS:
            target = today + timedelta(days=h)
            mm = qpf_by_date.get(target)
            if mm is None:
                continue  # forecast doesn't reach this far
            await self._log.upsert(
                target,
                {f"forecast_{h}d_mm": mm, f"forecast_{h}d_at": now},
            )
            forecasts_written[f"{h}d"] = mm

        yesterday = today - timedelta(days=1)
        nws = await weather.observed_rain_mm(self._settings, yesterday)
        gauge = hardware.get_rain_bucket_24h()
        actual_fields: dict[str, object] = {"actual_gauge_mm": gauge, "actuals_at": now}
        if nws is not None:
            actual_fields["actual_nws_mm"] = nws
        await self._log.upsert(yesterday, actual_fields)

        _log.info(
            "irrigation.forecast.roll",
            for_date=str(today),
            forecast_available=fc.available,
            horizons=list(forecasts_written),
            actual_nws=nws,
        )
        return RollResult(
            ran_for=today,
            forecasts_written=forecasts_written,
            actuals_written={"nws": nws, "gauge": gauge},
            forecast_available=fc.available,
            note=fc.error,
        )

    async def rows(self, since: date | None = None, until: date | None = None) -> list[RainfallLogRow]:
        until = until or datetime.now(timezone.utc).date()
        since = since or (until - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
        return [
            RainfallLogRow.model_validate(r)
            for r in await self._log.range(since, until)
        ]

    async def accuracy(self, since: date | None = None) -> ForecastAccuracy:
        rows = await self.rows(since=since)
        horizons: list[HorizonAccuracy] = []
        scored_dates: set[date] = set()

        for h in _HORIZONS:
            key = f"forecast_{h}d_mm"
            pairs = [
                (getattr(r, key), r.actual_nws_mm)
                for r in rows
                if getattr(r, key) is not None and r.actual_nws_mm is not None
            ]
            if not pairs:
                horizons.append(HorizonAccuracy(horizon=f"{h}d", n=0))
                continue
            for r in rows:
                if getattr(r, key) is not None and r.actual_nws_mm is not None:
                    scored_dates.add(r.for_date)
            errs = [f - a for f, a in pairs]
            hits = [
                (f >= _RAIN_THRESHOLD_MM) == (a >= _RAIN_THRESHOLD_MM)
                for f, a in pairs
            ]
            horizons.append(
                HorizonAccuracy(
                    horizon=f"{h}d",
                    n=len(pairs),
                    mae_mm=round(sum(abs(e) for e in errs) / len(errs), 2),
                    bias_mm=round(sum(errs) / len(errs), 2),
                    hit_rate=round(sum(hits) / len(hits), 3),
                )
            )

        return ForecastAccuracy(
            since=since,
            horizons=horizons,
            rows_scored=len(scored_dates),
        )
