"""Model Context Protocol server for the orchard backend.

Exposes the same domain logic the REST API uses (``ZoneService`` /
``TreeService``) as MCP tools + resources, so AI agents can read and mutate
orchard data without going through HTTP.

Two transports:

* **SSE** - mounted onto the FastAPI app at ``/mcp`` (see ``app/main.py``).
  Clients connect to ``/mcp/sse``.
* **stdio** - ``python -m app.mcp_server`` (for Claude Desktop / Cursor).

Every tool call gets its own short-lived SQLite connection, shared by both
services and wrapped in a transaction. sqlite runs with
``check_same_thread=False`` so the async tool body and the sync driver
coexist safely on the event loop.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from .config import get_settings
from .db import connect
from .dependencies import _ensure_schema
from .repositories.tree_repository import TreeRepository
from .repositories.zone_repository import ZoneRepository
from .schemas.tree import TreeCreate, TreeUpdate
from .schemas.zone import ZoneCreate, ZoneUpdate
from .services.exceptions import DomainError
from .services.tree_service import TreeService
from .services.validators import get_default_validation_agent
from .services.zone_service import ZoneService

mcp = FastMCP("Orchard Management Server")


@contextlib.contextmanager
def _session() -> Iterator[tuple[ZoneService, TreeService]]:
    """Yield ``(zone_service, tree_service)`` backed by one fresh connection.

    Commits on clean exit, rolls back on any exception, always closes.
    """
    settings = get_settings()
    _ensure_schema(settings)
    conn = connect(settings)
    validator = get_default_validation_agent()
    zones = ZoneRepository(conn)
    trees = TreeRepository(conn)
    try:
        yield (
            ZoneService(zones, validator),
            TreeService(trees, zones, validator),
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
    with _session() as (zones, _):
        return [z.model_dump(mode="json") for z in await zones.list_zones()]


@mcp.tool()
async def get_zone_details(zone_id: int) -> dict:
    """Fetch a single zone by its numeric id.

    Args:
        zone_id: The zone's integer primary key.

    Errors if no zone with that id exists.
    """
    with _session() as (zones, _):
        try:
            return (await zones.get_zone(zone_id)).model_dump(mode="json")
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
    with _session() as (zones, _):
        try:
            created = await zones.create_zone(
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
    with _session() as (zones, _):
        try:
            updated = await zones.update_zone(zone_id, ZoneUpdate(**patch))
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
    with _session() as (zones, _):
        try:
            await zones.delete_zone(zone_id)
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
    with _session() as (_, trees):
        rows = await trees.list_trees(zone_id=zone_id)
        return [t.model_dump(mode="json") for t in rows]


@mcp.tool()
async def get_tree_details(tree_id: int) -> dict:
    """Fetch a single tree record by its numeric id, including derived age.

    Args:
        tree_id: The tree's integer primary key.

    Errors if no tree with that id exists.
    """
    with _session() as (_, trees):
        try:
            return (await trees.get_tree(tree_id)).model_dump(mode="json")
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
    with _session() as (_, trees):
        try:
            created = await trees.create_tree(
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
    with _session() as (_, trees):
        try:
            updated = await trees.update_tree(tree_id, TreeUpdate(**patch))
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return updated.model_dump(mode="json")


@mcp.tool()
async def delete_tree(tree_id: int) -> str:
    """Permanently delete a tree record.

    Args:
        tree_id: The tree to delete.

    Returns a short confirmation string. Errors if the tree does not exist.
    """
    with _session() as (_, trees):
        try:
            await trees.delete_tree(tree_id)
        except DomainError as exc:
            raise ToolError(str(exc)) from exc
        return f"Tree {tree_id} deleted."


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("orchard://system-summary")
async def system_summary() -> str:
    """A plain-text snapshot of orchard database stats for grounding an agent.

    Reports total zones, total trees, how many trees are unassigned, a
    per-species tally, and overall system status.
    """
    try:
        with _session() as (zones, trees):
            zone_rows = await zones.list_zones()
            tree_rows = await trees.list_trees()
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
        "Status:           online",
    ]
    if species_tally:
        lines.append("")
        lines.append("Trees by species:")
        for name, count in sorted(species_tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name}: {count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# stdio transport - for Claude Desktop / Cursor
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
