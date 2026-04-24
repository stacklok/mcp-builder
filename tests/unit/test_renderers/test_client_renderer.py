"""Tests for the client renderer."""

from mcp_builder.generate.plan import ServerPlan
from mcp_builder.generate.renderers.client import render_client_module
from mcp_builder.schema.models import APIKeyAuth


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

    def test_has_request_bytes_method(self, plan: ServerPlan) -> None:
        """Binary/non-JSON endpoints need a bytes-returning path so the
        tool renderer can base64-encode the body for MCP transport."""
        source = render_client_module(plan)
        assert "async def request_bytes(" in source
        # Signature must promise bytes, not dict.
        assert "-> bytes:" in source
        # JSON path is still a single .json() read.
        assert "return response.json()" in source

    def test_has_request_text_method(self, plan: ServerPlan) -> None:
        """Text endpoints need a str-returning path so the tool renderer
        can hand the model decoded text (Drive export, HTML, CSV, ...)
        without base64 wrapping."""
        source = render_client_module(plan)
        assert "async def request_text(" in source
        assert "return response.text" in source

    def test_accept_header_split_by_response_kind(self, plan: ServerPlan) -> None:
        """JSON path advertises Accept: application/json so content-
        negotiating servers hand us JSON. Text path prefers text/* with
        a */* fallback for servers that don't honor the quality
        weighting. Binary path uses */* so non-JSON media types (PDF,
        octet-stream) aren't rejected by stricter servers."""
        source = render_client_module(plan)
        assert '"Accept"' in source
        assert '"application/json"' in source
        assert '"text/*, */*;q=0.8"' in source
        assert '"*/*"' in source

    def test_json_path_handles_empty_body(self, plan: ServerPlan) -> None:
        """204 / empty-body 2xx responses must not invoke ``.json()`` —
        an empty body raises JSONDecodeError. Return an empty dict
        instead so void endpoints (DELETE, PUT without a body) work."""
        source = render_client_module(plan)
        assert "if not response.content:" in source
        assert "return {}" in source

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
            auth=APIKeyAuth(type="api_key"),
            tools=[],
            groups=[],
        )
        source = render_client_module(plan)
        compile(source, "<test>", "exec")
