"""The Irrigation Supervisor - a checkpointed LangGraph that reviews one zone a
day, BEFORE its baseline Rachio schedule runs, and proposes one action:

    START -> deliberate ──(pass_no_action)──────────────────────────► END
                       └──(skip / adjust / emergency)─► contention ─► summarize ─► execute_rachio_action ─► END
                                                                                  ▲ interrupt_before

Every action that touches Rachio pauses at ``execute_rachio_action`` for
Human-In-The-Loop approval (``IrrigationSupervisorService`` reads the paused
state into an ``irrigation_proposal`` row; the UI resumes/aborts it).

The graph is **synchronous** (Postgres checkpointer + sync psycopg pool - async
psycopg can't run on Windows' Proactor loop). Deterministic pre-processing
(water balance) runs in the service and is injected into the initial state.
"""
from __future__ import annotations

import dataclasses
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
from ..schemas.irrigation import SupervisorDecision
from ..tools import irrigation as tools
from .zone_solver import TreeHydro, ZoneSolution, solve

_log = get_logger("app.irrigation.supervisor")

_WATERING_ACTIONS = {"skip_schedule", "adjust_duration", "start_zone_watering"}


class IrrigationSupervisorState(TypedDict, total=False):
    zone_id: str
    for_date: str
    baseline_minutes: int
    deficit_score: float
    rain_24h_mm: float
    forecast_rain_24h_mm: float
    forecast_available: bool
    trees: list[dict[str, Any]]
    decision: dict[str, Any]
    solution: dict[str, Any] | None
    summary: str
    result: dict[str, Any]
    llm_available: bool


class _DecisionModel(BaseModel):
    action: Literal[
        "skip_schedule", "pass_no_action", "adjust_duration", "start_zone_watering"
    ]
    days: int = Field(default=0, ge=0, le=14)
    duration_minutes: int = Field(default=0, ge=0, le=120)
    reason: str = ""


IRRIGATION_SUPERVISOR_PROMPT: str = (
    "You are the Orchard Irrigation Supervisor - an agronomic safety net that "
    "reviews ONE irrigation zone once a day, BEFORE its baseline Rachio "
    "schedule runs. Your objective is to SAVE WATER.\n\n"
    "KEY FACT: the baseline Rachio schedule is BLIND - it does not see the "
    "soil-moisture sensors or the rain that just fell. You correct for that.\n\n"
    "You are given a deterministic Water Deficit Score (it has ALREADY "
    "subtracted the last 24h of measured rain and the next 24h of forecast "
    "rain). Positive = drier than the target for the trees' growth stage; "
    "negative = rain has covered, or will cover, demand.\n\n"
    "Choose EXACTLY ONE `action`:\n"
    "- `skip_schedule` (`days`): pause the baseline run. Use when the deficit "
    "is clearly negative (below about -4). Bigger negative -> more days (1-2 "
    "light rain, 3-7 a soaking).\n"
    "- `adjust_duration`: keep watering today but change the run length "
    "because conditions differ from the baseline assumption (deficit mildly "
    "off from zero, or the zone mixes species). A downstream solver sizes the "
    "exact minutes - you just pick this action.\n"
    "- `pass_no_action`: let the baseline schedule run unchanged. The DEFAULT "
    "when the deficit is near zero and the zone is uniform.\n"
    "- `start_zone_watering`: force an emergency run NOW. ONLY when the deficit "
    "is high (> +8) AND a tree is in `flowering` or `fruit_set` AND no rain is "
    "forecast.\n\n"
    "Prefer `skip_schedule` > `adjust_duration` > `pass_no_action` > "
    "`start_zone_watering` when close. Give a one-sentence `reason` citing the "
    "score."
)

SUPERVISOR_SUMMARY_PROMPT: str = (
    "Write ONE plain-language sentence (max 40 words) for the grower explaining "
    "WHY this irrigation change is proposed. Cite the concrete numbers you are "
    "given (deficit score, soil VWC %, rain mm, run minutes). No preamble, no "
    "hedging. Example style: '30mm rain forecast and soil is at 28% VWC - "
    "proposing a 2-day skip and trimming the next run to 15 min to save water.'"
)


def _template_summary(state: IrrigationSupervisorState, decision: dict, sol: ZoneSolution | None) -> str:
    parts = [f"Deficit score {state.get('deficit_score')}"]
    fc = state.get("forecast_rain_24h_mm") or 0
    if fc:
        parts.append(f"{fc} mm rain forecast")
    action = decision["action"]
    if action == "skip_schedule":
        parts.append(f"proposing a {decision.get('days', 1)}-day skip")
        if sol and sol.recommended_minutes != sol.baseline_minutes:
            parts.append(f"then a {sol.recommended_minutes} min run (was {sol.baseline_minutes})")
    elif action == "adjust_duration" and sol:
        parts.append(
            f"proposing {sol.recommended_minutes} min instead of {sol.baseline_minutes}"
        )
    elif action == "start_zone_watering" and sol:
        parts.append(f"proposing an emergency {sol.recommended_minutes} min run")
    else:
        parts.append("no change - the baseline schedule is fine")
    return "; ".join(parts) + "."


def build_irrigation_graph(settings: Settings, checkpointer: Any) -> Any:
    def _llm(prompt: str, payload: dict, model: type[BaseModel] | None = None) -> Any:
        client = ChatOllama(
            model=settings.agent_model,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            client_kwargs={"timeout": 45.0},
        )
        if model is not None:
            client = client.with_structured_output(model)
        return client.invoke(
            [SystemMessage(prompt), HumanMessage(json.dumps(payload, default=str))]
        )

    def _deliberate(state: IrrigationSupervisorState) -> dict:
        payload = {
            "zone_id": state["zone_id"],
            "deficit_score": state["deficit_score"],
            "rain_last_24h_mm": state.get("rain_24h_mm"),
            "forecast_rain_next_24h_mm": state.get("forecast_rain_24h_mm"),
            "baseline_run_minutes": state.get("baseline_minutes"),
            "trees": [
                {
                    "species": t.get("species"),
                    "growth_stage": t.get("growth_stage"),
                    "current_vwc": t.get("current_vwc"),
                    "target_vwc": t.get("target_vwc"),
                }
                for t in state.get("trees", [])
            ],
        }
        try:
            out: _DecisionModel = _llm(IRRIGATION_SUPERVISOR_PROMPT, payload, _DecisionModel)
        except Exception as exc:  # noqa: BLE001 - a CRON job must not crash
            _log.warning("irrigation.supervisor.llm_unavailable", error=str(exc)[:200])
            return {
                "decision": SupervisorDecision(
                    action="pass_no_action",
                    reason="LLM unavailable - deferred to the baseline schedule.",
                ).model_dump(),
                "summary": "LLM unavailable - deferred to the baseline schedule.",
                "llm_available": False,
            }
        return {
            "decision": SupervisorDecision(
                action=out.action,
                days=out.days,
                duration_minutes=out.duration_minutes,
                reason=out.reason.strip(),
            ).model_dump(),
            "summary": out.reason.strip(),
            "llm_available": True,
        }

    def _route(state: IrrigationSupervisorState) -> str:
        return "done" if state["decision"]["action"] == "pass_no_action" else "plan"

    def _contention(state: IrrigationSupervisorState) -> dict:
        hydro = [
            TreeHydro(
                tree_id=t["tree_id"],
                species=t.get("species", ""),
                current_vwc=t.get("current_vwc"),
                canopy_spread_m=t.get("canopy_spread_m"),
                estimated_gph=t.get("estimated_gph"),
                wetted_area_m2=t.get("wetted_area_m2"),
                target_vwc=t.get("target_vwc"),
            )
            for t in state.get("trees", [])
        ]
        sol = solve(
            hydro,
            baseline_minutes=int(state.get("baseline_minutes", 20)),
            rain_24h_mm=float(state.get("rain_24h_mm", 0.0)),
            forecast_rain_24h_mm=float(state.get("forecast_rain_24h_mm", 0.0)),
        )

        decision = dict(state["decision"])
        if decision["action"] in ("adjust_duration", "start_zone_watering"):
            decision["duration_minutes"] = sol.recommended_minutes
            if sol.recommended_minutes <= 0:
                decision["duration_minutes"] = 15
        # skip_schedule stays a pure skip - it carries no run duration, even
        # though the solver still computes one for the "thoughts" trace.

        return {"decision": decision, "solution": dataclasses.asdict(sol)}

    def _summarize(state: IrrigationSupervisorState) -> dict:
        decision = state["decision"]
        sol_dict = state.get("solution") or {}
        sol = _sol_from_dict(sol_dict) if sol_dict else None
        payload = {
            "deficit_score": state["deficit_score"],
            "rain_last_24h_mm": state.get("rain_24h_mm"),
            "forecast_rain_next_24h_mm": state.get("forecast_rain_24h_mm"),
            "decision": decision,
            "solver": sol_dict,
            "trees": [
                {"species": t.get("species"), "current_vwc": t.get("current_vwc")}
                for t in state.get("trees", [])
            ],
        }
        try:
            msg = _llm(SUPERVISOR_SUMMARY_PROMPT, payload)
            text = (getattr(msg, "content", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            _log.info("irrigation.supervisor.summary_fallback", error=str(exc)[:120])
            text = ""
        return {"summary": text or _template_summary(state, decision, sol)}

    def _execute_rachio_action(state: IrrigationSupervisorState) -> dict:
        d = state["decision"]
        result = tools.dispatch(
            d["action"],
            state["zone_id"],
            days=int(d.get("days") or 0),
            duration_minutes=int(d.get("duration_minutes") or 0),
        )
        _log.info(
            "irrigation.supervisor.executed",
            zone_id=state["zone_id"],
            action=d["action"],
            minutes=d.get("duration_minutes"),
        )
        return {"result": result.as_dict()}

    g = StateGraph(IrrigationSupervisorState)
    g.add_node("deliberate", _deliberate)
    g.add_node("contention", _contention)
    g.add_node("summarize", _summarize)
    g.add_node("execute_rachio_action", _execute_rachio_action)
    g.add_edge(START, "deliberate")
    g.add_conditional_edges("deliberate", _route, {"plan": "contention", "done": END})
    g.add_edge("contention", "summarize")
    g.add_edge("summarize", "execute_rachio_action")
    g.add_edge("execute_rachio_action", END)
    return g.compile(
        checkpointer=checkpointer, interrupt_before=["execute_rachio_action"]
    )


def _sol_from_dict(d: dict) -> ZoneSolution:
    from .zone_solver import TreeOutcome

    return ZoneSolution(
        recommended_minutes=d["recommended_minutes"],
        pulses=d.get("pulses", 1),
        baseline_minutes=d["baseline_minutes"],
        delta_minutes=d["delta_minutes"],
        total_penalty=d["total_penalty"],
        per_tree=[TreeOutcome(**o) for o in d.get("per_tree", [])],
        candidates_considered=d.get("candidates_considered", 0),
        rationale=d.get("rationale", ""),
        thoughts=d.get("thoughts", []),
    )
