"""Low-level OpenAPI spec parsing.

This package handles file I/O, type extraction, and $ref resolution.
No business logic — purely mechanical parsing of OpenAPI specs.

Public API (re-exported here for convenience):
    - load_openapi_spec() — load a spec from a JSON/YAML file
    - get_parameters() — extract parameters from an operation
    - get_body_fields() — extract request body fields from an operation
    - parse_endpoint() — split "METHOD /path" into components
    - resolve_parameter_ref() — resolve a $ref to a parameter component
    - resolve_request_body_ref() — resolve a $ref to a requestBody component
    - resolve_schema_ref() — resolve a $ref to a schema component
    - extract_schema_type() — get the schema type from a parameter
    - schema_to_type() — get the schema type from a schema object
    - Type aliases: OpenAPISpec, OpenAPISchema, ExtractedParameter,
      ExtractedBodyField, ParameterLocation, PythonType, SchemaType
    - Constants: OPENAPI_TYPE_MAP
"""

from mcp_builder.spec.loader import load_openapi_spec
from mcp_builder.spec.parameters import get_body_fields, get_parameters, parse_endpoint
from mcp_builder.spec.resolver import (
    extract_schema_type,
    resolve_parameter_ref,
    resolve_request_body_ref,
    resolve_schema_ref,
    schema_to_type,
)
from mcp_builder.spec.types import (
    OPENAPI_TYPE_MAP,
    ExtractedBodyField,
    ExtractedParameter,
    OpenAPISchema,
    OpenAPISpec,
    ParameterLocation,
    PythonType,
    SchemaType,
)

__all__ = [
    "OPENAPI_TYPE_MAP",
    "ExtractedBodyField",
    "ExtractedParameter",
    "OpenAPISchema",
    "OpenAPISpec",
    "ParameterLocation",
    "PythonType",
    "SchemaType",
    "extract_schema_type",
    "get_body_fields",
    "get_parameters",
    "load_openapi_spec",
    "parse_endpoint",
    "resolve_parameter_ref",
    "resolve_request_body_ref",
    "resolve_schema_ref",
    "schema_to_type",
]
