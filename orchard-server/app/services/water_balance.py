"""Deterministic sensor-fusion pre-processing for the irrigation supervisor.

Computes a **Water Deficit Score** per tree / per zone from the Phase 1 stub
hardware + the real NWS forecast, before any LLM is involved:

    deficit_score = (target_vwc - current_vwc) - rain_24h_mm - forecast_rain_24h_mm

Higher = drier / more likely to need water. ``target_vwc`` is growth-stage
aware (``app.irrigation.phenology``); the moisture term is VWC percentage
points and the rainfall terms are mm - this is a monotonic heuristic score,
not a physical quantity, so every component is kept on the result.
"""
from __future__ import annotations

from datetime import date

from ..config import Settings
from ..irrigation import hardware, weather
from ..irrigation.phenology import growth_stage, target_vwc_for_stage
from ..irrigation.sensors import MoistureSensorService
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import WaterBalance, WeatherForecast, ZoneWaterBalance
from .exceptions import NotFoundError


def _qpf_for(forecast: WeatherForecast, day: date) -> float:
    return next((d.qpf_mm for d in forecast.daily if d.date == day), 0.0)


class WaterBalanceService:
    def __init__(
        self,
        sensors: MoistureSensorService,
        trees: TreeRepository,
        settings: Settings,
    ) -> None:
        self._sensors = sensors
        self._trees = trees
        self._settings = settings

    async def for_tree(
        self,
        tree_id: int,
        *,
        on_date: date | None = None,
        rain_24h_mm: float | None = None,
        forecast_rain_24h_mm: float | None = None,
    ) -> WaterBalance:
        on_date = on_date or date.today()
        tree = await self._trees.get(tree_id)
        if tree is None:
            raise NotFoundError(f"tree {tree_id} not found")

        stage = growth_stage(
            tree["species"], on_date, hemisphere=self._settings.hemisphere
        )
        target = target_vwc_for_stage(
            stage, fallback=self._settings.irrigation_target_vwc
        )

        moisture = await self._sensors.tree_moisture(tree_id)
        current = moisture.mean_vwc_pct

        rain = (
            hardware.get_rain_bucket_24h() if rain_24h_mm is None else float(rain_24h_mm)
        )
        fc_mm = (
            await self._forecast_rain_mm(on_date)
            if forecast_rain_24h_mm is None
            else float(forecast_rain_24h_mm)
        )

        gap = round(target - current, 1) if current is not None else 0.0
        deficit = round(gap - rain - fc_mm, 1)

        notes: list[str] = []
        if current is None:
            notes.append("no moisture sensor - deficit reflects rainfall only")
        if moisture.resolved_via == "zone":
            notes.append("moisture read from a zone-level sensor, not this tree")

        return WaterBalance(
            for_date=on_date,
            tree_id=tree_id,
            zone_id=tree.get("zone_id"),
            growth_stage=stage,
            target_vwc=target,
            current_vwc=current,
            moisture_gap=gap,
            rain_24h_mm=rain,
            forecast_rain_24h_mm=fc_mm,
            deficit_score=deficit,
            moisture_resolved_via=moisture.resolved_via,
            notes=notes,
        )

    async def for_zone(
        self, zone_id: str, *, on_date: date | None = None
    ) -> ZoneWaterBalance:
        on_date = on_date or date.today()
        forecast = await weather.forecast(self._settings)
        rain = hardware.get_rain_bucket_24h()
        fc_mm = _qpf_for(forecast, on_date)

        rows = await self._trees.list(zone_id=zone_id)
        trees = [
            await self.for_tree(
                r["tree_id"],
                on_date=on_date,
                rain_24h_mm=rain,
                forecast_rain_24h_mm=fc_mm,
            )
            for r in rows
        ]

        # protect the driest tree in the zone
        deficit = max(
            (t.deficit_score for t in trees),
            default=round(self._settings.irrigation_target_vwc - rain - fc_mm, 1),
        )
        return ZoneWaterBalance(
            for_date=on_date,
            zone_id=zone_id,
            trees=trees,
            deficit_score=deficit,
            rain_24h_mm=rain,
            forecast_rain_24h_mm=fc_mm,
            forecast_available=forecast.available,
        )

    # -- helpers -----------------------------------------------

    async def _forecast_rain_mm(self, on_date: date) -> float:
        return _qpf_for(await weather.forecast(self._settings), on_date)
