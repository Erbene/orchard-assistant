"""Smoke test for the MCP server: a stdio tool + resource round-trip.

Runs the server exactly as Claude Desktop would (``python -m app.mcp_server``)
and drives it with the MCP client's stdio transport.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_ROOT = Path(__file__).resolve().parent.parent


async def _exercise(db_path: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(SERVER_ROOT),
        env={"ORCHARD_DB_PATH": db_path, "PYTHONPATH": str(SERVER_ROOT)},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            assert {
                "list_zones",
                "get_zone_details",
                "list_trees",
                "get_tree_details",
                "create_tree",
                "update_tree",
                "delete_tree",
            } <= tools, tools

            created = await session.call_tool(
                "create_tree", {"species": "mango", "variety": "Kent"}
            )
            assert not created.isError, created.content

            listed = await session.call_tool("list_trees", {})
            assert not listed.isError
            payload = str(listed.structuredContent) + "".join(
                getattr(c, "text", "") for c in listed.content
            )
            assert "Kent" in payload

            summary = await session.read_resource("orchard://system-summary")
            body = summary.contents[0].text
            assert "Trees:            1" in body
            assert "mango: 1" in body

            missing = await session.call_tool(
                "get_tree_details", {"tree_id": 9999}
            )
            assert missing.isError  # DomainError -> ToolError -> isError


def test_mcp_stdio_round_trip(tmp_path: Path) -> None:
    asyncio.run(_exercise(str(tmp_path / "mcp.db")))
