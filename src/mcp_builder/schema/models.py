"""Pydantic v2 models for mcp-scope.yaml validation."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = structlog.get_logger()


class ParamLocation(StrEnum):
    """Where a parameter belongs in the HTTP request."""

    PATH = "path"
    QUERY = "query"
    BODY = "body"


class Parameter(BaseModel):
    """A parameter entry for a tool in mcp-scope.yaml.

    When a tool defines a ``parameters`` list, those entries act as an
    **allowlist**: only the listed parameters are included in the generated
    MCP tool. The ``description`` and ``required`` fields override the
    corresponding values from the OpenAPI spec.

    The ``location`` field tells codegen where this parameter belongs:
    - ``path``: URL template slot (e.g., ``/items/{itemId}``)
    - ``query``: URL query parameter (e.g., ``?fields=name``)
    - ``body``: JSON request body property (e.g., ``{"color": "red"}``)
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    required: bool
    location: ParamLocation


class OAuthConfig(BaseModel):
    """OAuth configuration for oauth_bearer auth type."""

    model_config = ConfigDict(extra="forbid")

    issuer: str
    scopes: list[str]


class SpecConfig(BaseModel):
    """OpenAPI spec metadata."""

    model_config = ConfigDict(extra="forbid")

    source: str
    format: Literal["openapi3", "openapi3.1"]
    base_url: str
    total_endpoints: int | None = None
    scoped_endpoints: int | None = None


class ServerConfig(BaseModel):
    """Server identity metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str

    @field_validator("name")
    @classmethod
    def validate_dns_label(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", v) or len(v) > 63:
            raise ValueError(
                f"Server name '{v}' is not a valid DNS label. "
                "Must contain only lowercase letters, digits, and hyphens, "
                "must start and end with a letter or digit, and be at most 63 characters."
            )
        return v


class Tool(BaseModel):
    """A single tool definition within a group."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    endpoint: str
    description: str
    parameters: list[Parameter] = Field(default_factory=list)
    hints: list[str] | None = None

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        if len(v) > 40:
            raise ValueError(f"Tool name '{v}' exceeds 40 characters ({len(v)} chars)")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(
                f"Tool name '{v}' must be snake_case: lowercase letters, digits, "
                "and underscores only, starting with a letter."
            )
        return v

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE) /\S+", v):
            raise ValueError(
                f"Endpoint '{v}' must match 'METHOD /path' where METHOD is "
                "one of GET, POST, PUT, PATCH, DELETE."
            )
        return v

    @model_validator(mode="after")
    def validate_path_params_declared(self) -> Self:
        """Every {placeholder} in the endpoint path must have a parameter with location=path."""
        _, path = self.endpoint.split(" ", 1)
        placeholders = set(re.findall(r"\{(\w+)\}", path))
        if not placeholders:
            return self
        declared = {p.name for p in self.parameters if p.location == ParamLocation.PATH}
        missing = placeholders - declared
        if missing:
            raise ValueError(
                f"Endpoint '{self.endpoint}' has path parameters {missing} "
                f"that are not declared in parameters with location='path'."
            )
        return self


class Group(BaseModel):
    """A semantic grouping of related tools."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    tools: list[Tool] = Field(min_length=1)


class AuthConfig(BaseModel):
    """Authentication configuration."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth_bearer", "api_key", "none"]
    oauth: OAuthConfig | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_oauth_required(self) -> Self:
        if self.type == "oauth_bearer" and self.oauth is None:
            raise ValueError("'oauth' is required when auth type is 'oauth_bearer'")
        return self


class MCPScope(BaseModel):
    """Root model for mcp-scope.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"]
    server: ServerConfig
    spec: SpecConfig
    workflows: list[str] | None = None
    groups: list[Group] = Field(min_length=1)
    auth: AuthConfig

    @model_validator(mode="after")
    def validate_unique_tool_names(self) -> Self:
        seen: dict[str, str] = {}
        for group in self.groups:
            for tool in group.tools:
                if tool.tool_name in seen:
                    raise ValueError(
                        f"Duplicate tool_name '{tool.tool_name}' found in groups "
                        f"'{seen[tool.tool_name]}' and '{group.name}'"
                    )
                seen[tool.tool_name] = group.name
        return self


def load_scope(path: str | Path) -> MCPScope:
    """Load and validate an mcp-scope.yaml file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated MCPScope instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        pydantic.ValidationError: If the YAML content fails schema validation.
    """
    path = Path(path)
    logger.info("loading scope", path=str(path))
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise ValueError(f"File '{path}' is empty or contains only comments")
    scope = MCPScope.model_validate(raw)
    tool_count = sum(len(g.tools) for g in scope.groups)
    logger.info(
        "scope loaded",
        server_name=scope.server.name,
        group_count=len(scope.groups),
        tool_count=tool_count,
        auth_type=scope.auth.type,
    )
    return scope
