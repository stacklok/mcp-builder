"""Tool function code generation."""

from __future__ import annotations

from mcp_builder.codegen.spec_parser import (
    OpenAPIParameter,
    get_body_fields,
    get_parameters,
    parse_endpoint,
)
from mcp_builder.schema.models import MCPScope, Tool

OPENAPI_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def generate_tools(scope: MCPScope, spec: dict, module_name: str) -> str:
    """Generate the tools.py module with a Tools class.

    Each tool in the scope becomes an async method on the Tools class.
    Method arguments are flattened from path/query params and body fields,
    with YAML parameter overrides applied. Required args come first, then
    optional ones with None defaults.

    Args:
        scope: Validated MCP scope configuration.
        spec: Parsed OpenAPI spec as a dict.
        module_name: Python module name (e.g., 'test_api_mcp').

    Returns:
        Python source code for the tools module.
    """
    lines: list[str] = []
    lines.append('"""Generated MCP tool methods."""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from typing import Annotated")
    lines.append("")
    lines.append("from pydantic import Field")
    lines.append("")
    lines.append(f"from {module_name}.client import APIClient")
    lines.append("")
    lines.append("")
    lines.append("class Tools:")
    lines.append('    """MCP tool implementations backed by the upstream API."""')
    lines.append("")
    lines.append("    def __init__(self, client: APIClient) -> None:")
    lines.append("        self._client = client")

    for group in scope.groups:
        lines.append("")
        lines.append(f"    # --- Group: {group.name} ---")
        for tool in group.tools:
            lines.append("")
            method_lines = _generate_method(tool, spec)
            lines.extend(method_lines)

    lines.append("")
    return "\n".join(lines)


def _generate_method(tool: Tool, spec: dict) -> list[str]:
    """Generate the lines for a single async tool method."""
    http_method, path = parse_endpoint(tool.endpoint)

    # Collect path/query params and body fields
    all_params = get_parameters(spec, http_method, path)
    path_params = [p for p in all_params if p.location == "path"]
    query_params = [p for p in all_params if p.location == "query"]
    body_params = get_body_fields(spec, http_method, path)

    # Build YAML override lookup: name -> (description, required)
    yaml_overrides: dict[str, tuple[str, bool]] = {}
    if tool.parameters:
        for override in tool.parameters:
            yaml_overrides[override.name] = (override.description, override.required)

    # Build ordered arg list: required first, then optional
    required_args: list[tuple[str, str, str]] = []  # (name, py_type, description)
    optional_args: list[tuple[str, str, str]] = []

    for param in path_params + query_params + body_params:
        py_type = OPENAPI_TYPE_MAP.get(param.schema_type, "str")
        desc, required = _resolve_param_info(param, yaml_overrides)
        desc_escaped = _escape_description(desc)
        if required:
            required_args.append((param.name, py_type, desc_escaped))
        else:
            optional_args.append((param.name, py_type, desc_escaped))

    # Build signature lines
    sig_parts: list[str] = ["        self,"]
    for name, py_type, desc in required_args:
        sig_parts.append(
            f'        {name}: Annotated[{py_type}, Field(description="{desc}")],'
        )
    for name, py_type, desc in optional_args:
        sig_parts.append(
            f'        {name}: Annotated[{py_type} | None, Field(description="{desc}")] = None,'
        )

    desc_escaped = _escape_description(tool.description)

    lines: list[str] = []
    lines.append(f"    async def {tool.tool_name}(")
    lines.extend(sig_parts)
    lines.append("    ) -> str:")
    lines.append(f'        """{desc_escaped}"""')

    # Build call body
    path_param_names = {p.name for p in path_params}
    query_param_names = [p.name for p in query_params]
    body_param_names = [p.name for p in body_params]

    # Path interpolation: OpenAPI {paramName} -> Python f-string
    # The param names in the path match the flat arg names directly
    has_path_params = bool(path_param_names)
    f_prefix = "f" if has_path_params else ""
    path_str = f'{f_prefix}"{path}"'

    # Query params dict comprehension (filter out None values)
    if query_param_names:
        inner = ", ".join(f'"{n}": {n}' for n in query_param_names)
        params_expr = "{k: v for k, v in {" + inner + "}.items() if v is not None}"
        params_line = f"            params={params_expr},"
    else:
        params_line = None

    # Body json dict comprehension (filter out None values)
    if body_param_names:
        inner = ", ".join(f'"{n}": {n}' for n in body_param_names)
        body_expr = "{k: v for k, v in {" + inner + "}.items() if v is not None}"
        body_line = f"            json_body={body_expr},"
    else:
        body_line = None

    lines.append("        resp = await self._client.request(")
    lines.append(f'            "{http_method}",')
    lines.append(f"            {path_str},")
    if params_line:
        lines.append(params_line)
    if body_line:
        lines.append(body_line)
    lines.append("        )")
    lines.append("        return resp.text")

    return lines


def _resolve_param_info(
    param: OpenAPIParameter,
    yaml_overrides: dict[str, tuple[str, bool]],
) -> tuple[str, bool]:
    """Return (description, required) using YAML override if available."""
    if param.name in yaml_overrides:
        return yaml_overrides[param.name]
    return param.description, param.required


def _escape_description(desc: str) -> str:
    """Escape a string for use in a Python string literal."""
    return desc.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()
