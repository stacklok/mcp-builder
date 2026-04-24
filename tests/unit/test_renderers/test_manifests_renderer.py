"""Tests for the deployment manifest renderer."""

from __future__ import annotations

import pytest
import yaml

from mcp_builder.generate.plan import ServerPlan
from mcp_builder.generate.renderers.manifests import (
    _derive_provider_name,
    render_deploy_readme,
    render_external_auth_config,
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
        # Embedded auth server binds via spec.authServerRef (the inverse,
        # externalAuthConfigRef, is the controller's legacy path).
        doc = yaml.safe_load(render_mcpserver(OIDC_PLAN))
        ref = doc["spec"]["authServerRef"]
        assert ref["kind"] == "MCPExternalAuthConfig"
        assert ref["name"] == "test-api-auth"
        assert "externalAuthConfigRef" not in doc["spec"]

    def test_auth_ref_when_oauth2(self) -> None:
        doc = yaml.safe_load(render_mcpserver(OAUTH2_PLAN))
        ref = doc["spec"]["authServerRef"]
        assert ref["kind"] == "MCPExternalAuthConfig"
        assert ref["name"] == "test-api-auth"
        assert "externalAuthConfigRef" not in doc["spec"]

    def test_auth_ref_for_api_key(self) -> None:
        # bearerToken is an upstream-request-mutation auth type, not an
        # embedded auth server — it binds via externalAuthConfigRef.
        doc = yaml.safe_load(render_mcpserver(API_KEY_PLAN))
        assert doc["spec"]["externalAuthConfigRef"]["name"] == "test-api-auth"
        assert "authServerRef" not in doc["spec"]

    def test_no_auth_ref_when_none(self) -> None:
        doc = yaml.safe_load(render_mcpserver(NONE_PLAN))
        assert "externalAuthConfigRef" not in doc["spec"]
        assert "authServerRef" not in doc["spec"]

    def test_proxy_port(self, plan: ServerPlan) -> None:
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["proxyPort"] == 8080

    def test_mcp_port(self, plan: ServerPlan) -> None:
        # Upstream ToolHive examples and docs consistently set both
        # proxyPort and mcpPort on MCPServer.
        doc = yaml.safe_load(render_mcpserver(plan))
        assert doc["spec"]["mcpPort"] == 8080

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
# render_deploy_readme
# ---------------------------------------------------------------------------


class TestRenderDeployReadme:
    def test_contains_server_name(self, plan: ServerPlan) -> None:
        out = render_deploy_readme(plan)
        assert plan.server_name in out
        # The README instructs users to expose a specific ClusterIP service
        # — pin the exact name since users will copy-paste it.
        assert f"mcp-{plan.server_name}-proxy" in out

    def test_flags_missing_ingress(self, plan: ServerPlan) -> None:
        # The README is the only place we tell the user they must provide
        # external access — this guarantee matters enough to pin.
        out = render_deploy_readme(plan)
        assert "external access" in out.lower()
        assert "ingress" in out.lower()

    def test_api_key_lists_secret_file(self) -> None:
        out = render_deploy_readme(API_KEY_PLAN)
        assert "secret.yaml" in out
        assert "mcpoidcconfig.yaml" not in out
        # Apply order matters: secret must exist before the auth config
        # references it; auth config before the MCPServer that binds it.
        # Scope to the apply-order section — filenames also appear in the
        # Files table above, in a different order.
        apply = out.split("Recommended apply order", 1)[1]
        assert (
            apply.index("secret.yaml")
            < apply.index("mcpexternalauthconfig.yaml")
            < apply.index("mcpserver.yaml")
        )

    def test_oidc_lists_oidc_config(self) -> None:
        out = render_deploy_readme(OIDC_PLAN)
        assert "mcpoidcconfig.yaml" in out
        assert "secret.yaml" not in out
        # Embedded-auth apply order: oidc config → external auth config → mcpserver.
        apply = out.split("Recommended apply order", 1)[1]
        assert (
            apply.index("mcpoidcconfig.yaml")
            < apply.index("mcpexternalauthconfig.yaml")
            < apply.index("mcpserver.yaml")
        )

    def test_oauth2_lists_oidc_config(self) -> None:
        out = render_deploy_readme(OAUTH2_PLAN)
        assert "mcpoidcconfig.yaml" in out
        # Same embedded-auth apply order as OIDC.
        apply = out.split("Recommended apply order", 1)[1]
        assert (
            apply.index("mcpoidcconfig.yaml")
            < apply.index("mcpexternalauthconfig.yaml")
            < apply.index("mcpserver.yaml")
        )

    def test_none_lists_no_auth_files(self) -> None:
        out = render_deploy_readme(NONE_PLAN)
        assert "secret.yaml" not in out
        assert "mcpoidcconfig.yaml" not in out
        assert "mcpexternalauthconfig.yaml" not in out

    @pytest.mark.parametrize("embedded_plan", [OIDC_PLAN, OAUTH2_PLAN])
    def test_embedded_auth_flags_replace_me_domain_in_all_files(
        self, embedded_plan: ServerPlan
    ) -> None:
        # The README is the only user-facing place that enumerates which
        # files carry REPLACE_ME_DOMAIN and warns that all occurrences must
        # agree. Pin those guarantees — a silent drop would produce subtly
        # broken OAuth flows at runtime.
        out = render_deploy_readme(embedded_plan)
        assert "REPLACE_ME_DOMAIN" in out
        assert "mcpserver.yaml" in out
        assert "mcpexternalauthconfig.yaml" in out
        assert "mcpoidcconfig.yaml" in out
        assert "All occurrences must agree" in out


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
            "README.md",
            "mcpexternalauthconfig.yaml",
            "secret.yaml",
        }

    def test_filenames_oidc(self) -> None:
        result = render_manifests(OIDC_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "README.md",
            "mcpexternalauthconfig.yaml",
            "mcpoidcconfig.yaml",
        }

    def test_filenames_oauth2(self) -> None:
        result = render_manifests(OAUTH2_PLAN)
        assert set(result.keys()) == {
            "mcpserver.yaml",
            "README.md",
            "mcpexternalauthconfig.yaml",
            "mcpoidcconfig.yaml",
        }

    def test_filenames_without_auth(self) -> None:
        result = render_manifests(NONE_PLAN)
        assert set(result.keys()) == {"mcpserver.yaml", "README.md"}

    def test_no_ingress_generated(self) -> None:
        # External access (Ingress/Gateway) is intentionally not emitted —
        # the URL shape is cluster-specific. The README is where we tell
        # the user about that.
        for p in (API_KEY_PLAN, OIDC_PLAN, OAUTH2_PLAN, NONE_PLAN):
            assert "ingress.yaml" not in render_manifests(p)

    def test_all_values_are_strings(self) -> None:
        for content in render_manifests(OIDC_PLAN).values():
            assert isinstance(content, str)
        for content in render_manifests(OAUTH2_PLAN).values():
            assert isinstance(content, str)

    def test_all_yaml_values_parse_as_yaml(self) -> None:
        # README.md is markdown — exclude it from the YAML parse check.
        for name, content in render_manifests(OIDC_PLAN).items():
            if name.endswith(".yaml"):
                doc = yaml.safe_load(content)
                assert isinstance(doc, dict)
        for name, content in render_manifests(OAUTH2_PLAN).items():
            if name.endswith(".yaml"):
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
