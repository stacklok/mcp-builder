"""OpenAPI spec loading and parameter extraction.

Pipeline stage: loading (files → typed data).
This is the first step in the codegen pipeline. It loads an OpenAPI spec
file into a fully typed model (via openapi-pydantic) and provides helper
functions to extract parameters and request body fields from operations.

Downstream consumers (codegen.plan) call these helpers to build a
ServerPlan. Renderers never call this module directly.

OpenAPI terminology used in this module:
    - Operation: a single HTTP method on a path (e.g., GET /items/{id}).
      Each operation can have parameters and a request body.
    - Parameter: a named value passed via URL path, query string, header,
      or cookie (e.g., ``itemId`` in /items/{itemId}, ``fields`` in ?fields=name).
    - Body field: a property of the JSON request body schema
      (e.g., ``name`` in {"name": "foo"}). Body fields are separate from
      parameters in OpenAPI — they live under ``requestBody``, not ``parameters``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import structlog
import yaml
from openapi_pydantic import parse_obj
from openapi_pydantic.v3.v3_0 import OpenAPI as OpenAPI30
from openapi_pydantic.v3.v3_0 import Operation as Op30
from openapi_pydantic.v3.v3_0 import Parameter as OAParam30
from openapi_pydantic.v3.v3_0 import PathItem as PathItem30
from openapi_pydantic.v3.v3_0 import Reference as Ref30
from openapi_pydantic.v3.v3_0 import RequestBody as ReqBody30
from openapi_pydantic.v3.v3_0 import Schema as Schema30
from openapi_pydantic.v3.v3_1 import OpenAPI as OpenAPI31
from openapi_pydantic.v3.v3_1 import Operation as Op31
from openapi_pydantic.v3.v3_1 import Parameter as OAParam31
from openapi_pydantic.v3.v3_1 import PathItem as PathItem31
from openapi_pydantic.v3.v3_1 import Reference as Ref31
from openapi_pydantic.v3.v3_1 import RequestBody as ReqBody31
from openapi_pydantic.v3.v3_1 import Schema as Schema31
from pydantic import BaseModel

logger = structlog.get_logger()

# Union of both OpenAPI versions. The field interfaces are identical
# (same names, same types) so downstream code can treat them uniformly.
OpenAPISpec = OpenAPI30 | OpenAPI31
OpenAPISchema = Schema30 | Schema31

# OpenAPI types that map to Python built-in types. We intentionally error
# on unknown types rather than silently defaulting to str — this catches
# spec issues early rather than producing subtly wrong generated code.
# The set of parameter locations, schema types, and Python types we support,
# expressed as Literal types for static type safety.
ParameterLocation = Literal["path", "query", "header", "cookie"]
PythonType = Literal["str", "int", "float", "bool", "list", "dict"]

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

    Pipeline stage: loading (intermediate data from spec_parser).
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

    Pipeline stage: loading (intermediate data from spec_parser).
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


def load_openapi_spec(path: str | Path) -> OpenAPISpec:
    """Load an OpenAPI spec from a JSON or YAML file into a typed model.

    Pipeline stage: loading (file → typed OpenAPI model).
    Called by: codegen.plan.build_server_plan() or cli.run_pipeline().

    Supports OpenAPI 3.0.x and 3.1.x specs. The version is auto-detected
    from the ``openapi`` field in the document.

    Args:
        path: Path to the OpenAPI spec file (.json, .yaml, or .yml).

    Returns:
        Typed OpenAPI model (OpenAPI30 or OpenAPI31).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the spec cannot be parsed into a valid OpenAPI model.
    """
    path = Path(path)
    logger.info("loading openapi spec", path=str(path))
    with path.open() as f:
        if path.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(f)
        else:
            raw = json.load(f)
    logger.debug("detected spec format", suffix=path.suffix)

    # Swagger 2.0 specs use "swagger" instead of "openapi". The
    # openapi-pydantic library only supports 3.x, so fail early with a
    # message that tells the caller how to convert.
    if "swagger" in raw and not raw.get("openapi"):
        is_yaml = path.suffix in (".yaml", ".yml")
        output = path.with_suffix(".openapi3.yaml" if is_yaml else ".openapi3.json")
        yaml_flag = " --yaml" if is_yaml else ""
        raise ValueError(
            f"'{path}' is a Swagger {raw['swagger']} spec. "
            "Only OpenAPI 3.0+ is supported. Convert with: "
            f"npm install -g swagger2openapi && "
            f"swagger2openapi {path} -o {output}{yaml_flag}"
        )

    spec = parse_obj(raw)
    if spec is None:
        raise ValueError(f"Failed to parse OpenAPI spec from '{path}'")

    path_count = len(spec.paths) if spec.paths else 0
    logger.info(
        "openapi spec loaded",
        openapi_version=raw.get("openapi", "unknown"),
        title=spec.info.title,
        spec_version=spec.info.version,
        path_count=path_count,
    )
    return spec


def parse_endpoint(endpoint: str) -> tuple[str, str]:
    """Parse an endpoint string into its HTTP method and path.

    Pipeline stage: loading (string parsing utility).
    Used by: codegen.plan.build_server_plan() when iterating over tools.

    Example:
        >>> parse_endpoint("GET /items/{itemId}")
        ("GET", "/items/{itemId}")

    Args:
        endpoint: Endpoint string in "METHOD /path" format.

    Returns:
        Tuple of (method, path).

    Raises:
        ValueError: If the endpoint string is not in the expected format.
    """
    parts = endpoint.split(" ", 1)
    if len(parts) != 2:
        raise ValueError(f"Endpoint '{endpoint}' must be in 'METHOD /path' format")
    return parts[0], parts[1]


def _get_operation(
    spec: OpenAPISpec, method: str, path: str
) -> tuple[PathItem30 | PathItem31, Op30 | Op31]:
    """Look up a path item and operation from the spec.

    Shared by get_parameters() and get_body_fields() to avoid
    duplicating the path/method lookup and error handling.

    Example:
        path_item, operation = _get_operation(spec, "GET", "/items/{itemId}")
        # path_item contains all methods for /items/{itemId}
        # operation is the GET operation object

    Raises:
        KeyError: If the path or method is not found in the spec.
    """
    path_item = (spec.paths or {}).get(path)
    if path_item is None:
        raise KeyError(f"Path '{path}' not found in spec")
    operation = getattr(path_item, method.lower(), None)
    if operation is None:
        raise KeyError(f"Method '{method}' not found for path '{path}'")
    logger.debug(
        "resolved operation",
        method=method,
        path=path,
        operation_id=getattr(operation, "operationId", None),
    )
    return path_item, operation


def get_parameters(
    spec: OpenAPISpec, method: str, path: str
) -> list[ExtractedParameter]:
    """Extract all path/query parameters for an operation.

    Pipeline stage: loading (spec → typed parameter list).
    Called by: codegen.plan.build_server_plan().

    Merges path-level and operation-level parameters. When both define a
    parameter with the same (name, location), the operation-level one wins.

    Example:
        Given GET /items/{itemId} with path param "itemId" and query param "fields":
        >>> get_parameters(spec, "GET", "/items/{itemId}")
        [ExtractedParameter(name="itemId", ...), ExtractedParameter(name="fields", ...)]

    Args:
        spec: Typed OpenAPI spec.
        method: HTTP method (e.g., "GET").
        path: URL path (e.g., "/items/{itemId}").

    Returns:
        List of extracted parameters. Empty if the operation has none.

    Raises:
        KeyError: If the path or method is not found in the spec.
    """
    path_item, operation = _get_operation(spec, method, path)

    # Merge path-level and operation-level params. Operation wins on conflict.
    merged: dict[tuple[str, str], OAParam30 | OAParam31] = {}

    for param in path_item.parameters or []:
        if isinstance(param, Ref30 | Ref31):
            param = _resolve_parameter_ref(spec, param.ref)
        merged[(param.name, param.param_in.value)] = param

    for param in operation.parameters or []:
        if isinstance(param, Ref30 | Ref31):
            param = _resolve_parameter_ref(spec, param.ref)
        merged[(param.name, param.param_in.value)] = param

    path_level_count = len(path_item.parameters or [])
    op_level_count = len(operation.parameters or [])
    logger.debug(
        "merged parameters",
        method=method,
        path=path,
        path_level=path_level_count,
        operation_level=op_level_count,
        unique=len(merged),
    )

    result = []
    for param in merged.values():
        schema_type = _extract_schema_type(param)
        result.append(
            ExtractedParameter(
                name=param.name,
                location=param.param_in.value,
                required=param.required,
                schema_type=schema_type,
                description=param.description or "",
            )
        )
        logger.debug(
            "extracted parameter",
            name=param.name,
            location=param.param_in.value,
            schema_type=schema_type,
            required=param.required,
        )

    if not result:
        logger.debug("no parameters found", method=method, path=path)
    else:
        logger.debug(
            "parameter extraction complete",
            method=method,
            path=path,
            count=len(result),
        )
    return result


def get_body_fields(
    spec: OpenAPISpec, method: str, path: str
) -> list[ExtractedBodyField]:
    """Extract request body fields for an operation.

    Pipeline stage: loading (spec → typed body field list).
    Called by: codegen.plan.build_server_plan().

    Looks for an application/json request body with either inline properties
    or a $ref to a component schema. Resolves the $ref and extracts fields.

    Example:
        Given POST /items with a CreateItemRequest body containing "name" (required)
        and "description" (optional):
        >>> get_body_fields(spec, "POST", "/items")
        [ExtractedBodyField(name="name", ..., required=True),
         ExtractedBodyField(name="description", ..., required=False)]

    Args:
        spec: Typed OpenAPI spec.
        method: HTTP method (e.g., "POST").
        path: URL path (e.g., "/items").

    Returns:
        List of extracted body fields. Empty if the operation has no JSON body.

    Raises:
        KeyError: If the path or method is not found in the spec.
    """
    _, operation = _get_operation(spec, method, path)

    if operation.requestBody is None:
        logger.debug("no request body", method=method, path=path)
        return []

    req_body = operation.requestBody
    if isinstance(req_body, Ref30 | Ref31):
        req_body = _resolve_request_body_ref(spec, req_body.ref)

    json_media = (req_body.content or {}).get("application/json")
    if json_media is None:
        logger.debug("no application/json media type", method=method, path=path)
        return []

    schema = json_media.media_type_schema
    if schema is None:
        logger.debug("no schema in json media type", method=method, path=path)
        return []

    # Resolve $ref to component schema
    if isinstance(schema, Ref30 | Ref31):
        ref_str = schema.ref
        logger.debug(
            "resolving body schema $ref", ref=ref_str, method=method, path=path
        )
        resolved = _resolve_schema_ref(spec, ref_str)
        if resolved is None:
            logger.warning(
                "failed to resolve body schema $ref",
                ref=ref_str,
                method=method,
                path=path,
            )
            return []
        schema = resolved

    required_names = set(schema.required or [])
    fields = []
    # NOTE: allOf/oneOf/anyOf schema composition is not yet supported.
    # Real-world specs use these for inheritance and union types.
    # See https://github.com/StacklokLabs/mcp-builder/issues/19
    for composed_key in ("allOf", "oneOf", "anyOf"):
        if getattr(schema, composed_key, None):
            raise NotImplementedError(
                f"Schema composition '{composed_key}' in {method} {path} body "
                "is not yet supported. "
                "See https://github.com/StacklokLabs/mcp-builder/issues/19"
            )

    if not (schema.properties or {}):
        logger.warning("body schema has no properties", method=method, path=path)

    for name, prop in (schema.properties or {}).items():
        # NOTE: $ref on individual body properties is not yet resolved.
        # See https://github.com/StacklokLabs/mcp-builder/issues/19
        if isinstance(prop, Ref30 | Ref31):
            raise NotImplementedError(
                f"$ref property '{prop.ref}' in {method} {path} body "
                "is not yet supported. "
                "See https://github.com/StacklokLabs/mcp-builder/issues/19"
            )
        prop_type = _schema_to_type(prop)
        fields.append(
            ExtractedBodyField(
                name=name,
                schema_type=prop_type,
                description=prop.description or "",
                required=name in required_names,
            )
        )
        logger.debug(
            "extracted body field",
            name=name,
            schema_type=prop_type,
            required=name in required_names,
        )

    logger.debug(
        "body field extraction complete",
        method=method,
        path=path,
        field_count=len(fields),
        required_fields=sorted(required_names),
    )
    return fields


def _extract_schema_type(param: OAParam30 | OAParam31) -> SchemaType:
    """Extract the schema type string from a parameter's schema.

    Raises ValueError for unknown types rather than silently defaulting.
    """
    if param.param_schema is None or isinstance(param.param_schema, Ref30 | Ref31):
        schema_kind = (
            type(param.param_schema).__name__ if param.param_schema else "None"
        )
        logger.debug(
            "no inline schema for parameter, defaulting to string",
            param_name=param.name,
            schema_kind=schema_kind,
        )
        return "string"
    return _schema_to_type(param.param_schema)


def _schema_to_type(schema: OpenAPISchema) -> SchemaType:
    """Extract the type string from an inline schema object."""
    raw_type = schema.type
    if raw_type is None:
        logger.debug("schema has no type field, defaulting to string")
        return "string"
    # v3.1 can return a list of types; take the first non-null one
    if isinstance(raw_type, list):
        for t in raw_type:
            if t.value != "null":
                raw_type = t
                break
        else:
            logger.warning(
                "schema type list contains only null types, defaulting to string"
            )
            return "string"
    type_str: str = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
    if type_str not in OPENAPI_TYPE_MAP:
        raise ValueError(
            f"Unknown OpenAPI schema type '{type_str}'. "
            f"Supported types: {sorted(OPENAPI_TYPE_MAP.keys())}"
        )
    # We've verified type_str is in OPENAPI_TYPE_MAP, which only contains valid
    # SchemaType values, so this cast is safe.
    return cast(SchemaType, type_str)


def _resolve_parameter_ref(spec: OpenAPISpec, ref: str) -> OAParam30 | OAParam31:
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


def _resolve_request_body_ref(spec: OpenAPISpec, ref: str) -> ReqBody30 | ReqBody31:
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


def _resolve_schema_ref(spec: OpenAPISpec, ref: str) -> OpenAPISchema | None:
    """Resolve a $ref string like '#/components/schemas/Foo' to the schema object."""
    if not ref.startswith("#/components/schemas/"):
        logger.warning("cannot resolve non-component $ref", ref=ref)
        return None
    schema_name = ref.rsplit("/", 1)[-1]
    logger.debug("resolving schema $ref", ref=ref, component=schema_name)
    if spec.components is None:
        logger.warning("spec has no components section, cannot resolve $ref", ref=ref)
        return None
    schemas = spec.components.schemas or {}
    schema = schemas.get(schema_name)
    if schema is None or isinstance(schema, Ref30 | Ref31):
        logger.warning(
            "schema not found in components (or is a nested $ref)",
            schema_name=schema_name,
        )
        return None  # nested $ref not supported
    logger.debug("resolved schema $ref", schema_name=schema_name)
    return schema
