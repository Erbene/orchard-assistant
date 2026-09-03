"""The three actions the irrigation supervisor can take on the Rachio
execution layer. Phase 2: **stubbed** - each logs / prints and returns a
``ToolResult`` with ``dry_run=True``. Phase 3 wires these to
``RachioService`` (skip via ``PUT /device/{id}/rain_delay`` or schedule pause,
emergency run via ``start_zone_watering``).

The functions are plain and synchronous so an agent node dispatches on the
LLM's structured decision without a tool-calling loop; ``app/mcp_server.py``
also registers them for external MCP clients.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..core.logging import get_logger

_log = get_logger("app.tools.irrigation")

IrrigationAction = Literal["skip_schedule", "pass_no_action", "start_zone_watering"]


@dataclass(frozen=True)
class ToolResult:
    action: IrrigationAction
    zone_id: str
    params: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "zone_id": self.zone_id,
            "params": self.params,
            "dry_run": self.dry_run,
            "at": self.at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rachio_skip_schedule(zone_id: str, days: int) -> ToolResult:
    """Pause the baseline Rachio schedule for ``zone_id`` for ``days`` days -
    the water-saving action when recent or forecast rain covers demand."""
    days = max(0, min(int(days), 14))
    _log.info("irrigation.tool.skip_schedule", zone_id=zone_id, days=days, dry_run=True)
    print(f"[IRRIGATION STUB] rachio_skip_schedule(zone_id={zone_id!r}, days={days})")
    return ToolResult("skip_schedule", zone_id, {"days": days}, at=_now())


def pass_no_action(zone_id: str) -> ToolResult:
    """Take no action - defer to the baseline Rachio schedule. The default when
    the deficit is unremarkable."""
    _log.info("irrigation.tool.pass_no_action", zone_id=zone_id, dry_run=True)
    print(f"[IRRIGATION STUB] pass_no_action(zone_id={zone_id!r})")
    return ToolResult("pass_no_action", zone_id, {}, at=_now())


def start_zone_watering(zone_id: str, duration_minutes: int) -> ToolResult:
    """Force an immediate emergency run of ``zone_id`` for ``duration_minutes`` -
    only when a moisture-critical stage would be harmed by waiting for the
    baseline schedule."""
    duration_minutes = max(1, min(int(duration_minutes), 120))
    _log.info(
        "irrigation.tool.start_zone_watering",
        zone_id=zone_id,
        duration_minutes=duration_minutes,
        dry_run=True,
    )
    print(
        f"[IRRIGATION STUB] start_zone_watering(zone_id={zone_id!r}, "
        f"duration_minutes={duration_minutes})"
    )
    return ToolResult(
        "start_zone_watering", zone_id, {"duration_minutes": duration_minutes}, at=_now()
    )


def dispatch(
    action: str, zone_id: str, *, days: int = 0, duration_minutes: int = 0
) -> ToolResult:
    """Run the tool named by an LLM decision."""
    if action == "skip_schedule":
        return rachio_skip_schedule(zone_id, days)
    if action == "start_zone_watering":
        return start_zone_watering(zone_id, duration_minutes)
    return pass_no_action(zone_id)


__all__ = [
    "IrrigationAction",
    "ToolResult",
    "rachio_skip_schedule",
    "pass_no_action",
    "start_zone_watering",
    "dispatch",
]
