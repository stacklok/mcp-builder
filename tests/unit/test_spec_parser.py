"""Tests for codegen.spec_parser — OpenAPI spec loading and parameter extraction."""

import json

import pytest
import yaml

from mcp_builder.codegen.spec_parser import (
    ExtractedBodyField,
    ExtractedParameter,
    get_body_fields,
    get_parameters,
    load_openapi_spec,
    parse_endpoint,
)


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

    def test_swagger_2_gives_clear_error(self, tmp_path):
        """Swagger 2.0 specs should fail early with a helpful conversion hint."""
        swagger_file = tmp_path / "swagger2.json"
        swagger_file.write_text(
            json.dumps(
                {
                    "swagger": "2.0",
                    "info": {"title": "Test", "version": "1.0"},
                    "paths": {},
                }
            )
        )
        with pytest.raises(ValueError, match="Swagger.*swagger2openapi"):
            load_openapi_spec(swagger_file)


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

    def test_path_with_server_prefix_not_found(self, spec):
        """Paths must match the spec exactly; prepending the server base path is wrong."""
        with pytest.raises(KeyError, match="/v1/items/\\{itemId\\}"):
            get_parameters(spec, "GET", "/v1/items/{itemId}")

    def test_resolves_ref_parameter_in_operation(self, spec):
        """$ref parameters like '#/components/parameters/owner' are resolved."""
        params = get_parameters(spec, "GET", "/repos/{owner}/{repo}/issues")
        owner = next(p for p in params if p.name == "owner")
        assert owner.location == "path"
        assert owner.required is True
        assert owner.schema_type == "string"

    def test_resolves_ref_query_parameter(self, spec):
        """$ref query parameters are resolved with correct type."""
        params = get_parameters(spec, "GET", "/repos/{owner}/{repo}/issues")
        per_page = next(p for p in params if p.name == "per_page")
        assert per_page.location == "query"
        assert per_page.schema_type == "integer"

    def test_ref_and_inline_params_merge(self, spec):
        """$ref and inline params merge into a single list."""
        params = get_parameters(spec, "GET", "/repos/{owner}/{repo}/issues")
        names = {p.name for p in params}
        assert names == {"owner", "repo", "per_page"}

    def test_resolves_ref_parameter_at_path_level(self, spec):
        """$ref parameters at path level (not operation level) are resolved."""
        params = get_parameters(spec, "GET", "/repos/{owner}/{repo}/issues")
        owner = next(p for p in params if p.name == "owner")
        assert owner.location == "path"
        assert owner.required is True
        assert owner.schema_type == "string"
        assert owner.description == "The account owner of the repository."

    def test_ref_to_missing_component_raises(self, tmp_path):
        """A $ref pointing to a nonexistent component raises ValueError."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "Minimal", "version": "0.0.1"},
            "paths": {
                "/things": {
                    "get": {
                        "operationId": "testOp",
                        "parameters": [{"$ref": "#/components/parameters/nonexistent"}],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {"parameters": {}},
        }
        spec_file = tmp_path / "minimal.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        with pytest.raises(ValueError, match="nonexistent.*not found"):
            get_parameters(spec, "GET", "/things")


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

    def test_resolves_ref_request_body(self, spec):
        """A $ref requestBody pointing to components.requestBodies is resolved."""
        fields = get_body_fields(spec, "POST", "/items-with-ref-body")
        names = {f.name for f in fields}
        assert "name" in names
        assert "description" in names
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.required is True
        assert name_field.description == "The name of the item."

    def test_ref_request_body_missing_component_raises(self, tmp_path):
        """A $ref requestBody pointing to a nonexistent component raises ValueError."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "Minimal", "version": "0.0.1"},
            "paths": {
                "/things": {
                    "post": {
                        "operationId": "createThing",
                        "requestBody": {
                            "$ref": "#/components/requestBodies/Nonexistent"
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
            "components": {"requestBodies": {}},
        }
        spec_file = tmp_path / "minimal.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        with pytest.raises(ValueError, match="Nonexistent.*not found"):
            get_body_fields(spec, "POST", "/things")

    def test_missing_path_raises(self, spec):
        with pytest.raises(KeyError, match="not found in spec"):
            get_body_fields(spec, "POST", "/nonexistent")
