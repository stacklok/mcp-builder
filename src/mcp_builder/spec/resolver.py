"""$ref resolution and schema-level type utilities.

OpenAPI specs avoid repetition by using **$ref pointers** — instead of
writing out the same parameter or schema definition in every endpoint,
the spec says ``$ref: '#/components/parameters/owner'`` and defines
``owner`` once under ``components``. Think of it like a symbolic link:
the pointer says "go look over there for the real definition."

This module resolves those pointers: given a ``$ref`` string, it finds
the matching object in ``spec.components`` and returns it as a typed
Python object. It also provides schema-to-type extraction, which maps
OpenAPI schema types (``string``, ``integer``, ...) to the type names
used in code generation.
"""

from __future__ import annotations

from typing import cast

import structlog
from openapi_pydantic.v3.v3_0 import Parameter as OAParam30
from openapi_pydantic.v3.v3_0 import Reference as Ref30
from openapi_pydantic.v3.v3_0 import RequestBody as ReqBody30
from openapi_pydantic.v3.v3_1 import Parameter as OAParam31
from openapi_pydantic.v3.v3_1 import Reference as Ref31
from openapi_pydantic.v3.v3_1 import RequestBody as ReqBody31

from mcp_builder.spec.types import (
    OPENAPI_TYPE_MAP,
    OpenAPISchema,
    OpenAPISpec,
    SchemaType,
)

logger = structlog.get_logger()


def resolve_parameter_ref(spec: OpenAPISpec, ref: str) -> OAParam30 | OAParam31:
    """Look up an OpenAPI ``$ref`` string in ``spec.components.parameters``.

    OpenAPI specs use JSON Reference pointers like
    ``#/components/parameters/owner`` instead of inlining a parameter object.
    This function extracts the component name from the pointer (``owner``),
    finds the matching entry in ``spec.components.parameters``, and returns
    the resolved parameter object.

    Raises:
        ValueError: If the ref is external/non-component, the components
            section is missing, the named parameter doesn't exist, or it
            is itself a nested ``$ref``.
    """
    if not ref.startswith("#/components/parameters/"):
        raise ValueError(
            f"Cannot resolve parameter $ref '{ref}': "
            "only local '#/components/parameters/...' refs are supported."
        )
    param_name = ref.rsplit("/", 1)[-1]
    logger.debug("resolving parameter $ref", ref=ref, component=param_name)
    if spec.components is None:
        raise ValueError(
            f"Cannot resolve parameter $ref '{ref}': spec has no 'components' section."
        )
    params = spec.components.parameters or {}
    param = params.get(param_name)
    if param is None:
        raise ValueError(
            f"Cannot resolve parameter $ref '{ref}': "
            f"'{param_name}' not found in components.parameters."
        )
    if isinstance(param, Ref30 | Ref31):
        raise ValueError(
            f"Cannot resolve parameter $ref '{ref}': "
            f"'{param_name}' is itself a nested $ref, which is not supported."
        )
    logger.debug("resolved parameter $ref", param_name=param_name)
    return param


def resolve_request_body_ref(spec: OpenAPISpec, ref: str) -> ReqBody30 | ReqBody31:
    """Look up an OpenAPI ``$ref`` string in ``spec.components.requestBodies``.

    OpenAPI specs use JSON Reference pointers like
    ``#/components/requestBodies/CreateUserRequest`` instead of inlining a
    request body object. This function extracts the component name from the
    pointer, finds the matching entry in ``spec.components.requestBodies``,
    and returns the resolved request body object.

    Raises:
        ValueError: If the ref is external/non-component, the components
            section is missing, the named request body doesn't exist, or it
            is itself a nested ``$ref``.
    """
    if not ref.startswith("#/components/requestBodies/"):
        raise ValueError(
            f"Cannot resolve requestBody $ref '{ref}': "
            "only local '#/components/requestBodies/...' refs are supported."
        )
    body_name = ref.rsplit("/", 1)[-1]
    logger.debug("resolving requestBody $ref", ref=ref, component=body_name)
    if spec.components is None:
        raise ValueError(
            f"Cannot resolve requestBody $ref '{ref}': "
            "spec has no 'components' section."
        )
    bodies = spec.components.requestBodies or {}
    body = bodies.get(body_name)
    if body is None:
        raise ValueError(
            f"Cannot resolve requestBody $ref '{ref}': "
            f"'{body_name}' not found in components.requestBodies."
        )
    if isinstance(body, Ref30 | Ref31):
        raise ValueError(
            f"Cannot resolve requestBody $ref '{ref}': "
            f"'{body_name}' is itself a nested $ref, which is not supported."
        )
    logger.debug("resolved requestBody $ref", body_name=body_name)
    return body


def resolve_schema_ref(spec: OpenAPISpec, ref: str) -> OpenAPISchema:
    """Resolve a $ref string like '#/components/schemas/Foo' to the schema object.

    Raises:
        ValueError: If the ref is external/non-component, the components
            section is missing, the named schema doesn't exist, or it
            is itself a nested ``$ref``.
    """
    if not ref.startswith("#/components/schemas/"):
        raise ValueError(
            f"Cannot resolve schema $ref '{ref}': "
            "only local '#/components/schemas/...' refs are supported."
        )
    schema_name = ref.rsplit("/", 1)[-1]
    logger.debug("resolving schema $ref", ref=ref, component=schema_name)
    if spec.components is None:
        raise ValueError(
            f"Cannot resolve schema $ref '{ref}': spec has no 'components' section."
        )
    schemas = spec.components.schemas or {}
    schema = schemas.get(schema_name)
    if schema is None:
        raise ValueError(
            f"Cannot resolve schema $ref '{ref}': "
            f"'{schema_name}' not found in components.schemas."
        )
    if isinstance(schema, Ref30 | Ref31):
        raise ValueError(
            f"Cannot resolve schema $ref '{ref}': "
            f"'{schema_name}' is itself a nested $ref, which is not supported."
        )
    logger.debug("resolved schema $ref", schema_name=schema_name)
    return schema


def extract_schema_type(param: OAParam30 | OAParam31) -> SchemaType:
    """Extract the schema type string from a parameter's schema.

    Raises:
        ValueError: If the parameter has no inline schema (None or $ref),
            or the schema type is missing, null-only, or unknown.
    """
    if param.param_schema is None or isinstance(param.param_schema, Ref30 | Ref31):
        schema_kind = (
            type(param.param_schema).__name__ if param.param_schema else "None"
        )
        raise ValueError(
            f"Parameter '{param.name}' has no inline schema "
            f"(schema_kind={schema_kind}). Cannot determine type."
        )
    return schema_to_type(param.param_schema)


def schema_to_type(schema: OpenAPISchema) -> SchemaType:
    """Extract the type string from an inline schema object.

    Raises:
        ValueError: If the schema has no type field, the type list contains
            only nulls, or the type is not in OPENAPI_TYPE_MAP.
    """
    raw_type = schema.type
    if raw_type is None:
        # No explicit type: default to "object" (dict). OpenAPI specs
        # commonly omit type on schemas that have properties, use
        # composition (allOf/oneOf/anyOf), or are intentionally free-form.
        return cast(SchemaType, "object")
    # v3.1 can return a list of types; take the first non-null one
    if isinstance(raw_type, list):
        for t in raw_type:
            if t.value != "null":
                raw_type = t
                break
        else:
            raise ValueError("Schema type list contains only null types.")
    type_str: str = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
    if type_str not in OPENAPI_TYPE_MAP:
        raise ValueError(
            f"Unknown OpenAPI schema type '{type_str}'. "
            f"Supported types: {sorted(OPENAPI_TYPE_MAP.keys())}"
        )
    # We've verified type_str is in OPENAPI_TYPE_MAP, which only contains valid
    # SchemaType values, so this cast is safe.
    return cast(SchemaType, type_str)
