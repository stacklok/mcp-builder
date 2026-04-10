"""Tests for Pydantic model generation from OpenAPI specs."""

from pathlib import Path

from mcp_builder.codegen.models import (
    generate_body_models,
    generate_models_file,
    generate_parameter_model,
    tool_name_to_class,
)
from mcp_builder.schema.models import MCPScope


def test_tool_name_to_class_simple() -> None:
    assert tool_name_to_class("get_item") == "GetItem"


def test_tool_name_to_class_multi_word() -> None:
    assert tool_name_to_class("list_all_files") == "ListAllFiles"


def test_tool_name_to_class_single_word() -> None:
    assert tool_name_to_class("status") == "Status"


def test_body_models_produces_valid_python(
    openapi_spec_path: Path, tmp_path: Path
) -> None:
    output = generate_body_models(openapi_spec_path, tmp_path)
    assert "class Item" in output
    assert "class CreateItemRequest" in output


def test_body_models_uses_pydantic(openapi_spec_path: Path, tmp_path: Path) -> None:
    output = generate_body_models(openapi_spec_path, tmp_path)
    assert "BaseModel" in output


def test_param_model_for_get_endpoint(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    tool = scope_with_tools.groups[0].tools[0]  # get_item
    output = generate_parameter_model(tool, openapi_spec)
    assert output is not None
    assert "class GetItemParams" in output


def test_param_model_yaml_override_wins(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    tool = scope_with_tools.groups[0].tools[0]  # get_item
    output = generate_parameter_model(tool, openapi_spec)
    assert output is not None
    # YAML: "The unique identifier..." vs Spec: "The ID of the item."
    assert "unique identifier" in output
    assert "The ID of the item" not in output


def test_param_model_post_no_params_returns_none(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    tool = scope_with_tools.groups[0].tools[1]  # create_item (POST, no path/query)
    output = generate_parameter_model(tool, openapi_spec)
    assert output is None


def test_param_model_optional_has_none_default(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    tool = scope_with_tools.groups[0].tools[0]
    output = generate_parameter_model(tool, openapi_spec)
    assert output is not None
    assert "None" in output  # fields param is optional


def test_param_model_required_has_ellipsis(
    scope_with_tools: MCPScope, openapi_spec: dict
) -> None:
    tool = scope_with_tools.groups[0].tools[0]
    output = generate_parameter_model(tool, openapi_spec)
    assert output is not None
    assert "..." in output  # itemId is required


def test_models_file_combines_body_and_params(
    scope_with_tools: MCPScope,
    openapi_spec: dict,
    openapi_spec_path: Path,
    tmp_path: Path,
) -> None:
    output = generate_models_file(
        scope_with_tools, openapi_spec, openapi_spec_path, tmp_path
    )
    assert "class Item" in output
    assert "class GetItemParams" in output


def test_models_file_deterministic(
    scope_with_tools: MCPScope,
    openapi_spec: dict,
    openapi_spec_path: Path,
    tmp_path: Path,
) -> None:
    d1 = tmp_path / "r1"
    d2 = tmp_path / "r2"
    d1.mkdir()
    d2.mkdir()
    r1 = generate_models_file(scope_with_tools, openapi_spec, openapi_spec_path, d1)
    r2 = generate_models_file(scope_with_tools, openapi_spec, openapi_spec_path, d2)
    assert r1 == r2
