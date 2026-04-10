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
