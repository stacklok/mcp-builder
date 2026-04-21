"""Scope validation: check an MCPScope against an OpenAPI spec.

Pipeline stage: validation (scope + optional spec → errors/warnings).
This module sits at the same abstraction level as plan.py and analyzer.py —
it's a domain operation that consumes the low-level spec/ and schema/ packages.
"""

from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, Field

from mcp_builder.schema.models import MCPScope, ParamLocation
from mcp_builder.spec import (
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

                # Generated client calls response.json() unconditionally;
                # a non-JSON 2xx body crashes at runtime. Surface it so
                # the scoping model can drop the endpoint.
                response_types = get_response_content_types(spec, method, path)
                _check_response_content_types(
                    tool.tool_name, response_types, errors, warnings
                )

    logger.info(
        "validation complete",
        error_count=len(errors),
        warning_count=len(warnings),
    )
    return ValidationResult(errors=errors, warnings=warnings)


# Matches application/json, text/json, and any RFC 6839 structured-suffix
# JSON type (application/vnd.api+json, application/ld+json, etc.).
_JSON_MEDIA_RE = re.compile(
    r"^(?:application|text)/(?:[\w.+-]+\+)?json$", re.IGNORECASE
)


def _is_json_media_type(media_type: str) -> bool:
    """Return True if the media type is JSON-decodable.

    Accepts ``application/json``, ``text/json`` (legacy), and any
    ``application/foo+json`` / ``text/foo+json`` structured-suffix
    variant per RFC 6839.
    """
    # Strip media-type parameters like "; charset=utf-8" before matching.
    bare = media_type.split(";", 1)[0].strip()
    return bool(_JSON_MEDIA_RE.match(bare))


def _check_response_content_types(
    tool_name: str,
    response_types: dict[str, list[str]],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Error if any 2xx status can return a body the JSON-only client cannot decode.

    Four outcomes:

    - No 2xx responses declared at all → warning (spec is incomplete;
      we can't prove anything).
    - Every 2xx response has an empty ``content`` block (e.g. 204 No
      Content) → silent pass; no body to decode.
    - Every 2xx response with content includes at least one JSON media
      type → silent pass.
    - Any 2xx response declares content without a JSON option → error,
      naming the offending status codes and media types.

    The rule is per-status, not flattened: a spec that returns
    ``application/pdf`` on 200 and ``application/json`` on 201 still
    errors, because the server will crash on 200.
    """
    if not response_types:
        warnings.append(
            f"Tool '{tool_name}': spec declares no 2xx responses — "
            "unable to verify the generated client can decode the "
            "response body. The spec may be incomplete."
        )
        return

    offending: dict[str, list[str]] = {}
    any_with_content = False
    for status, media_types in response_types.items():
        if not media_types:
            continue
        any_with_content = True
        if not any(_is_json_media_type(mt) for mt in media_types):
            offending[status] = media_types

    if not any_with_content:
        return  # All 2xx responses are 204-style; no body to decode.

    if offending:
        detail = "; ".join(
            f"{status} returns {', '.join(sorted(offending[status]))}"
            for status in sorted(offending)
        )
        errors.append(
            f"Tool '{tool_name}': 2xx response(s) declare non-JSON content "
            f"type(s) ({detail}), but the generated client only handles "
            "application/json. The resulting server will crash at "
            "runtime when calling this endpoint. Exclude this tool from "
            "the scope, or track the gap in "
            "https://github.com/StacklokLabs/mcp-builder/issues/81 "
            "(binary/non-JSON response support)."
        )
