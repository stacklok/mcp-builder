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

    def test_strips_none_query_params(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        # None-stripping appears for query params
        lines = source.splitlines()
        none_filter_lines = [line for line in lines if "if v is not None" in line]
        assert len(none_filter_lines) == 1
        # The filter is on params, not json_body
        assert "params" in none_filter_lines[0]

    def test_preserves_none_in_json_body(self, plan: ServerPlan) -> None:
        source = render_client_module(plan)
        # json_body should NOT have None-stripping — APIs may distinguish
        # null from absent (e.g. PATCH endpoints).
        lines = source.splitlines()
        json_body_filter = [
            line for line in lines if "json_body" in line and "if v is not None" in line
        ]
        assert len(json_body_filter) == 0

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
