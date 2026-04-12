"""Shared fixtures for unit tests."""

from pathlib import Path

import pytest

from mcp_builder.spec import load_openapi_spec
from mcp_builder.schema.models import load_scope

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def spec():
    """Load the test OpenAPI spec fixture."""
    return load_openapi_spec(FIXTURES / "test_openapi.yaml")


@pytest.fixture()
def scope():
    """Load the test scope fixture."""
    return load_scope(FIXTURES / "test_scope.yaml")
