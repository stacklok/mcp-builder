"""Tests for scope validation against an OpenAPI spec."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mcp_builder.spec.media import is_json_media_type
from mcp_builder.validate import validate_scope
from mcp_builder.schema.models import (
    Group,
    MCPScope,
    ParamLocation,
    Parameter,
    Tool,
    load_scope,
)
from mcp_builder.spec import OpenAPISpec, load_openapi_spec

FIXTURES = Path(__file__).parent / "fixtures"


def _scope_with_tool(tool: Tool) -> MCPScope:
    """Build a minimal scope wrapping a single tool for testing."""
    scope = load_scope(FIXTURES / "test_scope.yaml")
    scope.groups = [
        Group(
            name="focus",
            description="Group under test.",
            tools=[tool],
        )
    ]
    return scope


def _mini_spec(tmp_path: Path, paths: dict) -> OpenAPISpec:
    """Write and load a tiny OpenAPI spec with the given paths block."""
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "servers": [{"url": "https://x"}],
        "paths": paths,
    }
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(doc))
    return load_openapi_spec(path)


class TestParameterCoverage:
    """Warnings when YAML params don't exist in the spec."""

    def test_body_param_missing_from_spec_warns(self, spec):
        """Body params on an endpoint with no requestBody get the
        'spec may be incomplete' warning."""
        # POST /files has no requestBody in the test spec.
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            response_kind="json",
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
        # POST /items has a requestBody with CreateItemRequest
        # (properties: name, description).
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_item",
            endpoint="POST /items",
            description="Create an item.",
            response_kind="json",
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
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            response_kind="json",
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


class TestResponseKindSchema:
    """Pydantic-level rejection of scopes missing response_kind.

    Having this enforced at load time means the CLI's generate/validate
    commands can't silently fall through to a default decode path.
    """

    def test_missing_response_kind_fails_at_load(self):
        # Model instantiation via dict bypasses the static-type check so
        # the runtime Pydantic validation is what we're exercising.
        with pytest.raises(ValidationError):
            Tool.model_validate(
                {
                    "tool_name": "no_kind",
                    "endpoint": "GET /items",
                    "description": "Tool missing response_kind.",
                    "parameters": [],
                }
            )

    def test_invalid_response_kind_fails_at_load(self):
        with pytest.raises(ValidationError):
            Tool.model_validate(
                {
                    "tool_name": "bad_kind",
                    "endpoint": "GET /items",
                    "description": "Tool with bogus response_kind.",
                    "response_kind": "maybe",
                    "parameters": [],
                }
            )


class TestResponseKindSpecCompatibility:
    """Validator cross-checks scope's response_kind against the spec's 2xx.

    Errors surface a mismatch now so the scope author either drops the
    endpoint or fixes the decode choice — no silent base64 of JSON
    responses, no runtime crash on ``response.json()`` of a PDF.
    """

    def test_binary_scope_with_non_json_spec_passes(self, spec):
        """binary scope against an image/jpeg-only endpoint is the intended
        happy path."""
        tool = Tool(
            tool_name="get_employee_photo",
            endpoint="GET /employees/{employeeId}/photo",
            description="Fetch the employee photo.",
            response_kind="binary",
            parameters=[
                Parameter(
                    name="employeeId",
                    description="Employee ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        assert not any("get_employee_photo" in e for e in result.errors)

    def test_json_scope_against_non_json_endpoint_errors(self, spec):
        """Declaring json against a PDF/image-only endpoint would crash at
        runtime when the generated tool calls ``response.json()``."""
        tool = Tool(
            tool_name="get_employee_photo",
            endpoint="GET /employees/{employeeId}/photo",
            description="Fetch the employee photo.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="employeeId",
                    description="Employee ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        matching = [e for e in result.errors if "get_employee_photo" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='json'" in msg
        assert "image/jpeg" in msg

    def test_binary_scope_against_json_endpoint_errors(self, spec):
        """Declaring binary against a JSON-only endpoint would base64-wrap a
        JSON body, handing the caller opaque bytes."""
        tool = Tool(
            tool_name="get_item",
            endpoint="GET /items/{itemId}",
            description="Get an item.",
            response_kind="binary",
            parameters=[
                Parameter(
                    name="itemId",
                    description="Item ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        matching = [e for e in result.errors if "get_item" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='binary'" in msg
        assert "application/json" in msg

    def test_same_status_mixed_json_and_non_json_errors(self, spec):
        """A single 2xx declaring both JSON and non-JSON media types
        (/reports/{reportId}/download) is ambiguous: content negotiation
        at runtime can hand back either shape. Error regardless of
        ``response_kind`` so the scope author picks one or drops the
        endpoint."""
        for kind in ("json", "binary"):
            tool = Tool(
                tool_name="download_report",
                endpoint="GET /reports/{reportId}/download",
                description="Download a report.",
                response_kind=kind,
                parameters=[
                    Parameter(
                        name="reportId",
                        description="Report ID.",
                        required=True,
                        location=ParamLocation.PATH,
                    ),
                ],
            )
            result = validate_scope(_scope_with_tool(tool), spec)
            matching = [e for e in result.errors if "download_report" in e]
            assert matching, (kind, result.errors)
            (msg,) = matching
            assert "both JSON and non-JSON" in msg
            assert "application/json" in msg
            assert "application/pdf" in msg

    def test_no_content_block_passes(self, spec):
        """2xx with no 'content' block is a legitimate empty response
        (204-style); must not error regardless of response_kind."""
        # GET /items declares 200 without a content block.
        tool = Tool(
            tool_name="list_items",
            endpoint="GET /items",
            description="List items.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        assert not any("list_items" in e for e in result.errors)
        assert not any("list_items" in w and "no 2xx" in w for w in result.warnings)

    def test_missing_2xx_warns(self, tmp_path):
        """An operation with no 2xx responses declared produces a
        'spec may be incomplete' warning, not an error — we can't prove
        it's broken."""
        small_spec = _mini_spec(
            tmp_path,
            {
                "/only-errors": {
                    "get": {
                        "responses": {
                            "500": {"description": "server error"},
                        }
                    }
                }
            },
        )
        tool = Tool(
            tool_name="only_errors",
            endpoint="GET /only-errors",
            description="Only errors declared.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), small_spec)
        assert not any("only_errors" in e for e in result.errors)
        assert any("only_errors" in w and "no 2xx" in w for w in result.warnings)

    def test_vendor_json_type_accepted(self, tmp_path):
        """RFC 6839 structured-suffix +json types (e.g. application/vnd.api+json)
        are JSON-decodable, so they should not error with response_kind=json."""
        small_spec = _mini_spec(
            tmp_path,
            {
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
        )
        tool = Tool(
            tool_name="get_vendor",
            endpoint="GET /vendor",
            description="Vendor JSON response.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), small_spec)
        assert not any("get_vendor" in e for e in result.errors)

    def test_mixed_status_2xx_errors_regardless_of_response_kind(self, tmp_path):
        """Spec that returns PDF on 200 and JSON on 201 is ambiguous for
        single-tool codegen — error whichever response_kind is set, because
        the tool commits to one decode path and the other status will
        either crash (json) or get base64-wrapped (binary)."""
        paths = {
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
        }

        for kind in ("json", "binary"):
            small_spec = _mini_spec(tmp_path, paths)
            tool = Tool(
                tool_name="get_mixed",
                endpoint="GET /mixed",
                description="Mixed statuses.",
                response_kind=kind,
                parameters=[],
            )
            result = validate_scope(_scope_with_tool(tool), small_spec)
            matching = [e for e in result.errors if "get_mixed" in e]
            assert matching, (kind, result.errors)
            (msg,) = matching
            assert "mixed JSON and non-JSON" in msg
            assert "application/pdf" in msg
            assert "application/json" in msg


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
