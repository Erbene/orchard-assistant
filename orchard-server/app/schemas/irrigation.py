"""Transport models for the Irrigation workflow (app/irrigation/).

Phase 1: the sensor map, the stub hardware reads, the NWS forecast, and the
rainfall forecast-accuracy log. No HTTP routes yet.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# -- moisture sensors -------------------------------------------------

class MoistureSensorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, description="Physical sensor id / UUID.")
    label: str | None = None
    tree_id: int | None = Field(default=None, gt=0)
    zone_id: str | None = Field(default=None, description="Rachio zone id (free text).")


class MoistureSensorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    tree_id: int | None = Field(default=None, gt=0)
    zone_id: str | None = None


class MoistureSensorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str | None = None
    tree_id: int | None = None
    zone_id: str | None = None
    created_at: datetime


class SensorReading(BaseModel):
    """One sensor's current volumetric water content (stubbed in Phase 1)."""

    sensor_id: str
    vwc_pct: float
    source: str = "stub"


class TreeMoisture(BaseModel):
    """A tree's effective moisture: its own sensors if any, else its zone's."""

    tree_id: int
    readings: list[SensorReading] = Field(default_factory=list)
    mean_vwc_pct: float | None = None
    resolved_via: str  # "tree" | "zone" | "none"


# -- weather --------------------------------------------------------

class DailyForecast(BaseModel):
    date: date
    qpf_mm: float = Field(description="Quantitative precipitation forecast, millimetres.")
    pop_pct: float | None = Field(default=None, description="Probability of precipitation, %.")
    temp_high_c: float | None = None
    temp_low_c: float | None = None


class WeatherForecast(BaseModel):
    available: bool
    fetched_at: datetime | None = None
    source: str = "nws"
    location: str | None = None
    daily: list[DailyForecast] = Field(default_factory=list)
    error: str | None = None


# -- rainfall forecast-accuracy log --------------------------------

class RainfallLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    for_date: date
    forecast_1d_mm: float | None = None
    forecast_3d_mm: float | None = None
    forecast_5d_mm: float | None = None
    forecast_1d_at: datetime | None = None
    forecast_3d_at: datetime | None = None
    forecast_5d_at: datetime | None = None
    actual_nws_mm: float | None = None
    actual_gauge_mm: float | None = None
    actuals_at: datetime | None = None
    updated_at: datetime


class RollResult(BaseModel):
    """What one `roll` (daily job) did."""

    ran_for: date
    forecasts_written: dict[str, float | None] = Field(default_factory=dict)  # {"1d": mm, ...}
    actuals_written: dict[str, float | None] = Field(default_factory=dict)     # {"nws": mm, "gauge": mm}
    forecast_available: bool = True
    note: str | None = None


class HorizonAccuracy(BaseModel):
    horizon: str            # "1d" | "3d" | "5d"
    n: int
    mae_mm: float | None = None       # mean absolute error vs actual_nws
    bias_mm: float | None = None      # mean(forecast - actual); + = over-forecast
    hit_rate: float | None = None     # fraction where rain/no-rain call was right (>1mm threshold)


class ForecastAccuracy(BaseModel):
    since: date | None = None
    horizons: list[HorizonAccuracy] = Field(default_factory=list)
    rows_scored: int = 0


# -- Phase 2: water balance + supervisor ---------------------------

GrowthStage = str  # see app.irrigation.phenology.STAGES

IrrigationAction = str  # "skip_schedule" | "pass_no_action" | "start_zone_watering"


class TreeWaterContext(BaseModel):
    """Per-tree inputs the supervisor weighs."""

    tree_id: int
    species: str
    variety: str
    growth_stage: str
    target_vwc: float
    current_vwc: float | None = None
    moisture_resolved_via: str = "none"   # tree | zone | none
    deficit_score: float


class WaterBalance(BaseModel):
    """Deterministic sensor-fusion result for one tree, computed before the LLM.

    ``deficit_score = (target_vwc - current_vwc) - rain_24h_mm -
    forecast_rain_24h_mm`` (higher = drier / more likely to need water). The
    two rainfall terms are mm and the moisture term is VWC points - this is a
    heuristic score, not a physical quantity; the components are all exposed.
    """

    for_date: date
    tree_id: int
    zone_id: str | None = None
    growth_stage: str
    target_vwc: float
    current_vwc: float | None = None
    moisture_gap: float                    # target_vwc - current_vwc (0 if no sensor)
    rain_24h_mm: float
    forecast_rain_24h_mm: float
    deficit_score: float
    moisture_resolved_via: str = "none"
    notes: list[str] = Field(default_factory=list)


class ZoneWaterBalance(BaseModel):
    for_date: date
    zone_id: str
    trees: list[WaterBalance] = Field(default_factory=list)
    deficit_score: float                   # max across trees (protect the driest)
    rain_24h_mm: float
    forecast_rain_24h_mm: float
    forecast_available: bool = True


class SupervisorDecision(BaseModel):
    action: str                            # IrrigationAction
    days: int = 0                          # for skip_schedule
    duration_minutes: int = 0             # for start_zone_watering
    reason: str = ""


class SupervisorRun(BaseModel):
    ran_at: datetime
    for_date: date
    zone_id: str
    deficit_score: float
    growth_stages: list[str] = Field(default_factory=list)
    decision: SupervisorDecision
    executed: dict = Field(default_factory=dict)   # ToolResult
    llm_available: bool = True
