"""Tests for the parameter models renderer."""

from mcp_builder.codegen.plan import AuthPlan, ParamPlan, ServerPlan, ToolPlan
from mcp_builder.spec import PythonType
from mcp_builder.codegen.renderers.models import render_parameter_models


def _make_plan(tools: list[ToolPlan] | None = None) -> ServerPlan:
    return ServerPlan(
        module_name="test_api_mcp",
        server_name="test-api",
        description="A test API server.",
        base_url="https://api.example.com",
        auth=AuthPlan(type="api_key"),
        tools=tools or [],
        groups=[],
    )


def _make_tool(
    name: str = "create_item",
    body_fields: list[ParamPlan] | None = None,
) -> ToolPlan:
    return ToolPlan(
        tool_name=name,
        class_name=name.replace("_", " ").title().replace(" ", ""),
        http_method="POST",
        path="/items",
        description=f"Create a {name}.",
        path_params=[],
        query_params=[],
        body_fields=body_fields or [],
        hints=[],
        group_name="default",
    )


def _make_body_field(
    name: str = "title",
    py_type: PythonType = "str",
    required: bool = True,
    description: str = "The title.",
) -> ParamPlan:
    return ParamPlan(
        name=name,
        py_name=name,
        py_type=py_type,
        description=description,
        required=required,
        location="body",
        original_name=name,
    )


class TestRenderParameterModels:
    def test_no_body_fields_returns_empty(self) -> None:
        tool = _make_tool(body_fields=[])
        plan = _make_plan(tools=[tool])
        assert render_parameter_models(plan) == ""

    def test_no_tools_returns_empty(self) -> None:
        plan = _make_plan(tools=[])
        assert render_parameter_models(plan) == ""

    def test_generates_model_class(self) -> None:
        tool = _make_tool(
            body_fields=[_make_body_field("title"), _make_body_field("color")]
        )
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        assert "class CreateItemParams(BaseModel):" in source

    def test_compiles(self) -> None:
        tool = _make_tool(
            body_fields=[_make_body_field("title"), _make_body_field("color")]
        )
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        compile(source, "<test>", "exec")

    def test_required_field(self) -> None:
        tool = _make_tool(body_fields=[_make_body_field("title", required=True)])
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        assert 'title: str = Field(..., description="The title.")' in source

    def test_optional_field(self) -> None:
        tool = _make_tool(
            body_fields=[
                _make_body_field("notes", required=False, description="Optional notes.")
            ]
        )
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        assert "notes: str | None = Field(default=None" in source

    def test_multiple_tools(self) -> None:
        tool_a = _make_tool(
            name="create_item",
            body_fields=[_make_body_field("title")],
        )
        tool_b = _make_tool(
            name="update_item",
            body_fields=[_make_body_field("status")],
        )
        plan = _make_plan(tools=[tool_a, tool_b])
        source = render_parameter_models(plan)
        assert "class CreateItemParams(BaseModel):" in source
        assert "class UpdateItemParams(BaseModel):" in source

    def test_skips_tools_without_body(self) -> None:
        tool_with = _make_tool(
            name="create_item",
            body_fields=[_make_body_field("title")],
        )
        tool_without = _make_tool(name="get_item", body_fields=[])
        plan = _make_plan(tools=[tool_with, tool_without])
        source = render_parameter_models(plan)
        assert "CreateItemParams" in source
        assert "GetItemParams" not in source

    def test_imports_pydantic(self) -> None:
        tool = _make_tool(body_fields=[_make_body_field("title")])
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        assert "from pydantic import BaseModel, Field" in source

    def test_description_with_quotes_compiles(self) -> None:
        tool = _make_tool(
            body_fields=[_make_body_field("title", description='The "default" title.')]
        )
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        compile(source, "<test>", "exec")
        assert '\\"default\\"' in source

    def test_description_with_newlines_compiles(self) -> None:
        tool = _make_tool(
            body_fields=[_make_body_field("title", description="Line one.\nLine two.")]
        )
        plan = _make_plan(tools=[tool])
        source = render_parameter_models(plan)
        compile(source, "<test>", "exec")
