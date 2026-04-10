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


def _sanitize_name(name: str) -> str:
    """Convert an OpenAPI parameter name to a valid Python identifier.

    Replaces hyphens, dots, and dollar signs with underscores, then strips
    any leading underscores introduced by the replacement (e.g. ``$filter``
    becomes ``filter``).  If the result starts with a digit or is empty,
    ``param_`` is prepended.  The final value is guaranteed to satisfy
    ``str.isidentifier()``.
    """
    sanitized = name.replace("-", "_").replace(".", "_").replace("$", "_")
    sanitized = sanitized.lstrip("_")
    if not sanitized or sanitized[0].isdigit():
        sanitized = "param_" + sanitized
    assert sanitized.isidentifier(), (
        f"Could not sanitize {name!r} to a valid identifier"
    )
    return sanitized


def _build_path_fstring(path: str, path_param_names: dict[str, str]) -> str:
    """Build the path string for a request, replacing OpenAPI placeholders.

    ``path_param_names`` maps original OpenAPI name -> sanitized Python name.
    Returns a bare string (no f-prefix) when there are no path params, or an
    f-string literal (with the ``f`` prefix) when substitution is needed.
    """
    if not path_param_names:
        return f'"{path}"'
    result = path
    for original, sanitized in path_param_names.items():
        result = result.replace(f"{{{original}}}", f"{{{sanitized}}}")
    return f'f"{result}"'


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

    # Assign sanitized names, then detect collisions and suffix with location.
    # Each entry: (sanitized_name, original_name, location, OpenAPIParameter)
    entries: list[tuple[str, str, str, OpenAPIParameter]] = []
    for param in path_params:
        entries.append((_sanitize_name(param.name), param.name, "path", param))
    for param in query_params:
        entries.append((_sanitize_name(param.name), param.name, "query", param))
    for param in body_params:
        entries.append((_sanitize_name(param.name), param.name, "body", param))

    # Count occurrences of each sanitized name to find collisions.
    name_counts: dict[str, int] = {}
    for sanitized, _, _, _ in entries:
        name_counts[sanitized] = name_counts.get(sanitized, 0) + 1

    deduped: list[tuple[str, str, str, OpenAPIParameter]] = []
    for sanitized, original, location, param in entries:
        if name_counts[sanitized] > 1:
            sanitized = f"{sanitized}_{location}"
        deduped.append((sanitized, original, location, param))

    # Build ordered arg list: required first, then optional.
    # Each arg: (sanitized_name, original_name, location, py_type, description)
    required_args: list[tuple[str, str, str, str, str]] = []
    optional_args: list[tuple[str, str, str, str, str]] = []

    for sanitized, original, location, param in deduped:
        py_type = OPENAPI_TYPE_MAP.get(param.schema_type, "str")
        desc, required = _resolve_param_info(param, yaml_overrides)
        desc_escaped = _escape_description(desc)
        if required:
            required_args.append((sanitized, original, location, py_type, desc_escaped))
        else:
            optional_args.append((sanitized, original, location, py_type, desc_escaped))

    # Build signature lines
    sig_parts: list[str] = ["        self,"]
    for sanitized, _orig, _loc, py_type, desc in required_args:
        sig_parts.append(
            f'        {sanitized}: Annotated[{py_type}, Field(description="{desc}")],'
        )
    for sanitized, _orig, _loc, py_type, desc in optional_args:
        sig_parts.append(
            f'        {sanitized}: Annotated[{py_type} | None, Field(description="{desc}")] = None,'
        )

    desc_escaped = _escape_description(tool.description)

    lines: list[str] = []
    lines.append(f"    async def {tool.tool_name}(")
    lines.extend(sig_parts)
    lines.append("    ) -> str:")
    lines.append(f'        """{desc_escaped}"""')

    # Build call body using sanitized names for values, original names for keys.
    all_args = required_args + optional_args

    path_arg_map: dict[str, str] = {
        orig: san for san, orig, loc, _pt, _desc in all_args if loc == "path"
    }
    query_arg_pairs: list[tuple[str, str]] = [
        (orig, san) for san, orig, loc, _pt, _desc in all_args if loc == "query"
    ]
    body_arg_pairs: list[tuple[str, str]] = [
        (orig, san) for san, orig, loc, _pt, _desc in all_args if loc == "body"
    ]

    # Path f-string uses sanitized variable names
    path_str = _build_path_fstring(path, path_arg_map)

    # Query params dict: original name as key, sanitized name as value
    if query_arg_pairs:
        inner = ", ".join(f'"{orig}": {san}' for orig, san in query_arg_pairs)
        params_expr = "{k: v for k, v in {" + inner + "}.items() if v is not None}"
        params_line: str | None = f"            params={params_expr},"
    else:
        params_line = None

    # Body json dict: original name as key, sanitized name as value
    if body_arg_pairs:
        inner = ", ".join(f'"{orig}": {san}' for orig, san in body_arg_pairs)
        body_expr = "{k: v for k, v in {" + inner + "}.items() if v is not None}"
        body_line: str | None = f"            json_body={body_expr},"
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
