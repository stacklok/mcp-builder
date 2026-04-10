"""Tests for codegen.plan — ServerPlan building from scope + spec."""

from pathlib import Path

import pytest

from mcp_builder.codegen.plan import (
    GroupPlan,
    ServerPlan,
    ToolPlan,
    build_server_plan,
    server_name_to_module,
)
from mcp_builder.schema.models import load_scope

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plan(scope, spec):
    return build_server_plan(scope, spec)


# ---------------------------------------------------------------------------
# server_name_to_module
# ---------------------------------------------------------------------------


class TestServerNameToModule:
    def test_simple_name(self):
        assert server_name_to_module("google-drive") == "google_drive_mcp"

    def test_no_hyphens(self):
        assert server_name_to_module("slack") == "slack_mcp"

    def test_multiple_hyphens(self):
        assert server_name_to_module("my-cool-api") == "my_cool_api_mcp"


# ---------------------------------------------------------------------------
# build_server_plan — top-level structure
# ---------------------------------------------------------------------------


class TestBuildServerPlan:
    def test_returns_server_plan(self, plan):
        assert isinstance(plan, ServerPlan)

    def test_module_name(self, plan):
        assert plan.module_name == "test_api_mcp"

    def test_server_name(self, plan):
        assert plan.server_name == "test-api"

    def test_description(self, plan):
        assert plan.description == "Test API MCP server"

    def test_base_url(self, plan):
        assert plan.base_url == "https://api.example.com"

    def test_tool_count(self, plan):
        assert len(plan.tools) == 2

    def test_group_count(self, plan):
        assert len(plan.groups) == 1


# ---------------------------------------------------------------------------
# build_server_plan — tools
# ---------------------------------------------------------------------------


class TestToolPlans:
    def test_get_item_tool(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "get_item")
        assert isinstance(tool, ToolPlan)
        assert tool.class_name == "GetItem"
        assert tool.http_method == "GET"
        assert tool.path == "/items/{itemId}"

    def test_get_item_path_params(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "get_item")
        assert len(tool.path_params) == 1
        item_id = tool.path_params[0]
        assert item_id.name == "itemId"
        assert item_id.required is True
        assert item_id.location == "path"

    def test_get_item_query_params(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "get_item")
        assert len(tool.query_params) == 1
        fields = tool.query_params[0]
        assert fields.name == "fields"
        assert fields.required is False
        assert fields.location == "query"

    def test_yaml_override_applied(self, plan):
        """YAML parameter overrides should win over OpenAPI descriptions."""
        tool = next(t for t in plan.tools if t.tool_name == "get_item")
        item_id = tool.path_params[0]
        # The YAML override says "The unique item identifier."
        # The OpenAPI spec says "The ID of the item."
        assert item_id.description == "The unique item identifier."

    def test_create_item_body_fields(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "create_item")
        assert len(tool.body_fields) == 2
        names = {f.name for f in tool.body_fields}
        assert "name" in names
        assert "description" in names

    def test_create_item_no_path_params(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "create_item")
        assert tool.path_params == []
        assert tool.query_params == []

    def test_tool_group_name(self, plan):
        for tool in plan.tools:
            assert tool.group_name == "item-operations"

    def test_body_field_required(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "create_item")
        name_field = next(f for f in tool.body_fields if f.name == "name")
        desc_field = next(f for f in tool.body_fields if f.name == "description")
        assert name_field.required is True
        assert desc_field.required is False


# ---------------------------------------------------------------------------
# build_server_plan — groups
# ---------------------------------------------------------------------------


class TestGroupPlans:
    def test_group_structure(self, plan):
        group = plan.groups[0]
        assert isinstance(group, GroupPlan)
        assert group.name == "item-operations"
        assert group.tool_names == ["get_item", "create_item"]


# ---------------------------------------------------------------------------
# build_server_plan — auth
# ---------------------------------------------------------------------------


class TestAuthPlan:
    def test_api_key_auth(self, plan):
        assert plan.auth.type == "api_key"
        assert plan.auth.issuer is None
        assert plan.auth.scopes is None

    def test_oauth_auth(self, spec):
        scope = load_scope(FIXTURES / "test_scope_oauth.yaml")
        plan = build_server_plan(scope, spec)
        assert plan.auth.type == "oauth_bearer"
        assert plan.auth.issuer == "https://accounts.google.com"
        assert plan.auth.scopes is not None
        assert "openid" in plan.auth.scopes


# ---------------------------------------------------------------------------
# ParamPlan — name sanitization
# ---------------------------------------------------------------------------


class TestParamNameSanitization:
    def test_simple_name_preserved(self, plan):
        tool = next(t for t in plan.tools if t.tool_name == "get_item")
        item_id = tool.path_params[0]
        assert item_id.py_name == "itemId"
        assert item_id.original_name == "itemId"

    def test_hyphenated_name(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("page-size") == "page_size"

    def test_dollar_prefix(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("$filter") == "filter"

    def test_dot_separated(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("user.name") == "user_name"

    def test_brackets(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("page[size]") == "page_size"

    def test_digit_prefix(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("2fa_code") == "param_2fa_code"

    def test_empty_string(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("$") == "param_"

    def test_python_keyword(self):
        from mcp_builder.codegen.plan import _sanitize_name

        assert _sanitize_name("from") == "from_"
        assert _sanitize_name("class") == "class_"
        assert _sanitize_name("import") == "import_"


# ---------------------------------------------------------------------------
# Name collision resolution
# ---------------------------------------------------------------------------


class TestNameCollisionResolution:
    def test_cross_location_collision(self):
        """Params with same name in different locations get location suffix."""
        from mcp_builder.codegen.plan import ParamPlan, _resolve_name_collisions

        params = [
            ParamPlan(
                name="id",
                py_name="id",
                py_type="str",
                description="path id",
                required=True,
                location="path",
                original_name="id",
            ),
            ParamPlan(
                name="id",
                py_name="id",
                py_type="str",
                description="query id",
                required=False,
                location="query",
                original_name="id",
            ),
        ]
        _resolve_name_collisions(params)
        assert params[0].py_name == "id_path"
        assert params[1].py_name == "id_query"

    def test_same_location_collision_gets_numeric_suffix(self):
        """Two params in the same location that sanitize to the same name get numeric suffix."""
        from mcp_builder.codegen.plan import ParamPlan, _resolve_name_collisions

        # foo-bar and foo.bar both sanitize to foo_bar, both are query params
        params = [
            ParamPlan(
                name="foo-bar",
                py_name="foo_bar",
                py_type="str",
                description="first",
                required=False,
                location="query",
                original_name="foo-bar",
            ),
            ParamPlan(
                name="foo.bar",
                py_name="foo_bar",
                py_type="str",
                description="second",
                required=False,
                location="query",
                original_name="foo.bar",
            ),
        ]
        _resolve_name_collisions(params)
        # First pass makes both "foo_bar_query", second pass disambiguates
        assert params[0].py_name != params[1].py_name
        assert "foo_bar_query" in params[0].py_name
        assert "foo_bar_query" in params[1].py_name

    def test_no_collision_unchanged(self):
        """Params with unique names are not modified."""
        from mcp_builder.codegen.plan import ParamPlan, _resolve_name_collisions

        params = [
            ParamPlan(
                name="id",
                py_name="id",
                py_type="str",
                description="",
                required=True,
                location="path",
                original_name="id",
            ),
            ParamPlan(
                name="name",
                py_name="name",
                py_type="str",
                description="",
                required=True,
                location="query",
                original_name="name",
            ),
        ]
        _resolve_name_collisions(params)
        assert params[0].py_name == "id"
        assert params[1].py_name == "name"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_plan_is_deterministic(self, scope, spec):
        """Building the plan twice from the same inputs produces identical output."""
        plan1 = build_server_plan(scope, spec)
        plan2 = build_server_plan(scope, spec)
        assert plan1 == plan2
