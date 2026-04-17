"""Scope validation: check an MCPScope against an OpenAPI spec.

Pipeline stage: validation (scope + optional spec → errors/warnings).
This module sits at the same abstraction level as plan.py and analyzer.py —
it's a domain operation that consumes the low-level spec/ and schema/ packages.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from mcp_builder.schema.models import MCPScope, ParamLocation
from mcp_builder.spec import (
    OpenAPISpec,
    get_body_fields,
    get_parameters,
    parse_endpoint,
)

logger = structlog.get_logger()


class ValidationResult(BaseModel):
    """Result of validating a scope, optionally against a spec."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_scope(
    scope: MCPScope, spec: OpenAPISpec | None = None
) -> ValidationResult:
    """Validate a scope file, optionally checking endpoints against a spec.

    Without a spec, performs structural checks on the scope itself.
    With a spec, also verifies that every endpoint in the scope exists
    in the spec.

    Args:
        scope: Validated MCPScope from a scope YAML file.
        spec: Optional typed OpenAPI spec to cross-reference.

    Returns:
        A ValidationResult with any errors and warnings found.
    """
    logger.info("validating scope", server_name=scope.server.name)
    errors: list[str] = []
    warnings: list[str] = []

    # Check that groups have descriptions
    for group in scope.groups:
        if not group.description.strip():
            warnings.append(f"Group '{group.name}' has an empty description.")

    # Check tool hints and parameter overrides
    for group in scope.groups:
        for tool in group.tools:
            if tool.parameters:
                for param in tool.parameters:
                    if not param.description.strip():
                        warnings.append(
                            f"Parameter override '{param.name}' in tool "
                            f"'{tool.tool_name}' has an empty description."
                        )

    # Cross-reference with spec if provided
    if spec is not None:
        spec_paths = spec.paths or {}
        for group in scope.groups:
            for tool in group.tools:
                method, path = parse_endpoint(tool.endpoint)
                path_item = spec_paths.get(path)
                if path_item is None:
                    errors.append(
                        f"Tool '{tool.tool_name}': path '{path}' "
                        "not found in OpenAPI spec."
                    )
                    continue
                operation = getattr(path_item, method.lower(), None)
                if operation is None:
                    errors.append(
                        f"Tool '{tool.tool_name}': method '{method}' "
                        f"not found for path '{path}' in OpenAPI spec."
                    )
                    continue

                # Check that each YAML parameter exists in the spec.
                # Params missing from the spec will default to type str
                # during code generation, which may be wrong.
                spec_params = get_parameters(spec, method, path)
                spec_body = get_body_fields(spec, method, path)
                spec_param_names = {p.name for p in spec_params}
                spec_body_names = {f.name for f in spec_body}
                for param in tool.parameters:
                    if param.location == ParamLocation.BODY:
                        if param.name not in spec_body_names:
                            warnings.append(
                                f"Tool '{tool.tool_name}': body parameter "
                                f"'{param.name}' not found in spec's "
                                f"requestBody — type will default to str. "
                                f"The spec may be incomplete."
                            )
                    else:
                        if param.name not in spec_param_names:
                            warnings.append(
                                f"Tool '{tool.tool_name}': {param.location} "
                                f"parameter '{param.name}' not found in "
                                f"spec's parameters — type will default to "
                                f"str. The spec may be incomplete."
                            )

    logger.info(
        "validation complete",
        error_count=len(errors),
        warning_count=len(warnings),
    )
    return ValidationResult(errors=errors, warnings=warnings)
