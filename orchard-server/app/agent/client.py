"""Bind the local FastMCP server's tools into LangChain tools.

The orchard MCP server is reused as-is over **stdio** (``python -m
app.mcp_server``), so the agent and the REST API share one code path to the
database. Swap ``_STDIO`` for ``_SSE`` to talk to a already-running server.
"""
from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent

_STDIO = {
    "orchard": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.mcp_server"],
        "cwd": str(_SERVER_ROOT),
        "env": {"PYTHONPATH": str(_SERVER_ROOT)},
    }
}

_SSE = {
    "orchard": {
        "transport": "sse",
        "url": "http://127.0.0.1:8000/mcp/sse",
    }
}


def make_mcp_client(*, use_sse: bool = False) -> MultiServerMCPClient:
    return MultiServerMCPClient(_SSE if use_sse else _STDIO)


async def load_orchard_tools(*, use_sse: bool = False) -> list[BaseTool]:
    """All orchard MCP tools as LangChain ``BaseTool``s, ready to bind to a
    model or hand to a ``ToolNode``."""
    return await make_mcp_client(use_sse=use_sse).get_tools()
