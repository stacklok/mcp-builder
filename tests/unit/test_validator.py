"""Tests for scope validation against an OpenAPI spec."""

from pathlib import Path

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
