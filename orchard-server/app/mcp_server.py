"""Model Context Protocol server for the orchard backend.

Exposes the same domain logic the REST API uses (``ZoneService`` /
``TreeService`` / ``TaskService`` / ``UserService``) as MCP tools + a
resource, so AI agents can read and mutate orchard data without going through
HTTP.

Two transports:

* **SSE** - mounted onto the FastAPI app at ``/mcp`` (see ``app/main.py``).
  Clients connect to ``/mcp/sse``.
* **stdio** - ``python -m app.mcp_server`` (for Claude Desktop / Cursor).

Every tool call gets its own short-lived SQLite connection, shared by every
service and wrapped in a transaction. sqlite runs with
``check_same_thread=False`` so the async tool body and the sync driver
coexist safely on the event loop.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from .config import get_settings
from .db import connect
from .dependencies import _ensure_schema
from .repositories.task_repository import TaskRepository
from .repositories.tree_repository import TreeRepository
from .repositories.user_repository import UserRepository
from .repositories.zone_repository import ZoneRepository
from .schemas.task import TaskCreate, TaskPriorityUpdate
from .schemas.tree import TreeCreate, TreeUpdate
from .schemas.user_context import UserContextUpdate
from .schemas.zone import ZoneCreate, ZoneUpdate
from .services.exceptions import DomainError
from .services.task_service import TaskService
from .services.tree_service import TreeService
from .services.user_service import UserService
from .services.validators import get_default_validation_agent
from .services.zone_service import ZoneService

mcp = FastMCP("Orchard Management Server")


@dataclass
class _Services:
    zones: ZoneService
    trees: TreeService
    tasks: TaskService
    users: UserService


@contextlib.contextmanager
def _session() -> Iterator[_Services]:
    """Yield connection-bound services. Commit on clean exit, roll back on any
    exception, always close."""
    settings = get_settings()
    _ensure_schema(settings)
    conn = connect(settings)
    validator = get_default_validation_agent()
    zone_repo = ZoneRepository(conn)
    tree_repo = TreeRepository(conn)
    task_repo = TaskRepository(conn)
    user_repo = UserRepository(conn)
    try:
        yield _Services(
            zones=ZoneService(zone_repo, validator),
            trees=TreeService(tree_repo, zone_repo, validator),
            tasks=TaskService(task_repo, tree_repo),
            users=UserService(user_repo),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tools - zones
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_zones() -> list[dict]:
    """List every orchard zone.

    Returns a list of zones, each with: ``zone_id`` (int), ``name``,
    ``soil_drainage`` (free text or null) and ``water_source`` (free text or
    null).
    """
    with _session() as svc:
        return [z.model_dump(mode="json") for z in await svc.zones.list_zones()]


@mcp.tool()
async def get_zone_details(zone_id: int) -> dict:
    """Fetch a single zone by its numeric id.

    Args:
        zone_id: The zone's integer primary key.

    Errors if no zone with that id exists.
    """
    with _session() as svc:
        try:
            return (await svc.zones.get_zone(zone_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_zone(
    name: str,
    soil_drainage: str | None = None,
    water_source: str | None = None,
) -> dict:
    """Create a new orchard zone and return the created row (with its new id).

    All descriptive fields are free text and stored exactly as typed - there
    is no controlled vocabulary.

    Args:
        name: Human-readable zone name, e.g. "North Block".
        soil_drainage: Optional free text, e.g. "sandy", "heavy clay".
        water_source: Optional free text irrigation source, e.g. "well",
            "canal", "municipal".
    """
    with _session() as svc:
        try:
            created = await svc.zones.create_zone(
                ZoneCreate(
                    name=name,
                    soil_drainage=soil_drainage,
                    water_source=water_source,
                )
            )
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return created.model_dump(mode="json")


@mcp.tool()
async def update_zone(
    zone_id: int,
    name: str | None = None,
    soil_drainage: str | None = None,
    water_source: str | None = None,
) -> dict:
    """Update fields on an existing zone. Only the arguments you pass change.

    Args:
        zone_id: The zone to update.
        name: New zone name.
        soil_drainage: New free-text soil drainage.
        water_source: New free-text water source.

    Passing an argument as null/None leaves that field unchanged. Errors if
    the zone does not exist.
    """
    patch = {
        key: value
        for key, value in {
            "name": name,
            "soil_drainage": soil_drainage,
            "water_source": water_source,
        }.items()
        if value is not None
    }
    with _session() as svc:
        try:
            updated = await svc.zones.update_zone(zone_id, ZoneUpdate(**patch))
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return updated.model_dump(mode="json")


@mcp.tool()
async def delete_zone(zone_id: int) -> str:
    """Permanently delete a zone.

    Args:
        zone_id: The zone to delete.

    Returns a short confirmation string. Errors if the zone does not exist,
    or if trees are still assigned to it (reassign or delete those first).
    """
    with _session() as svc:
        try:
            await svc.zones.delete_zone(zone_id)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return f"Zone {zone_id} deleted."


# ---------------------------------------------------------------------------
# Tools - trees
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_trees(zone_id: int | None = None) -> list[dict]:
    """List tree records, optionally scoped to one zone.

    Args:
        zone_id: If provided, only trees assigned to this zone are returned;
            otherwise every tree is returned.

    Each tree includes ``tree_id``, ``species``, ``variety``, ``zone_id``,
    ``planted_date`` (ISO date or null) and the derived ``age_days`` /
    ``age_years``.
    """
    with _session() as svc:
        rows = await svc.trees.list_trees(zone_id=zone_id)
        return [t.model_dump(mode="json") for t in rows]


@mcp.tool()
async def get_tree_details(tree_id: int) -> dict:
    """Fetch a single tree record by its numeric id, including derived age.

    Args:
        tree_id: The tree's integer primary key.

    Errors if no tree with that id exists.
    """
    with _session() as svc:
        try:
            return (await svc.trees.get_tree(tree_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_tree(
    species: str,
    variety: str,
    zone_id: int | None = None,
    planted_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a new tree record and return the created row.

    All descriptive fields are free text and are stored exactly as typed -
    there is no controlled vocabulary. (Soil drainage is a property of the
    *zone*, not the tree; set it with the zone tools.)

    Args:
        species: Common species name, e.g. "mango", "sapodilla", "sugar apple".
        variety: Cultivar / variety name, e.g. "Kent", "Nam Doc Mai".
        zone_id: Optional id of an existing zone to plant the tree in. Must
            reference a real zone or the call is rejected.
        planted_date: Optional planting date as an ISO-8601 string (YYYY-MM-DD).
        notes: Optional free-text notes.
    """
    with _session() as svc:
        try:
            created = await svc.trees.create_tree(
                TreeCreate(
                    species=species,
                    variety=variety,
                    zone_id=zone_id,
                    planted_date=planted_date,
                    notes=notes,
                )
            )
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return created.model_dump(mode="json")


@mcp.tool()
async def update_tree(
    tree_id: int,
    species: str | None = None,
    variety: str | None = None,
    zone_id: int | None = None,
    planted_date: str | None = None,
    notes: str | None = None,
    additional_context: str | None = None,
) -> dict:
    """Update fields on an existing tree. Only the arguments you pass change.

    Args:
        tree_id: The tree to update.
        species: New free-text species name.
        variety: New free-text variety name.
        zone_id: Move the tree to this (existing) zone.
        planted_date: New planting date, ISO-8601 (YYYY-MM-DD).
        notes: Replace the free-text notes.
        additional_context: Replace the free-text additional-context field.

    Passing an argument as null/None leaves that field unchanged (it cannot
    be used to clear a field). Errors if the tree does not exist.
    """
    patch = {
        key: value
        for key, value in {
            "species": species,
            "variety": variety,
            "zone_id": zone_id,
            "planted_date": planted_date,
            "notes": notes,
            "additional_context": additional_context,
        }.items()
        if value is not None
    }
    with _session() as svc:
        try:
            updated = await svc.trees.update_tree(tree_id, TreeUpdate(**patch))
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return updated.model_dump(mode="json")


@mcp.tool()
async def delete_tree(tree_id: int) -> str:
    """Permanently delete a tree record (and its tasks).

    Args:
        tree_id: The tree to delete.

    Returns a short confirmation string. Errors if the tree does not exist.
    """
    with _session() as svc:
        try:
            await svc.trees.delete_tree(tree_id)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return f"Tree {tree_id} deleted."


# ---------------------------------------------------------------------------
# Tools - tasks (Foreman agent)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_pending_tasks(scheduled_before: str | None = None) -> list[dict]:
    """Retrieve the current task queue: every task whose status is ``pending``,
    ordered by ``priority_score`` descending (most urgent first).

    This is the Foreman agent's primary read - the work backlog it must
    schedule against the user's labor and product constraints.

    Args:
        scheduled_before: Optional ISO-8601 date or datetime (e.g.
            "2026-09-30" or "2026-09-30T17:00:00Z"). When given, only tasks
            due on or before that day are returned, *plus* any task with no
            ``scheduled_date`` yet (those always need placing). Omit to get
            the entire pending backlog.

    Returns a list of task objects, each with: ``id``, ``tree_id``,
    ``action_type``, ``status``, ``priority_score``, ``scheduled_date``
    (ISO datetime or null), ``frequency_days`` (int or null; set = recurring),
    ``created_at`` and ``completed_at``.
    """
    before = _parse_dt(scheduled_before, field="scheduled_before")
    with _session() as svc:
        rows = await svc.tasks.get_pending_queue(scheduled_before=before)
        return [t.model_dump(mode="json") for t in rows]


@mcp.tool()
async def get_task_details(task_id: int) -> dict:
    """Fetch one task by its numeric id.

    Args:
        task_id: The task's integer primary key.

    Errors if no task with that id exists.
    """
    with _session() as svc:
        try:
            return (await svc.tasks.get_task(task_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_task(
    tree_id: int,
    action_type: str,
    priority_score: float = 0.0,
    scheduled_date: str | None = None,
    frequency_days: int | None = None,
) -> dict:
    """Create a single work task attached to a tree and return the new row.

    Args:
        tree_id: Id of an existing tree the task applies to. Rejected if the
            tree does not exist.
        action_type: Free-text work type, e.g. "prune", "fertilize",
            "irrigate", "scout_pests". No controlled vocabulary.
        priority_score: Relative urgency; higher sorts earlier in the queue.
            Defaults to 0.0.
        scheduled_date: Optional ISO-8601 date/datetime when the task is
            planned. Omit to leave it unscheduled (it will still surface in
            the pending queue as needing placement).
        frequency_days: Optional positive integer. If set, the task recurs:
            completing it automatically spawns the next pending occurrence
            ``frequency_days`` later.
    """
    with _session() as svc:
        try:
            created = await svc.tasks.create_task(
                TaskCreate(
                    tree_id=tree_id,
                    action_type=action_type,
                    priority_score=priority_score,
                    scheduled_date=_parse_dt(scheduled_date, field="scheduled_date"),
                    frequency_days=frequency_days,
                )
            )
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return created.model_dump(mode="json")


@mcp.tool()
async def create_baseline_tasks(tree_id: int, start_date: str | None = None) -> list[dict]:
    """Generate the standard recurring care task set for a tree (typically a
    newly planted one): a health inspection, fertilizing, mulching and a
    structural prune, each with a sensible default priority and cadence.

    Args:
        tree_id: The tree to generate tasks for. Rejected if it does not exist.
        start_date: Optional ISO-8601 date/datetime to anchor the first
            occurrence of each task from (defaults to now). Each task's first
            occurrence is scheduled one full cadence after this anchor.

    Returns the list of created task objects.
    """
    with _session() as svc:
        try:
            created = await svc.tasks.create_baseline_tasks(
                tree_id,
                start_date=_parse_dt(start_date, field="start_date"),
            )
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return [t.model_dump(mode="json") for t in created]


@mcp.tool()
async def batch_update_task_priorities(task_updates: list[dict]) -> list[dict]:
    """Update ``priority_score`` and/or ``scheduled_date`` across many tasks in
    a single atomic transaction - the Foreman agent's main write once it has
    reasoned about the queue against the user's constraints.

    Args:
        task_updates: A list of change objects. Each object MUST contain:
            - ``task_id`` (int, required): the task to change.
          and MAY contain either or both of:
            - ``priority_score`` (number): the task's new priority.
            - ``scheduled_date`` (string): ISO-8601 date/datetime to (re)schedule
              the task to.
            Fields you omit are left unchanged. Example:
            ``[{"task_id": 12, "priority_score": 9.5, "scheduled_date": "2026-09-15"},
               {"task_id": 15, "priority_score": 2.0}]``

    If any ``task_id`` is unknown the whole batch is rejected and nothing is
    written. Returns the full, updated task objects in the same order.
    """
    try:
        changes = [TaskPriorityUpdate.model_validate(item) for item in task_updates]
    except Exception as exc:  # noqa: BLE001 - malformed input -> clean tool error
        raise ToolError(f"Invalid task_updates payload: {exc}") from exc

    with _session() as svc:
        try:
            updated = await svc.tasks.batch_update_priorities(changes)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return [t.model_dump(mode="json") for t in updated]


@mcp.tool()
async def mark_task_complete(task_id: int) -> dict:
    """Mark a task as ``completed`` (stamping ``completed_at``). If the task is
    recurring (``frequency_days`` set), the next pending occurrence is created
    automatically.

    Args:
        task_id: The task to complete.

    Returns the completed task object. Errors if the task does not exist.
    """
    with _session() as svc:
        try:
            return (await svc.tasks.mark_complete(task_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def defer_task(task_id: int, until: str | None = None) -> dict:
    """Move a task to ``deferred`` status, optionally rescheduling it.

    Args:
        task_id: The task to defer.
        until: Optional ISO-8601 date/datetime to reschedule the task to.

    Returns the updated task object. Errors if the task does not exist.
    """
    with _session() as svc:
        try:
            return (
                await svc.tasks.defer_task(
                    task_id, until=_parse_dt(until, field="until")
                )
            ).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Tools - user context (scheduling constraints)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_user_constraints() -> dict:
    """Retrieve the scheduling constraints the Foreman agent must respect.

    Returns an object with:
        - ``available_labor_hours_per_day`` (number): person-hours of work
          that can be scheduled on a normal day.
        - ``available_products`` (list of strings): free-text names of
          fertilizers, sprays, tools and equipment currently on hand. Tasks
          needing a product not in this list should be deferred or flagged.
        - ``id`` and ``updated_at``.

    Defaults (8 hours/day, no products) are created on first read.
    """
    with _session() as svc:
        return (await svc.users.get_constraints()).model_dump(mode="json")


@mcp.tool()
async def update_user_constraints(
    available_labor_hours_per_day: float | None = None,
    available_products: list[str] | None = None,
) -> dict:
    """Update the scheduling constraints. Only the arguments you pass change.

    Args:
        available_labor_hours_per_day: New daily labor budget in person-hours.
        available_products: New full list of product/equipment names on hand
            (replaces the existing list).

    Returns the updated constraints object.
    """
    patch: dict[str, object] = {}
    if available_labor_hours_per_day is not None:
        patch["available_labor_hours_per_day"] = available_labor_hours_per_day
    if available_products is not None:
        patch["available_products"] = available_products
    with _session() as svc:
        updated = await svc.users.update_constraints(UserContextUpdate(**patch))
        return updated.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("orchard://system-summary")
async def system_summary() -> str:
    """A plain-text snapshot of orchard database stats for grounding an agent.

    Reports zone / tree / task counts, pending-task backlog, a per-species
    tree tally, and overall system status.
    """
    try:
        with _session() as svc:
            zone_rows = await svc.zones.list_zones()
            tree_rows = await svc.trees.list_trees()
            all_tasks = await svc.tasks.list_tasks()
            pending = await svc.tasks.get_pending_queue()
    except Exception as exc:  # noqa: BLE001 - resources surface errors this way
        raise ResourceError(f"Could not read orchard stats: {exc}") from exc

    unassigned = sum(1 for t in tree_rows if t.zone_id is None)
    species_tally: dict[str, int] = {}
    for tree in tree_rows:
        species_tally[tree.species] = species_tally.get(tree.species, 0) + 1

    lines = [
        "Orchard Management System - summary",
        "-----------------------------------",
        f"Zones:            {len(zone_rows)}",
        f"Trees:            {len(tree_rows)}",
        f"Unassigned trees: {unassigned}",
        f"Tasks (total):    {len(all_tasks)}",
        f"Tasks (pending):  {len(pending)}",
        "Status:           online",
    ]
    if species_tally:
        lines.append("")
        lines.append("Trees by species:")
        for name, count in sorted(species_tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name}: {count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: str | None, *, field: str) -> datetime | None:
    """Parse an ISO-8601 date or datetime string; ``None`` passes through.

    Bare dates ("2026-09-30") are accepted and returned as a datetime at
    midnight.
    """
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(f"{value}T00:00:00")
    except ValueError as exc:
        raise ToolError(
            f"{field}: '{value}' is not a valid ISO-8601 date or datetime"
        ) from exc


# ---------------------------------------------------------------------------
# stdio transport - for Claude Desktop / Cursor
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
