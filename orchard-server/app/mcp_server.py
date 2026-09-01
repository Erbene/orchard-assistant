"""Model Context Protocol server for the orchard backend.

Exposes the same domain logic the REST API uses (``ZoneService`` /
``TreeService`` / ``TaskService`` / ``SourceService``) as MCP tools + a
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
from .rag.vector_store import get_vector_store
from .repositories.source_repository import SourceRepository
from .repositories.task_repository import TaskRepository
from .repositories.tree_repository import TreeRepository
from .repositories.zone_repository import ZoneRepository
from .schemas.task import TaskBaselineItem, TaskCreate, TaskPriorityUpdate
from .schemas.tree import TreeCreate, TreeUpdate
from .schemas.zone import ZoneCreate, ZoneUpdate
from .services.exceptions import DomainError
from .services.source_service import SourceService
from .services.task_service import TaskService
from .services.tree_service import TreeService
from .services.validators import get_default_validation_agent
from .services.zone_service import ZoneService

mcp = FastMCP("Orchard Management Server")


@dataclass
class _Services:
    zones: ZoneService
    trees: TreeService
    tasks: TaskService
    sources: SourceService


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
    source_repo = SourceRepository(conn)
    try:
        yield _Services(
            zones=ZoneService(zone_repo, validator),
            trees=TreeService(tree_repo, zone_repo, validator),
            tasks=TaskService(task_repo, tree_repo),
            sources=SourceService(
                source_repo, tree_repo, get_vector_store(settings), settings
            ),
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

    This is the Foreman agent's primary read - the work backlog it fits, at
    conversation time, into the minutes and resources the user has just stated
    (the JIT scheduling model).

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
    estimated_minutes: int,
    required_resources: list[str],
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
        estimated_minutes: Your best estimate of the hands-on labor time in
            minutes. REQUIRED - the JIT scheduler fits tasks into the time the
            user says they have.
        required_resources: List of free-text product/equipment names the task
            needs (e.g. ["pruning saw", "10-10-10 fertilizer"]). Pass an empty
            list if nothing special is needed. REQUIRED.
        priority_score: Relative urgency; higher sorts earlier in the queue.
        scheduled_date: Optional ISO-8601 date/datetime. Omit to leave the task
            unscheduled (it still surfaces in the pending queue).
        frequency_days: Optional positive integer. If set, completing the task
            spawns the next occurrence ``frequency_days`` later.
    """
    with _session() as svc:
        try:
            created = await svc.tasks.create_task(
                TaskCreate(
                    tree_id=tree_id,
                    action_type=action_type,
                    estimated_minutes=estimated_minutes,
                    required_resources=required_resources,
                    priority_score=priority_score,
                    scheduled_date=_parse_dt(scheduled_date, field="scheduled_date"),
                    frequency_days=frequency_days,
                )
            )
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return created.model_dump(mode="json")


@mcp.tool()
async def create_baseline_tasks(tree_id: int, tasks: list[dict]) -> list[dict]:
    """Create a starter care-task set for a tree. YOU decide the tasks and MUST
    fully specify each one - the JIT scheduler needs labor time and resources
    up front.

    Args:
        tree_id: The tree to generate tasks for. Rejected if it does not exist.
        tasks: A list of task specs. Each object MUST contain:
            - ``action_type`` (str): free-text work type.
            - ``estimated_minutes`` (int > 0): hands-on labor time.
            - ``required_resources`` (list[str]): product/equipment names ([] if none).
          and MAY contain:
            - ``priority_score`` (number, default 0.0)
            - ``frequency_days`` (int > 0): recurring cadence.
            - ``scheduled_date`` (ISO string): first planned date.
          Example: ``[{"action_type": "inspect_health", "estimated_minutes": 15,
          "required_resources": [], "frequency_days": 30}]``

    Returns the list of created task objects.
    """
    try:
        items = [TaskBaselineItem.model_validate(item) for item in tasks]
    except Exception as exc:  # noqa: BLE001 - malformed input -> clean tool error
        raise ToolError(f"Invalid tasks payload: {exc}") from exc

    with _session() as svc:
        try:
            created = await svc.tasks.create_baseline_tasks(tree_id, items)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return [t.model_dump(mode="json") for t in created]


@mcp.tool()
async def batch_update_task_priorities(task_updates: list[dict]) -> list[dict]:
    """Update ``priority_score`` and/or ``scheduled_date`` across many tasks in
    a single atomic transaction - the Foreman agent's main write once it has
    reasoned about the queue against the stated time budget.

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
# Tools - knowledge base (Consensus Fusion RAG)
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_sources() -> list[dict]:
    """List every knowledge-base source (id, name, type, upload date).

    Sources are documents (pasted text or uploaded files) that have been
    chunked into the vector store. A source only becomes searchable for a tree
    once it is linked with ``link_tree_sources``.
    """
    with _session() as svc:
        return [s.model_dump(mode="json") for s in await svc.sources.list_sources()]


@mcp.tool()
async def add_text_source(name: str, text: str) -> dict:
    """Add a text-based knowledge source: store it and embed it into the
    vector store. Returns the new source (with its id).

    Args:
        name: A short human label, e.g. "UF/IFAS mango pruning guide".
        text: The full text / Markdown to ingest.

    After adding, call ``link_tree_sources`` to make it searchable for a tree.
    """
    with _session() as svc:
        try:
            created = await svc.sources.ingest_text(name, text)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return created.model_dump(mode="json")


@mcp.tool()
async def link_tree_sources(tree_id: int, source_ids: list[int]) -> list[dict]:
    """Set the full list of knowledge sources linked to a tree (replaces any
    existing links). ``search_ag_knowledge(tree_id, ...)`` searches exactly
    these sources.

    Args:
        tree_id: An existing tree.
        source_ids: Source ids to link (from ``list_sources``). Pass ``[]`` to
            unlink everything.
    """
    with _session() as svc:
        try:
            linked = await svc.sources.set_tree_sources(tree_id, source_ids)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return [s.model_dump(mode="json") for s in linked]


@mcp.tool()
async def search_ag_knowledge(tree_id: int, query: str) -> str:
    """Search the agronomy knowledge base for passages relevant to ``query``,
    restricted to the sources linked to ``tree_id``.

    Consensus-fusion retrieval: each linked source is searched *independently*
    in the vector store, and the results are returned grouped by source so the
    agent can weigh agreement / disagreement between sources itself.

    Args:
        tree_id: The tree whose linked sources define the allowed corpus.
        query: A natural-language question, e.g. "when should I prune a young
            mango" or "signs of nitrogen deficiency".

    Returns a single string. Each linked source that had a hit contributes a
    block:  ``--- SOURCE {id} ---`` followed by its matching chunks. Returns a
    short notice if the tree has no linked sources or nothing matched.
    """
    with _session() as svc:
        try:
            allowed_source_ids = svc.sources.allowed_source_ids(tree_id)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc

    if not allowed_source_ids:
        return f"No knowledge sources are linked to tree {tree_id}."

    store = get_vector_store(get_settings())
    blocks: list[str] = []
    for source_id in allowed_source_ids:
        chunks = store.search(query, source_id=source_id, n_results=4)
        if chunks:
            body = "\n".join(f"- {c.strip()}" for c in chunks)
            blocks.append(f"--- SOURCE {source_id} ---\n{body}")

    if not blocks:
        return "No relevant passages found in the sources linked to this tree."
    return "\n\n".join(blocks)


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
            source_rows = await svc.sources.list_sources()
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
        f"KB sources:       {len(source_rows)}",
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
    import sys

    from .core.logging import configure_logging

    # stdio uses stdout for the JSON-RPC protocol - every log line MUST go to
    # stderr or it corrupts the stream. (In SSE mode main.py configures stdout.)
    configure_logging(get_settings(), stream=sys.stderr)
    mcp.run(transport="stdio")
