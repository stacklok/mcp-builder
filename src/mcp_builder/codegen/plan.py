"""ServerPlan: the typed intermediate representation for code generation.

Pipeline stage: planning (MCPScope + OpenAPI → ServerPlan).
This module defines the data contract between spec analysis and rendering.
All raw OpenAPI access happens here in build_server_plan(). Downstream
renderers only receive the ServerPlan and never touch the spec.

Terminology (OpenAPI → plan mapping):
    - Parameters: path/query args from the URL (e.g., /items/{id}?fields=name).
      Defined in the operation's ``parameters`` array.
    - Body fields: properties of the JSON request body schema
      (e.g., {"color": "red"}). Defined under ``requestBody.content``.
    - Both are flattened into ParamPlan objects with a ``location`` tag
      ("path", "query", or "body") so renderers don't need to know the
      OpenAPI distinction.

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
import re
from typing import Literal

import structlog

from pydantic import BaseModel

from mcp_builder.codegen.spec_parser import (
    OPENAPI_TYPE_MAP,
    ExtractedBodyField,
    ExtractedParameter,
    OpenAPISpec,
    PythonType,
    get_body_fields,
    get_parameters,
    parse_endpoint,
)
from mcp_builder.schema.models import MCPScope, Tool

logger = structlog.get_logger()


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
    py_type: PythonType
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
            base_url="https://www.googleapis.com/drive/v3",
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
        "building server plan",
        server_name=scope.server.name,
        module_name=module_name,
    )

    tools: list[ToolPlan] = []
    groups: list[GroupPlan] = []

    for group in scope.groups:
        logger.debug(
            "processing group", group_name=group.name, tool_count=len(group.tools)
        )
        group_tool_names: list[str] = []
        for tool in group.tools:
            tool_plan = _build_tool_plan(tool, spec, group.name)
            tools.append(tool_plan)
            group_tool_names.append(tool.tool_name)
            logger.debug(
                "built tool plan",
                tool_name=tool.tool_name,
                path_params=len(tool_plan.path_params),
                query_params=len(tool_plan.query_params),
                body_fields=len(tool_plan.body_fields),
            )
        groups.append(GroupPlan(name=group.name, tool_names=group_tool_names))

    auth = _build_auth_plan(scope)

    logger.info("plan complete", tool_count=len(tools), group_count=len(groups))

    return ServerPlan(
        module_name=module_name,
        server_name=scope.server.name,
        description=scope.server.description,
        base_url=scope.spec.base_url,
        auth=auth,
        tools=tools,
        groups=groups,
    )


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
    logger.debug("building tool plan", tool_name=tool_name, endpoint=endpoint)

    # Build YAML override lookup: name → (description, required)
    yaml_overrides: dict[str, tuple[str, bool]] = {
        p.name: (p.description, p.required) for p in parameters
    }
    if yaml_overrides:
        logger.debug(
            "yaml overrides", tool_name=tool_name, override_keys=list(yaml_overrides)
        )

    # OpenAPI splits parameters into three locations. For a request like
    #   POST /items/{itemId}?fields=name  { "color": "red" }
    # the three param kinds are:
    #   path_params  — URL template slots (e.g., itemId)
    #   query_params — ?key=value pairs  (e.g., fields)
    #   body_fields  — JSON request body properties (e.g., color)
    #
    # NOTE: We intentionally skip header and cookie parameters — they are not
    # exposed as tool arguments. Auth headers are handled by the client layer
    # (token passthrough), and cookie params are not relevant for MCP tools.
    spec_params = get_parameters(spec, method, path)
    skipped = [p for p in spec_params if p.location not in ("path", "query")]
    if skipped:
        logger.debug(
            "skipping header/cookie params",
            tool_name=tool_name,
            skipped=[p.name for p in skipped],
        )
    path_params = _build_param_plans(
        [p for p in spec_params if p.location == "path"], yaml_overrides, "path"
    )
    query_params = _build_param_plans(
        [p for p in spec_params if p.location == "query"], yaml_overrides, "query"
    )

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
    """Convert URL parameters (path/query) into ParamPlan objects.

    Input comes from the operation's ``parameters`` array in the OpenAPI spec.
    YAML overrides from the scope file are applied on top.
    """
    plans = []
    for param in params:
        desc = param.description
        required = param.required
        if param.name in yaml_overrides:
            desc, required = yaml_overrides[param.name]
            logger.debug(
                "applied yaml override",
                param_name=param.name,
                location=location,
                required=required,
            )
        py_name = _sanitize_name(param.name)
        py_type = OPENAPI_TYPE_MAP[param.schema_type]
        logger.debug(
            "param plan",
            name=param.name,
            py_name=py_name,
            py_type=py_type,
            location=location,
            required=required,
        )
        plans.append(
            ParamPlan(
                name=param.name,
                py_name=py_name,
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
    """Convert JSON request body properties into ParamPlan objects.

    Input comes from the ``requestBody`` schema in the OpenAPI spec.
    YAML overrides from the scope file are applied on top.
    """
    plans = []
    for field in fields:
        desc = field.description
        required = field.required
        if field.name in yaml_overrides:
            desc, required = yaml_overrides[field.name]
            logger.debug(
                "applied yaml override",
                field_name=field.name,
                location="body",
                required=required,
            )
        py_name = _sanitize_name(field.name)
        py_type = OPENAPI_TYPE_MAP[field.schema_type]
        logger.debug(
            "body param plan",
            name=field.name,
            py_name=py_name,
            py_type=py_type,
            required=required,
        )
        plans.append(
            ParamPlan(
                name=field.name,
                py_name=py_name,
                py_type=py_type,
                description=desc,
                required=required,
                location="body",
                original_name=field.name,
            )
        )
    return plans


def _build_auth_plan(scope: MCPScope) -> AuthPlan:
    """Extract auth configuration from scope into an AuthPlan."""
    logger.debug("building auth plan", auth_type=scope.auth.type)
    if scope.auth.type == "oauth_bearer" and scope.auth.oauth is not None:
        logger.debug(
            "oauth config",
            issuer=scope.auth.oauth.issuer,
            scopes=scope.auth.oauth.scopes,
        )
        return AuthPlan(
            type="oauth_bearer",
            issuer=scope.auth.oauth.issuer,
            scopes=list(scope.auth.oauth.scopes),
        )
    return AuthPlan(type=scope.auth.type)


# ---------------------------------------------------------------------------
# Utilities — naming, sanitization, collision resolution
# ---------------------------------------------------------------------------


def server_name_to_module(name: str) -> str:
    """Convert a DNS-label server name to a Python module name.

    The generated MCP server project uses this as its Python package name
    (e.g., the directory under src/).

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
    if sanitized != name:
        logger.debug("sanitized name", original=name, sanitized=sanitized)
    return sanitized


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
    logger.debug("checking for name collisions", param_count=len(params))

    # First pass: suffix with location
    seen: dict[str, list[ParamPlan]] = {}
    for p in params:
        seen.setdefault(p.py_name, []).append(p)

    for py_name, group in seen.items():
        if len(group) > 1:
            logger.warning(
                "name collision detected",
                py_name=py_name,
                params=[(p.name, p.location) for p in group],
            )
            for p in group:
                old_name = p.py_name
                p.py_name = f"{py_name}_{p.location}"
                logger.debug(
                    "collision rename (location suffix)",
                    original=old_name,
                    renamed=p.py_name,
                    param_name=p.name,
                    location=p.location,
                )

    # Second pass: if location-suffixed names still collide, add numeric suffix
    seen2: dict[str, list[ParamPlan]] = {}
    for p in params:
        seen2.setdefault(p.py_name, []).append(p)

    for py_name, group in seen2.items():
        if len(group) > 1:
            logger.warning(
                "post-suffix collision",
                py_name=py_name,
                params=[(p.name, p.location) for p in group],
            )
            for i, p in enumerate(group):
                old_name = p.py_name
                p.py_name = f"{py_name}_{i + 1}" if i > 0 else py_name
                if p.py_name != old_name:
                    logger.debug(
                        "collision rename (numeric suffix)",
                        original=old_name,
                        renamed=p.py_name,
                    )

    collisions_found = any(len(g) > 1 for g in seen.values())
    if not collisions_found:
        logger.debug("no name collisions detected")
