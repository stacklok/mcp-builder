"""Tests for tool function code generation."""

from __future__ import annotations


from mcp_builder.codegen.tools import generate_tools
from mcp_builder.schema.models import MCPScope


def test_tools_produces_valid_python(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    compile(output, "<test>", "exec")


def test_tools_has_tools_class(scope_with_tools: MCPScope, openapi_spec: dict) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert "class Tools:" in output


def test_tools_init_takes_client(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert "def __init__(self, client: APIClient)" in output
    assert "self._client = client" in output


def test_tools_imports_client(scope_with_tools: MCPScope, openapi_spec: dict) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert "from test_api_mcp.client import APIClient" in output


def test_get_endpoint_has_flat_args(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def get_item")
    func_block = output[idx : idx + 600]
    assert "itemId:" in func_block
    assert "fields:" in func_block


def test_get_endpoint_uses_annotated_field(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert "Annotated" in output
    assert "Field" in output


def test_get_endpoint_uses_correct_method(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def get_item")
    func_block = output[idx : idx + 600]
    assert '"GET"' in func_block


def test_get_endpoint_interpolates_path_param(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def get_item")
    func_block = output[idx : idx + 600]
    assert "{itemId}" in func_block


def test_get_endpoint_passes_query_params(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def get_item")
    func_block = output[idx : idx + 600]
    assert '"fields": fields' in func_block
    assert "params=" in func_block


def test_get_endpoint_no_body(scope_with_tools: MCPScope, openapi_spec: dict) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def get_item")
    func_block = output[idx : idx + 600]
    assert "json_body" not in func_block


def test_post_endpoint_has_flat_body_args(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def create_item")
    func_block = output[idx : idx + 600]
    assert "name:" in func_block
    assert "description:" in func_block


def test_post_endpoint_uses_post_method(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def create_item")
    func_block = output[idx : idx + 600]
    assert '"POST"' in func_block


def test_post_endpoint_passes_body(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    idx = output.index("async def create_item")
    func_block = output[idx : idx + 600]
    assert "json_body=" in func_block


def test_put_endpoint_has_both_path_and_body_args(
    scope_with_update: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_update, openapi_spec, "test_api_mcp")
    idx = output.index("async def update_item")
    func_block = output[idx : idx + 600]
    assert "itemId" in func_block
    assert "name" in func_block
    assert "json_body=" in func_block


def test_tool_description_in_docstring(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert '"""Get an item by ID."""' in output
    assert '"""Create a new item."""' in output


def test_tools_grouped_by_yaml_group(
    scope_multi_group: MCPScope, openapi_spec: dict
) -> None:
    output = generate_tools(scope_multi_group, openapi_spec, "test_api_mcp")
    items_idx = output.index("# --- Group: items ---")
    mutations_idx = output.index("# --- Group: mutations ---")
    get_item_idx = output.index("async def get_item")
    create_item_idx = output.index("async def create_item")
    # items group comment appears before get_item
    assert items_idx < get_item_idx
    # mutations group comment appears before create_item
    assert mutations_idx < create_item_idx
    # items group comes before mutations group
    assert items_idx < mutations_idx


def test_tools_deterministic(scope_with_tools: MCPScope, openapi_spec: dict) -> None:
    r1 = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    r2 = generate_tools(scope_with_tools, openapi_spec, "test_api_mcp")
    assert r1 == r2
