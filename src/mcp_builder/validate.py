"""Scope validation: check an MCPScope against an OpenAPI spec.

Pipeline stage: validation (scope + optional spec → errors/warnings).
This module sits at the same abstraction level as plan.py and analyzer.py —
it's a domain operation that consumes the low-level spec/ and schema/ packages.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from mcp_builder.spec.media import is_json_media_type
from mcp_builder.schema.models import MCPScope, ParamLocation
from mcp_builder.spec import (
    ExtractedResponse,
    OpenAPISpec,
    get_body_fields,
    get_parameters,
    get_response_content_types,
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
                            if spec_body_names:
                                # Spec declares body properties but the YAML
                                # param doesn't match any of them — typically
                                # a YAML authoring issue (e.g. a `body`
                                # catch-all), not an incomplete spec.
                                available = ", ".join(sorted(spec_body_names))
                                warnings.append(
                                    f"Tool '{tool.tool_name}': body parameter "
                                    f"'{param.name}' not found in spec's "
                                    f"requestBody properties "
                                    f"(available: {available}). Type will "
                                    f"default to str. Consider expanding "
                                    f"this into per-field body parameters "
                                    f"to match the spec schema."
                                )
                            else:
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

                # Scope's response_kind commits the generated tool to one
                # decode path; cross-check it against the spec so a
                # mismatch surfaces now instead of at runtime.
                responses = get_response_content_types(spec, method, path)
                _check_response_kind_matches_spec(
                    tool.tool_name,
                    tool.response_kind,
                    responses,
                    errors,
                    warnings,
                )

    logger.info(
        "validation complete",
        error_count=len(errors),
        warning_count=len(warnings),
    )
    return ValidationResult(errors=errors, warnings=warnings)


def _check_response_kind_matches_spec(
    tool_name: str,
    response_kind: str,
    responses: list[ExtractedResponse],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Cross-check a tool's scope ``response_kind`` against the spec's 2xx media types.

    The scope commits the generated tool to a single decode path. When
    the spec and the scope disagree, the fix is in the scope — the
    author controls the scope YAML; the upstream OpenAPI spec they
    typically don't.

    The generated client sends ``Accept: application/json`` for
    ``response_kind=json`` and ``Accept: */*`` for ``response_kind=binary``.
    A status that offers both JSON and non-JSON (e.g. 200 returns
    ``application/json, application/xml``) is therefore safe for
    ``json`` — content negotiation picks JSON — but unsafe for
    ``binary``, which could hand the caller base64-wrapped JSON
    depending on the server's default.

    Outcomes:

    - Spec declares no 2xx responses: warning (can't verify the choice).
    - Spec's 2xx responses all have empty content (204-style): silent pass.
    - ``response_kind="json"`` but some 2xx status offers no JSON option: error.
    - ``response_kind="binary"`` but some 2xx status offers JSON: error.
    """
    if not responses:
        warnings.append(
            f"Tool '{tool_name}': spec declares no 2xx responses — "
            "unable to verify the generated client can decode the "
            "response body. The spec may be incomplete."
        )
        return

    responses_with_content = [r for r in responses if r.media_types]
    if not responses_with_content:
        return  # All 2xx responses are 204-style; no body to decode.

    if response_kind == "json":
        # Every 2xx with content must offer at least one JSON media type
        # so the generated client's ``Accept: application/json`` header
        # can negotiate a JSON body. A status that offers both JSON and
        # XML is fine — the Accept header picks JSON.
        bad = [
            r
            for r in responses_with_content
            if not any(is_json_media_type(mt) for mt in r.media_types)
        ]
        if bad:
            detail = "; ".join(
                f"{resp.status_code} returns {', '.join(resp.media_types)}"
                for resp in sorted(bad, key=lambda r: r.status_code)
            )
            errors.append(
                f"Tool '{tool_name}': scope declares response_kind='json' "
                f"but spec's 2xx responses have no JSON content type "
                f"({detail}). Update the scope to response_kind='binary' "
                "or drop the endpoint from the scope."
            )
        return

    if response_kind == "binary":
        # No 2xx status may offer JSON — the generated client sends
        # ``Accept: */*``, so a JSON-capable server could return JSON
        # that would then get base64-wrapped and returned as opaque
        # bytes.
        bad = [
            r
            for r in responses_with_content
            if any(is_json_media_type(mt) for mt in r.media_types)
        ]
        if bad:
            detail = "; ".join(
                f"{resp.status_code} returns {', '.join(resp.media_types)}"
                for resp in sorted(bad, key=lambda r: r.status_code)
            )
            errors.append(
                f"Tool '{tool_name}': scope declares response_kind='binary' "
                f"but spec's 2xx responses include JSON ({detail}). Update "
                "the scope to response_kind='json' or drop the endpoint "
                "from the scope."
            )
        return
