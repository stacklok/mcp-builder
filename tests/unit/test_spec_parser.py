"""Tests for OpenAPI spec parser."""

from pathlib import Path

import pytest

from mcp_builder.codegen.spec_parser import (
    OpenAPIParameter,
    find_operation,
    get_parameters,
    load_openapi_spec,
    parse_endpoint,
)


def test_load_yaml_spec(openapi_spec_path: Path) -> None:
    spec = load_openapi_spec(openapi_spec_path)
    assert spec["info"]["title"] == "Test API"
    assert "/items/{itemId}" in spec["paths"]


def test_load_nonexistent_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_openapi_spec(Path("/nonexistent/spec.yaml"))


def test_parse_get_endpoint() -> None:
    method, path = parse_endpoint("GET /items/{itemId}")
    assert method == "GET"
    assert path == "/items/{itemId}"


def test_parse_post_endpoint() -> None:
    method, path = parse_endpoint("POST /items")
    assert method == "POST"
    assert path == "/items"


def test_find_get_operation(openapi_spec: dict) -> None:
    op = find_operation(openapi_spec, "GET", "/items/{itemId}")
    assert op.operation_id == "getItem"


def test_find_post_operation(openapi_spec: dict) -> None:
    op = find_operation(openapi_spec, "POST", "/items")
    assert op.operation_id == "createItem"
    assert op.request_body_ref is not None


def test_find_missing_path_raises(openapi_spec: dict) -> None:
    with pytest.raises(KeyError, match="/nonexistent"):
        find_operation(openapi_spec, "GET", "/nonexistent")


def test_find_missing_method_raises(openapi_spec: dict) -> None:
    with pytest.raises(KeyError, match="DELETE"):
        find_operation(openapi_spec, "DELETE", "/items/{itemId}")


def test_get_parameters_merges_path_and_query(openapi_spec: dict) -> None:
    params = get_parameters(openapi_spec, "GET", "/items/{itemId}")
    names = {p.name for p in params}
    assert names == {"itemId", "fields"}


def test_get_parameters_returns_typed_objects(openapi_spec: dict) -> None:
    params = get_parameters(openapi_spec, "GET", "/items/{itemId}")
    item_id = next(p for p in params if p.name == "itemId")
    assert isinstance(item_id, OpenAPIParameter)
    assert item_id.location == "path"
    assert item_id.required is True
    assert item_id.schema_type == "string"


def test_get_parameters_post_no_params(openapi_spec: dict) -> None:
    params = get_parameters(openapi_spec, "POST", "/items")
    assert params == []
