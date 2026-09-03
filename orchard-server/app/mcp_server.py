"""Model Context Protocol server for the orchard backend.

Exposes the same domain logic the REST API uses (``TreeService`` /
``TaskService`` / ``SourceService`` for the local DB; ``RachioService`` for
read-only irrigation zones) as MCP tools + a resource, so AI agents can read
and mutate orchard data without going through HTTP.

Two transports:

* **SSE** - mounted onto the FastAPI app at ``/mcp`` (see ``app/main.py``).
  Clients connect to ``/mcp/sse``.
* **stdio** - ``python -m app.mcp_server`` (for Claude Desktop / Cursor).

Every tool call gets its own short-lived Postgres connection (from the same
pooled engine the HTTP API uses - see ``app/core/db.py``), shared by every
service and wrapped in a transaction.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from .agent.agronomist import format_priority_context
from .config import get_settings
from .core import db
from .rag.vector_store import get_vector_store
from .repositories.source_repository import SourceRepository
from .repositories.task_repository import TaskRepository
from .repositories.tree_repository import TreeRepository
from .schemas.task import TaskBaselineItem, TaskCreate, TaskPriorityUpdate
from .schemas.tree import TreeCreate, TreeUpdate
from .services.exceptions import DomainError
from .services.rachio import RachioService, get_rachio_service
from .services.source_service import SourceService
from .services.task_service import TaskService
from .services.tree_service import TreeService
from .services.validators import get_default_validation_agent
from .tools import irrigation as _irrigation_tools

mcp = FastMCP("Orchard Management Server")


@dataclass
class _Services:
    trees: TreeService
    tasks: TaskService
    sources: SourceService


@contextlib.asynccontextmanager
async def _session() -> AsyncIterator[_Services]:
    """Yield connection-bound services. Commit on clean exit, roll back on any
    exception (``db.connection`` handles both)."""
    settings = get_settings()
    validator = get_default_validation_agent()
    async with db.connection(settings) as conn:
        tree_repo = TreeRepository(conn)
        task_repo = TaskRepository(conn)
        source_repo = SourceRepository(conn)
        yield _Services(
            trees=TreeService(tree_repo, validator),
            tasks=TaskService(task_repo, tree_repo),
            sources=SourceService(
                source_repo, tree_repo, get_vector_store(settings), settings
            ),
        )


def _rachio() -> RachioService:
    """The process-wide Rachio client (not DB-bound - lives outside _session)."""
    return get_rachio_service(get_settings())


# ---------------------------------------------------------------------------
# Tools - Rachio irrigation zones (READ-ONLY + one watering action)
# ---------------------------------------------------------------------------
# Zone/device configuration lives in the grower's Rachio account and is edited
# ONLY in the official Rachio app. There is no create/update/delete tool.

@mcp.tool()
async def list_zones() -> list[dict]:
    """List every irrigation zone from the grower's Rachio account, grouped by
    device (controller).

    Returns a list of devices, each ``{id, name, status, model, zones: [...]}``
    where every zone has ``id`` (string), ``name``, ``enabled``,
    ``zone_number`` and the ``custom_*`` config objects (nozzle, soil, slope,
    crop/vegetation, shade/sun). **Read-only** - zone settings are changed in
    the Rachio app, never here. Errors cleanly if Rachio is not configured.
    """
    try:
        devices = await _rachio().get_devices_and_zones()
    except DomainError as exc:
        raise ToolError(str(exc)) from exc
    return [d.model_dump(mode="json") for d in devices]


@mcp.tool()
async def get_zone_details(zone_id: str) -> dict:
    """Fetch the full read-only configuration for one Rachio zone.

    Args:
        zone_id: The Rachio zone id (a string/UUID, from ``list_zones``).

    Returns ``{device_id, device_name, zone: {...}}``. Errors if the zone id
    is unknown or Rachio is not configured.
    """
    try:
        device, zone = await _rachio().get_zone(zone_id)
    except DomainError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "device_id": device.id,
        "device_name": device.name,
        "zone": zone.model_dump(mode="json"),
    }


@mcp.tool()
async def trigger_rachio_watering(zone_id: str, duration_minutes: int) -> str:
    """Start a manual watering run on one Rachio zone. **This turns on real
    irrigation hardware.**

    This is the Foreman agent's JIT irrigation action: when a scheduling turn
    calls for watering a zone now, call this with the zone id and how long to
    run it. It is the only write this system performs against Rachio.

    Args:
        zone_id: The Rachio zone id (string, from ``list_zones``).
        duration_minutes: Run length in minutes (clamped to Rachio's 1..180 range).

    Returns a short confirmation. Errors if the zone/Rachio is unavailable.
    """
    minutes = max(1, min(int(duration_minutes), 180))
    try:
        await _rachio().start_zone_watering(zone_id, minutes * 60)
    except DomainError as exc:
        raise ToolError(str(exc)) from exc
    return f"Started watering Rachio zone {zone_id} for {minutes} minute(s)."


# ---------------------------------------------------------------------------
# Tools - irrigation supervisor actions (Phase 2; STUBBED execution)
# ---------------------------------------------------------------------------

@mcp.tool()
def rachio_skip_schedule(zone_id: str, days: int) -> dict:
    """Pause a Rachio zone's baseline schedule for ``days`` days - the
    water-saving action when rain covers demand. Phase 2: logged, not executed."""
    return _irrigation_tools.rachio_skip_schedule(zone_id, days).as_dict()


@mcp.tool()
def pass_no_action(zone_id: str) -> dict:
    """Take no action on ``zone_id`` - defer to its baseline Rachio schedule."""
    return _irrigation_tools.pass_no_action(zone_id).as_dict()


@mcp.tool()
def start_zone_watering(zone_id: str, duration_minutes: int) -> dict:
    """Force an immediate emergency run of ``zone_id``. Phase 2: logged, not
    executed (use ``trigger_rachio_watering`` for the real hardware write)."""
    return _irrigation_tools.start_zone_watering(zone_id, duration_minutes).as_dict()


# ---------------------------------------------------------------------------
# Tools - trees
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_trees(zone_id: str | None = None) -> list[dict]:
    """List tree records, optionally scoped to one Rachio zone id.

    Args:
        zone_id: If provided (a Rachio zone id string), only trees bound to
            that zone are returned; otherwise every tree is returned.

    Each tree includes ``tree_id``, ``species``, ``variety``, ``zone_id``,
    ``planted_date`` (ISO date or null) and the derived ``age_days`` /
    ``age_years``.
    """
    async with _session() as svc:
        rows = await svc.trees.list_trees(zone_id=zone_id)
        return [t.model_dump(mode="json") for t in rows]


@mcp.tool()
async def get_tree_details(tree_id: int) -> dict:
    """Fetch a single tree record by its numeric id, including derived age.

    Args:
        tree_id: The tree's integer primary key.

    Errors if no tree with that id exists.
    """
    async with _session() as svc:
        try:
            return (await svc.trees.get_tree(tree_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_tree(
    species: str,
    variety: str,
    zone_id: str | None = None,
    planted_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a new tree record and return the created row.

    All descriptive fields are free text and are stored exactly as typed -
    there is no controlled vocabulary.

    Args:
        species: Common species name, e.g. "mango", "sapodilla", "sugar apple".
        variety: Cultivar / variety name, e.g. "Kent", "Nam Doc Mai".
        zone_id: Optional Rachio zone id (string) this tree is irrigated by.
            Free text - not validated against Rachio. Use ``list_zones`` to
            find ids.
        planted_date: Optional planting date as an ISO-8601 string (YYYY-MM-DD).
        notes: Optional free-text notes.
    """
    async with _session() as svc:
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
    zone_id: str | None = None,
    planted_date: str | None = None,
    notes: str | None = None,
    additional_context: str | None = None,
) -> dict:
    """Update fields on an existing tree. Only the arguments you pass change.

    Args:
        tree_id: The tree to update.
        species: New free-text species name.
        variety: New free-text variety name.
        zone_id: Bind the tree to this Rachio zone id (string; not validated).
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
    async with _session() as svc:
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
    async with _session() as svc:
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
    async with _session() as svc:
        rows = await svc.tasks.get_pending_queue(scheduled_before=before)
        return [t.model_dump(mode="json") for t in rows]


@mcp.tool()
async def get_task_details(task_id: int) -> dict:
    """Fetch one task by its numeric id.

    Args:
        task_id: The task's integer primary key.

    Errors if no task with that id exists.
    """
    async with _session() as svc:
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
    async with _session() as svc:
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

    async with _session() as svc:
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

    async with _session() as svc:
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
    async with _session() as svc:
        try:
            return (await svc.tasks.mark_complete(task_id)).model_dump(mode="json")
        except DomainError as exc:
            raise ToolError(str(exc)) from exc


@mcp.tool()
async def mark_tasks_complete(task_ids: list[int]) -> list[dict]:
    """Mark several tasks ``completed`` in one call - the Foreman's write path.

    Call this whenever the user says they finished work during a scheduling
    session, e.g. "done with task 3 and 5" or "completed the pruning (task 12)".
    Recurring tasks spawn their next occurrence. Unknown / already-completed
    ids are skipped.

    Args:
        task_ids: The task ids the user reported finishing.

    Returns the list of task objects that were actually completed.
    """
    async with _session() as svc:
        done = await svc.tasks.mark_many_complete(task_ids)
    return [t.model_dump(mode="json") for t in done]


@mcp.tool()
async def defer_task(task_id: int, until: str | None = None) -> dict:
    """Move a task to ``deferred`` status, optionally rescheduling it.

    Args:
        task_id: The task to defer.
        until: Optional ISO-8601 date/datetime to reschedule the task to.

    Returns the updated task object. Errors if the task does not exist.
    """
    async with _session() as svc:
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
    async with _session() as svc:
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
    async with _session() as svc:
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
    async with _session() as svc:
        try:
            linked = await svc.sources.set_tree_sources(tree_id, source_ids)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return [s.model_dump(mode="json") for s in linked]


@mcp.tool()
async def search_knowledge(query: str, tree_id: int | None = None) -> str:
    """Search the user's orchard knowledge base and return the relevant
    passages. Call this for any *"according to my sources / notes / documents"*
    question, or whenever the user wants an answer grounded in what they have
    ingested rather than general knowledge.

    Args:
        query: A natural-language question, e.g. "how often should I water a
            mango tree" or "signs of nitrogen deficiency in citrus".
        tree_id: Optional. When given, only the sources linked to that tree
            are searched (via ``link_tree_sources``). Omit to search **every**
            ingested source — the normal case.

    Consensus-fusion retrieval: results are grouped per source and ranked by
    the grower's authority order (for a tree scope) or by relevance (whole KB).
    Each hit contributes a block:
    ``[PRIORITY {n} SOURCE: {name} (ID: {id})]`` followed by the matching
    chunks. When sources conflict, prefer the lower priority number
    (Priority 1 > Priority 2). Returns a short notice if nothing was ingested /
    matched. Cite the source id(s) in your answer.
    """
    async with _session() as svc:
        scope: list[int] | None = None
        if tree_id is not None:
            try:
                scope = await svc.sources.allowed_source_ids(tree_id)
            except DomainError as exc:
                raise ToolError(str(exc)) from exc
            if not scope:
                return (
                    f"Tree {tree_id} has no linked knowledge sources. Link some "
                    f"with link_tree_sources, or call search_knowledge without a "
                    f"tree_id to search the whole knowledge base."
                )
        groups = await svc.sources.search(query, source_ids=scope)

    if not groups:
        where = "the knowledge base" if scope is None else f"tree {tree_id}'s sources"
        return f"No relevant passages found in {where}."

    return format_priority_context(groups)


@mcp.prompt(title="Ask the knowledge base")
def ask_sources(question: str) -> str:
    """Answer a question strictly from the user's ingested sources."""
    return (
        f"Use the `search_knowledge` tool to look up the orchard knowledge "
        f"base, then answer this question using ONLY what the returned sources "
        f"say. Cite the source id(s). If the sources don't cover it, say so.\n\n"
        f"Question: {question}"
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("orchard://system-summary")
async def system_summary() -> str:
    """A plain-text snapshot of orchard database stats for grounding an agent.

    Reports tree / task counts, pending-task backlog, a per-species tree
    tally, whether Rachio is connected, and overall system status.
    """
    try:
        async with _session() as svc:
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

    rachio = "configured" if get_settings().rachio_enabled else "not configured"
    lines = [
        "Orchard Management System - summary",
        "-----------------------------------",
        f"Trees:            {len(tree_rows)}",
        f"Trees w/o zone:   {unassigned}",
        f"Tasks (total):    {len(all_tasks)}",
        f"Tasks (pending):  {len(pending)}",
        f"KB sources:       {len(source_rows)}",
        f"Rachio:           {rachio}",
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
