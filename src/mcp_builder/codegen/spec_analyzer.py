"""OpenAPI spec analysis for AI scoping and human review.

Surveys all endpoints in an OpenAPI spec, capturing parameters, errors,
security schemes, and quality metrics as typed Pydantic output.

Error policy: SOFT. This module serves the ``analyze`` CLI command, which
produces a structured survey for humans and AI agents. One bad endpoint
must not block the whole analysis, so extraction errors are captured
per-endpoint in the ``errors`` list rather than raised. This is the
opposite of the spec package (mcp_builder.spec), which feeds code
generation and must fail fast on any unresolvable input.

One-directional dependency: spec_analyzer -> mcp_builder.spec.
"""

from __future__ import annotations

import structlog
from openapi_pydantic.v3.v3_0 import Parameter as OAParam30
from openapi_pydantic.v3.v3_0 import Reference as Ref30
from openapi_pydantic.v3.v3_0 import SecurityScheme as SecScheme30
from openapi_pydantic.v3.v3_1 import Parameter as OAParam31
from openapi_pydantic.v3.v3_1 import Reference as Ref31
from openapi_pydantic.v3.v3_1 import SecurityScheme as SecScheme31
from pydantic import BaseModel, Field

from mcp_builder.spec import (
    OpenAPISpec,
    extract_schema_type,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pydantic models — field names match the consumer-facing JSON contract
# ---------------------------------------------------------------------------


class AnalyzedParameter(BaseModel):
    name: str
    # "in" is a Python keyword, so the field is stored as ``location`` but
    # serialised as "in" for JSON output.
    location: str = Field(serialization_alias="in")
    required: bool
    description: str
    # Stored as ``schema_type``, serialised as "type" for JSON output.
    schema_type: str = Field(serialization_alias="type")


class AnalyzedRequestBody(BaseModel):
    content_type: str
    required: bool
    description: str


class AnalyzedEndpoint(BaseModel):
    method: str
    path: str
    operation_id: str | None
    summary: str | None
    description: str | None
    tags: list[str]
    deprecated: bool
    parameters: list[AnalyzedParameter]
    request_body: AnalyzedRequestBody | None
    errors: list[str]


class OAuthFlowInfo(BaseModel):
    flow_type: str
    authorization_url: str | None
    token_url: str | None
    scopes: dict[str, str]


class SecuritySchemeInfo(BaseModel):
    type: str
    scheme: str | None
    parameter_name: str | None
    location: str | None
    openid_connect_url: str | None
    flows: dict[str, OAuthFlowInfo]


class QualityMetrics(BaseModel):
    endpoint_count: int
    endpoints_with_descriptions: int
    total_parameters: int
    parameters_with_descriptions: int


class SpecAnalysis(BaseModel):
    spec_version: str
    base_url: str
    security_schemes: dict[str, SecuritySchemeInfo]
    quality: QualityMetrics
    endpoints: list[AnalyzedEndpoint]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_spec(spec: OpenAPISpec) -> SpecAnalysis:
    """Analyze an OpenAPI spec, producing a typed survey of all endpoints.

    Walks every path/operation, extracts parameters (capturing extraction
    errors per-endpoint), collects security scheme definitions, and computes
    quality metrics.
    """
    endpoints = _analyze_endpoints(spec)
    security_schemes = _extract_security_schemes(spec)
    quality = _compute_quality(endpoints)

    base_url = ""
    if spec.servers:
        base_url = spec.servers[0].url or ""

    return SpecAnalysis(
        spec_version=spec.openapi,
        base_url=base_url,
        endpoints=endpoints,
        security_schemes=security_schemes,
        quality=quality,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _analyze_endpoints(spec: OpenAPISpec) -> list[AnalyzedEndpoint]:
    endpoints: list[AnalyzedEndpoint] = []
    for path, path_item in (spec.paths or {}).items():
        # Collect path-level parameters once per path
        path_params: list[OAParam30 | OAParam31] = []
        for p in path_item.parameters or []:
            if isinstance(p, Ref30 | Ref31):
                continue  # skip unresolvable refs at analysis level
            path_params.append(p)

        for method_name in HTTP_METHODS:
            operation = getattr(path_item, method_name, None)
            if operation is None:
                continue

            params: list[AnalyzedParameter] = []
            errors: list[str] = []

            # Merge path-level and operation-level parameters
            merged: dict[tuple[str, str], OAParam30 | OAParam31] = {}
            for p in path_params:
                merged[(p.name, p.param_in.value)] = p
            for p in operation.parameters or []:
                if isinstance(p, Ref30 | Ref31):
                    continue
                merged[(p.name, p.param_in.value)] = p

            for param in merged.values():
                try:
                    schema_type = extract_schema_type(param)
                except ValueError as exc:
                    errors.append(str(exc))
                    schema_type = "string"
                params.append(
                    AnalyzedParameter(
                        name=param.name,
                        location=param.param_in.value,
                        required=param.required,
                        schema_type=schema_type,
                        description=param.description or "",
                    )
                )

            # Extract request body info
            request_body = _extract_request_body(operation)

            endpoints.append(
                AnalyzedEndpoint(
                    method=method_name.upper(),
                    path=path,
                    operation_id=getattr(operation, "operationId", None),
                    summary=getattr(operation, "summary", None),
                    description=getattr(operation, "description", None),
                    tags=list(operation.tags or []),
                    deprecated=bool(getattr(operation, "deprecated", False)),
                    parameters=params,
                    request_body=request_body,
                    errors=errors,
                )
            )
    return endpoints


def _extract_request_body(operation: object) -> AnalyzedRequestBody | None:
    """Extract request body metadata from an operation, if present."""
    req_body = getattr(operation, "requestBody", None)
    if req_body is None:
        return None
    if isinstance(req_body, Ref30 | Ref31):
        # Unresolved $ref — report what we can
        return AnalyzedRequestBody(
            content_type="unknown",
            required=False,
            description=f"$ref: {req_body.ref}",
        )
    content = req_body.content or {}
    # Pick the first content type (prefer application/json)
    content_type = (
        "application/json"
        if "application/json" in content
        else next(iter(content), "unknown")
    )
    return AnalyzedRequestBody(
        content_type=content_type,
        required=bool(req_body.required),
        description=req_body.description or "",
    )


def _extract_security_schemes(spec: OpenAPISpec) -> dict[str, SecuritySchemeInfo]:
    if spec.components is None:
        return {}
    raw_schemes = spec.components.securitySchemes or {}
    result: dict[str, SecuritySchemeInfo] = {}
    for name, scheme in raw_schemes.items():
        if isinstance(scheme, Ref30 | Ref31):
            continue
        if not isinstance(scheme, SecScheme30 | SecScheme31):
            continue
        flows: dict[str, OAuthFlowInfo] = {}
        if scheme.flows:
            for flow_type in (
                "implicit",
                "password",
                "clientCredentials",
                "authorizationCode",
            ):
                flow = getattr(scheme.flows, flow_type, None)
                if flow is None:
                    continue
                flows[flow_type] = OAuthFlowInfo(
                    flow_type=flow_type,
                    authorization_url=getattr(flow, "authorizationUrl", None),
                    token_url=getattr(flow, "tokenUrl", None),
                    scopes=dict(flow.scopes) if flow.scopes else {},
                )
        result[name] = SecuritySchemeInfo(
            type=scheme.type,
            scheme=scheme.scheme,
            parameter_name=scheme.name,
            location=getattr(scheme, "security_scheme_in", None),
            openid_connect_url=getattr(scheme, "openIdConnectUrl", None),
            flows=flows,
        )
    return result


def _compute_quality(endpoints: list[AnalyzedEndpoint]) -> QualityMetrics:
    endpoint_count = len(endpoints)
    endpoints_with_desc = sum(1 for e in endpoints if e.description)
    all_params = [p for e in endpoints for p in e.parameters]
    total_params = len(all_params)
    params_with_desc = sum(1 for p in all_params if p.description)
    return QualityMetrics(
        endpoint_count=endpoint_count,
        endpoints_with_descriptions=endpoints_with_desc,
        total_parameters=total_params,
        parameters_with_descriptions=params_with_desc,
    )
