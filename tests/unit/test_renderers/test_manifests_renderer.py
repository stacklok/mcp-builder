"""Tests for the deployment manifest renderer."""

from __future__ import annotations

import pytest
import yaml

from mcp_builder.codegen.plan import AuthPlan, ServerPlan
from mcp_builder.codegen.renderers.manifests import (
    _derive_provider_name,
    render_external_auth_config,
    render_ingress,
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
        assert doc["apiVersion"] == "toolhive.stacklok.dev/v1alpha1"

    def test_kind(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["kind"] == "MCPServer"

    def test_metadata_name(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["metadata"]["name"] == plan.server_name

    def test_namespace(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["metadata"]["namespace"] == "toolhive-system"

    def test_image_name(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["image"] == f"{plan.server_name}-mcp:latest"

    def test_transport(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["transport"] == "streamable-http"

    def test_permission_profile(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["permissionProfile"] == {
            "type": "builtin",
            "name": "network",
        }

    def test_auth_ref_when_oauth(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OAUTH_PLAN))
        assert doc["spec"]["externalAuthConfigRef"]["name"] == "test-api-auth"

    def test_auth_ref_for_api_key(self) -> None:
        doc = yaml.safe_load(render_mcpserver(API_KEY_PLAN))
        assert doc["spec"]["externalAuthConfigRef"]["name"] == "test-api-auth"

    def test_no_auth_ref_when_none(self) -> None:
        doc = yaml.safe_load(render_mcpserver(NONE_PLAN))
        assert "externalAuthConfigRef" not in doc["spec"]

    def test_proxy_port(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["proxyPort"] == 8080

    def test_resources(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        res = doc["spec"]["resources"]
        assert res["requests"] == {"cpu": "50m", "memory": "64Mi"}
        assert res["limits"] == {"cpu": "100m", "memory": "128Mi"}

    def test_audit_enabled(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["audit"]["enabled"] is True

    def test_telemetry(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        telemetry = doc["spec"]["telemetry"]
        assert "REPLACE_ME_OTEL_ENDPOINT" in telemetry["openTelemetry"]["endpoint"]
        assert telemetry["prometheus"]["enabled"] is True

    def test_oidc_config_when_oauth(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OAUTH_PLAN))
        oidc = doc["spec"]["oidcConfig"]
        assert "REPLACE_ME_DOMAIN" in oidc["issuer"]
        assert "test-api" in oidc["issuer"]
        assert len(oidc["audiences"]) == 1

    def test_no_oidc_config_when_api_key(self) -> None:
        doc = yaml.safe_load(render_mcpserver(API_KEY_PLAN))
        assert "oidcConfig" not in doc["spec"]

    def test_no_oidc_config_when_none(self) -> None:
        doc = yaml.safe_load(render_mcpserver(NONE_PLAN))
        assert "oidcConfig" not in doc["spec"]

    def test_deterministic(self, plan: ServerPlan) -> None:
        assert render_mcpserver(plan) == render_mcpserver(plan)

    def test_has_comment_header(self, plan: ServerPlan) -> None:
        raw = render_mcpserver(plan)
        assert raw.startswith("# MCPServer")
        assert "docs.stacklok.com" in raw


# ---------------------------------------------------------------------------
# render_external_auth_config — embedded auth server (OAuth)
# ---------------------------------------------------------------------------


class TestRenderEmbeddedAuthServer:
    def test_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert isinstance(doc, dict)

    def test_api_version(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["apiVersion"] == "toolhive.stacklok.dev/v1alpha1"

    def test_kind(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["kind"] == "MCPExternalAuthConfig"

    def test_metadata_name(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["metadata"]["name"] == "test-api-auth"

    def test_namespace(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["metadata"]["namespace"] == "toolhive-system"

    def test_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        assert doc["spec"]["type"] == "embeddedAuthServer"

    def test_issuer_placeholder(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        issuer = doc["spec"]["embeddedAuthServer"]["issuer"]
        assert "REPLACE_ME_DOMAIN" in issuer
        assert "test-api" in issuer

    def test_upstream_provider_name(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        providers = doc["spec"]["embeddedAuthServer"]["upstreamProviders"]
        assert len(providers) == 1
        assert providers[0]["name"] == "google"

    def test_upstream_provider_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        providers = doc["spec"]["embeddedAuthServer"]["upstreamProviders"]
        assert providers[0]["type"] == "oidc"

    def test_upstream_issuer_url(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["issuerUrl"] == "https://accounts.google.com"

    def test_upstream_client_id_placeholder(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["clientId"] == "REPLACE_ME"

    def test_upstream_scopes(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"] == ["openid", "email"]

    def test_redirect_uri(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert "REPLACE_ME_DOMAIN" in oidc["redirectUri"]
        assert "test-api/oauth/callback" in oidc["redirectUri"]

    def test_token_lifespans(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        lifespans = doc["spec"]["embeddedAuthServer"]["tokenLifespans"]
        assert lifespans["accessToken"] == "1h"
        assert lifespans["refreshToken"] == "168h"
        assert lifespans["authorizationCode"] == "10m"

    def test_scopes_inject_openid_email(self) -> None:
        """Scopes missing openid/email get them injected."""
        plan = make_plan(
            auth=AuthPlan(
                type="oauth_bearer",
                issuer="https://accounts.google.com",
                scopes=["https://www.googleapis.com/auth/drive.readonly"],
            )
        )
        doc = yaml.safe_load(render_external_auth_config(plan))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"][:2] == ["openid", "email"]
        assert "https://www.googleapis.com/auth/drive.readonly" in oidc["scopes"]

    def test_scopes_no_duplicate_openid_email(self) -> None:
        """Scopes already containing openid/email are not duplicated."""
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"].count("openid") == 1
        assert oidc["scopes"].count("email") == 1

    def test_no_signing_keys(self) -> None:
        """Signing keys are intentionally omitted — auto-generated at runtime."""
        doc = yaml.safe_load(render_external_auth_config(OAUTH_PLAN))
        eas = doc["spec"]["embeddedAuthServer"]
        assert "signingKeySecretRefs" not in eas
        assert "hmacSecretRefs" not in eas

    def test_has_comment_header(self) -> None:
        raw = render_external_auth_config(OAUTH_PLAN)
        assert "REQUIRED" in raw
        assert "clientId" in raw
        assert "docs.stacklok.com" in raw


# ---------------------------------------------------------------------------
# render_external_auth_config — bearer token (API key)
# ---------------------------------------------------------------------------


class TestRenderBearerTokenAuth:
    def test_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        assert isinstance(doc, dict)

    def test_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        assert doc["spec"]["type"] == "bearerToken"

    def test_token_secret_ref(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        ref = doc["spec"]["bearerToken"]["tokenSecretRef"]
        assert ref["name"] == "test-api-secret"
        assert ref["key"] == "token"

    def test_namespace(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(API_KEY_PLAN))
        assert doc["metadata"]["namespace"] == "toolhive-system"

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="none"):
            render_external_auth_config(NONE_PLAN)


# ---------------------------------------------------------------------------
# render_secret
# ---------------------------------------------------------------------------


class TestRenderSecret:
    def test_api_key_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert isinstance(doc, dict)

    def test_api_key_kind(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert doc["kind"] == "Secret"

    def test_api_key_namespace(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert doc["metadata"]["namespace"] == "toolhive-system"

    def test_api_key_metadata_name(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert doc["metadata"]["name"] == "test-api-secret"

    def test_api_key_placeholder(self) -> None:
        doc = yaml.safe_load(render_secret(API_KEY_PLAN))
        assert doc["stringData"]["token"] == "REPLACE_ME"

    def test_oauth_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            render_secret(OAUTH_PLAN)

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            render_secret(NONE_PLAN)


# ---------------------------------------------------------------------------
# render_ingress
# ---------------------------------------------------------------------------


class TestRenderIngress:
    def test_valid_yaml(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        assert isinstance(doc, dict)

    def test_api_version(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        assert doc["apiVersion"] == "networking.k8s.io/v1"

    def test_kind(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        assert doc["kind"] == "Ingress"

    def test_metadata_name(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        assert doc["metadata"]["name"] == f"{plan.server_name}-ingress"

    def test_namespace(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        assert doc["metadata"]["namespace"] == "toolhive-system"

    def test_host_placeholder(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        host = doc["spec"]["rules"][0]["host"]
        assert "REPLACE_ME_DOMAIN" in host

    def test_path(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        path = doc["spec"]["rules"][0]["http"]["paths"][0]
        assert path["path"] == f"/{plan.server_name}"
        assert path["pathType"] == "Prefix"

    def test_backend_port(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_ingress(plan))
        backend = doc["spec"]["rules"][0]["http"]["paths"][0]["backend"]
        assert backend["service"]["name"] == plan.server_name
        assert backend["service"]["port"]["number"] == 8080

    def test_has_comment_header(self, plan: ServerPlan) -> None:
        raw = render_ingress(plan)
        assert raw.startswith("# Ingress")


# ---------------------------------------------------------------------------
# render_manifests (convenience wrapper)
# ---------------------------------------------------------------------------


class TestRenderManifests:
    def test_api_key_returns_four_files(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert len(result) == 4

    def test_oauth_returns_three_files(self) -> None:
        result = render_manifests(OAUTH_PLAN)
        assert len(result) == 3

    def test_none_returns_two_files(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert len(result) == 2

    def test_filenames_api_key(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "ingress.yaml",
            "mcpexternalauthconfig.yaml",
            "secret.yaml",
        }

    def test_filenames_oauth(self) -> None:
        result = render_manifests(OAUTH_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "ingress.yaml",
            "mcpexternalauthconfig.yaml",
        }

    def test_filenames_without_auth(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert set(result.keys()) == {"mcpserver.yaml", "ingress.yaml"}

    def test_all_values_are_strings(self) -> None:
        for content in render_manifests(OAUTH_PLAN).values():
            assert isinstance(content, str)

    def test_all_values_parse_as_yaml(self) -> None:
        for content in render_manifests(OAUTH_PLAN).values():
            doc = yaml.safe_load(content)
            assert isinstance(doc, dict)


# ---------------------------------------------------------------------------
# _derive_provider_name
# ---------------------------------------------------------------------------


class TestDeriveProviderName:
    @pytest.mark.parametrize(
        ("issuer", "expected"),
        [
            ("https://accounts.google.com", "google"),
            ("https://login.microsoftonline.com/tenant/v2.0", "microsoft"),
            ("https://my-org.okta.com", "okta"),
            ("https://auth.atlassian.com/authorize", "atlassian"),
            ("https://github.com/login/oauth", "github"),
            ("https://slack.com/oauth/v2", "slack"),
            ("https://sso.example.com", "example"),
            ("upstream", "upstream"),
        ],
    )
    def test_known_providers(self, issuer: str, expected: str) -> None:
        assert _derive_provider_name(issuer) == expected
