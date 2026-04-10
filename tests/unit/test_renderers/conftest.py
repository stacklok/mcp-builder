"""Shared fixtures for renderer tests."""

from pathlib import Path

import pytest

from mcp_builder.codegen.plan import AuthPlan, ServerPlan

FIXTURES = Path(__file__).parent.parent / "fixtures"
TEMPLATE_DIR = FIXTURES / "template"


@pytest.fixture()
def plan() -> ServerPlan:
    """A minimal ServerPlan for renderer tests."""
    return ServerPlan(
        module_name="test_api_mcp",
        server_name="test-api",
        description="A test API server.",
        base_url="https://api.example.com",
        auth=AuthPlan(type="api_key"),
        tools=[],
        groups=[],
    )
