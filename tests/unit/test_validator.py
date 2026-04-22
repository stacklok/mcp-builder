"""Tests for scope validation against an OpenAPI spec."""

from pathlib import Path

import pytest

from mcp_builder.codegen.media import is_json_media_type
from mcp_builder.codegen.validator import validate_scope
from mcp_builder.schema.models import load_scope

FIXTURES = Path(__file__).parent / "fixtures"


class TestParameterCoverage:
    """Warnings when YAML params don't exist in the spec."""

    def test_body_param_missing_from_spec_warns(self, spec):
        """Body params on an endpoint with no requestBody get the
        'spec may be incomplete' warning."""
        from mcp_builder.schema.models import (
            ParamLocation,
            Parameter,
            Tool,
        )

        # POST /files has no requestBody in the test spec.
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            parameters=[
                Parameter(
                    name="name",
                    description="File name.",
                    required=True,
                    location=ParamLocation.BODY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        matching = [w for w in result.warnings if "name" in w and "requestBody" in w]
        assert matching, result.warnings
        assert any("spec may be incomplete" in w for w in matching)
        # The mismatched-properties wording must NOT fire when the spec
        # has no declared properties.
        assert not any("available:" in w for w in matching)

    def test_body_param_mismatch_lists_available_fields(self, spec):
        """When the spec has declared requestBody properties but the YAML
        body param doesn't match any of them, the warning lists the
        available field names and does not claim the spec is incomplete."""
        from mcp_builder.schema.models import (
            ParamLocation,
            Parameter,
            Tool,
        )

        # POST /items has a requestBody with CreateItemRequest
        # (properties: name, description).
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_item",
            endpoint="POST /items",
            description="Create an item.",
            parameters=[
                Parameter(
                    name="body",
                    description="Catch-all body.",
                    required=True,
                    location=ParamLocation.BODY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        matching = [
            w
            for w in result.warnings
            if "create_item" in w and "body parameter 'body'" in w
        ]
        assert matching, result.warnings
        (warning,) = matching
        assert "available: description, name" in warning
        assert "per-field body parameters" in warning
        assert "spec may be incomplete" not in warning

    def test_all_params_in_spec_no_warnings(self, spec):
        """When all YAML params exist in the spec, no param warnings."""
        scope = load_scope(FIXTURES / "test_scope.yaml")
        result = validate_scope(scope, spec)
        param_warnings = [w for w in result.warnings if "default to str" in w]
        assert param_warnings == []

    def test_query_param_missing_from_spec_warns(self, spec):
        """Query params not in spec's parameters produce a warning."""
        from mcp_builder.schema.models import ParamLocation, Parameter, Tool

        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            parameters=[
                Parameter(
                    name="nonexistent_query",
                    description="Not in spec.",
                    required=False,
                    location=ParamLocation.QUERY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        assert any("nonexistent_query" in w for w in result.warnings)


class TestResponseContentTypes:
    """Flag scopes that include non-JSON endpoints so users know the
    generated tool returns base64-encoded bytes instead of a dict."""

    def _scope_with_tool(self, tool):
        """Build a minimal scope wrapping a single tool for testing."""
        from mcp_builder.schema.models import Group

        scope = load_scope(FIXTURES / "test_scope.yaml")
        scope.groups = [
            Group(
                name="focus",
                description="Group under test.",
                tools=[tool],
            )
        ]
        return scope

    def test_binary_response_warns(self, spec):
        """An endpoint returning image/jpeg warns so users know the
        generated tool returns base64 instead of a dict. It no longer
        errors: codegen now emits a bytes path for these endpoints."""
        from mcp_builder.schema.models import ParamLocation, Parameter, Tool

        tool = Tool(
            tool_name="get_employee_photo",
            endpoint="GET /employees/{employeeId}/photo",
            description="Fetch the employee photo.",
            parameters=[
                Parameter(
                    name="employeeId",
                    description="Employee ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(self._scope_with_tool(tool), spec)
        assert not any("get_employee_photo" in e for e in result.errors)
        matching = [w for w in result.warnings if "get_employee_photo" in w]
        assert matching, result.warnings
        (msg,) = matching
        assert "image/jpeg" in msg
        assert "base64" in msg

    def test_mixed_response_passes_when_json_present(self, spec):
        """If JSON is among the declared media types, no error fires —
        the generated client can decode that path even if peers exist."""
        from mcp_builder.schema.models import ParamLocation, Parameter, Tool

        tool = Tool(
            tool_name="download_report",
            endpoint="GET /reports/{reportId}/download",
            description="Download a report.",
            parameters=[
                Parameter(
                    name="reportId",
                    description="Report ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(self._scope_with_tool(tool), spec)
        assert not any("download_report" in e for e in result.errors)

    def test_ref_response_binary_warns(self, spec):
        """A $ref'd components.responses entry is resolved before the
        content-type check, so ref-based binary responses also warn."""
        from mcp_builder.schema.models import Tool

        tool = Tool(
            tool_name="get_shared_binary",
            endpoint="GET /shared-binary",
            description="Fetch shared binary.",
            parameters=[],
        )
        result = validate_scope(self._scope_with_tool(tool), spec)
        assert not any("get_shared_binary" in e for e in result.errors)
        matching = [w for w in result.warnings if "get_shared_binary" in w]
        assert matching, result.warnings
        assert "image/png" in matching[0]

    def test_no_content_block_passes(self, spec):
        """2xx with no 'content' block is a legitimate empty response
        (204-style); must not error."""
        from mcp_builder.schema.models import Tool

        # GET /items declares 200 without a content block
        tool = Tool(
            tool_name="list_items",
            endpoint="GET /items",
            description="List items.",
            parameters=[],
        )
        result = validate_scope(self._scope_with_tool(tool), spec)
        assert not any("list_items" in e for e in result.errors)
        # Also must not warn about missing responses — they exist, they
        # just have no body.
        assert not any("list_items" in w and "no 2xx" in w for w in result.warnings)

    def test_missing_responses_warns(self, spec, tmp_path):
        """An operation with no 2xx responses declared produces a
        'spec may be incomplete' warning, not an error — we can't prove
        it's broken."""
        # Build a tiny spec with one endpoint that declares only a 500.
        import yaml as _yaml

        from mcp_builder.schema.models import Tool
        from mcp_builder.spec import load_openapi_spec as _load

        doc = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "servers": [{"url": "https://x"}],
            "paths": {
                "/only-errors": {
                    "get": {
                        "responses": {
                            "500": {"description": "server error"},
                        }
                    }
                }
            },
        }
        f = tmp_path / "spec.yaml"
        f.write_text(_yaml.safe_dump(doc))
        small_spec = _load(f)

        tool = Tool(
            tool_name="only_errors",
            endpoint="GET /only-errors",
            description="Only errors declared.",
            parameters=[],
        )
        result = validate_scope(self._scope_with_tool(tool), small_spec)
        assert not any("only_errors" in e for e in result.errors)
        assert any("only_errors" in w and "no 2xx" in w for w in result.warnings)

    def test_vendor_json_type_accepted(self, spec, tmp_path):
        """RFC 6839 structured-suffix +json types (e.g. application/vnd.api+json)
        are JSON-decodable, so they should not error."""
        import yaml as _yaml

        from mcp_builder.schema.models import Tool
        from mcp_builder.spec import load_openapi_spec as _load

        doc = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "servers": [{"url": "https://x"}],
            "paths": {
                "/vendor": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/vnd.api+json": {},
                                },
                            },
                        }
                    }
                }
            },
        }
        f = tmp_path / "spec.yaml"
        f.write_text(_yaml.safe_dump(doc))
        small_spec = _load(f)

        tool = Tool(
            tool_name="get_vendor",
            endpoint="GET /vendor",
            description="Vendor JSON response.",
            parameters=[],
        )
        result = validate_scope(self._scope_with_tool(tool), small_spec)
        assert not any("get_vendor" in e for e in result.errors)

    def test_mixed_status_codes_with_non_json_warns(self, tmp_path):
        """Per-status check: a spec that returns PDF on 200 and JSON on
        201 still warns. The generated tool commits to one return shape,
        even though some peer status declares JSON."""
        import yaml as _yaml

        from mcp_builder.schema.models import Tool
        from mcp_builder.spec import load_openapi_spec as _load

        doc = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "servers": [{"url": "https://x"}],
            "paths": {
                "/mixed": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "pdf",
                                "content": {"application/pdf": {}},
                            },
                            "201": {
                                "description": "json",
                                "content": {"application/json": {}},
                            },
                        }
                    }
                }
            },
        }
        f = tmp_path / "spec.yaml"
        f.write_text(_yaml.safe_dump(doc))
        small_spec = _load(f)

        tool = Tool(
            tool_name="get_mixed",
            endpoint="GET /mixed",
            description="Mixed statuses.",
            parameters=[],
        )
        result = validate_scope(self._scope_with_tool(tool), small_spec)
        assert not any("get_mixed" in e for e in result.errors)
        matching = [w for w in result.warnings if "get_mixed" in w]
        assert matching, result.warnings
        # Warning must cite the offending status (200) and media type,
        # not hide them behind a flattened "some JSON exists somewhere".
        assert "200" in matching[0]
        assert "application/pdf" in matching[0]


class TestIsJsonMediaType:
    """Direct coverage of the JSON-media-type predicate.

    The validator's error/pass decision hinges on this predicate. If it
    miscategorizes a type, validate_scope silently passes a scope that
    should have errored (or vice versa) — the existing validator tests
    only exercise two media types transitively.
    """

    @pytest.mark.parametrize(
        "media_type",
        [
            "application/json",
            "text/json",  # legacy
            "Application/JSON",  # case-insensitive
            "APPLICATION/JSON",
            "application/json; charset=utf-8",  # parameter stripped
            "application/json ; charset=utf-8",  # whitespace ok
            "application/vnd.api+json",  # RFC 6839 structured suffix
            "application/problem+json",  # RFC 7807
            "application/ld+json",
            "text/foo+json",
        ],
    )
    def test_accepts(self, media_type):
        assert is_json_media_type(media_type) is True

    @pytest.mark.parametrize(
        "media_type",
        [
            "application/xml",
            "application/octet-stream",
            "image/jpeg",
            "text/plain",
            "multipart/form-data",
            "application/jsonl",  # JSON Lines, not JSON
            "application/json-seq",  # JSON text sequences
            "application/json-patch",  # not +json suffixed
            "application/+json",  # malformed: empty prefix before +
        ],
    )
    def test_rejects(self, media_type):
        assert is_json_media_type(media_type) is False
