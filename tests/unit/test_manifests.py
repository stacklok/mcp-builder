"""Tests for ToolHive deployment manifest generation."""

from __future__ import annotations

import yaml

from mcp_builder.codegen.manifests import (
    generate_auth_config,
    generate_mcpserver,
    generate_secret,
)
from mcp_builder.schema.models import MCPScope


# ---------------------------------------------------------------------------
# MCPServer tests
# ---------------------------------------------------------------------------


def test_mcpserver_valid_yaml(scope_oauth: MCPScope) -> None:
    result = generate_mcpserver(scope_oauth)
    parsed = yaml.safe_load(result)
    assert parsed is not None


def test_mcpserver_has_correct_image(scope_oauth: MCPScope) -> None:
    result = generate_mcpserver(scope_oauth)
    parsed = yaml.safe_load(result)
    assert parsed["spec"]["image"] == "google-drive-mcp:latest"


def test_mcpserver_has_server_name(scope_oauth: MCPScope) -> None:
    result = generate_mcpserver(scope_oauth)
    parsed = yaml.safe_load(result)
    assert parsed["metadata"]["name"] == "google-drive"


def test_mcpserver_refs_auth_config_when_auth(scope_oauth: MCPScope) -> None:
    result = generate_mcpserver(scope_oauth)
    parsed = yaml.safe_load(result)
    assert parsed["spec"]["externalAuthConfig"]["name"] == "google-drive-auth"


def test_mcpserver_no_auth_ref_when_none(minimal_scope: MCPScope) -> None:
    result = generate_mcpserver(minimal_scope)
    parsed = yaml.safe_load(result)
    assert "externalAuthConfig" not in parsed["spec"]


def test_mcpserver_deterministic(scope_oauth: MCPScope) -> None:
    assert generate_mcpserver(scope_oauth) == generate_mcpserver(scope_oauth)


# ---------------------------------------------------------------------------
# AuthConfig tests
# ---------------------------------------------------------------------------


def test_auth_config_oauth_produces_yaml(scope_oauth: MCPScope) -> None:
    result = generate_auth_config(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    assert parsed is not None


def test_auth_config_oauth_type(scope_oauth: MCPScope) -> None:
    result = generate_auth_config(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    assert parsed["spec"]["type"] == "embeddedAuthServer"


def test_auth_config_oauth_issuer(scope_oauth: MCPScope) -> None:
    result = generate_auth_config(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    assert (
        parsed["spec"]["embeddedAuthServer"]["issuer"] == "https://accounts.google.com"
    )


def test_auth_config_oauth_scopes(scope_oauth: MCPScope) -> None:
    result = generate_auth_config(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    scopes = parsed["spec"]["embeddedAuthServer"]["scopes"]
    assert "openid" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes


def test_auth_config_api_key_type(scope_api_key: MCPScope) -> None:
    result = generate_auth_config(scope_api_key)
    assert result is not None
    parsed = yaml.safe_load(result)
    assert parsed["spec"]["type"] == "bearerToken"


def test_auth_config_api_key_secret_ref(scope_api_key: MCPScope) -> None:
    result = generate_auth_config(scope_api_key)
    assert result is not None
    parsed = yaml.safe_load(result)
    bearer = parsed["spec"]["bearerToken"]
    assert bearer["secretRef"]["name"] == "weather-api-secret"
    assert bearer["key"] == "api-key"


def test_auth_config_none_returns_none(minimal_scope: MCPScope) -> None:
    assert generate_auth_config(minimal_scope) is None


def test_auth_config_deterministic(scope_oauth: MCPScope) -> None:
    assert generate_auth_config(scope_oauth) == generate_auth_config(scope_oauth)


# ---------------------------------------------------------------------------
# Secret tests
# ---------------------------------------------------------------------------


def test_secret_oauth_has_placeholders(scope_oauth: MCPScope) -> None:
    result = generate_secret(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    string_data = parsed["stringData"]
    assert string_data["client-id"] == "REPLACE_ME"
    assert string_data["client-secret"] == "REPLACE_ME"


def test_secret_api_key_has_placeholder(scope_api_key: MCPScope) -> None:
    result = generate_secret(scope_api_key)
    assert result is not None
    parsed = yaml.safe_load(result)
    assert parsed["stringData"]["api-key"] == "REPLACE_ME"


def test_secret_none_returns_none(minimal_scope: MCPScope) -> None:
    assert generate_secret(minimal_scope) is None


def test_secret_never_has_real_creds(scope_oauth: MCPScope) -> None:
    result = generate_secret(scope_oauth)
    assert result is not None
    parsed = yaml.safe_load(result)
    for value in parsed["stringData"].values():
        assert value == "REPLACE_ME"


def test_secret_deterministic(scope_api_key: MCPScope) -> None:
    assert generate_secret(scope_api_key) == generate_secret(scope_api_key)
