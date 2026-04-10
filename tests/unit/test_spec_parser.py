"""Tests for codegen.spec_parser — OpenAPI spec loading and parameter extraction."""

from pathlib import Path

import pytest

from mcp_builder.codegen.spec_parser import (
    ExtractedBodyField,
    ExtractedParameter,
    get_body_fields,
    get_parameters,
    load_openapi_spec,
    parse_endpoint,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def spec():
    """Load the test OpenAPI spec fixture."""
    return load_openapi_spec(FIXTURES / "test_openapi.yaml")


# ---------------------------------------------------------------------------
# load_openapi_spec
# ---------------------------------------------------------------------------


class TestLoadSpec:
    def test_loads_yaml_spec(self, spec):
        assert spec.info.title == "Test API"
        assert spec.paths is not None
        assert "/items/{itemId}" in spec.paths
        assert "/items" in spec.paths

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_openapi_spec("/no/such/file.yaml")

    def test_returns_typed_model(self, spec):
        """The return type should be an openapi-pydantic model, not a raw dict."""
        assert not isinstance(spec, dict)
        assert hasattr(spec, "paths")
        assert hasattr(spec, "info")
        assert hasattr(spec, "components")


# ---------------------------------------------------------------------------
# parse_endpoint
# ---------------------------------------------------------------------------


class TestParseEndpoint:
    def test_get_endpoint(self):
        method, path = parse_endpoint("GET /items/{itemId}")
        assert method == "GET"
        assert path == "/items/{itemId}"

    def test_post_endpoint(self):
        method, path = parse_endpoint("POST /items")
        assert method == "POST"
        assert path == "/items"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="must be in 'METHOD /path' format"):
            parse_endpoint("GETITEMS")


# ---------------------------------------------------------------------------
# get_parameters
# ---------------------------------------------------------------------------


class TestGetParameters:
    def test_merges_path_and_query_params(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        names = {p.name for p in params}
        assert "itemId" in names
        assert "fields" in names

    def test_returns_typed_objects(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        assert all(isinstance(p, ExtractedParameter) for p in params)

    def test_path_param_is_required(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        item_id = next(p for p in params if p.name == "itemId")
        assert item_id.required is True
        assert item_id.location == "path"

    def test_query_param_is_optional(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        fields = next(p for p in params if p.name == "fields")
        assert fields.required is False
        assert fields.location == "query"

    def test_post_no_params(self, spec):
        params = get_parameters(spec, "POST", "/items")
        assert params == []

    def test_missing_path_raises(self, spec):
        with pytest.raises(KeyError, match="not found in spec"):
            get_parameters(spec, "GET", "/nonexistent")

    def test_missing_method_raises(self, spec):
        with pytest.raises(KeyError, match="not found for path"):
            get_parameters(spec, "DELETE", "/items/{itemId}")

    def test_has_descriptions(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        item_id = next(p for p in params if p.name == "itemId")
        assert item_id.description == "The ID of the item."

    def test_has_schema_types(self, spec):
        params = get_parameters(spec, "GET", "/items/{itemId}")
        for p in params:
            assert p.schema_type == "string"


# ---------------------------------------------------------------------------
# get_body_fields
# ---------------------------------------------------------------------------


class TestGetBodyFields:
    def test_extracts_body_fields(self, spec):
        fields = get_body_fields(spec, "POST", "/items")
        names = {f.name for f in fields}
        assert "name" in names
        assert "description" in names

    def test_returns_typed_objects(self, spec):
        fields = get_body_fields(spec, "POST", "/items")
        assert all(isinstance(f, ExtractedBodyField) for f in fields)

    def test_required_field(self, spec):
        fields = get_body_fields(spec, "POST", "/items")
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.required is True

    def test_optional_field(self, spec):
        fields = get_body_fields(spec, "POST", "/items")
        desc_field = next(f for f in fields if f.name == "description")
        assert desc_field.required is False

    def test_get_has_no_body(self, spec):
        fields = get_body_fields(spec, "GET", "/items/{itemId}")
        assert fields == []

    def test_field_descriptions(self, spec):
        fields = get_body_fields(spec, "POST", "/items")
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.description == "The name of the item."

    def test_missing_path_raises(self, spec):
        with pytest.raises(KeyError, match="not found in spec"):
            get_body_fields(spec, "POST", "/nonexistent")
