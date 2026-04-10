"""Tests for HTTP client code generation."""

from mcp_builder.codegen.client import generate_client
from mcp_builder.schema.models import MCPScope


def test_client_produces_valid_python(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    compile(output, "<test>", "exec")


def test_client_imports_httpx(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "import httpx" in output


def test_client_imports_get_bearer_token(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "from test_api_mcp.auth import get_bearer_token" in output


def test_client_uses_base_url(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "https://api.example.com" in output


def test_client_forwards_bearer_token(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "get_bearer_token()" in output
    assert "Authorization" in output
    assert "Bearer" in output


def test_client_has_api_client_class(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "class APIClient" in output


def test_client_has_request_method(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "async def request" in output


def test_client_has_close_method(minimal_scope: MCPScope) -> None:
    output = generate_client(minimal_scope, "test_api_mcp")
    assert "async def close" in output


def test_client_deterministic(minimal_scope: MCPScope) -> None:
    r1 = generate_client(minimal_scope, "test_api_mcp")
    r2 = generate_client(minimal_scope, "test_api_mcp")
    assert r1 == r2
