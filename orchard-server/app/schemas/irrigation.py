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
    0.3 * forecast_rain_24h_mm`` (higher = drier / more likely to need water).
    Forecast rain is discounted because QPF is often wrong. The rainfall terms
    are mm and the moisture term is VWC points - this is a heuristic score, not
    a physical quantity; the components are all exposed.
    """

    for_date: date
    tree_id: int
    zone_id: str | None = None
    species: str = ""
    variety: str = ""
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
    action: str                            # skip_schedule | pass_no_action | adjust_duration | start_zone_watering
    days: int = 0                          # skip_schedule / adjust_duration
    duration_minutes: int = 0             # adjust_duration / start_zone_watering (solver-sized)
    reason: str = ""


class TreeOutcome(BaseModel):
    tree_id: int
    species: str
    delivered_gal: float
    post_vwc: float
    penalty: float


class ZoneSolutionOut(BaseModel):
    recommended_minutes: int
    pulses: int = 1
    baseline_minutes: int
    delta_minutes: int
    total_penalty: float
    per_tree: list[TreeOutcome] = Field(default_factory=list)
    candidates_considered: int = 0
    rationale: str = ""
    thoughts: list[dict] = Field(default_factory=list)


ProposalStatus = str  # pending | approved | rejected | executed | no_action | error


class SupervisorProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    thread_id: str
    zone_id: str
    label: str | None = None
    display_name: str | None = None
    zone_number: int | None = None
    for_date: date
    status: str
    action: str
    summary: str = ""
    decision: SupervisorDecision | None = None
    solution: ZoneSolutionOut | None = None
    deficit_score: float | None = None
    result: dict | None = None
    created_at: datetime
    resolved_at: datetime | None = None


# -- schedule / supervisor config --------------------------------

class ZoneConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zone_id: str
    baseline_minutes: int = 20
    supervised: bool = True
    tree_count: int = 0                     # filled by the overview endpoint
    label: str | None = None
    display_name: str | None = None
    zone_number: int | None = None


class ZoneConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_minutes: int | None = Field(default=None, ge=0, le=180)
    supervised: bool | None = None


class SupervisorConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supervisor_frequency_hours: int = 24
    auto_approve_skips: bool = False


class SupervisorConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supervisor_frequency_hours: int | None = Field(default=None, gt=0, le=168)
    auto_approve_skips: bool | None = None


class IrrigationOverview(BaseModel):
    supervisor: SupervisorConfig
    zones: list[ZoneConfig] = Field(default_factory=list)
    pending_proposals: int = 0
    demo_enabled: bool = False


class DemoScenario(BaseModel):
    id: str
    title: str
    expected_action: str
    summary: str
    detail: str


class DemoCatalog(BaseModel):
    enabled: bool
    active_scenario_id: str | None = None
    scenarios: list[DemoScenario] = Field(default_factory=list)


class DemoApplyResult(BaseModel):
    scenario_id: str
    expected_action: str
    on_date: date
    zone_ids: list[str]
    trees_pinned: int
    message: str


# -- sensor board (Irrigation Sensors tab) -----------------------------

class SensorPinRead(BaseModel):
    sensor_id: str
    label: str | None = None
    vwc_pct: float
    overridden: bool = False
    source: str = "stub"  # stub | override


class SensorTreeRead(BaseModel):
    tree_id: int
    species: str = ""
    variety: str = ""
    growth_stage: str
    target_vwc: float
    current_vwc: float | None = None
    moisture_gap: float = 0.0
    deficit_score: float = 0.0
    moisture_resolved_via: str = "none"
    notes: list[str] = Field(default_factory=list)
    sensors: list[SensorPinRead] = Field(default_factory=list)


class SensorZoneRead(BaseModel):
    zone_id: str
    last_watered_date: date | None = None
    last_watered_source: str = "none"  # rachio | demo | none
    deficit_score: float = 0.0
    baseline_minutes: int = 20
    trees: list[SensorTreeRead] = Field(default_factory=list)
    label: str | None = None
    display_name: str | None = None
    zone_number: int | None = None


class SensorSnapshot(BaseModel):
    demo_enabled: bool = False
    for_date: date
    rain_24h_mm: float = 0.0
    rain_overridden: bool = False
    rain_source: str = "stub"
    forecast_rain_24h_mm: float = 0.0
    forecast_available: bool = True
    forecast_overridden: bool = False
    forecast_source: str = "nws"
    forecast_error: str | None = None
    active_scenario_id: str | None = None
    pins_active: bool = False
    zones: list[SensorZoneRead] = Field(default_factory=list)


class MoistureOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tree_id: int | None = Field(default=None, gt=0)
    sensor_id: str | None = None
    vwc_pct: float | None = Field(default=None, ge=0, le=100)
    clear: bool = False


class LastWateredOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    last_watered_date: date | None = None


class SensorOverridesIn(BaseModel):
    """Partial demo pins. Omitted fields are left unchanged."""

    model_config = ConfigDict(extra="forbid")

    rain_24h_mm: float | None = Field(default=None, ge=0, le=500)
    forecast_rain_24h_mm: float | None = Field(default=None, ge=0, le=500)
    for_date: date | None = None
    clear: list[str] = Field(default_factory=list)
    moisture: list[MoistureOverride] = Field(default_factory=list)
    last_watered: list[LastWateredOverride] = Field(default_factory=list)


class SupervisorRunResult(BaseModel):
    ran_at: datetime
    for_date: date
    proposals: list[SupervisorProposal] = Field(default_factory=list)
