"""Shared fixtures for integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

INTEGRATION_FIXTURES = Path(__file__).parent / "fixtures"
OPENAPI_FIXTURES = INTEGRATION_FIXTURES / "openapi"
TEMPLATE_DIR = Path(__file__).parent.parent / "unit" / "fixtures" / "template"


@dataclass(frozen=True)
class FixtureConfig:
    """Configuration for a single integration test fixture pair."""

    scope_yaml: str
    openapi_yaml: str
    server_name: str
    module_name: str
    tool_count: int
    group_count: int
    auth_type: str


ALL_FIXTURES = [
    FixtureConfig(
        "google_drive.yaml",
        "google_drive_openapi.yaml",
        "google-drive",
        "google_drive_mcp",
        5,
        2,
        "oauth_bearer",
    ),
    FixtureConfig(
        "github.yaml",
        "github_openapi.yaml",
        "github",
        "github_mcp",
        8,
        3,
        "oauth_bearer",
    ),
    FixtureConfig(
        "bamboohr.yaml",
        "bamboohr_openapi.yaml",
        "bamboohr",
        "bamboohr_mcp",
        8,
        3,
        "oauth_bearer",
    ),
    FixtureConfig(
        "jira.yaml",
        "jira_openapi.yaml",
        "jira-cloud",
        "jira_cloud_mcp",
        7,
        1,
        "oauth_bearer",
    ),
    FixtureConfig(
        "slack.yaml", "slack_openapi.yaml", "slack", "slack_mcp", 7, 3, "oauth_bearer"
    ),
    FixtureConfig(
        "weather_api.yaml",
        "weather_api_openapi.yaml",
        "weather-api",
        "weather_api_mcp",
        1,
        1,
        "api_key",
    ),
    FixtureConfig(
        "minimal_api.yaml",
        "minimal_api_openapi.yaml",
        "minimal-api",
        "minimal_api_mcp",
        1,
        1,
        "none",
    ),
]

ALL_SCOPE_YAMLS = [
    "bamboohr.yaml",
    "github.yaml",
    "google_drive.yaml",
    "jira.yaml",
    "slack.yaml",
    "weather_api.yaml",
    "minimal_api.yaml",
]


@pytest.fixture
def integration_fixtures_dir() -> Path:
    return INTEGRATION_FIXTURES


@pytest.fixture
def template_dir() -> Path:
    return TEMPLATE_DIR


def spec_available(config: FixtureConfig) -> bool:
    """Check if the OpenAPI spec for a fixture exists (may need downloading)."""
    return (OPENAPI_FIXTURES / config.openapi_yaml).exists()


def run_generator(config: FixtureConfig, output_dir: Path) -> Path:
    """Run the full generation pipeline for a fixture config.

    Returns the generated project directory path.
    """
    from mcp_builder.cli import run_pipeline

    return run_pipeline(
        scope_yaml=INTEGRATION_FIXTURES / config.scope_yaml,
        openapi_spec=OPENAPI_FIXTURES / config.openapi_yaml,
        template_dir=TEMPLATE_DIR,
        output_dir=output_dir,
    )
