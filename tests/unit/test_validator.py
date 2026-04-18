"""Tests for scope validation against an OpenAPI spec."""

from pathlib import Path

from mcp_builder.codegen.validator import validate_scope
from mcp_builder.schema.models import load_scope

FIXTURES = Path(__file__).parent / "fixtures"


class TestParameterCoverage:
    """Warnings when YAML params don't exist in the spec."""

    def test_body_param_missing_from_spec_warns(self, spec):
        """Body params not in spec's requestBody produce a warning."""
        from mcp_builder.schema.models import (
            ParamLocation,
            Parameter,
            Tool,
        )

        # Build a minimal scope with a body param on POST /files,
        # which has no requestBody in the test spec.
        scope = load_scope(FIXTURES / "test_scope.yaml")
        # Replace create_item with a tool that has a body param not in spec
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
        assert any("name" in w and "requestBody" in w for w in result.warnings)

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
