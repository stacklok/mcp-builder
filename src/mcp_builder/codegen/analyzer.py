"""Spec analysis: summarize an OpenAPI spec for human review.

Pipeline stage: analysis (spec → structured summary).
This module sits at the same abstraction level as plan.py and validator.py —
it's a domain operation that consumes the low-level spec/ package.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from mcp_builder.spec import OpenAPISpec, get_body_fields, get_parameters

logger = structlog.get_logger()


class EndpointSummary(BaseModel):
    """Summary of a single operation in the spec."""

    method: str
    path: str
    operation_id: str | None = None
    summary: str = ""
    parameter_count: int = 0
    body_field_count: int = 0


class SpecAnalysis(BaseModel):
    """Structured summary of an OpenAPI spec."""

    title: str
    version: str
    base_url: str = ""
    endpoint_count: int = 0
    endpoints: list[EndpointSummary] = Field(default_factory=list)


def analyze_spec(spec: OpenAPISpec) -> SpecAnalysis:
    """Analyze an OpenAPI spec and return a structured summary.

    Walks every path and operation in the spec, counting parameters and
    body fields for each. The result is a machine-readable overview useful
    for understanding what a spec exposes before writing a scope file.

    Args:
        spec: Typed OpenAPI spec (3.0 or 3.1).

    Returns:
        A SpecAnalysis summarizing the spec's endpoints.
    """
    logger.info("analyzing spec", title=spec.info.title)

    # Extract base URL from servers list (first server, if present)
    base_url = ""
    if spec.servers:
        base_url = spec.servers[0].url

    endpoints: list[EndpointSummary] = []
    methods = ("get", "post", "put", "patch", "delete")

    for path, path_item in (spec.paths or {}).items():
        for method_name in methods:
            operation = getattr(path_item, method_name, None)
            if operation is None:
                continue

            method_upper = method_name.upper()
            param_count = len(get_parameters(spec, method_upper, path))
            body_count = len(get_body_fields(spec, method_upper, path))

            endpoints.append(
                EndpointSummary(
                    method=method_upper,
                    path=path,
                    operation_id=getattr(operation, "operationId", None),
                    summary=getattr(operation, "summary", None) or "",
                    parameter_count=param_count,
                    body_field_count=body_count,
                )
            )

    logger.info("spec analysis complete", endpoint_count=len(endpoints))

    return SpecAnalysis(
        title=spec.info.title,
        version=spec.info.version,
        base_url=base_url,
        endpoint_count=len(endpoints),
        endpoints=endpoints,
    )
