"""OpenAPI spec loading and querying with typed returns."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel


class OpenAPIParameter(BaseModel):
    """A typed representation of an OpenAPI parameter."""

    name: str
    location: str  # "path", "query", "header", "cookie"
    required: bool = False
    schema_type: str = "string"
    description: str = ""


class OperationInfo(BaseModel):
    """Key fields extracted from an OpenAPI operation object.

    Note: Only captures $ref-based schemas. Inline schemas are not extracted.
    For issue #10, a helper to resolve $ref to class name may be needed.
    """

    operation_id: str | None = None
    request_body_ref: str | None = None
    response_ref: str | None = None


def load_openapi_spec(path: str | Path) -> dict:
    """Load an OpenAPI spec from a JSON or YAML file."""
    path = Path(path)
    with path.open() as f:
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def parse_endpoint(endpoint: str) -> tuple[str, str]:
    """Parse 'GET /items/{itemId}' into ('GET', '/items/{itemId}')."""
    method, path = endpoint.split(" ", 1)
    return method, path


def find_operation(spec: dict, method: str, path: str) -> OperationInfo:
    """Find an operation and return typed info.

    Raises:
        KeyError: If the path or method is not found.
    """
    path_item = spec.get("paths", {}).get(path)
    if path_item is None:
        raise KeyError(f"Path '{path}' not found in spec")
    operation = path_item.get(method.lower())
    if operation is None:
        raise KeyError(f"Method '{method}' not found for path '{path}'")

    # Extract request body schema $ref if present
    request_body_ref = None
    req_body = operation.get("requestBody", {})
    content = req_body.get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    if "$ref" in schema:
        request_body_ref = schema["$ref"]

    # Extract response schema $ref (from first 2xx response)
    response_ref = None
    for code, resp in operation.get("responses", {}).items():
        if code.startswith("2"):
            resp_content = resp.get("content", {}).get("application/json", {})
            resp_schema = resp_content.get("schema", {})
            if "$ref" in resp_schema:
                response_ref = resp_schema["$ref"]
            break

    return OperationInfo(
        operation_id=operation.get("operationId"),
        request_body_ref=request_body_ref,
        response_ref=response_ref,
    )


def ref_to_class_name(ref: str) -> str:
    """Extract class name from an OpenAPI $ref string.

    Example: '#/components/schemas/CreateItemRequest' -> 'CreateItemRequest'
    """
    return ref.rsplit("/", 1)[-1]


def get_body_fields(spec: dict, method: str, path: str) -> list[OpenAPIParameter]:
    """Get request body schema fields as flat parameters.

    Resolves the $ref in the request body to extract top-level fields
    from the referenced schema. Returns empty list if no request body.
    """
    op = find_operation(spec, method, path)
    if not op.request_body_ref:
        return []

    schema_name = ref_to_class_name(op.request_body_ref)
    schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})
    required_fields = set(schema.get("required", []))

    return [
        OpenAPIParameter(
            name=name,
            location="body",
            required=name in required_fields,
            schema_type=prop.get("type", "string"),
            description=prop.get("description", ""),
        )
        for name, prop in schema.get("properties", {}).items()
    ]


def get_parameters(spec: dict, method: str, path: str) -> list[OpenAPIParameter]:
    """Get all parameters for an operation (path-level + operation-level).

    Operation-level parameters override path-level parameters with the
    same name and location.
    """
    path_item = spec.get("paths", {}).get(path, {})
    path_params = path_item.get("parameters", [])
    operation = path_item.get(method.lower(), {})
    op_params = operation.get("parameters", [])

    # Merge: operation params override path params with same (name, in)
    merged: dict[tuple[str, str], dict] = {}
    for p in path_params:
        merged[(p["name"], p["in"])] = p
    for p in op_params:
        merged[(p["name"], p["in"])] = p

    return [
        OpenAPIParameter(
            name=p["name"],
            location=p["in"],
            required=p.get("required", False),
            schema_type=p.get("schema", {}).get("type", "string"),
            description=p.get("description", ""),
        )
        for p in merged.values()
    ]
