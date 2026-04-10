"""Shared fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mcp_builder.schema.models import MCPScope

if TYPE_CHECKING:
    pass

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def openapi_spec_path() -> Path:
    return FIXTURES / "test_openapi.yaml"


@pytest.fixture
def openapi_spec(openapi_spec_path: Path) -> dict:
    from mcp_builder.codegen.spec_parser import load_openapi_spec

    return load_openapi_spec(openapi_spec_path)


@pytest.fixture
def template_dir() -> Path:
    return FIXTURES / "template"


@pytest.fixture
def minimal_scope() -> MCPScope:
    """A minimal valid MCPScope for tests that don't care about specific tools."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {"name": "test-api", "description": "Test API MCP server"},
            "spec": {
                "source": "test_openapi.yaml",
                "format": "openapi3",
                "base_url": "https://api.example.com",
            },
            "groups": [
                {
                    "name": "default",
                    "description": "Default group",
                    "tools": [
                        {
                            "tool_name": "get_status",
                            "endpoint": "GET /status",
                            "description": "Get status.",
                        }
                    ],
                }
            ],
            "auth": {"type": "none"},
        }
    )


@pytest.fixture
def scope_with_tools() -> MCPScope:
    """An MCPScope with tools matching the test OpenAPI spec fixture."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {"name": "test-api", "description": "Test API"},
            "spec": {
                "source": "test_openapi.yaml",
                "format": "openapi3",
                "base_url": "https://api.example.com",
            },
            "groups": [
                {
                    "name": "items",
                    "description": "Item operations",
                    "tools": [
                        {
                            "tool_name": "get_item",
                            "endpoint": "GET /items/{itemId}",
                            "description": "Get an item by ID.",
                            "parameters": [
                                {
                                    "name": "itemId",
                                    "description": "The unique identifier of the item to retrieve.",
                                    "required": True,
                                },
                                {
                                    "name": "fields",
                                    "description": "Comma-separated list of fields to return.",
                                    "required": False,
                                },
                            ],
                        },
                        {
                            "tool_name": "create_item",
                            "endpoint": "POST /items",
                            "description": "Create a new item.",
                        },
                    ],
                }
            ],
            "auth": {"type": "none"},
        }
    )


@pytest.fixture
def scope_with_update() -> MCPScope:
    """MCPScope with GET (params), POST (body), and PUT (params+body) tools."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {"name": "test-api", "description": "Test API"},
            "spec": {
                "source": "test_openapi.yaml",
                "format": "openapi3",
                "base_url": "https://api.example.com",
            },
            "groups": [
                {
                    "name": "items",
                    "description": "Item operations",
                    "tools": [
                        {
                            "tool_name": "get_item",
                            "endpoint": "GET /items/{itemId}",
                            "description": "Get an item by ID.",
                            "parameters": [
                                {
                                    "name": "itemId",
                                    "description": "The unique identifier of the item.",
                                    "required": True,
                                },
                                {
                                    "name": "fields",
                                    "description": "Comma-separated list of fields.",
                                    "required": False,
                                },
                            ],
                        },
                        {
                            "tool_name": "create_item",
                            "endpoint": "POST /items",
                            "description": "Create a new item.",
                        },
                        {
                            "tool_name": "update_item",
                            "endpoint": "PUT /items/{itemId}",
                            "description": "Update an existing item.",
                            "parameters": [
                                {
                                    "name": "itemId",
                                    "description": "The ID of the item to update.",
                                    "required": True,
                                },
                            ],
                        },
                    ],
                }
            ],
            "auth": {"type": "none"},
        }
    )


@pytest.fixture
def scope_multi_group() -> MCPScope:
    """MCPScope with two groups for testing group organization."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {"name": "test-api", "description": "Test API"},
            "spec": {
                "source": "test_openapi.yaml",
                "format": "openapi3",
                "base_url": "https://api.example.com",
            },
            "groups": [
                {
                    "name": "items",
                    "description": "Item operations",
                    "tools": [
                        {
                            "tool_name": "get_item",
                            "endpoint": "GET /items/{itemId}",
                            "description": "Get an item by ID.",
                            "parameters": [
                                {
                                    "name": "itemId",
                                    "description": "The unique identifier of the item.",
                                    "required": True,
                                },
                                {
                                    "name": "fields",
                                    "description": "Comma-separated list of fields.",
                                    "required": False,
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "mutations",
                    "description": "Write operations",
                    "tools": [
                        {
                            "tool_name": "create_item",
                            "endpoint": "POST /items",
                            "description": "Create a new item.",
                        },
                    ],
                },
            ],
            "auth": {"type": "none"},
        }
    )


@pytest.fixture
def scope_oauth() -> MCPScope:
    """MCPScope with oauth_bearer auth for manifest testing."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {
                "name": "google-drive",
                "description": "Google Drive MCP server",
            },
            "spec": {
                "source": "drive.yaml",
                "format": "openapi3",
                "base_url": "https://www.googleapis.com",
            },
            "groups": [
                {
                    "name": "files",
                    "description": "File operations",
                    "tools": [
                        {
                            "tool_name": "list_files",
                            "endpoint": "GET /drive/v3/files",
                            "description": "List files.",
                        }
                    ],
                }
            ],
            "auth": {
                "type": "oauth_bearer",
                "oauth": {
                    "issuer": "https://accounts.google.com",
                    "scopes": [
                        "openid",
                        "https://www.googleapis.com/auth/drive.readonly",
                    ],
                },
            },
        }
    )


@pytest.fixture
def scope_api_key() -> MCPScope:
    """MCPScope with api_key auth for manifest testing."""
    return MCPScope.model_validate(
        {
            "version": "1",
            "server": {"name": "weather-api", "description": "Weather API MCP server"},
            "spec": {
                "source": "weather.yaml",
                "format": "openapi3",
                "base_url": "https://api.weather.com",
            },
            "groups": [
                {
                    "name": "weather",
                    "description": "Weather data",
                    "tools": [
                        {
                            "tool_name": "get_forecast",
                            "endpoint": "GET /forecast",
                            "description": "Get weather forecast.",
                        }
                    ],
                }
            ],
            "auth": {"type": "api_key"},
        }
    )
