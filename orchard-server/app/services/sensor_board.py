"""Irrigation Sensors tab: live supervisor inputs + demo-only pins.

The snapshot is what the supervisor actually consumes (stub moisture, rain
gauge, NWS QPF, Rachio last-watered, water-balance deficit). Demo mode can
pin those inputs in-process; production mode is read-only.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from ..config import Settings
from ..core.logging import get_logger
from ..irrigation import demo, hardware, weather
from ..irrigation.sensors import MoistureSensorService
from ..repositories.irrigation_config_repository import IrrigationConfigRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import (
    DailyForecast,
    MoistureOverride,
    MoistureSensorRead,
    SensorOverridesIn,
    SensorPinRead,
    SensorSnapshot,
    SensorTreeRead,
    SensorZoneRead,
    WeatherForecast,
)
from .exceptions import DomainValidationError, NotFoundError, RachioError, RachioNotConfigured
from .rachio import get_rachio_service
from .water_balance import WaterBalanceService, _qpf_for

_log = get_logger("app.irrigation.sensors")

_CLEAR_ALLOWED = frozenset(
    {"rain", "forecast", "for_date", "moisture", "last_watered", "all"}
)
_DEFAULT_BASELINE_MIN = 20


class SensorBoardService:
    def __init__(
        self,
        water: WaterBalanceService,
        trees: TreeRepository,
        sensors: MoistureSensorService,
        config: IrrigationConfigRepository,
        settings: Settings,
    ) -> None:
        self._water = water
        self._trees = trees
        self._sensors = sensors
        self._config = config
        self._settings = settings

    async def snapshot(self) -> SensorSnapshot:
        on_date = demo.overlay_on_date() or date.today()
        forecast = await weather.forecast(self._settings)
        rain = hardware.get_rain_bucket_24h()
        rain_over = hardware.rain_is_overridden()
        fc_over = weather.forecast_is_overridden()
        qpf = _qpf_for(forecast, on_date)

        zone_ids = await self._trees.distinct_zone_ids()
        zone_cfgs = await self._config.all_zones()
        zones: list[SensorZoneRead] = []
        for zone_id in zone_ids:
            zwb = await self._water.for_zone(zone_id, on_date=on_date)
            last, last_source = await self._last_watered(zone_id)
            trees_out: list[SensorTreeRead] = []
            for wb in zwb.trees:
                pins = await self._tree_pins(wb.tree_id)
                trees_out.append(
                    SensorTreeRead(
                        tree_id=wb.tree_id,
                        species=wb.species,
                        variety=wb.variety,
                        growth_stage=wb.growth_stage,
                        target_vwc=wb.target_vwc,
                        current_vwc=wb.current_vwc,
                        moisture_gap=wb.moisture_gap,
                        deficit_score=wb.deficit_score,
                        moisture_resolved_via=wb.moisture_resolved_via,
                        notes=wb.notes,
                        sensors=pins,
                    )
                )
            cfg = zone_cfgs.get(zone_id) or {}
            zones.append(
                SensorZoneRead(
                    zone_id=zone_id,
                    last_watered_date=last,
                    last_watered_source=last_source,
                    deficit_score=zwb.deficit_score,
                    baseline_minutes=cfg.get("baseline_minutes", _DEFAULT_BASELINE_MIN),
                    trees=trees_out,
                )
            )

        pins_active = bool(
            demo.active_scenario_id()
            or rain_over
            or fc_over
            or demo.overlay_on_date() is not None
            or any(p.overridden for z in zones for t in z.trees for p in t.sensors)
            or any(z.last_watered_source == "demo" for z in zones)
        )

        return SensorSnapshot(
            demo_enabled=self._settings.orchard_demo,
            for_date=on_date,
            rain_24h_mm=rain,
            rain_overridden=rain_over,
            rain_source="override" if rain_over else "stub",
            forecast_rain_24h_mm=qpf,
            forecast_available=forecast.available,
            forecast_overridden=fc_over,
            forecast_source=(
                "demo" if fc_over else ("nws" if forecast.available else "unavailable")
            ),
            forecast_error=forecast.error,
            active_scenario_id=demo.active_scenario_id(),
            pins_active=pins_active,
            zones=zones,
        )

    async def apply_overrides(self, payload: SensorOverridesIn) -> SensorSnapshot:
        unknown = [c for c in payload.clear if c not in _CLEAR_ALLOWED]
        if unknown:
            raise DomainValidationError("clear", f"unknown clear target(s): {unknown}")

        if "all" in payload.clear:
            demo.reset()
            return await self.snapshot()

        if "for_date" in payload.clear:
            demo.set_on_date(None)
        elif payload.for_date is not None:
            demo.set_on_date(payload.for_date)

        if "rain" in payload.clear:
            hardware.set_rain_bucket_24h(None)
        elif payload.rain_24h_mm is not None:
            hardware.set_rain_bucket_24h(payload.rain_24h_mm)

        if "forecast" in payload.clear:
            weather.set_forecast(None)
        elif payload.forecast_rain_24h_mm is not None:
            await self._pin_forecast_qpf(
                demo.overlay_on_date() or date.today(),
                payload.forecast_rain_24h_mm,
            )

        if "moisture" in payload.clear:
            hardware.clear_all_moisture()

        for pin in payload.moisture:
            await self._apply_moisture(pin)

        if "last_watered" in payload.clear:
            demo.clear_last_watered()
        for row in payload.last_watered:
            demo.set_last_watered(row.zone_id, row.last_watered_date)

        touched = (
            bool(payload.clear)
            or payload.rain_24h_mm is not None
            or payload.forecast_rain_24h_mm is not None
            or payload.for_date is not None
            or bool(payload.moisture)
            or bool(payload.last_watered)
        )
        if touched:
            demo.clear_scenario_id()
        return await self.snapshot()

    # -- internals ------------------------------------------------

    async def _tree_pins(self, tree_id: int) -> list[SensorPinRead]:
        rows = await self._sensors.sensors_for_tree(tree_id)
        return [self._pin_read(r) for r in rows]

    @staticmethod
    def _pin_read(row: MoistureSensorRead) -> SensorPinRead:
        overridden = hardware.moisture_is_overridden(row.id)
        return SensorPinRead(
            sensor_id=row.id,
            label=row.label,
            vwc_pct=hardware.get_moisture(row.id),
            overridden=overridden,
            source="override" if overridden else "stub",
        )

    async def _last_watered(self, zone_id: str) -> tuple[date | None, str]:
        pinned = demo.overlay_last_watered(zone_id)
        if pinned is not None:
            return pinned, "demo"
        try:
            _, zone = await get_rachio_service(self._settings).get_zone(zone_id)
        except RachioNotConfigured:
            return None, "none"
        except (RachioError, NotFoundError) as exc:
            _log.warning(
                "irrigation.sensors.rachio_unavailable",
                zone_id=zone_id,
                error=str(exc),
            )
            return None, "none"
        if zone.last_watered_date is None:
            return None, "none"
        return zone.last_watered_date, "rachio"

    async def _pin_forecast_qpf(self, on_date: date, qpf_mm: float) -> None:
        existing = await weather.forecast(self._settings)
        days = [d.model_copy() for d in existing.daily]
        replaced = False
        for i, day in enumerate(days):
            if day.date == on_date:
                days[i] = day.model_copy(update={"qpf_mm": qpf_mm})
                replaced = True
                break
        if not replaced:
            days.append(
                DailyForecast(
                    date=on_date,
                    qpf_mm=qpf_mm,
                    pop_pct=80.0 if qpf_mm else 10.0,
                )
            )
        weather.set_forecast(
            WeatherForecast(
                available=True,
                fetched_at=datetime.now(timezone.utc),
                source="demo",
                location=existing.location,
                daily=sorted(days, key=lambda d: d.date),
            )
        )

    async def _apply_moisture(self, pin: MoistureOverride) -> None:
        if pin.sensor_id:
            row = await self._sensors.get(pin.sensor_id)
            sid = row.id
        elif pin.tree_id is not None:
            sid = (await self._sensors.ensure_for_tree(pin.tree_id)).id
        else:
            raise DomainValidationError(
                "moisture", "each moisture pin needs tree_id or sensor_id"
            )

        if pin.clear:
            hardware.clear_moisture(sid)
            return
        if pin.vwc_pct is None:
            raise DomainValidationError("vwc_pct", "required unless clear is true")
        hardware.set_moisture(sid, pin.vwc_pct)
