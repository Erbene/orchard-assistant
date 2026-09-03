"""In-process DEMO pins for the irrigation supervisor.

When ``ORCHARD_DEMO`` is on, the grower picks a scenario; we override stub
moisture / rain / forecast / last-watered so a subsequent supervisor run
produces a known outcome (and a LangSmith ToT trace). Pins live in this
process only — they do not write Rachio or NWS.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .sensors import MoistureSensorService
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import (
    DailyForecast,
    DemoApplyResult,
    DemoScenario,
    MoistureSensorCreate,
    WeatherForecast,
)
from ..services.exceptions import ConflictError, DomainValidationError, NotFoundError
from . import hardware, weather

_log_last_watered: dict[str, date] = {}
_on_date: date | None = None
_scenario_id: str | None = None
_zone_ids: list[str] = []


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    title: str
    expected_action: str
    summary: str
    detail: str
    # Relative to the scenario's on_date
    last_watered_days_ago: int
    rain_mm: float
    qpf_mm: float
    on_date: date
    # VWC strategy applied per tree in the zone (see apply).
    vwc_mode: str  # "wet" | "contrast" | "drought"


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        id="rain-skip",
        title="Soaking rain on the way",
        expected_action="skip_schedule",
        summary="Skip today's run — soil is already wet and 25 mm is forecast.",
        detail="Pins high VWC and a heavy QPF so the supervisor should propose "
        "skip_schedule (water-saving). LangSmith: deliberate + summarize; "
        "ToT still sizes a duration that a skip must not narrate.",
        last_watered_days_ago=5,
        rain_mm=0.0,
        qpf_mm=25.0,
        on_date=date(2026, 6, 15),
        vwc_mode="wet",
    ),
    ScenarioSpec(
        id="mixed-zone-tot",
        title="Mixed zone: mango vs. a thirsty neighbour",
        expected_action="adjust_duration",
        summary="One duration for two appetites — watch the ToT beam in LangSmith.",
        detail="Contrasting VWC across trees in the zone (first tree comfortable, "
        "others dry). The zone solver's beam search is the LangSmith span "
        "irrigation.tot_solver (candidates + penalties).",
        last_watered_days_ago=5,
        rain_mm=0.0,
        qpf_mm=0.0,
        on_date=date(2026, 5, 15),
        vwc_mode="contrast",
    ),
    ScenarioSpec(
        id="drought-emergency",
        title="Fruit-set drought",
        expected_action="start_zone_watering",
        summary="Severe deficit at fruit set — emergency run, grower must approve.",
        detail="March fruit-set phenology + VWC near wilt. Expect "
        "start_zone_watering; ToT sizes the minutes. Last watered 5 days ago "
        "so the 2-day Rachio gap does not rewrite this to a skip.",
        last_watered_days_ago=5,
        rain_mm=0.0,
        qpf_mm=0.0,
        on_date=date(2026, 3, 15),
        vwc_mode="drought",
    ),
)

_BY_ID = {s.id: s for s in SCENARIOS}


def catalog() -> list[DemoScenario]:
    return [
        DemoScenario(
            id=s.id,
            title=s.title,
            expected_action=s.expected_action,
            summary=s.summary,
            detail=s.detail,
        )
        for s in SCENARIOS
    ]


def get_spec(scenario_id: str) -> ScenarioSpec | None:
    return _BY_ID.get(scenario_id)


def active_scenario_id() -> str | None:
    return _scenario_id


def overlay_on_date() -> date | None:
    return _on_date


def overlay_zone_ids() -> list[str]:
    return list(_zone_ids)


def overlay_last_watered(zone_id: str) -> date | None:
    return _log_last_watered.get(zone_id)


def reset() -> None:
    global _on_date, _scenario_id, _zone_ids
    hardware.reset()
    weather.clear_cache()
    _log_last_watered.clear()
    _on_date = None
    _scenario_id = None
    _zone_ids = []


def _vwc_for(mode: str, index: int) -> float:
    if mode == "wet":
        return 30.0
    if mode == "drought":
        return 12.0
    # contrast: first tree comfortable for mango, later trees drought-ish
    return 24.0 if index == 0 else 16.0


def apply_pins(
    spec: ScenarioSpec,
    *,
    zone_ids: list[str],
    sensors_by_tree: dict[int, str],
    tree_order: list[int],
) -> None:
    """Pin hardware + weather + last-watered. ``sensors_by_tree`` maps tree_id → sensor id."""
    global _on_date, _scenario_id, _zone_ids

    hardware.reset()
    weather.clear_cache()
    _log_last_watered.clear()

    hardware.set_rain_bucket_24h(spec.rain_mm)
    weather.set_forecast(
        WeatherForecast(
            available=True,
            fetched_at=datetime.now(timezone.utc),
            source="demo",
            daily=[
                DailyForecast(
                    date=spec.on_date,
                    qpf_mm=spec.qpf_mm,
                    pop_pct=80.0 if spec.qpf_mm else 10.0,
                )
            ],
        )
    )

    last = spec.on_date - timedelta(days=spec.last_watered_days_ago)
    for zid in zone_ids:
        _log_last_watered[zid] = last

    for i, tree_id in enumerate(tree_order):
        sid = sensors_by_tree.get(tree_id)
        if sid:
            hardware.set_moisture(sid, _vwc_for(spec.vwc_mode, i))

    _on_date = spec.on_date
    _scenario_id = spec.id
    _zone_ids = list(zone_ids)


async def apply_to_orchard(
    scenario_id: str,
    trees: TreeRepository,
    sensors: MoistureSensorService,
) -> DemoApplyResult:
    spec = get_spec(scenario_id)
    if spec is None:
        raise NotFoundError(f"unknown demo scenario {scenario_id!r}")

    all_trees = await trees.list()
    zoned = [t for t in all_trees if t.get("zone_id")]
    if not zoned:
        raise DomainValidationError(
            "trees",
            "Add at least one tree with a Rachio zone before running a demo scenario.",
        )

    from collections import Counter

    counts = Counter(t["zone_id"] for t in zoned)
    if spec.vwc_mode == "contrast":
        zone_id = max(counts, key=counts.get)
    else:
        zone_id = next(iter(counts))
    zone_ids = [zone_id]
    trees_in = [t for t in zoned if t["zone_id"] == zone_id]

    sensors_by_tree: dict[int, str] = {}
    for t in trees_in:
        tid = t["tree_id"]
        existing = await sensors.sensors_for_tree(tid)
        if existing:
            sensors_by_tree[tid] = existing[0].id
            continue
        sid = f"demo-{tid}"
        try:
            created = await sensors.create(
                MoistureSensorCreate(
                    id=sid,
                    label="Demo pin",
                    tree_id=tid,
                    zone_id=t["zone_id"],
                )
            )
            sensors_by_tree[tid] = created.id
        except ConflictError:
            sensors_by_tree[tid] = sid

    apply_pins(
        spec,
        zone_ids=zone_ids,
        sensors_by_tree=sensors_by_tree,
        tree_order=[t["tree_id"] for t in trees_in],
    )
    return DemoApplyResult(
        scenario_id=spec.id,
        expected_action=spec.expected_action,
        on_date=spec.on_date,
        zone_ids=zone_ids,
        trees_pinned=len(trees_in),
        message=(
            f"Pinned {len(trees_in)} tree(s) in zone {zone_id}. "
            "Run Supervision Task to generate the proposal (LangSmith will "
            "record irrigation.tot_solver)."
        ),
    )