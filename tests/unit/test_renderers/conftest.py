"""Shared fixtures for renderer tests."""

from pathlib import Path

import pytest

from mcp_builder.generate.plan import AuthPlan, ServerPlan, ToolPlan

FIXTURES = Path(__file__).parent.parent / "fixtures"
TEMPLATE_DIR = FIXTURES / "template"


def make_plan(
    tools: list[ToolPlan] | None = None,
    auth: AuthPlan | None = None,
) -> ServerPlan:
    """Build a minimal ServerPlan for renderer tests.

    Shared across all renderer test modules to avoid duplicating the
    same factory helper.
    """
    return ServerPlan(
        module_name="test_api_mcp",
        server_name="test-api",
        description="A test API server.",
        base_url="https://api.example.com",
        auth=auth or AuthPlan(type="api_key"),
        tools=tools or [],
        groups=[],
    )


@pytest.fixture()
def plan() -> ServerPlan:
    """A minimal ServerPlan with api_key auth for renderer tests."""
    return make_plan()
