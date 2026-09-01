"""Smoke test for the MCP server: a stdio tool + resource round-trip.

Runs the server exactly as Claude Desktop would (``python -m app.mcp_server``)
and drives it with the MCP client's stdio transport.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TOOLS = {
    "list_zones",
    "get_zone_details",
    "create_zone",
    "update_zone",
    "delete_zone",
    "list_trees",
    "get_tree_details",
    "create_tree",
    "update_tree",
    "delete_tree",
    "get_pending_tasks",
    "create_task",
    "create_baseline_tasks",
    "batch_update_task_priorities",
    "mark_task_complete",
    "list_sources",
    "add_text_source",
    "link_tree_sources",
    "search_ag_knowledge",
}


def _payload(result: Any) -> Any:
    """Best-effort extraction of a tool's return value across FastMCP shapes."""
    sc = result.structuredContent
    if isinstance(sc, dict):
        return sc.get("result", sc)
    if sc is not None:
        return sc
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return text
    return None


async def _exercise(db_path: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(SERVER_ROOT),
        env={
            "ORCHARD_DB_PATH": db_path,
            "ORCHARD_CHROMA_PATH": str(Path(db_path).with_name("chroma")),
            "PYTHONPATH": str(SERVER_ROOT),
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            assert EXPECTED_TOOLS <= tools, tools

            zone = await session.call_tool(
                "create_zone",
                {"name": "North Block", "soil_drainage": "sandy", "water_source": "well"},
            )
            assert not zone.isError, zone.content
            zone_id = _payload(zone)["zone_id"]

            created = await session.call_tool(
                "create_tree",
                {"species": "mango", "variety": "Kent", "zone_id": zone_id},
            )
            assert not created.isError, created.content
            assert _payload(created)["zone_id"] == zone_id

            listed = await session.call_tool("list_trees", {"zone_id": zone_id})
            assert not listed.isError
            assert _payload(listed)[0]["variety"] == "Kent"
            tree_id = _payload(created)["tree_id"]

            # --- Foreman task tools (JIT: minutes + resources required) -----
            t1 = _payload(await session.call_tool("create_task", {
                "tree_id": tree_id, "action_type": "prune", "priority_score": 3.0,
                "estimated_minutes": 30, "required_resources": ["pruning saw"],
            }))
            t2 = _payload(await session.call_tool("create_task", {
                "tree_id": tree_id, "action_type": "fertilize", "priority_score": 8.0,
                "estimated_minutes": 20, "required_resources": [],
            }))
            assert t1["required_resources"] == ["pruning saw"]

            queue = _payload(await session.call_tool("get_pending_tasks", {}))
            assert [t["action_type"] for t in queue] == ["fertilize", "prune"]

            batched = await session.call_tool("batch_update_task_priorities", {
                "task_updates": [
                    {"task_id": t1["id"], "priority_score": 10.0, "scheduled_date": "2026-09-15"},
                    {"task_id": t2["id"], "priority_score": 1.0},
                ],
            })
            assert not batched.isError, batched.content
            requeued = _payload(await session.call_tool("get_pending_tasks", {}))
            assert [t["action_type"] for t in requeued] == ["prune", "fertilize"]

            done = await session.call_tool("mark_task_complete", {"task_id": t1["id"]})
            assert _payload(done)["status"] == "completed"

            # --- RAG fusion tool: no sources linked -> graceful notice -----
            rag = await session.call_tool(
                "search_ag_knowledge", {"tree_id": tree_id, "query": "pruning"}
            )
            assert not rag.isError
            assert "No knowledge sources" in _payload(rag)

            # --- full RAG flow from the terminal: add -> link -> search -----
            src = _payload(await session.call_tool("add_text_source", {
                "name": "Mango notes",
                "text": "Prune young mango trees to three or four scaffold limbs "
                        "in the first years. Seal large cuts.",
            }))
            assert not (await session.call_tool(
                "link_tree_sources", {"tree_id": tree_id, "source_ids": [src["id"]]}
            )).isError
            fused = _payload(await session.call_tool(
                "search_ag_knowledge",
                {"tree_id": tree_id, "query": "how many limbs when pruning a young mango"},
            ))
            assert f"--- SOURCE {src['id']} ---" in fused
            assert "scaffold" in fused

            summary = await session.read_resource("orchard://system-summary")
            body = summary.contents[0].text
            assert "Zones:            1" in body
            assert "Trees:            1" in body
            assert "Tasks (total):    2" in body
            assert "KB sources:       1" in body  # the one added above
            assert "mango: 1" in body

            missing = await session.call_tool(
                "get_tree_details", {"tree_id": 9999}
            )
            assert missing.isError  # DomainError -> ToolError -> isError


def test_mcp_stdio_round_trip(tmp_path: Path) -> None:
    asyncio.run(_exercise(str(tmp_path / "mcp.db")))
