"""Tests for the client renderer."""

from mcp_builder.codegen.plan import AuthPlan, ServerPlan
from mcp_builder.codegen.renderers.client import render_client_module


class TestRenderClientModule:
    def test_compiles(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        compile(source, "<test>", "exec")

    def test_has_base_url(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "https://api.example.com" in source

    def test_has_auth_header(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "Authorization" in source
        assert "Bearer" in source

    def test_has_request_method(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "async def request(" in source

    def test_imports_get_bearer_token(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "from test_api_mcp.auth import get_bearer_token" in source

    def test_uses_httpx(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "import httpx" in source

    def test_has_api_client_class(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        assert "class APIClient:" in source

    def test_base_url_with_quotes_compiles(self) -> None:
        plan = ServerPlan(
            module_name="test_api_mcp",
            server_name="test-api",
            description="Test.",
            base_url='https://api.example.com/path"bad',
            auth=AuthPlan(type="api_key"),
            tools=[],
            groups=[],
        )
        source = render_client_module(plan)
        compile(source, "<test>", "exec")
