"""Tests for the deployment manifest renderer."""

from __future__ import annotations

import pytest
import yaml

from mcp_builder.codegen.plan import AuthPlan, ServerPlan
from mcp_builder.codegen.renderers.manifests import (
    render_external_auth_config,
    render_manifests,
    render_mcpserver,
    render_secret,
)
from tests.unit.test_renderers.conftest import make_plan

OAUTH_PLAN = make_plan(
    auth=AuthPlan(
        type="oauth_bearer",
        issuer="https://accounts.google.com",
        scopes=["openid", "email"],
    )
)
API_KEY_PLAN = make_plan()
NONE_PLAN = make_plan(auth=AuthPlan(type="none"))


# ---------------------------------------------------------------------------
# render_mcpserver
# ---------------------------------------------------------------------------


class TestRenderMcpserver:
    def test_valid_yaml(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert isinstance(doc, dict)

    def test_api_version(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["apiVersion"] == "mcp.toolhive.stacklok.dev/v1alpha1"

    def test_kind(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["kind"] == "MCPServer"

    def test_metadata_name(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["metadata"]["name"] == plan.server_name

    def test_image_name(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["image"] == f"{plan.server_name}-mcp:latest"

    def test_transport(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["transport"] == "streamablehttp"

    def test_auth_ref_when_auth_present(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OAUTH_PLAN))
        assert doc["spec"]["externalAuthConfig"]["name"] == "test-api-auth"

    def test_auth_ref_for_api_key(self) -> None:
        doc = yaml.safe_load(render_mcpserver(API_KEY_PLAN))
        assert doc["spec"]["externalAuthConfig"]["name"] == "test-api-auth"

    def test_no_auth_ref_when_none(self) -> None:
        doc = yaml.safe_load(render_mcpserver(NONE_PLAN))
        assert "externalAuthConfig" not in doc["spec"]

    def test_deterministic(self, plan: ServerPlan) -> None:
        assert render_mcpserver(plan) == render_mcpserver(plan)


# ---------------------------------------------------------------------------
# render_external_auth_config
# ---------------------------------------------------------------------------


class TestRenderExternalAuthConfig:
    def test_oauth_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert isinstance(doc, dict)

    def test_oauth_api_version(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["apiVersion"] == "mcp.toolhive.stacklok.dev/v1alpha1"

    def test_oauth_kind(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["kind"] == "MCPExternalAuthConfig"

    def test_oauth_metadata_name(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["metadata"]["name"] == "test-api-auth"

    def test_oauth_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["spec"]["type"] == "embeddedAuthServer"

    def test_oauth_issuer(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert (
            doc["spec"]["embeddedAuthServer"]["issuer"] == "https://accounts.google.com"
        )

    def test_oauth_scopes(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["spec"]["embeddedAuthServer"]["scopes"] == ["openid", "email"]

    def test_api_key_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        assert doc["spec"]["type"] == "bearerToken"

    def test_api_key_secret_ref(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        ref = doc["spec"]["bearerToken"]["secretRef"]
        assert ref["name"] == "test-api-secret"
        assert ref["key"] == "api-key"

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="none"):
            render_external_auth_config(NONE_PLAN)


# ---------------------------------------------------------------------------
# render_secret
# ---------------------------------------------------------------------------


class TestRenderSecret:
    def test_oauth_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert isinstance(doc, dict)

    def test_oauth_api_version(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert doc["apiVersion"] == "v1"

    def test_oauth_kind(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert doc["kind"] == "Secret"

    def test_oauth_metadata_name(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert doc["metadata"]["name"] == "test-api-secret"

    def test_oauth_type_opaque(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert doc["type"] == "Opaque"

    def test_oauth_placeholders(self) -> None:
        doc = yaml.safe_load(render_secret(OAUTH_PLAN))
        assert doc["stringData"]["client-id"] == "REPLACE_ME"
        assert doc["stringData"]["client-secret"] == "REPLACE_ME"

    def test_api_key_placeholder(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert doc["stringData"]["api-key"] == "REPLACE_ME"

    def test_api_key_no_oauth_keys(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert "client-id" not in doc["stringData"]

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="none"):
            render_secret(NONE_PLAN)


# ---------------------------------------------------------------------------
# render_manifests (convenience wrapper)
# ---------------------------------------------------------------------------


class TestRenderManifests:
    def test_api_key_returns_three_files(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert len(result) == 3

    def test_oauth_returns_three_files(self) -> None:
        result = render_manifests(OAUTH_PLAN)
        assert len(result) == 3

    def test_none_returns_one_file(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert len(result) == 1

    def test_filenames_with_auth(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "mcpexternalauthconfig.yaml",
            "secret.yaml",
        }

    def test_filenames_without_auth(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert set(result.keys()) == {"mcpserver.yaml"}

    def test_all_values_are_strings(self) -> None:
        for content in render_manifests(OAUTH_PLAN).values():
            assert isinstance(content, str)

    def test_all_values_parse_as_yaml(self) -> None:
        for content in render_manifests(OAUTH_PLAN).values():
            doc = yaml.safe_load(content)
            assert isinstance(doc, dict)
