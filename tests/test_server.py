"""Tests for src/server.py: the MCP wiring layer.

The tool logic itself is covered by tests/test_agent_tools.py; this file
checks the one thing that module can't -- that the FastMCP server actually
registers all five typed tools (and nothing else, e.g. no run_sql). Listing
registered tools touches no database and no network.
"""

import asyncio

from src.server import mcp

EXPECTED_TOOLS = {
    "resolve_vendor",
    "entity_profile",
    "cross_level_exposure",
    "compare_buyers",
    "coverage",
}


def test_server_registers_exactly_the_five_typed_tools():
    tools = asyncio.run(mcp.get_tools())
    assert set(tools.keys()) == EXPECTED_TOOLS


def test_every_registered_tool_has_a_description():
    tools = asyncio.run(mcp.get_tools())
    for name, tool in tools.items():
        assert tool.description, f"{name} has no description for MCP clients to show"
