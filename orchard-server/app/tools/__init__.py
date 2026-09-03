"""Actionable tool functions for agent nodes (thin execution layer).

Kept separate from ``app/mcp_server.py`` (which only *registers* them for
external MCP clients) so agent nodes can call them directly and tests can
assert on the returned :class:`ToolResult` without an MCP round-trip.
"""
