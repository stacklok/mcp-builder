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

                # Check success-response content types. "2xx" refers to
                # HTTP status codes in the 200–299 range (the success
                # family: 200 OK, 201 Created, 204 No Content, etc.) —
                # those are the only responses that shape the return
                # type of the generated tool. The generated client only
                # handles JSON today, so a non-JSON response (e.g.
                # image/jpeg, application/octet-stream) produces a server
                # that crashes at runtime with JSONDecodeError. Surface
                # it as an error here so the user/scoping model can
                # exclude the endpoint or track the gap.
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
# JSON type like application/vnd.api+json or application/ld+json. Python's
# stdlib has no built-in primitive for the "+json" structured suffix, so
# we use a small regex rather than a chain of string operations — it's
# more declarative and keeps the RFC 6839 rule in one place.
_JSON_MEDIA_RE = re.compile(
    r"^(?:application|text)/(?:[\w.+-]+\+)?json$", re.IGNORECASE
)


def _is_json_media_type(media_type: str) -> bool:
    """Return True if the media type is JSON-decodable.

    Accepts ``application/json``, ``text/json`` (legacy), and any
    ``application/foo+json`` / ``text/foo+json`` structured-suffix
    variant per RFC 6839.
    """
    # Strip any parameters (e.g. "; charset=utf-8"). Content-type keys in
    # OpenAPI specs occasionally include them, though most omit the params.
    bare = media_type.split(";", 1)[0].strip()
    return bool(_JSON_MEDIA_RE.match(bare))


def _check_response_content_types(
    tool_name: str,
    response_types: dict[str, list[str]],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate that a tool's 2xx responses are JSON-compatible.

    Three signals (the generated client only handles JSON today):

    - No 2xx responses declared at all → warning (spec is incomplete; we
      can't know whether it will work).
    - All 2xx responses declare media types and none are JSON → error
      (server will crash at runtime on response.json()). Points the user
      at the fix: exclude the endpoint, or track the gap upstream.
    - All 2xx responses have no ``content`` block (e.g. 204 No Content)
      → silent pass; the generated code's empty-dict fallback is fine.
    """
    if not response_types:
        warnings.append(
            f"Tool '{tool_name}': spec declares no 2xx responses — "
            "unable to verify the generated client can decode the "
            "response body. The spec may be incomplete."
        )
        return

    has_any_content = False
    has_json = False
    observed_types: set[str] = set()
    for media_types in response_types.values():
        if not media_types:
            continue
        has_any_content = True
        for mt in media_types:
            observed_types.add(mt)
            if _is_json_media_type(mt):
                has_json = True
                break
        if has_json:
            break

    if has_any_content and not has_json:
        type_list = ", ".join(sorted(observed_types))
        errors.append(
            f"Tool '{tool_name}': 2xx response declares non-JSON content "
            f"type(s) ({type_list}), but the generated client only "
            "handles application/json. The resulting server will crash "
            "at runtime when calling this endpoint. Exclude this tool "
            "from the scope, or track the gap in "
            "https://github.com/StacklokLabs/mcp-builder/issues/81 "
            "(binary/non-JSON response support)."
        )
