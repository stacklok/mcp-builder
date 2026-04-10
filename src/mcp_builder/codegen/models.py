"""Pydantic model generation from OpenAPI specs."""

from __future__ import annotations

from pathlib import Path

from datamodel_code_generator import DataModelType, PythonVersion, generate

from mcp_builder.codegen.spec_parser import (
    OpenAPIParameter,
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


def tool_name_to_class(name: str) -> str:
    """Convert snake_case tool name to PascalCase. E.g. 'get_item' -> 'GetItem'."""
    return "".join(word.capitalize() for word in name.split("_"))


def generate_body_models(spec_path: Path, work_dir: Path) -> str:
    """Generate Pydantic v2 models from an OpenAPI spec via datamodel-code-generator."""
    output_file = work_dir / "_body_models.py"
    generate(
        input_=spec_path,
        output=output_file,
        target_python_version=PythonVersion.PY_313,
        output_model_type=DataModelType.PydanticV2BaseModel,
    )
    content = output_file.read_text()
    output_file.unlink()
    return content


def generate_parameter_model(tool: Tool, spec: dict) -> str | None:
    """Generate a Pydantic model for a tool's path/query parameters.

    Applies description overrides from the YAML. Returns None if the
    endpoint has no path/query parameters.
    """
    method, path = parse_endpoint(tool.endpoint)
    params = get_parameters(spec, method, path)
    if not params:
        return None

    yaml_overrides: dict[str, tuple[str, bool]] = {}
    if tool.parameters:
        for p in tool.parameters:
            yaml_overrides[p.name] = (p.description, p.required)

    class_name = tool_name_to_class(tool.tool_name) + "Params"
    fields: list[str] = []

    for param in params:
        py_type = OPENAPI_TYPE_MAP.get(param.schema_type, "str")
        desc, required = _resolve_param_info(param, yaml_overrides)
        desc_escaped = _escape_description(desc)

        if required:
            fields.append(
                f'    {param.name}: {py_type} = Field(..., description="{desc_escaped}")'
            )
        else:
            fields.append(
                f'    {param.name}: {py_type} | None = Field(None, description="{desc_escaped}")'
            )

    return f"class {class_name}(BaseModel):\n" + "\n".join(fields)


def generate_models_file(
    scope: MCPScope,
    spec: dict,
    spec_path: Path,
    work_dir: Path,
) -> str:
    """Generate the complete models.py for the output project.

    Combines body schema models (from datamodel-code-generator) with
    per-tool parameter models (built manually with YAML overrides).
    """
    body_models = generate_body_models(spec_path, work_dir)

    param_models: list[str] = []
    for group in scope.groups:
        for tool in group.tools:
            model = generate_parameter_model(tool, spec)
            if model:
                param_models.append(model)

    parts = [body_models.rstrip()]
    if param_models:
        if "from pydantic import" not in body_models:
            parts.insert(0, "from pydantic import BaseModel, Field\n")
        parts.append(
            "\n\n# --- Parameter models (with YAML description overrides) ---\n"
        )
        parts.append("\n\n\n".join(param_models))
    parts.append("\n")

    return "\n".join(parts)


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
