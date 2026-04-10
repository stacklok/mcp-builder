"""Tests that all integration YAML fixtures pass schema validation."""

from __future__ import annotations

import pytest

from mcp_builder.schema.models import load_scope

from .conftest import ALL_SCOPE_YAMLS, INTEGRATION_FIXTURES


@pytest.mark.parametrize("fixture_name", ALL_SCOPE_YAMLS)
def test_fixture_passes_schema_validation(fixture_name: str) -> None:
    """Every integration fixture must parse and validate successfully."""
    scope = load_scope(INTEGRATION_FIXTURES / fixture_name)
    assert scope.server.name
    assert scope.auth.type in ("oauth_bearer", "api_key", "none")
    assert len(scope.groups) >= 1
    for group in scope.groups:
        assert len(group.tools) >= 1


@pytest.mark.parametrize(
    ("fixture_name", "expected_auth", "expected_groups", "expected_tools"),
    [
        ("google_drive.yaml", "oauth_bearer", 2, 5),
        ("github.yaml", "oauth_bearer", 3, 8),
        ("bamboohr.yaml", "oauth_bearer", 3, 8),
        ("jira.yaml", "oauth_bearer", 1, 7),
        ("slack.yaml", "oauth_bearer", 3, 7),
        ("weather_api.yaml", "api_key", 1, 1),
        ("minimal_api.yaml", "none", 1, 1),
    ],
)
def test_fixture_has_expected_structure(
    fixture_name: str,
    expected_auth: str,
    expected_groups: int,
    expected_tools: int,
) -> None:
    """Each fixture should have the expected auth type, group count, and tool count."""
    scope = load_scope(INTEGRATION_FIXTURES / fixture_name)
    assert scope.auth.type == expected_auth
    assert len(scope.groups) == expected_groups
    total_tools = sum(len(g.tools) for g in scope.groups)
    assert total_tools == expected_tools


def test_all_fixtures_have_unique_tool_names() -> None:
    """Within each fixture, all tool names must be unique (already enforced by model, but verify)."""
    for fixture_name in ALL_SCOPE_YAMLS:
        scope = load_scope(INTEGRATION_FIXTURES / fixture_name)
        tool_names = [t.tool_name for g in scope.groups for t in g.tools]
        assert len(tool_names) == len(set(tool_names)), (
            f"Duplicate tool names in {fixture_name}: {tool_names}"
        )


@pytest.mark.parametrize(
    ("fixture_name", "expected_issuer"),
    [
        ("google_drive.yaml", "https://accounts.google.com"),
        ("github.yaml", "https://github.com"),
        ("bamboohr.yaml", "https://{companyDomain}.bamboohr.com"),
        ("jira.yaml", "https://auth.atlassian.com"),
        ("slack.yaml", "https://slack.com"),
    ],
)
def test_oauth_fixtures_have_expected_issuer(
    fixture_name: str,
    expected_issuer: str,
) -> None:
    """OAuth fixtures must have the correct issuer URL."""
    scope = load_scope(INTEGRATION_FIXTURES / fixture_name)
    assert scope.auth.oauth is not None
    assert scope.auth.oauth.issuer == expected_issuer
