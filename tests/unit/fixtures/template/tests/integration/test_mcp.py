"""Integration tests for the MCP server."""

import os

import pytest

from tests.integration.conftest import get_mcp_client_session

mcp_client = pytest.mark.skipif(
    not os.getenv("MCP_SERVER_URL"),
    reason="MCP_SERVER_URL environment variable not set.",
)


@mcp_client
class TestMCPClient:
    @pytest.mark.asyncio
    async def test_mcp_client_list_tools(self):
        async with get_mcp_client_session() as session:
            tools_result = await session.list_tools()
            tool_names = [tool.name for tool in tools_result.tools]
            assert "hello" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_client_call_hello_tool(self):
        async with get_mcp_client_session() as session:
            result = await session.call_tool("hello", arguments={"name": "Alice"})
            assert result is not None
