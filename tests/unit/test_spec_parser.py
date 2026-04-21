"""Tests for spec package — OpenAPI spec loading and parameter extraction."""

import json

import pytest
import yaml

from mcp_builder.spec import (
    ExtractedBodyField,
    ExtractedParameter,
    get_body_fields,
    get_parameters,
    get_response_content_types,
    load_openapi_spec,
    parse_endpoint,
    resolve_response_ref,
)


def _load_inline_spec(doc, tmp_path):
    """Serialize a dict to YAML and load it as an OpenAPI spec.

    Used by the error-path tests that need a minimal in-memory spec.
    """
    f = tmp_path / "spec.yaml"
    f.write_text(yaml.safe_dump(doc))
    return load_openapi_spec(f)


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


# ---------------------------------------------------------------------------
# extract_schema_type / schema_to_type — strict error behavior
# ---------------------------------------------------------------------------


class TestExtractSchemaType:
    def test_raises_on_no_schema(self, tmp_path):
        """Parameter with no schema raises ValueError (not silent default)."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "0.1"},
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "op",
                        "parameters": [{"name": "q", "in": "query", "required": False}],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_file = tmp_path / "no_schema.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        with pytest.raises(ValueError, match="no inline schema"):
            get_parameters(spec, "GET", "/x")

    def test_resolves_ref_schema(self, tmp_path):
        """Parameter whose schema is a $ref is resolved against components.schemas."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "0.1"},
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "op",
                        "parameters": [
                            {
                                "name": "q",
                                "in": "query",
                                "required": False,
                                "schema": {"$ref": "#/components/schemas/Foo"},
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Foo": {"type": "string"},
                }
            },
        }
        spec_file = tmp_path / "ref_schema.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        params = get_parameters(spec, "GET", "/x")
        assert len(params) == 1
        assert params[0].name == "q"
        assert params[0].schema_type == "string"

    def test_resolves_nested_ref_chain(self, tmp_path):
        """Parameter schema $ref → $ref → inline is followed to the end."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "0.1"},
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "op",
                        "parameters": [
                            {
                                "name": "q",
                                "in": "query",
                                "required": False,
                                "schema": {"$ref": "#/components/schemas/Foo"},
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Foo": {"$ref": "#/components/schemas/Bar"},
                    "Bar": {"type": "integer"},
                }
            },
        }
        spec_file = tmp_path / "nested_ref.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        params = get_parameters(spec, "GET", "/x")
        assert len(params) == 1
        assert params[0].schema_type == "integer"

    def test_raises_on_missing_ref_target(self, tmp_path):
        """Parameter $ref pointing at a nonexistent component raises ValueError."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "0.1"},
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "op",
                        "parameters": [
                            {
                                "name": "q",
                                "in": "query",
                                "required": False,
                                "schema": {"$ref": "#/components/schemas/Missing"},
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {"schemas": {}},
        }
        spec_file = tmp_path / "missing_ref.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        with pytest.raises(ValueError, match="not found in components.schemas"):
            get_parameters(spec, "GET", "/x")


class TestSchemaToType:
    def test_no_type_defaults_to_object(self, tmp_path):
        """Schema with no type field defaults to object (dict)."""
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "0.1"},
            "paths": {
                "/x": {
                    "post": {
                        "operationId": "op",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "freeform": {
                                                # no type at all
                                                "description": "free-form field"
                                            }
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_file = tmp_path / "no_type.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        fields = get_body_fields(spec, "POST", "/x")
        assert len(fields) == 1
        assert fields[0].name == "freeform"
        assert fields[0].schema_type == "object"


# ---------------------------------------------------------------------------
# Composed body fields (allOf / oneOf / anyOf)
# ---------------------------------------------------------------------------


class TestComposedBodyFields:
    def test_allof_merges_properties(self, spec):
        """allOf merges properties from $ref and inline sub-schemas."""
        fields = get_body_fields(spec, "POST", "/items-allof")
        names = {f.name for f in fields}
        assert "id" in names
        assert "created_at" in names
        assert "priority" in names

    def test_allof_merges_required(self, spec):
        """allOf unions required lists from all sub-schemas."""
        fields = get_body_fields(spec, "POST", "/items-allof")
        required = {f.name for f in fields if f.required}
        assert "id" in required
        assert "priority" in required

    def test_allof_refs_only(self, spec):
        """allOf with only $ref sub-schemas resolves all."""
        fields = get_body_fields(spec, "POST", "/items-allof-refs")
        names = {f.name for f in fields}
        assert "id" in names
        assert "created_at" in names
        assert "priority" in names

    def test_oneof_merges_all_variants(self, spec):
        """oneOf merges properties from all variants."""
        fields = get_body_fields(spec, "POST", "/items-oneof")
        names = {f.name for f in fields}
        assert "name" in names
        assert "color" in names
        assert "size" in names

    def test_oneof_fields_not_required(self, spec):
        """oneOf fields are not required — any variant may omit them."""
        fields = get_body_fields(spec, "POST", "/items-oneof")
        for f in fields:
            assert f.required is False

    def test_anyof_merges_variants(self, spec):
        """anyOf merges all variant properties."""
        fields = get_body_fields(spec, "POST", "/items-anyof")
        names = {f.name for f in fields}
        assert "text" in names
        assert "html" in names

    def test_anyof_fields_not_required(self, spec):
        """anyOf fields are not required."""
        fields = get_body_fields(spec, "POST", "/items-anyof")
        for f in fields:
            assert f.required is False

    def test_ref_property_resolved(self, spec):
        """$ref on an individual body property resolves to its type."""
        fields = get_body_fields(spec, "POST", "/items-with-ref-property")
        names = {f.name for f in fields}
        assert "item" in names
        assert "note" in names
        item_field = next(f for f in fields if f.name == "item")
        assert item_field.schema_type == "object"
        assert item_field.required is True


# ---------------------------------------------------------------------------
# get_response_content_types
# ---------------------------------------------------------------------------


class TestGetResponseContentTypes:
    """Exercise the response-media-type extraction helper.

    The helper feeds the validator's non-JSON-response check, so the
    cases here mirror the decisions the validator needs to make:
    plain JSON, binary-only, mixed, no-content, and $ref-resolved.
    """

    def test_json_response(self, spec):
        """Plain application/json response maps status -> [media]."""
        result = get_response_content_types(spec, "GET", "/items/{itemId}")
        assert result == {"200": ["application/json"]}

    def test_binary_only_response(self, spec):
        """Binary-only endpoint reports its media type."""
        result = get_response_content_types(
            spec, "GET", "/employees/{employeeId}/photo"
        )
        assert result == {"200": ["image/jpeg"]}

    def test_mixed_response_sorted(self, spec):
        """Mixed content types are returned sorted for stable output."""
        result = get_response_content_types(spec, "GET", "/reports/{reportId}/download")
        assert result == {"200": ["application/json", "application/pdf"]}

    def test_response_without_content_block(self, spec):
        """A 2xx response with no content block yields an empty list,
        not a missing key — that distinguishes '204 No Content' from
        'spec omits responses entirely'."""
        # GET /items declares 200 with no content block
        result = get_response_content_types(spec, "GET", "/items")
        assert result == {"200": []}

    def test_response_ref_resolved(self, spec):
        """A $ref'd 2xx Response resolves to its underlying content types."""
        result = get_response_content_types(spec, "GET", "/shared-binary")
        assert result == {"200": ["image/png"]}

    def test_ignores_non_2xx_responses(self, tmp_path):
        """Error/redirect responses don't shape the generated return type."""
        from mcp_builder.spec import load_openapi_spec as _load

        doc = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/ok": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {"application/json": {}},
                            },
                            "404": {
                                "description": "not found",
                                "content": {"text/plain": {}},
                            },
                        }
                    }
                }
            },
        }
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.safe_dump(doc))
        small_spec = _load(f)
        result = get_response_content_types(small_spec, "GET", "/ok")
        assert result == {"200": ["application/json"]}
        assert "404" not in result

    def test_missing_responses_returns_empty(self, tmp_path):
        """An operation with no 'responses' key returns an empty dict —
        callers treat this as 'spec is incomplete'."""
        from mcp_builder.spec import load_openapi_spec as _load

        doc = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/no-responses": {
                    "get": {
                        "responses": {},
                    }
                }
            },
        }
        f = tmp_path / "spec.yaml"
        f.write_text(yaml.safe_dump(doc))
        small_spec = _load(f)
        assert get_response_content_types(small_spec, "GET", "/no-responses") == {}

    def test_unknown_path_raises(self, spec):
        with pytest.raises(KeyError):
            get_response_content_types(spec, "GET", "/nope")

    def test_unknown_method_raises(self, spec):
        with pytest.raises(KeyError):
            get_response_content_types(spec, "DELETE", "/items/{itemId}")

    def test_default_included_when_no_2xx(self, tmp_path):
        """Thinly-spec'd APIs sometimes declare only ``default``.
        Treat it as the success shape in that narrow case."""
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/x": {
                        "get": {
                            "responses": {
                                "default": {
                                    "description": "ok",
                                    "content": {"application/json": {}},
                                }
                            }
                        }
                    }
                },
            },
            tmp_path,
        )
        result = get_response_content_types(small_spec, "GET", "/x")
        assert result == {"default": ["application/json"]}

    def test_default_ignored_when_2xx_present(self, tmp_path):
        """When an explicit 2xx exists, ``default`` is the error
        fallback and must not contaminate the success analysis."""
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {
                    "/x": {
                        "get": {
                            "responses": {
                                "200": {
                                    "description": "ok",
                                    "content": {"application/json": {}},
                                },
                                "default": {
                                    "description": "error",
                                    "content": {"text/plain": {}},
                                },
                            }
                        }
                    }
                },
            },
            tmp_path,
        )
        result = get_response_content_types(small_spec, "GET", "/x")
        assert result == {"200": ["application/json"]}
        assert "default" not in result


class TestResolveResponseRef:
    """Error-path coverage for resolve_response_ref.

    The happy path is already exercised transitively via
    TestGetResponseContentTypes.test_response_ref_resolved. Each
    rejection branch has its own non-obvious failure mode — in
    particular the nested-$ref case, which a future "helpful" refactor
    might silently loosen.
    """

    def test_rejects_external_ref(self, tmp_path):
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
            },
            tmp_path,
        )
        with pytest.raises(ValueError, match="only local"):
            resolve_response_ref(small_spec, "https://example.com/r/Foo")

    def test_rejects_when_components_missing(self, tmp_path):
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
            },
            tmp_path,
        )
        with pytest.raises(ValueError, match="no 'components' section"):
            resolve_response_ref(small_spec, "#/components/responses/Missing")

    def test_rejects_missing_component_name(self, tmp_path):
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
                "components": {
                    "responses": {
                        "Other": {"description": "ok"},
                    }
                },
            },
            tmp_path,
        )
        with pytest.raises(ValueError, match="'NotThere' not found"):
            resolve_response_ref(small_spec, "#/components/responses/NotThere")

    def test_rejects_nested_ref(self, tmp_path):
        """A components.responses entry that is itself a $ref should be
        rejected — the resolver does not walk chains."""
        small_spec = _load_inline_spec(
            {
                "openapi": "3.0.3",
                "info": {"title": "T", "version": "1"},
                "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
                "components": {
                    "responses": {
                        "Chained": {"$ref": "#/components/responses/Target"},
                        "Target": {"description": "ok"},
                    }
                },
            },
            tmp_path,
        )
        with pytest.raises(ValueError, match="nested"):
            resolve_response_ref(small_spec, "#/components/responses/Chained")
