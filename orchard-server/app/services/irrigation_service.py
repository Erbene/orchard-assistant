"""Irrigation Phase 3 services: schedule/supervisor config, and the HITL
supervisor run / approve / reject flow.

The supervisor graph is synchronous + Postgres-checkpointed (see
``app.agent.checkpointer``); it is invoked via ``asyncio.to_thread`` and pauses
at ``interrupt_before=["execute_rachio_action"]``. Each deliberation is
persisted as an ``irrigation_proposal`` row - the UI's approval queue.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from ..config import Settings
from ..core.logging import get_logger
from ..core.tracing import traced
from ..repositories.irrigation_config_repository import IrrigationConfigRepository
from ..repositories.irrigation_proposal_repository import IrrigationProposalRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import (
    IrrigationOverview,
    SupervisorConfig,
    SupervisorConfigUpdate,
    SupervisorDecision,
    SupervisorProposal,
    SupervisorRunResult,
    ZoneConfig,
    ZoneConfigUpdate,
    ZoneSolutionOut,
)
from .exceptions import DomainValidationError, NotFoundError
from .water_balance import WaterBalanceService

_log = get_logger("app.irrigation")

_DEFAULT_BASELINE_MIN = 20
_DEFAULT_FREQ_DAYS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(value: Any) -> float | None:
    return float(value) if value is not None else None


# --------------------------------------------------------------------------

class IrrigationConfigService:
    def __init__(
        self,
        config: IrrigationConfigRepository,
        trees: TreeRepository,
        proposals: IrrigationProposalRepository,
    ) -> None:
        self._config = config
        self._trees = trees
        self._proposals = proposals

    async def overview(self) -> IrrigationOverview:
        sup = await self._config.get_supervisor()
        zone_cfgs = await self._config.all_zones()
        zone_ids = await self._trees.distinct_zone_ids()
        counts = await self._trees.zone_tree_counts()
        zones = [
            self._zone_config(z, zone_cfgs.get(z), counts.get(z, 0)) for z in zone_ids
        ]
        pending = len(await self._proposals.list(status="pending"))
        return IrrigationOverview(
            supervisor=SupervisorConfig(
                supervisor_frequency_hours=sup["supervisor_frequency_hours"],
                auto_approve_skips=sup["auto_approve_skips"],
            ),
            zones=zones,
            pending_proposals=pending,
        )

    async def update_supervisor(self, patch: SupervisorConfigUpdate) -> SupervisorConfig:
        row = await self._config.update_supervisor(patch.model_dump(exclude_unset=True))
        return SupervisorConfig(
            supervisor_frequency_hours=row["supervisor_frequency_hours"],
            auto_approve_skips=row["auto_approve_skips"],
        )

    async def update_zone(self, zone_id: str, patch: ZoneConfigUpdate) -> ZoneConfig:
        fields = patch.model_dump(exclude_unset=True)
        if not fields:
            raise DomainValidationError("body", "no fields to update")
        row = await self._config.upsert_zone(zone_id, fields)
        counts = await self._trees.zone_tree_counts()
        return self._zone_config(zone_id, row, counts.get(zone_id, 0))

    @staticmethod
    def _zone_config(zone_id: str, row: dict | None, tree_count: int) -> ZoneConfig:
        row = row or {}
        return ZoneConfig(
            zone_id=zone_id,
            baseline_minutes=row.get("baseline_minutes", _DEFAULT_BASELINE_MIN),
            baseline_frequency_days=row.get("baseline_frequency_days", _DEFAULT_FREQ_DAYS),
            supervised=row.get("supervised", True),
            tree_count=tree_count,
        )


# --------------------------------------------------------------------------

class IrrigationSupervisorService:
    def __init__(
        self,
        water: WaterBalanceService,
        trees: TreeRepository,
        config: IrrigationConfigRepository,
        proposals: IrrigationProposalRepository,
        graph: Any,
        settings: Settings,
    ) -> None:
        self._water = water
        self._trees = trees
        self._config = config
        self._proposals = proposals
        self._graph = graph
        self._settings = settings

    @staticmethod
    def _cfg(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    # -- run ---------------------------------------------------

    @traced("irrigation.supervisor_run")
    async def run(
        self, *, zone_ids: list[str] | None = None, on_date: date | None = None
    ) -> SupervisorRunResult:
        on_date = on_date or date.today()
        sup_cfg = await self._config.get_supervisor()
        zone_cfgs = await self._config.all_zones()
        zones = zone_ids or await self._trees.distinct_zone_ids()

        out: list[SupervisorProposal] = []
        for zone_id in zones:
            zc = zone_cfgs.get(zone_id, {})
            if zc.get("supervised", True) is False:
                continue

            state = await self._build_state(zone_id, zc, on_date)
            thread_id = f"irr-{zone_id}-{on_date.isoformat()}"

            await asyncio.to_thread(self._graph.invoke, state, self._cfg(thread_id))
            snap = await asyncio.to_thread(self._graph.get_state, self._cfg(thread_id))

            proposal = self._proposal_row(thread_id, zone_id, on_date, snap)

            if proposal["action"] == "pass_no_action":
                proposal["status"] = "no_action"
                proposal["resolved_at"] = _now()
            elif proposal["action"] == "skip_schedule" and sup_cfg["auto_approve_skips"]:
                result = await self._resume(thread_id)
                proposal["status"] = "executed"
                proposal["result"] = result
                proposal["resolved_at"] = _now()

            saved = await self._proposals.upsert(proposal)
            out.append(self._to_read(saved))

        _log.info("irrigation.supervisor.run", zones=len(out), for_date=str(on_date))
        return SupervisorRunResult(ran_at=_now(), for_date=on_date, proposals=out)

    async def _build_state(self, zone_id: str, zc: dict, on_date: date) -> dict:
        zwb = await self._water.for_zone(zone_id, on_date=on_date)
        tree_rows = {r["tree_id"]: r for r in await self._trees.list(zone_id=zone_id)}
        trees_state = []
        for wb in zwb.trees:
            row = tree_rows.get(wb.tree_id, {})
            trees_state.append(
                {
                    "tree_id": wb.tree_id,
                    "species": wb.species,
                    "variety": wb.variety,
                    "growth_stage": wb.growth_stage,
                    "target_vwc": wb.target_vwc,
                    "current_vwc": wb.current_vwc,
                    "deficit_score": wb.deficit_score,
                    "canopy_spread_m": _f(row.get("canopy_spread_m")),
                    "estimated_gph": _f(row.get("estimated_gph")),
                    "wetted_area_m2": _f(row.get("wetted_area_m2")),
                }
            )
        return {
            "zone_id": zone_id,
            "for_date": on_date.isoformat(),
            "baseline_minutes": zc.get("baseline_minutes", _DEFAULT_BASELINE_MIN),
            "deficit_score": zwb.deficit_score,
            "rain_24h_mm": zwb.rain_24h_mm,
            "forecast_rain_24h_mm": zwb.forecast_rain_24h_mm,
            "forecast_available": zwb.forecast_available,
            "trees": trees_state,
        }

    # -- approve / reject ------------------------------------

    async def approve(self, thread_id: str) -> SupervisorProposal:
        row = await self._require_pending(thread_id)
        result = await self._resume(thread_id)
        saved = await self._proposals.resolve(thread_id, "executed", result)
        _log.info("irrigation.proposal.approved", thread_id=thread_id, zone_id=row["zone_id"])
        return self._to_read(saved)

    async def reject(self, thread_id: str) -> SupervisorProposal:
        await self._require_pending(thread_id)
        saved = await self._proposals.resolve(thread_id, "rejected", None)
        _log.info("irrigation.proposal.rejected", thread_id=thread_id)
        return self._to_read(saved)

    async def list_proposals(self, *, status: str | None = None) -> list[SupervisorProposal]:
        return [self._to_read(r) for r in await self._proposals.list(status=status)]

    # -- helpers -------------------------------------------

    async def _require_pending(self, thread_id: str) -> dict:
        row = await self._proposals.get(thread_id)
        if row is None:
            raise NotFoundError(f"irrigation proposal {thread_id!r} not found")
        if row["status"] != "pending":
            raise DomainValidationError(
                "status", f"proposal is '{row['status']}', not pending"
            )
        return row

    async def _resume(self, thread_id: str) -> dict | None:
        """Resume the graph past ``interrupt_before`` -> runs execute_rachio_action."""
        await asyncio.to_thread(self._graph.invoke, None, self._cfg(thread_id))
        snap = await asyncio.to_thread(self._graph.get_state, self._cfg(thread_id))
        return snap.values.get("result")

    def _proposal_row(
        self, thread_id: str, zone_id: str, on_date: date, snap: Any
    ) -> dict:
        vals = snap.values or {}
        decision = vals.get("decision") or {"action": "pass_no_action", "reason": ""}
        interrupted = tuple(snap.next or ()) == ("execute_rachio_action",)
        return {
            "thread_id": thread_id,
            "zone_id": zone_id,
            "for_date": on_date,
            "status": "pending" if interrupted else "no_action",
            "action": decision["action"],
            "summary": vals.get("summary") or decision.get("reason", ""),
            "payload": {
                "decision": decision,
                "solution": vals.get("solution"),
                "deficit_score": vals.get("deficit_score"),
                "trees": vals.get("trees", []),
                "llm_available": vals.get("llm_available", True),
            },
            "result": None,
        }

    @staticmethod
    def _to_read(row: dict) -> SupervisorProposal:
        payload = row.get("payload") or {}
        decision = payload.get("decision")
        solution = payload.get("solution")
        return SupervisorProposal(
            thread_id=row["thread_id"],
            zone_id=row["zone_id"],
            for_date=row["for_date"],
            status=row["status"],
            action=row["action"],
            summary=row.get("summary", ""),
            decision=SupervisorDecision.model_validate(decision) if decision else None,
            solution=ZoneSolutionOut.model_validate(solution) if solution else None,
            deficit_score=payload.get("deficit_score"),
            result=row.get("result"),
            created_at=row["created_at"],
            resolved_at=row.get("resolved_at"),
        )
