"""Tests for the deployment manifest renderer."""

from __future__ import annotations

import pytest
import yaml

from mcp_builder.generate.plan import ServerPlan
from mcp_builder.generate.renderers.manifests import (
    _derive_provider_name,
    _split_external_url,
    _substitute_external_url,
    render_external_auth_config,
    render_ingress,
    render_manifests,
    render_mcpoidc_config,
    render_mcpserver,
    render_secret,
)
from mcp_builder.schema.models import NoAuth, OAuth2Auth, OIDCAuth
from tests.unit.test_renderers.conftest import make_plan

OIDC_PLAN = make_plan(
    auth=OIDCAuth(
        type="oidc",
        issuer="https://accounts.google.com",
        scopes_required=["openid", "email"],
    )
)
OAUTH2_PLAN = make_plan(
    auth=OAuth2Auth(
        type="oauth2",
        flow="authorizationCode",
        authorization_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        userinfo_url="https://api.spotify.com/v1/me",
        scopes_required=["user-read-private", "playlist-read-private"],
    )
)
API_KEY_PLAN = make_plan()
NONE_PLAN = make_plan(auth=NoAuth(type="none"))


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

    def test_auth_ref_when_oidc(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OIDC_PLAN))
        assert doc["spec"]["externalAuthConfigRef"]["name"] == "test-api-auth"

    def test_auth_ref_when_oauth2(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OAUTH2_PLAN))
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

    def test_no_inline_telemetry(self, plan: ServerPlan) -> None:
        # The MCPServer CRD no longer supports an inline `telemetry` field;
        # telemetry is configured via a separate MCPTelemetryConfig and
        # referenced via `telemetryConfigRef`.
        doc = yaml.safe_load(render_mcpserver(plan))
        assert "telemetry" not in doc["spec"]

    def test_oidc_config_ref_when_oidc(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OIDC_PLAN))
        ref = doc["spec"]["oidcConfigRef"]
        assert ref["name"] == "test-api-oidc"
        assert "REPLACE_ME_DOMAIN" in ref["audience"]
        assert "REPLACE_ME_DOMAIN" in ref["resourceUrl"]
        assert "oidcConfig" not in doc["spec"]

    def test_oidc_config_ref_when_oauth2(self) -> None:
        # Embedded auth server always issues OIDC tokens to clients, even
        # when the upstream is OAuth2 — so oidcConfigRef applies.
        doc = yaml.safe_load(render_mcpserver(OAUTH2_PLAN))
        ref = doc["spec"]["oidcConfigRef"]
        assert ref["name"] == "test-api-oidc"

    def test_no_oidc_config_ref_when_api_key(self) -> None:
        doc = yaml.safe_load(render_mcpserver(API_KEY_PLAN))
        assert "oidcConfigRef" not in doc["spec"]
        assert "oidcConfig" not in doc["spec"]

    def test_no_oidc_config_ref_when_none(self) -> None:
        doc = yaml.safe_load(render_mcpserver(NONE_PLAN))
        assert "oidcConfigRef" not in doc["spec"]
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


class TestRenderEmbeddedOIDC:
    def test_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        assert isinstance(doc, dict)

    def test_api_version(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        assert doc["apiVersion"] == "toolhive.stacklok.dev/v1alpha1"

    def test_kind(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        assert doc["kind"] == "MCPExternalAuthConfig"

    def test_metadata_name(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        assert doc["metadata"]["name"] == "test-api-auth"

    def test_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        assert doc["spec"]["type"] == "embeddedAuthServer"

    def test_upstream_provider_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        providers = doc["spec"]["embeddedAuthServer"]["upstreamProviders"]
        assert providers[0]["type"] == "oidc"
        assert providers[0]["name"] == "google"

    def test_upstream_issuer_url(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["issuerUrl"] == "https://accounts.google.com"

    def test_upstream_client_id_placeholder(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["clientId"] == "REPLACE_ME"

    def test_upstream_scopes(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"] == ["openid", "email"]

    def test_redirect_uri(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert "REPLACE_ME_DOMAIN" in oidc["redirectUri"]
        assert "test-api/oauth/callback" in oidc["redirectUri"]

    def test_token_lifespans(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        lifespans = doc["spec"]["embeddedAuthServer"]["tokenLifespans"]
        assert lifespans["accessTokenLifespan"] == "1h"

    def test_scopes_inject_openid_email(self) -> None:
        """Scopes missing openid/email get them injected."""
        plan = make_plan(
            auth=OIDCAuth(
                type="oidc",
                issuer="https://accounts.google.com",
                scopes_required=["https://www.googleapis.com/auth/drive.readonly"],
            )
        )
        doc = yaml.safe_load(render_external_auth_config(plan))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"][:2] == ["openid", "email"]
        assert "https://www.googleapis.com/auth/drive.readonly" in oidc["scopes"]

    def test_scopes_no_duplicate_openid_email(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        oidc = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oidcConfig"]
        assert oidc["scopes"].count("openid") == 1
        assert oidc["scopes"].count("email") == 1


class TestRenderEmbeddedOAuth2:
    def test_valid_yaml(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        assert isinstance(doc, dict)

    def test_upstream_provider_type(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        providers = doc["spec"]["embeddedAuthServer"]["upstreamProviders"]
        assert providers[0]["type"] == "oauth2"
        assert providers[0]["name"] == "spotify"

    def test_oauth2_config_endpoints(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        cfg = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oauth2Config"]
        assert cfg["authorizationEndpoint"] == "https://accounts.spotify.com/authorize"
        assert cfg["tokenEndpoint"] == "https://accounts.spotify.com/api/token"
        assert cfg["userInfo"] == "https://api.spotify.com/v1/me"

    def test_no_issuer_url(self) -> None:
        # OAuth2 has no issuer; the CRD must not carry one.
        raw = render_external_auth_config(OAUTH2_PLAN)
        assert "issuerUrl" not in raw

    def test_no_oidc_config_block(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert "oidcConfig" not in provider

    def test_client_id_placeholder(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        cfg = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oauth2Config"]
        assert cfg["clientId"] == "REPLACE_ME"

    def test_scopes_not_injected_with_openid(self) -> None:
        # openid/email are OIDC concepts — OAuth2 scopes are API-defined
        # only, so we do NOT inject openid/email into the oauth2 template.
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN))
        cfg = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oauth2Config"]
        assert "openid" not in cfg["scopes"]
        assert "user-read-private" in cfg["scopes"]

    def test_userinfo_url_omitted_when_none(self) -> None:
        plan = make_plan(
            auth=OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://accounts.spotify.com/authorize",
                token_url="https://accounts.spotify.com/api/token",
                scopes_required=["user-read-private"],
            )
        )
        doc = yaml.safe_load(render_external_auth_config(plan))
        cfg = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]["oauth2Config"]
        assert "userInfo" not in cfg


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

    def test_oidc_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            render_secret(OIDC_PLAN)

    def test_oauth2_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            render_secret(OAUTH2_PLAN)

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
# render_mcpoidc_config
# ---------------------------------------------------------------------------


class TestRenderMcpoidcConfig:
    def test_valid_for_oidc(self) -> None:
        doc = yaml.safe_load(render_mcpoidc_config(OIDC_PLAN))
        assert doc["kind"] == "MCPOIDCConfig"

    def test_valid_for_oauth2(self) -> None:
        # Embedded auth server issues OIDC tokens to clients regardless of
        # upstream, so MCPOIDCConfig applies to oauth2 too.
        doc = yaml.safe_load(render_mcpoidc_config(OAUTH2_PLAN))
        assert doc["kind"] == "MCPOIDCConfig"

    def test_api_version_and_kind(self) -> None:
        doc = yaml.safe_load(render_mcpoidc_config(OIDC_PLAN))
        assert doc["apiVersion"] == "toolhive.stacklok.dev/v1alpha1"

    def test_metadata_name_matches_ref(self) -> None:
        doc = yaml.safe_load(render_mcpoidc_config(OIDC_PLAN))
        assert doc["metadata"]["name"] == "test-api-oidc"

    def test_inline_issuer(self) -> None:
        doc = yaml.safe_load(render_mcpoidc_config(OIDC_PLAN))
        assert doc["spec"]["type"] == "inline"
        assert "REPLACE_ME_DOMAIN" in doc["spec"]["inline"]["issuer"]

    def test_raises_for_api_key(self) -> None:
        with pytest.raises(ValueError, match="oauth2/oidc"):
            render_mcpoidc_config(API_KEY_PLAN)

    def test_raises_for_none(self) -> None:
        with pytest.raises(ValueError, match="oauth2/oidc"):
            render_mcpoidc_config(NONE_PLAN)


# ---------------------------------------------------------------------------
# render_manifests (convenience wrapper)
# ---------------------------------------------------------------------------


class TestRenderManifests:
    def test_api_key_returns_four_files(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert len(result) == 4

    def test_oidc_returns_four_files(self) -> None:
        result = render_manifests(OIDC_PLAN)
        assert len(result) == 4

    def test_oauth2_returns_four_files(self) -> None:
        result = render_manifests(OAUTH2_PLAN)
        assert len(result) == 4

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

    def test_filenames_oidc(self) -> None:
        result = render_manifests(OIDC_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "ingress.yaml",
            "mcpexternalauthconfig.yaml",
            "mcpoidcconfig.yaml",
        }

    def test_filenames_oauth2(self) -> None:
        result = render_manifests(OAUTH2_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "ingress.yaml",
            "mcpexternalauthconfig.yaml",
            "mcpoidcconfig.yaml",
        }

    def test_filenames_without_auth(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert set(result.keys()) == {"mcpserver.yaml", "ingress.yaml"}

    def test_all_values_are_strings(self) -> None:
        for content in render_manifests(OIDC_PLAN).values():
            assert isinstance(content, str)
        for content in render_manifests(OAUTH2_PLAN).values():
            assert isinstance(content, str)

    def test_all_values_parse_as_yaml(self) -> None:
        for content in render_manifests(OIDC_PLAN).values():
            doc = yaml.safe_load(content)
            assert isinstance(doc, dict)
        for content in render_manifests(OAUTH2_PLAN).values():
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


# ---------------------------------------------------------------------------
# _substitute_external_url
# ---------------------------------------------------------------------------


class TestSubstituteExternalUrl:
    def test_none_returns_none(self) -> None:
        assert _substitute_external_url(None, "google-drive") is None

    def test_path_placeholder(self) -> None:
        assert (
            _substitute_external_url(
                "https://mcp.example.com/<server_name>", "google-drive"
            )
            == "https://mcp.example.com/google-drive"
        )

    def test_nested_path_placeholder(self) -> None:
        assert (
            _substitute_external_url(
                "https://example.com/<server_name>/mcp", "google-drive"
            )
            == "https://example.com/google-drive/mcp"
        )

    def test_subdomain_placeholder(self) -> None:
        assert (
            _substitute_external_url(
                "https://<server_name>.example.com/mcp", "google-drive"
            )
            == "https://google-drive.example.com/mcp"
        )


# ---------------------------------------------------------------------------
# _split_external_url
# ---------------------------------------------------------------------------


class TestSplitExternalUrl:
    @pytest.mark.parametrize(
        ("url", "expected_host", "expected_path"),
        [
            (
                "https://mcp.example.com/google-drive",
                "mcp.example.com",
                "/google-drive",
            ),
            (
                "https://example.com/google-drive/mcp",
                "example.com",
                "/google-drive/mcp",
            ),
            (
                "https://google-drive.example.com/mcp",
                "google-drive.example.com",
                "/mcp",
            ),
            # Host-only URL — path defaults to "/"
            ("https://example.com", "example.com", "/"),
            ("https://example.com/", "example.com", "/"),
        ],
    )
    def test_split(self, url: str, expected_host: str, expected_path: str) -> None:
        host, path = _split_external_url(url)
        assert host == expected_host
        assert path == expected_path

    def test_strips_trailing_slash_from_non_root_path(self) -> None:
        # An auth endpoint URL with a trailing slash should not produce a
        # double-slash in the ingress path.
        host, path = _split_external_url("https://example.com/google-drive/")
        assert host == "example.com"
        assert path == "/google-drive"


# ---------------------------------------------------------------------------
# external_url_template + client_type end-to-end wiring
# ---------------------------------------------------------------------------


OIDC_PLAN_WITH_URL_CONFIDENTIAL = make_plan(
    auth=OIDCAuth(
        type="oidc",
        issuer="https://accounts.google.com",
        scopes_required=["openid", "email"],
        external_url_template="https://mcp.example.com/<server_name>",
        client_type="confidential",
    )
)
OIDC_PLAN_WITH_URL_PUBLIC = make_plan(
    auth=OIDCAuth(
        type="oidc",
        issuer="https://accounts.google.com",
        external_url_template="https://example.com/<server_name>/mcp",
        client_type="public",
    )
)
OAUTH2_PLAN_WITH_URL_CONFIDENTIAL = make_plan(
    auth=OAuth2Auth(
        type="oauth2",
        flow="authorizationCode",
        authorization_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        external_url_template="https://mcp.example.com/<server_name>",
        client_type="confidential",
    )
)
OAUTH2_PLAN_WITH_URL_PUBLIC = make_plan(
    auth=OAuth2Auth(
        type="oauth2",
        flow="authorizationCode",
        authorization_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        external_url_template="https://<server_name>.example.com/mcp",
        client_type="public",
    )
)


class TestExternalUrlThreading:
    """Concrete external URLs flow through every auth-dependent manifest."""

    def test_oidc_externalauthconfig_issuer_concrete(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OIDC_PLAN_WITH_URL_CONFIDENTIAL)
        )
        assert (
            doc["spec"]["embeddedAuthServer"]["issuer"]
            == "https://mcp.example.com/test-api"
        )

    def test_oidc_externalauthconfig_redirect_uri_concrete(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OIDC_PLAN_WITH_URL_CONFIDENTIAL)
        )
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert (
            provider["oidcConfig"]["redirectUri"]
            == "https://mcp.example.com/test-api/oauth/callback"
        )

    def test_oauth2_externalauthconfig_issuer_concrete(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OAUTH2_PLAN_WITH_URL_CONFIDENTIAL)
        )
        assert (
            doc["spec"]["embeddedAuthServer"]["issuer"]
            == "https://mcp.example.com/test-api"
        )

    def test_oauth2_externalauthconfig_redirect_uri_concrete(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OAUTH2_PLAN_WITH_URL_CONFIDENTIAL)
        )
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert (
            provider["oauth2Config"]["redirectUri"]
            == "https://mcp.example.com/test-api/oauth/callback"
        )

    def test_mcpserver_audience_and_resource_url_concrete(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OIDC_PLAN_WITH_URL_CONFIDENTIAL))
        ref = doc["spec"]["oidcConfigRef"]
        assert ref["audience"] == "https://mcp.example.com/test-api"
        assert ref["resourceUrl"] == "https://mcp.example.com/test-api"

    def test_mcpoidcconfig_issuer_concrete(self) -> None:
        doc = yaml.safe_load(render_mcpoidc_config(OIDC_PLAN_WITH_URL_CONFIDENTIAL))
        assert doc["spec"]["inline"]["issuer"] == "https://mcp.example.com/test-api"

    def test_ingress_host_and_path_concrete_shared_host(self) -> None:
        doc = yaml.safe_load(render_ingress(OIDC_PLAN_WITH_URL_CONFIDENTIAL))
        rule = doc["spec"]["rules"][0]
        assert rule["host"] == "mcp.example.com"
        assert rule["http"]["paths"][0]["path"] == "/test-api"

    def test_ingress_host_and_path_concrete_path_at_root(self) -> None:
        doc = yaml.safe_load(render_ingress(OIDC_PLAN_WITH_URL_PUBLIC))
        rule = doc["spec"]["rules"][0]
        assert rule["host"] == "example.com"
        assert rule["http"]["paths"][0]["path"] == "/test-api/mcp"

    def test_ingress_host_and_path_concrete_subdomain(self) -> None:
        doc = yaml.safe_load(render_ingress(OAUTH2_PLAN_WITH_URL_PUBLIC))
        rule = doc["spec"]["rules"][0]
        assert rule["host"] == "test-api.example.com"
        assert rule["http"]["paths"][0]["path"] == "/mcp"

    def test_fallback_placeholder_when_template_absent(self) -> None:
        # Backward-compat: when external_url_template is None, templates emit
        # the REPLACE_ME_DOMAIN placeholder so deploy-assist can substitute.
        rendered = render_external_auth_config(OIDC_PLAN)
        assert "REPLACE_ME_DOMAIN" in rendered
        assert "https://mcp.REPLACE_ME_DOMAIN/test-api" in rendered

    def test_mcpserver_fallback_when_template_absent(self) -> None:
        rendered = render_mcpserver(OIDC_PLAN)
        assert "REPLACE_ME_DOMAIN" in rendered

    def test_ingress_fallback_when_template_absent(self) -> None:
        rendered = render_ingress(OIDC_PLAN)
        assert "REPLACE_ME_DOMAIN" in rendered


class TestClientTypeRendering:
    """client_type drives live-vs-commented clientSecretRef and secret-oauth emission."""

    def test_confidential_oidc_renders_client_secret_ref_live(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OIDC_PLAN_WITH_URL_CONFIDENTIAL)
        )
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        ref = provider["oidcConfig"]["clientSecretRef"]
        assert ref["name"] == "test-api-oauth-secret"
        assert ref["key"] == "client-secret"

    def test_confidential_oauth2_renders_client_secret_ref_live(self) -> None:
        doc = yaml.safe_load(
            render_external_auth_config(OAUTH2_PLAN_WITH_URL_CONFIDENTIAL)
        )
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        ref = provider["oauth2Config"]["clientSecretRef"]
        assert ref["name"] == "test-api-oauth-secret"
        assert ref["key"] == "client-secret"

    def test_public_oidc_does_not_emit_client_secret_ref(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN_WITH_URL_PUBLIC))
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert "clientSecretRef" not in provider["oidcConfig"]

    def test_public_oauth2_does_not_emit_client_secret_ref(self) -> None:
        doc = yaml.safe_load(render_external_auth_config(OAUTH2_PLAN_WITH_URL_PUBLIC))
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert "clientSecretRef" not in provider["oauth2Config"]

    def test_absent_client_type_does_not_emit_client_secret_ref(self) -> None:
        # When client_type is None, the template still emits a commented
        # example block (not a YAML key) so the YAML parses cleanly.
        doc = yaml.safe_load(render_external_auth_config(OIDC_PLAN))
        provider = doc["spec"]["embeddedAuthServer"]["upstreamProviders"][0]
        assert "clientSecretRef" not in provider["oidcConfig"]


class TestSecretOauthEmission:
    """A deploy/secret-oauth.yaml Secret is emitted only when client_type == confidential."""

    def test_confidential_oidc_emits_secret_oauth(self) -> None:
        result = render_manifests(OIDC_PLAN_WITH_URL_CONFIDENTIAL)
        assert "secret-oauth.yaml" in result
        doc = yaml.safe_load(result["secret-oauth.yaml"])
        assert doc["kind"] == "Secret"
        assert doc["metadata"]["name"] == "test-api-oauth-secret"
        assert doc["stringData"]["client-secret"] == "REPLACE_ME"

    def test_confidential_oauth2_emits_secret_oauth(self) -> None:
        result = render_manifests(OAUTH2_PLAN_WITH_URL_CONFIDENTIAL)
        assert "secret-oauth.yaml" in result

    def test_public_does_not_emit_secret_oauth(self) -> None:
        result = render_manifests(OIDC_PLAN_WITH_URL_PUBLIC)
        assert "secret-oauth.yaml" not in result

    def test_absent_client_type_does_not_emit_secret_oauth(self) -> None:
        result = render_manifests(OIDC_PLAN)
        assert "secret-oauth.yaml" not in result

    def test_api_key_does_not_emit_secret_oauth(self) -> None:
        result = render_manifests(API_KEY_PLAN)
        assert "secret-oauth.yaml" not in result
