"""Tests for the server wiring renderer."""

import textwrap

from mcp_builder.codegen.plan import AuthPlan, ServerPlan, ToolPlan
from mcp_builder.codegen.renderers.server_wiring import (
    patch_app_builder,
    patch_mcp_builder,
)

# Post-scaffold mcp_builder.py source — matches the real mcp-template-py
# after scaffold has renamed mcp_template_py -> test_api_mcp.
_MCP_BUILDER_SOURCE = textwrap.dedent("""\
    import structlog
    from mcp.server.fastmcp import FastMCP

    from test_api_mcp.api.tools import Tools
    from test_api_mcp.settings import Settings


    class MCPBuilder:
        logger: structlog.BoundLogger = structlog.get_logger()

        @staticmethod
        def build_mcp(
            settings: Settings | None = None,
        ) -> FastMCP:
            settings = settings or Settings()

            mcp = FastMCP("mcp-template-py", host=settings.mcp_host, port=settings.mcp_port)

            # Register tools directly - preserves original docstrings
            tools = Tools()
            mcp.add_tool(tools.hello)

            return mcp
""")

_APP_BUILDER_SOURCE = textwrap.dedent("""\
    from test_api_mcp.api.mcp_builder import MCPBuilder

    class AppBuilder:
        @staticmethod
        def build_app():
            return MCPBuilder.build_mcp()
""")


def _make_plan(tools: list[ToolPlan] | None = None) -> ServerPlan:
    return ServerPlan(
        module_name="test_api_mcp",
        server_name="test-api",
        description="A test API server.",
        base_url="https://api.example.com",
        auth=AuthPlan(type="api_key"),
        tools=tools or [],
        groups=[],
    )


def _make_tool(name: str = "get_item") -> ToolPlan:
    return ToolPlan(
        tool_name=name,
        class_name=name.replace("_", " ").title().replace(" ", ""),
        http_method="GET",
        path=f"/{name}",
        description=f"Run {name}.",
        path_params=[],
        query_params=[],
        body_fields=[],
        hints=[],
        group_name="default",
    )


class TestPatchMcpBuilder:
    def test_adds_client_import(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert "from test_api_mcp.client import APIClient" in result

    def test_client_import_before_settings(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        client_pos = result.index("import APIClient")
        settings_pos = result.index("import Settings")
        assert client_pos < settings_pos

    def test_fixes_server_name(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert 'FastMCP("test-api"' in result
        assert 'FastMCP("mcp-template-py"' not in result

    def test_wires_client_to_tools(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert "tools = Tools(APIClient())" in result
        assert "tools = Tools()" not in result

    def test_removes_template_tool(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert "tools.hello" not in result

    def test_registers_all_tools(self) -> None:
        plan = _make_plan(tools=[_make_tool("get_item"), _make_tool("create_item")])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert "mcp.add_tool(tools.get_item)" in result
        assert "mcp.add_tool(tools.create_item)" in result

    def test_registration_order_matches_plan(self) -> None:
        plan = _make_plan(tools=[_make_tool("alpha"), _make_tool("beta")])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        alpha_pos = result.index("tools.alpha")
        beta_pos = result.index("tools.beta")
        assert alpha_pos < beta_pos

    def test_registrations_before_return(self) -> None:
        plan = _make_plan(tools=[_make_tool()])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        reg_pos = result.index("mcp.add_tool(tools.get_item)")
        return_pos = result.index("return mcp")
        assert reg_pos < return_pos

    def test_compiles(self) -> None:
        plan = _make_plan(tools=[_make_tool("get_item"), _make_tool("create_item")])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        compile(result, "<test>", "exec")

    def test_zero_tools(self) -> None:
        plan = _make_plan(tools=[])
        result = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        compile(result, "<test>", "exec")
        assert "tools.hello" not in result
        assert "return mcp" in result

    def test_deterministic(self) -> None:
        plan = _make_plan(tools=[_make_tool("a"), _make_tool("b")])
        r1 = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        r2 = patch_mcp_builder(_MCP_BUILDER_SOURCE, plan)
        assert r1 == r2


class TestPatchAppBuilder:
    def test_returns_source_unchanged(self) -> None:
        plan = _make_plan()
        result = patch_app_builder(_APP_BUILDER_SOURCE, plan)
        assert result == _APP_BUILDER_SOURCE
