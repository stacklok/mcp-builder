"""Low-level OpenAPI spec parsing.

An OpenAPI spec is a machine-readable description of a REST API, written in
YAML or JSON. It lists every URL path the API exposes (e.g. ``/items/{itemId}``),
what HTTP methods each path supports (GET, POST, ...), and what data each
endpoint expects and returns.

This package turns those raw spec files into typed Python objects so that the
code generation pipeline can work with them safely. It handles:

    - **Loading** — reading a YAML/JSON file into a typed model (``loader``).
    - **Parameters** — extracting the inputs an endpoint expects.
      In a REST API, inputs arrive in two places:

        * **URL parameters** — values embedded in the URL itself.
          Path parameters like ``{itemId}`` in ``/items/{itemId}`` and query
          parameters like ``?fields=name`` are both URL parameters.
        * **Body fields** — properties of the JSON object sent in the request
          body (typically for POST/PUT/PATCH). For example, ``{"name": "Foo"}``
          has one body field called ``name``.

    - **$ref resolution** — OpenAPI specs use JSON Reference pointers
      (``$ref: '#/components/parameters/owner'``) to avoid repeating the same
      definition in multiple places. The ``resolver`` module looks up these
      pointers and returns the actual object they point to.

Public API (re-exported here for convenience):
    - load_openapi_spec() — load a spec from a JSON/YAML file
    - get_parameters() — extract URL parameters from an operation
    - get_body_fields() — extract request body fields from an operation
    - parse_endpoint() — split "METHOD /path" into components
    - resolve_parameter_ref() — resolve a $ref to a parameter component
    - resolve_request_body_ref() — resolve a $ref to a requestBody component
    - resolve_schema_ref() — resolve a $ref to a schema component
    - resolve_composed_schema() — flatten allOf/oneOf/anyOf into merged properties
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
    resolve_composed_schema,
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
    "resolve_composed_schema",
    "get_parameters",
    "load_openapi_spec",
    "parse_endpoint",
    "resolve_parameter_ref",
    "resolve_request_body_ref",
    "resolve_schema_ref",
    "schema_to_type",
]
