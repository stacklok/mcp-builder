"""Tests for the tools module renderer."""

from typing import Literal

from mcp_builder.generate.plan import ParamPlan, ToolPlan
from mcp_builder.generate.renderers.tools import render_tools_module
from mcp_builder.schema.models import ParamLocation
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
    response_kind: Literal["json", "text", "binary", "auto"] = "json",
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
        response_kind=response_kind,
    )


def _make_param(
    name: str = "item_id",
    py_name: str | None = None,
    py_type: PythonType = "str",
    required: bool = True,
    location: ParamLocation = ParamLocation.PATH,
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
            body_fields=[_make_param("title", location=ParamLocation.BODY)],
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
                _make_param(
                    "page_size", location=ParamLocation.QUERY, original_name="page-size"
                ),
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
                _make_param("title", location=ParamLocation.BODY),
                _make_param("color", location=ParamLocation.BODY, required=False),
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
                _make_param("color", location=ParamLocation.BODY, required=False),
                _make_param("title", location=ParamLocation.BODY, required=True),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        # title (required) should appear before color (optional) in signature
        title_pos = source.index("title: Annotated[str,")
        color_pos = source.index("color: Annotated[str | None,")
        assert title_pos < color_pos

    def test_optional_params_have_none_default(self) -> None:
        tool = _make_tool(
            query_params=[
                _make_param("fields", location=ParamLocation.QUERY, required=False),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "fields: Annotated[str | None," in source
        assert "= None" in source

    def test_param_descriptions_in_annotated(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param(
                    "q",
                    location=ParamLocation.QUERY,
                    required=False,
                    description="Search query.",
                ),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert 'Annotated[str | None, Field(description="Search query.")]' in source

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
            query_params=[_make_param("q", location=ParamLocation.QUERY)],
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
            body_fields=[_make_param("title", location=ParamLocation.BODY)],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        assert "json_body=" in source
        assert "params=" not in source

    def test_original_name_as_dict_key(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param(
                    "page_size", location=ParamLocation.QUERY, original_name="page-size"
                ),
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

    def test_param_description_with_quotes_compiles(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param(
                    "q",
                    location=ParamLocation.QUERY,
                    description='Filter by "type" field.',
                ),
            ],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")

    def test_original_name_with_quotes_compiles(self) -> None:
        tool = _make_tool(
            path="/items",
            query_params=[
                _make_param(
                    "filter",
                    location=ParamLocation.QUERY,
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
            query_params=[
                _make_param("dry_run", location=ParamLocation.QUERY, required=False)
            ],
            body_fields=[_make_param("title", location=ParamLocation.BODY)],
        )
        source = render_tools_module(make_plan(tools=[tool]))
        compile(source, "<test>", "exec")
        assert 'f"/items/{item_id}"' in source
        assert "params=" in source
        assert "json_body=" in source

    def test_json_tool_does_not_import_base64(self) -> None:
        """Pure-JSON servers must not carry an unused base64 import."""
        source = render_tools_module(make_plan(tools=[_make_tool()]))
        assert "import base64" not in source

    def test_deterministic(self) -> None:
        tool = _make_tool(
            path_params=[_make_param("item_id", original_name="itemId")],
            query_params=[
                _make_param("fields", location=ParamLocation.QUERY, required=False)
            ],
        )
        plan = make_plan(tools=[tool])
        source1 = render_tools_module(plan)
        source2 = render_tools_module(plan)
        assert source1 == source2


class TestRenderToolsModuleBinaryBranch:
    """Binary tools go through request_bytes() and base64-encode the
    response body so it survives MCP transport as a ``str``."""

    def _binary_tool(self) -> ToolPlan:
        return _make_tool(
            name="get_employee_photo",
            path="/employees/{employeeId}/photo",
            path_params=[_make_param("employee_id", original_name="employeeId")],
            description="Fetch the employee photo.",
            response_kind="binary",
        )

    def test_binary_tool_returns_str(self) -> None:
        source = render_tools_module(make_plan(tools=[self._binary_tool()]))
        assert "async def get_employee_photo(self" in source
        assert ") -> str:" in source
        # Must not claim to return dict.
        assert "async def get_employee_photo(self, employee_id: " in source

    def test_binary_tool_calls_request_bytes(self) -> None:
        source = render_tools_module(make_plan(tools=[self._binary_tool()]))
        assert "self._client.request_bytes(" in source
        # JSON path must not leak into a binary tool.
        binary_section = source.split("async def get_employee_photo")[1]
        assert "self._client.request(" not in binary_section.split("async def", 1)[0]

    def test_binary_tool_base64_encodes_response(self) -> None:
        source = render_tools_module(make_plan(tools=[self._binary_tool()]))
        assert 'base64.b64encode(raw).decode("ascii")' in source

    def test_binary_tool_imports_base64(self) -> None:
        source = render_tools_module(make_plan(tools=[self._binary_tool()]))
        assert "import base64" in source

    def test_binary_tool_compiles(self) -> None:
        source = render_tools_module(make_plan(tools=[self._binary_tool()]))
        compile(source, "<test>", "exec")

    def test_mixed_json_and_binary_tools_coexist(self) -> None:
        """A server with both tool shapes renders one JSON tool and one
        binary tool from the same template invocation."""
        json_tool = _make_tool(
            name="get_item",
            path="/items/{itemId}",
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        source = render_tools_module(make_plan(tools=[json_tool, self._binary_tool()]))
        compile(source, "<test>", "exec")
        assert "import base64" in source
        # JSON tool keeps its -> dict signature.
        get_item_section = source.split("async def get_item")[1].split("async def")[0]
        assert "-> dict:" in get_item_section
        assert "self._client.request(" in get_item_section
        # Binary tool uses the bytes path.
        photo_section = source.split("async def get_employee_photo")[1]
        assert "-> str:" in photo_section
        assert "request_bytes(" in photo_section


class TestRenderToolsModuleTextBranch:
    """Text tools go through request_text() and return the decoded body
    directly — no base64 wrapping, no JSON parsing."""

    def _text_tool(self) -> ToolPlan:
        return _make_tool(
            name="export_doc",
            path="/files/{fileId}/export",
            path_params=[_make_param("file_id", original_name="fileId")],
            query_params=[
                _make_param(
                    "mime_type",
                    original_name="mimeType",
                    location=ParamLocation.QUERY,
                    required=True,
                )
            ],
            description="Export a Google Doc as text.",
            response_kind="text",
        )

    def test_text_tool_returns_str(self) -> None:
        source = render_tools_module(make_plan(tools=[self._text_tool()]))
        assert "async def export_doc(self" in source
        text_section = source.split("async def export_doc")[1]
        assert "-> str:" in text_section

    def test_text_tool_calls_request_text(self) -> None:
        source = render_tools_module(make_plan(tools=[self._text_tool()]))
        text_section = source.split("async def export_doc")[1].split("async def", 1)[0]
        assert "self._client.request_text(" in text_section
        # Neither JSON nor bytes paths may leak into a text tool.
        assert "self._client.request(" not in text_section
        assert "self._client.request_bytes(" not in text_section

    def test_text_tool_does_not_base64_encode(self) -> None:
        source = render_tools_module(make_plan(tools=[self._text_tool()]))
        text_section = source.split("async def export_doc")[1].split("async def", 1)[0]
        assert "base64" not in text_section

    def test_text_only_tools_do_not_import_base64(self) -> None:
        source = render_tools_module(make_plan(tools=[self._text_tool()]))
        assert "import base64" not in source

    def test_text_tool_compiles(self) -> None:
        source = render_tools_module(make_plan(tools=[self._text_tool()]))
        compile(source, "<test>", "exec")

    def test_all_three_kinds_coexist(self) -> None:
        """A server with json, text, and binary tools renders all three
        shapes from the same template invocation."""
        json_tool = _make_tool(
            name="get_item",
            path="/items/{itemId}",
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        binary_tool = _make_tool(
            name="get_employee_photo",
            path="/employees/{employeeId}/photo",
            path_params=[_make_param("employee_id", original_name="employeeId")],
            description="Fetch the employee photo.",
            response_kind="binary",
        )
        plan = make_plan(tools=[json_tool, self._text_tool(), binary_tool])
        source = render_tools_module(plan)
        compile(source, "<test>", "exec")
        assert "import base64" in source  # needed for binary
        json_section = source.split("async def get_item")[1].split("async def", 1)[0]
        assert "-> dict:" in json_section
        assert "self._client.request(" in json_section
        text_section = source.split("async def export_doc")[1].split("async def", 1)[0]
        assert "-> str:" in text_section
        assert "request_text(" in text_section
        binary_section = source.split("async def get_employee_photo")[1]
        assert "-> str:" in binary_section
        assert "request_bytes(" in binary_section


class TestRenderToolsModuleAutoBranch:
    """Auto tools go through request_auto() and return ``dict | str`` —
    the decoder picks at runtime from the response Content-Type."""

    def _auto_tool(self) -> ToolPlan:
        return _make_tool(
            name="export_anything",
            path="/files/{fileId}/export",
            path_params=[_make_param("file_id", original_name="fileId")],
            query_params=[
                _make_param(
                    "mime_type",
                    original_name="mimeType",
                    location=ParamLocation.QUERY,
                    required=True,
                )
            ],
            description="Export with runtime-determined shape.",
            response_kind="auto",
        )

    def test_auto_tool_returns_union(self) -> None:
        source = render_tools_module(make_plan(tools=[self._auto_tool()]))
        section = source.split("async def export_anything")[1].split("async def", 1)[0]
        assert "-> dict | str:" in section

    def test_auto_tool_calls_request_auto(self) -> None:
        source = render_tools_module(make_plan(tools=[self._auto_tool()]))
        section = source.split("async def export_anything")[1].split("async def", 1)[0]
        assert "self._client.request_auto(" in section
        # Other request paths must not leak into an auto tool.
        assert "self._client.request(" not in section
        assert "self._client.request_text(" not in section
        assert "self._client.request_bytes(" not in section

    def test_auto_tool_does_not_base64_in_tool_body(self) -> None:
        # base64 wrapping is the client's job, not the tool's — the tool
        # returns whatever request_auto handed back. Allow the term in
        # the docstring (which describes runtime behavior to a reader),
        # but disallow any actual base64 call.
        source = render_tools_module(make_plan(tools=[self._auto_tool()]))
        section = source.split("async def export_anything")[1].split("async def", 1)[0]
        assert "base64.b64encode" not in section

    def test_auto_only_tools_do_not_import_base64(self) -> None:
        # base64 import is gated on any_binary; auto-only servers don't need it.
        source = render_tools_module(make_plan(tools=[self._auto_tool()]))
        assert "import base64" not in source

    def test_auto_tool_compiles(self) -> None:
        source = render_tools_module(make_plan(tools=[self._auto_tool()]))
        compile(source, "<test>", "exec")

    def test_all_four_kinds_coexist(self) -> None:
        """A server with json, text, binary, and auto tools renders all
        four shapes from the same template invocation."""
        json_tool = _make_tool(
            name="get_item",
            path="/items/{itemId}",
            path_params=[_make_param("item_id", original_name="itemId")],
        )
        text_tool = _make_tool(
            name="export_doc",
            path="/files/{fileId}/export",
            path_params=[_make_param("file_id", original_name="fileId")],
            query_params=[
                _make_param(
                    "mime_type",
                    original_name="mimeType",
                    location=ParamLocation.QUERY,
                    required=True,
                )
            ],
            description="Export a Google Doc as text.",
            response_kind="text",
        )
        binary_tool = _make_tool(
            name="get_employee_photo",
            path="/employees/{employeeId}/photo",
            path_params=[_make_param("employee_id", original_name="employeeId")],
            description="Fetch the employee photo.",
            response_kind="binary",
        )
        plan = make_plan(tools=[json_tool, text_tool, binary_tool, self._auto_tool()])
        source = render_tools_module(plan)
        compile(source, "<test>", "exec")
        # Auto tool keeps its dict | str signature.
        auto_section = source.split("async def export_anything")[1]
        assert "-> dict | str:" in auto_section
        assert "request_auto(" in auto_section
