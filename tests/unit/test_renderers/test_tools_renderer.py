"""Tests for the tools module renderer."""

from typing import Literal

from mcp_builder.codegen.plan import ParamPlan, ToolPlan
from mcp_builder.codegen.renderers.tools import render_tools_module
from mcp_builder.spec import PythonType
from tests.unit.test_renderers.conftest import make_plan


def _make_tool(
    name: str = "get_item",
    http_method: str = "GET",
    path: str = "/items/{itemId}",
    description: str = "Get an item by its ID.",
    path_params: list[ParamPlan] | None = None,
    query_params: list[ParamPlan] | None = None,
    body_fields: list[ParamPlan] | None = None,
    hints: list[str] | None = None,
) -> ToolPlan:
    return ToolPlan(
        tool_name=name,
        class_name=name.replace("_", " ").title().replace(" ", ""),
        http_method=http_method,
        path=path,
        description=description,
        path_params=path_params or [],
        query_params=query_params or [],
        body_fields=body_fields or [],
        hints=hints or [],
        group_name="default",
    )


def _make_param(
    name: str = "item_id",
    py_name: str | None = None,
    py_type: PythonType = "str",
    required: bool = True,
    location: Literal["path", "query", "body"] = "path",
    original_name: str | None = None,
    description: str = "A parameter.",
) -> ParamPlan:
    return ParamPlan(
        name=name,
        py_name=py_name or name,
        py_type=py_type,
        description=description,
        required=required,
        location=location,
        original_name=original_name or name,
    )


class TestRenderToolsModuleStructure:
    def test_compiles(self) -> None:
        tool = _make_tool(
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")

    def test_has_tools_class(self) -> None:
        source = render_tools_module(make_plan(tools=[_make_tool()]))
        assert "class Tools:" in source

    def test_init_takes_client(self) -> None:
        source = render_tools_module(make_plan(tools=[_make_tool()]))
        assert "def __init__(self, client: APIClient)" in source
        assert "self._client = client" in source

    def test_imports_client(self) -> None:
        source = render_tools_module(make_plan(tools=[_make_tool()]))
        assert "from test_api_mcp.client import APIClient" in source

    def test_module_docstring_has_server_name(self) -> None:
        source = render_tools_module(make_plan(tools=[_make_tool()]))
        assert "test-api MCP server" in source

    def test_no_tools_still_compiles(self) -> None:
        source = render_tools_module(make_plan(tools=[]))
        compile(source, "<test>", "exec")
        assert "class Tools:" in source


class TestRenderToolsModuleMethods:
    def test_generates_async_method(self) -> None:
        tool = _make_tool(name="get_item")
        source = render_tools_module(make_plan(tools=[tool]))
        assert "async def get_item(self" in source

    def test_method_has_docstring(self) -> None:
        tool = _make_tool(description="Get an item by its ID.")
        source = render_tools_module(make_plan(tools=[tool]))
        assert '"""Get an item by its ID."""' in source

    def test_returns_dict(self) -> None:
        tool = _make_tool()
        source = render_tools_module(make_plan(tools=[tool]))
        assert ") -> dict:" in source

    def test_multiple_tools(self) -> None:
        tool_a = _make_tool(name="get_item", path="/items/{itemId}")
        tool_b = _make_tool(
            name="create_item",
            http_method="POST",
            path="/items",
            body_fields=[_make_param("title", location="body")],
        )
        source = render_tools_module(make_plan(tools=[tool_a, tool_b]))
        assert "async def get_item(" in source
        assert "async def create_item(" in source


class TestRenderToolsModuleParams:
    def test_path_param_in_fstring(self) -> None:
        tool = _make_tool(
            path="/items/{itemId}",
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert 'f"/items/{item_id}"' in source

    def test_multiple_path_params(self) -> None:
        tool = _make_tool(
            path="/orgs/{orgId}/items/{itemId}",
            path_params=[
                _make_param("org_id", original_name="orgId"),
                _make_param("item_id", original_name="itemId"),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert 'f"/orgs/{org_id}/items/{item_id}"' in source

    def test_no_path_params_uses_plain_string(self) -> None:
        tool = _make_tool(path="/items", path_params=[])
        source = render_tools_module(make_plan(tools=[tool]))
        assert '"/items"' in source
        assert 'f"/items"' not in source

    def test_query_params_in_params_dict(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param("page_size", location="query", original_name="page-size"),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert '"page-size": page_size' in source
        assert "params=" in source

    def test_body_fields_in_json_body_dict(self) -> None:
        tool = _make_tool(
            name="create_item",
            http_method="POST",
            path="/items",
            body_fields=[
                _make_param("title", location="body"),
                _make_param("color", location="body", required=False),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert '"title": title' in source
        assert '"color": color' in source
        assert "json_body=" in source

    def test_required_before_optional(self) -> None:
        tool = _make_tool(
            name="create_item",
            http_method="POST",
            path="/items",
            body_fields=[
                _make_param("color", location="body", required=False),
                _make_param("title", location="body", required=True),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        # title (required) should appear before color (optional) in signature
        title_pos = source.index("title: str")
        color_pos = source.index("color: str | None = None")
        assert title_pos < color_pos

    def test_optional_params_have_none_default(self) -> None:
        tool = _make_tool(
            query_params=[
                _make_param("fields", location="query", required=False),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "fields: str | None = None" in source

    def test_tool_with_no_params(self) -> None:
        tool = _make_tool(
            path="/status", path_params=[], query_params=[], body_fields=[]
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "async def get_item(self) -> dict:" in source
        compile(source, "<test>", "exec")

    def test_only_query_params_no_json_body(self) -> None:
        tool = _make_tool(
            path="/items",
            path_params=[],
            query_params=[_make_param("q", location="query")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "params=" in source
        assert "json_body=" not in source

    def test_only_body_fields_no_params(self) -> None:
        tool = _make_tool(
            name="create_item",
            http_method="POST",
            path="/items",
            path_params=[],
            body_fields=[_make_param("title", location="body")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "json_body=" in source
        assert "params=" not in source

    def test_original_name_as_dict_key(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param("page_size", location="query", original_name="page-size"),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert '"page-size": page_size' in source


class TestRenderToolsModuleEdgeCases:
    def test_description_with_quotes_compiles(self) -> None:
        tool = _make_tool(description='Get the "default" item.')
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")
        assert '\\"default\\"' in source

    def test_description_with_newlines_compiles(self) -> None:
        tool = _make_tool(description="Line one.\nLine two.")
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")

    def test_hints_rendered_as_comments(self) -> None:
        tool = _make_tool(hints=["response has 50+ fields"])
        source = render_tools_module(make_plan(tools=[tool]))
        assert "# Hint: response has 50+ fields" in source

    def test_no_hints_no_comment(self) -> None:
        tool = _make_tool(hints=[])
        source = render_tools_module(make_plan(tools=[tool]))
        assert "# Hint:" not in source

    def test_hints_with_quotes_compiles(self) -> None:
        tool = _make_tool(hints=['response includes "metadata" field'])
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")

    def test_original_name_with_quotes_compiles(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param(
                    "filter",
                    location="query",
                    original_name='my"filter',
                ),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")
        assert 'my\\"filter' in source

    def test_path_with_special_chars_and_params_compiles(self) -> None:
        tool = _make_tool(
            path='/items/{itemId}/notes/"default"',
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")

    def test_all_three_param_locations(self) -> None:
        tool = _make_tool(
            name="update_item",
            http_method="PUT",
            path="/items/{itemId}",
            path_params=[_make_param("item_id", original_name="itemId")],
            query_params=[_make_param("dry_run", location="query", required=False)],
            body_fields=[_make_param("title", location="body")],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")
        assert 'f"/items/{item_id}"' in source
        assert "params=" in source
        assert "json_body=" in source

    def test_deterministic(self) -> None:
        tool = _make_tool(
            path_params=[_make_param("item_id", original_name="itemId")],
            query_params=[_make_param("fields", location="query", required=False)],
        )
        plan = make_plan(tools=[tool])
        source1 = render_tools_module(plan)
        source2 = render_tools_module(plan)
        assert source1 == source2
