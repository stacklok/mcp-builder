"""Type definitions and constants for OpenAPI spec parsing.

This module contains only type aliases, pydantic models, and constants.
No functions — it serves as the shared vocabulary for the spec package.

OpenAPI terminology:
    - Parameter: a named value passed via URL path, query string, header,
      or cookie (e.g., ``itemId`` in /items/{itemId}).
    - Body field: a property of the JSON request body schema
      (e.g., ``name`` in {"name": "foo"}).
"""

from __future__ import annotations

from typing import Literal

from openapi_pydantic.v3.v3_0 import OpenAPI as OpenAPI30
from openapi_pydantic.v3.v3_0 import Schema as Schema30
from openapi_pydantic.v3.v3_1 import OpenAPI as OpenAPI31
from openapi_pydantic.v3.v3_1 import Schema as Schema31
from pydantic import BaseModel

# Union of both OpenAPI versions. The field interfaces are identical
# (same names, same types) so downstream code can treat them uniformly.
OpenAPISpec = OpenAPI30 | OpenAPI31
OpenAPISchema = Schema30 | Schema31

# The set of parameter locations, schema types, and Python types we support,
# expressed as Literal types for static type safety.
ParameterLocation = Literal["path", "query", "header", "cookie"]
PythonType = Literal["str", "int", "float", "bool", "list", "dict"]

# OpenAPI types that map to Python built-in types. We intentionally error
# on unknown types rather than silently defaulting to str — this catches
# spec issues early rather than producing subtly wrong generated code.
OPENAPI_TYPE_MAP: dict[str, PythonType] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}
SchemaType = Literal["string", "integer", "number", "boolean", "array", "object"]


class ExtractedParameter(BaseModel):
    """A single parameter extracted from an OpenAPI operation.

    Consumed by: codegen.plan.build_server_plan() to build ParamPlan objects.

    Example (from GET /items/{itemId}):
        ExtractedParameter(
            name="itemId", location="path", required=True,
            schema_type="string", description="The ID of the item."
        )
    """

    name: str
    location: ParameterLocation
    required: bool = False
    schema_type: SchemaType = "string"
    description: str = ""


class ExtractedBodyField(BaseModel):
    """A single field from a request body schema.

    Consumed by: codegen.plan.build_server_plan() to build ParamPlan objects
    with location="body".

    Example (from POST /items with CreateItemRequest body):
        ExtractedBodyField(
            name="name", schema_type="string",
            description="The name of the item.", required=True
        )
    """

    name: str
    schema_type: SchemaType = "string"
    description: str = ""
    required: bool = False
