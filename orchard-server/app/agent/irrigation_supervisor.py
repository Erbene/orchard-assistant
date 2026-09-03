"""The Irrigation Supervisor - a LangGraph node that reviews a zone once a day,
BEFORE its baseline Rachio schedule runs, and either lets the schedule run,
pauses it, or forces a short emergency run.

    START -> deliberate (LLM, structured output) -> execute (dispatch a tool) -> END

The deterministic Water Deficit Score + per-tree growth stages are computed by
``app.services.water_balance`` and injected into the initial state - the LLM
does judgment, not arithmetic. Triggered by a daily CRON job (Phase 3 wires the
trigger); on LLM failure it defers to the baseline schedule.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..config import Settings
from ..core.logging import get_logger
from ..core.tracing import traced
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import SupervisorDecision, SupervisorRun
from ..services.water_balance import WaterBalanceService
from ..tools import irrigation as tools

_log = get_logger("app.irrigation.supervisor")


class IrrigationSupervisorState(TypedDict, total=False):
    zone_id: str
    for_date: str
    deficit_score: float
    rain_24h_mm: float
    forecast_rain_24h_mm: float
    forecast_available: bool
    trees: list[dict[str, Any]]      # [{tree_id, species, growth_stage, target_vwc, current_vwc, deficit_score}]
    decision: dict[str, Any]
    result: dict[str, Any]
    llm_available: bool


class _DecisionModel(BaseModel):
    action: Literal["skip_schedule", "pass_no_action", "start_zone_watering"]
    days: int = Field(default=0, ge=0, le=14, description="skip_schedule only")
    duration_minutes: int = Field(
        default=0, ge=0, le=120, description="start_zone_watering only"
    )
    reason: str = ""


IRRIGATION_SUPERVISOR_PROMPT: str = (
    "You are the Orchard Irrigation Supervisor - an agronomic safety net that "
    "reviews ONE irrigation zone once a day, BEFORE its baseline Rachio "
    "schedule runs. Your objective is to SAVE WATER.\n\n"
    "KEY FACT: the baseline Rachio schedule is BLIND - it does not see the "
    "soil-moisture sensors or the rain that just fell. Your job is to correct "
    "for that.\n\n"
    "You are given a deterministic Water Deficit Score for the zone (it has "
    "ALREADY subtracted the last 24h of measured rain and the next 24h of "
    "forecast rain). Positive = the soil is drier than the target for the "
    "trees' growth stage. Negative = rain has covered, or will cover, demand.\n\n"
    "Choose EXACTLY ONE action, using the score as the primary signal:\n"
    "- deficit below about -4  ->  `skip_schedule`. The soil is wet / rain is "
    "coming; letting the blind baseline run now would WASTE water. Set `days` "
    "to how long that water lasts: 1-2 for a light rain, 3-7 for a soaking "
    "(bigger negative score = more days).\n"
    "- deficit about -4 to +7  ->  `pass_no_action`. Ordinary demand; let the "
    "baseline schedule run.\n"
    "- deficit above about +7 AND at least one tree in a moisture-critical "
    "stage - ONLY `flowering` or `fruit_set` - AND no rain forecast  ->  "
    "`start_zone_watering` for 15-25 minutes. This is the rare exception.\n"
    "- deficit above +7 at ANY OTHER stage (including `fruit_development`, "
    "`vegetative`, `harvest`)  ->  `pass_no_action`. `pass_no_action` does NOT "
    "mean no water - the baseline schedule still runs and will catch up. Do "
    "not add an emergency run on top of it.\n\n"
    "Always give a one-sentence `reason` citing the score."
)


def build_irrigation_graph(settings: Settings) -> Any:
    async def _deliberate(state: IrrigationSupervisorState) -> dict:
        context = {
            "zone_id": state["zone_id"],
            "deficit_score": state["deficit_score"],
            "rain_last_24h_mm": state.get("rain_24h_mm"),
            "forecast_rain_next_24h_mm": state.get("forecast_rain_24h_mm"),
            "forecast_available": state.get("forecast_available", True),
            "trees": [
                {
                    "tree_id": t.get("tree_id"),
                    "species": t.get("species"),
                    "growth_stage": t.get("growth_stage"),
                    "target_vwc": t.get("target_vwc"),
                    "current_vwc": t.get("current_vwc"),
                    "deficit_score": t.get("deficit_score"),
                }
                for t in state.get("trees", [])
            ],
        }
        llm = ChatOllama(
            model=settings.agent_model,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            client_kwargs={"timeout": 45.0},
        ).with_structured_output(_DecisionModel)
        try:
            out: _DecisionModel = await llm.ainvoke(
                [SystemMessage(IRRIGATION_SUPERVISOR_PROMPT), HumanMessage(json.dumps(context))]
            )
        except Exception as exc:  # noqa: BLE001 - a CRON job must not crash; defer safely
            _log.warning("irrigation.supervisor.llm_unavailable", error=str(exc)[:200])
            return {
                "decision": SupervisorDecision(
                    action="pass_no_action",
                    reason="LLM unavailable - deferred to the baseline schedule.",
                ).model_dump(),
                "llm_available": False,
            }

        return {
            "decision": SupervisorDecision(
                action=out.action,
                days=out.days,
                duration_minutes=out.duration_minutes,
                reason=out.reason.strip(),
            ).model_dump(),
            "llm_available": True,
        }

    async def _execute(state: IrrigationSupervisorState) -> dict:
        d = state["decision"]
        minutes = int(d.get("duration_minutes") or 0)
        if d["action"] == "start_zone_watering" and minutes <= 0:
            minutes = 15  # sane default when the model forgot the duration
        result = tools.dispatch(
            d["action"],
            state["zone_id"],
            days=int(d.get("days") or 0),
            duration_minutes=minutes,
        )
        _log.info(
            "irrigation.supervisor.acted",
            zone_id=state["zone_id"],
            action=d["action"],
            deficit=state["deficit_score"],
        )
        return {"result": result.as_dict()}

    g = StateGraph(IrrigationSupervisorState)
    g.add_node("deliberate", _deliberate)
    g.add_node("execute", _execute)
    g.add_edge(START, "deliberate")
    g.add_edge("deliberate", "execute")
    g.add_edge("execute", END)
    return g.compile()


class IrrigationSupervisorService:
    """Runs the supervisor graph over a zone (or every zone) for a day."""

    def __init__(
        self,
        water: WaterBalanceService,
        trees: TreeRepository,
        settings: Settings,
    ) -> None:
        self._water = water
        self._trees = trees
        self._settings = settings
        self._graph = build_irrigation_graph(settings)

    @traced("irrigation.supervise_zone")
    async def run_for_zone(
        self, zone_id: str, *, on_date: date | None = None
    ) -> SupervisorRun:
        zwb = await self._water.for_zone(zone_id, on_date=on_date)
        state: IrrigationSupervisorState = {
            "zone_id": zone_id,
            "for_date": zwb.for_date.isoformat(),
            "deficit_score": zwb.deficit_score,
            "rain_24h_mm": zwb.rain_24h_mm,
            "forecast_rain_24h_mm": zwb.forecast_rain_24h_mm,
            "forecast_available": zwb.forecast_available,
            "trees": [t.model_dump(mode="json") for t in zwb.trees],
        }
        result = await self._graph.ainvoke(state)

        return SupervisorRun(
            ran_at=datetime.now(timezone.utc),
            for_date=zwb.for_date,
            zone_id=zone_id,
            deficit_score=zwb.deficit_score,
            growth_stages=sorted({t.growth_stage for t in zwb.trees}),
            decision=SupervisorDecision.model_validate(result["decision"]),
            executed=result.get("result", {}),
            llm_available=result.get("llm_available", True),
        )

    async def run_daily(self, *, on_date: date | None = None) -> list[SupervisorRun]:
        """The CRON entrypoint: supervise every zone that has trees."""
        zones = await self._trees.distinct_zone_ids()
        return [await self.run_for_zone(z, on_date=on_date) for z in zones]
