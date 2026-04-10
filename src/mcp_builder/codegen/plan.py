"""ServerPlan: the typed intermediate representation for code generation.

Pipeline stage: planning (MCPScope + OpenAPI → ServerPlan).
This module defines the data contract between spec analysis and rendering.
All raw OpenAPI access happens here in build_server_plan(). Downstream
renderers only receive the ServerPlan and never touch the spec.

Reading guide:
    - ServerPlan is the root — it contains everything needed to generate
      an entire MCP server project.
    - build_server_plan() is the only function — it transforms scope + spec
      into a ServerPlan.
    - Renderers in codegen.renderers/ consume the plan via their function
      signatures (e.g., render_client_module(plan: ServerPlan) -> str).
"""

from __future__ import annotations

import keyword
import logging
import re
from typing import Literal

from pydantic import BaseModel

from mcp_builder.codegen.spec_parser import (
    OPENAPI_TYPE_MAP,
    ExtractedBodyField,
    ExtractedParameter,
    OpenAPISpec,
    get_body_fields,
    get_parameters,
    parse_endpoint,
)
from mcp_builder.schema.models import MCPScope, Tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan models — the data contract between analysis and rendering
# ---------------------------------------------------------------------------


class ParamPlan(BaseModel):
    """A single parameter in a generated tool method.

    Represents a flattened argument that will appear in the tool's function
    signature. Can originate from path params, query params, or body fields.

    Example:
        ParamPlan(
            name="itemId", py_name="item_id", py_type="str",
            description="The ID of the item.", required=True,
            location="path", original_name="itemId"
        )
    """

    name: str  # original OpenAPI name
    py_name: str  # sanitized Python identifier (e.g., hyphens → underscores)
    py_type: str  # Python type string (e.g., "str", "int", "list")
    description: str
    required: bool
    location: Literal["path", "query", "body"]
    original_name: str  # preserved for path template substitution


class ToolPlan(BaseModel):
    """Everything needed to render one tool method and its parameter model.

    Example:
        ToolPlan(
            tool_name="get_item", class_name="GetItem",
            http_method="GET", path="/items/{itemId}",
            description="Get an item by ID.",
            path_params=[ParamPlan(name="itemId", ...)],
            query_params=[ParamPlan(name="fields", ...)],
            body_fields=[],
            hints=["response has 50+ fields"],
            group_name="item-operations"
        )
    """

    tool_name: str  # snake_case, e.g. "get_item"
    class_name: str  # PascalCase, e.g. "GetItem"
    http_method: str  # e.g. "GET"
    path: str  # e.g. "/items/{itemId}"
    description: str
    path_params: list[ParamPlan]
    query_params: list[ParamPlan]
    body_fields: list[ParamPlan]
    hints: list[str]
    group_name: str


class GroupPlan(BaseModel):
    """A semantic group of tools, used for organizing tool registrations.

    Example:
        GroupPlan(name="file-operations", tool_names=["list_files", "get_file"])
    """

    name: str
    tool_names: list[str]


class AuthPlan(BaseModel):
    """Authentication configuration for the generated server.

    Example (OAuth):
        AuthPlan(type="oauth_bearer", issuer="https://accounts.google.com",
                 scopes=["openid", "email"])
    """

    type: Literal["oauth_bearer", "api_key", "none"]
    issuer: str | None = None
    scopes: list[str] | None = None


class ServerPlan(BaseModel):
    """The complete intermediate representation for generating one MCP server.

    Pipeline stage: planning (this is the output of build_server_plan()).
    Consumed by: every renderer in codegen.renderers/.

    This is the single data contract between "understanding the spec" and
    "generating code." A reviewer can inspect this model to understand
    exactly what data is available to each renderer.

    Example:
        ServerPlan(
            module_name="google_drive_mcp",
            server_name="google-drive",
            description="Google Drive MCP server",
            base_url="https://www.googleapis.com",
            auth=AuthPlan(type="oauth_bearer", ...),
            tools=[ToolPlan(tool_name="list_files", ...), ...],
            groups=[GroupPlan(name="file-operations", ...), ...],
        )
    """

    module_name: str  # Python module name, e.g. "google_drive_mcp"
    server_name: str  # DNS label, e.g. "google-drive"
    description: str
    base_url: str
    auth: AuthPlan
    tools: list[ToolPlan]
    groups: list[GroupPlan]


# ---------------------------------------------------------------------------
# Plan builder — the only function that touches the raw OpenAPI spec
# ---------------------------------------------------------------------------


def build_server_plan(scope: MCPScope, spec: OpenAPISpec) -> ServerPlan:
    """Build a ServerPlan from a validated scope and typed OpenAPI spec.

    Pipeline stage: planning (scope + spec → ServerPlan).
    Called by: cli.run_pipeline().

    This is the only place in the codebase that reads from both the MCPScope
    and the OpenAPI spec. After this function returns, all downstream code
    works exclusively with the ServerPlan.

    Args:
        scope: Validated mcp-scope.yaml content.
        spec: Typed OpenAPI spec (3.0 or 3.1).

    Returns:
        A fully populated ServerPlan ready for rendering.
    """
    module_name = server_name_to_module(scope.server.name)
    logger.info(
        "Building plan for server '%s' (module: %s)", scope.server.name, module_name
    )

    tools: list[ToolPlan] = []
    groups: list[GroupPlan] = []

    for group in scope.groups:
        group_tool_names: list[str] = []
        for tool in group.tools:
            tool_plan = _build_tool_plan(tool, spec, group.name)
            tools.append(tool_plan)
            group_tool_names.append(tool.tool_name)
        groups.append(GroupPlan(name=group.name, tool_names=group_tool_names))

    auth = _build_auth_plan(scope)

    return ServerPlan(
        module_name=module_name,
        server_name=scope.server.name,
        description=scope.server.description,
        base_url=scope.spec.base_url,
        auth=auth,
        tools=tools,
        groups=groups,
    )


def server_name_to_module(name: str) -> str:
    """Convert a DNS-label server name to a Python module name.

    Pipeline stage: planning (naming utility).

    Example:
        >>> server_name_to_module("google-drive")
        "google_drive_mcp"
    """
    return name.replace("-", "_") + "_mcp"


def _tool_name_to_class(name: str) -> str:
    """Convert a snake_case tool name to PascalCase.

    Example:
        >>> _tool_name_to_class("get_item")
        "GetItem"
    """
    return "".join(word.capitalize() for word in name.split("_"))


def _sanitize_name(name: str) -> str:
    """Convert an OpenAPI parameter name to a valid Python identifier.

    Replaces any non-alphanumeric character (hyphens, dots, dollar signs,
    brackets, etc.) with underscores, collapses runs of underscores, strips
    leading underscores, and prepends ``param_`` if the result starts with
    a digit or is empty. Also appends ``_`` to Python keywords.

    Example:
        >>> _sanitize_name("$filter")
        "filter"
        >>> _sanitize_name("page-size")
        "page_size"
        >>> _sanitize_name("from")
        "from_"
        >>> _sanitize_name("page[size]")
        "page_size"
    """
    # Replace any non-alphanumeric, non-underscore character with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Collapse runs of underscores and strip leading/trailing
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized or sanitized[0].isdigit():
        sanitized = "param_" + sanitized
    # Avoid Python keywords: from -> from_, class -> class_
    if keyword.iskeyword(sanitized):
        sanitized += "_"
    return sanitized


def _build_tool_plan(tool: Tool, spec: OpenAPISpec, group_name: str) -> ToolPlan:
    """Build a ToolPlan for a single tool definition.

    Extracts parameters from the OpenAPI spec, applies YAML overrides,
    sanitizes names, and detects collisions.
    """
    tool_name = tool.tool_name
    endpoint = tool.endpoint
    description = tool.description
    parameters = tool.parameters or []
    hints: list[str] = tool.hints or []

    method, path = parse_endpoint(endpoint)

    # Build YAML override lookup: name → (description, required)
    yaml_overrides: dict[str, tuple[str, bool]] = {
        p.name: (p.description, p.required) for p in parameters
    }

    # Extract params from spec and apply overrides.
    # NOTE: We intentionally skip header and cookie parameters — they are not
    # exposed as tool arguments. Auth headers are handled by the client layer
    # (token passthrough), and cookie params are not relevant for MCP tools.
    spec_params = get_parameters(spec, method, path)
    path_params = _build_param_plans(
        [p for p in spec_params if p.location == "path"], yaml_overrides, "path"
    )
    query_params = _build_param_plans(
        [p for p in spec_params if p.location == "query"], yaml_overrides, "query"
    )

    # Extract body fields
    spec_body = get_body_fields(spec, method, path)
    body_fields = _build_body_param_plans(spec_body, yaml_overrides)

    # Detect and resolve name collisions across all param locations
    all_params = path_params + query_params + body_fields
    _resolve_name_collisions(all_params)

    return ToolPlan(
        tool_name=tool_name,
        class_name=_tool_name_to_class(tool_name),
        http_method=method,
        path=path,
        description=description,
        path_params=path_params,
        query_params=query_params,
        body_fields=body_fields,
        hints=hints,
        group_name=group_name,
    )


def _build_param_plans(
    params: list[ExtractedParameter],
    yaml_overrides: dict[str, tuple[str, bool]],
    location: Literal["path", "query"],
) -> list[ParamPlan]:
    """Convert extracted parameters into ParamPlan objects with YAML overrides applied."""
    plans = []
    for param in params:
        desc = param.description
        required = param.required
        if param.name in yaml_overrides:
            desc, required = yaml_overrides[param.name]
        py_type = OPENAPI_TYPE_MAP.get(param.schema_type, "str")
        plans.append(
            ParamPlan(
                name=param.name,
                py_name=_sanitize_name(param.name),
                py_type=py_type,
                description=desc,
                required=required,
                location=location,
                original_name=param.name,
            )
        )
    return plans


def _build_body_param_plans(
    fields: list[ExtractedBodyField],
    yaml_overrides: dict[str, tuple[str, bool]],
) -> list[ParamPlan]:
    """Convert extracted body fields into ParamPlan objects."""
    plans = []
    for field in fields:
        desc = field.description
        required = field.required
        if field.name in yaml_overrides:
            desc, required = yaml_overrides[field.name]
        py_type = OPENAPI_TYPE_MAP.get(field.schema_type, "str")
        plans.append(
            ParamPlan(
                name=field.name,
                py_name=_sanitize_name(field.name),
                py_type=py_type,
                description=desc,
                required=required,
                location="body",
                original_name=field.name,
            )
        )
    return plans


def _resolve_name_collisions(params: list[ParamPlan]) -> None:
    """Detect and resolve py_name collisions by suffixing with location.

    Mutates the params in-place. If two params have the same py_name
    (e.g., "id" from both path and query), they get suffixed:
    "id_path" and "id_query".

    Runs a second pass to catch collisions introduced by the first rename
    (e.g., "foo-bar" and "foo.bar" both become "foo_bar", then both become
    "foo_bar_query" if they're in the same location). In that case, appends
    a numeric suffix.
    """
    # First pass: suffix with location
    seen: dict[str, list[ParamPlan]] = {}
    for p in params:
        seen.setdefault(p.py_name, []).append(p)

    for py_name, group in seen.items():
        if len(group) > 1:
            for p in group:
                p.py_name = f"{py_name}_{p.location}"

    # Second pass: if location-suffixed names still collide, add numeric suffix
    seen2: dict[str, list[ParamPlan]] = {}
    for p in params:
        seen2.setdefault(p.py_name, []).append(p)

    for py_name, group in seen2.items():
        if len(group) > 1:
            for i, p in enumerate(group):
                p.py_name = f"{py_name}_{i + 1}" if i > 0 else py_name


def _build_auth_plan(scope: MCPScope) -> AuthPlan:
    """Extract auth configuration from scope into an AuthPlan."""
    if scope.auth.type == "oauth_bearer" and scope.auth.oauth is not None:
        return AuthPlan(
            type="oauth_bearer",
            issuer=scope.auth.oauth.issuer,
            scopes=list(scope.auth.oauth.scopes),
        )
    return AuthPlan(type=scope.auth.type)
