"""Render ToolHive deployment manifests from a ServerPlan.

Pipeline stage: rendering (plan -> YAML strings).
Produces Kubernetes-style manifests for deploying a generated MCP server
on ToolHive:

    - MCPServer CRD — always generated
    - Ingress — always generated (external access)
    - MCPExternalAuthConfig CRD — only when auth is configured
    - Secret template — only when auth type is api_key (bearerToken)

Each render_* function returns a YAML string. ``render_manifests()`` is
the entry point — it returns a dict mapping filenames to content and
handles the conditional logic for auth-dependent manifests. Templates
live in ``renderers/templates/*.yaml.jinja2``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader

from mcp_builder.generate.plan import ServerPlan
from mcp_builder.schema.models import OAuth2Auth, OIDCAuth

logger = logging.getLogger(__name__)

TOOLHIVE_API_VERSION = "toolhive.stacklok.dev/v1alpha1"
DEFAULT_NAMESPACE = "toolhive-system"

# Auth variants that use the embedded OIDC auth server (MCPOIDCConfig +
# MCPExternalAuthConfig). Use with ``isinstance`` so the type checker keeps
# the narrowed variant inside each branch.
_EMBEDDED_AUTH_CLASSES: tuple[type, ...] = (OAuth2Auth, OIDCAuth)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(  # nosec B701 — generating YAML manifests, not HTML
    loader=FileSystemLoader(_TEMPLATES_DIR),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_manifests(plan: ServerPlan) -> dict[str, str]:
    """Render all deployment manifests as a filename -> content mapping.

    Pipeline stage: rendering (plan -> {filename: YAML string}).

    Returns a dict with 2-5 entries depending on auth type + client_type:
        - "mcpserver.yaml" — always present
        - "ingress.yaml" — always present
        - "mcpexternalauthconfig.yaml" — present when auth.type != "none"
        - "mcpoidcconfig.yaml" — present when auth is oauth2 or oidc
        - "secret.yaml" — present only when auth.type == "api_key"
        - "secret-oauth.yaml" — present when auth is oauth2/oidc and
          auth.client_type == "confidential"
    """
    logger.info("Rendering deployment manifests for '%s'", plan.server_name)

    manifests: dict[str, str] = {
        "mcpserver.yaml": render_mcpserver(plan),
        "ingress.yaml": render_ingress(plan),
    }

    if plan.auth.type != "none":
        manifests["mcpexternalauthconfig.yaml"] = render_external_auth_config(plan)

    # Inline the isinstance tuple (rather than _EMBEDDED_AUTH_CLASSES) so the
    # type checker can narrow plan.auth and resolve client_type.
    if isinstance(plan.auth, (OAuth2Auth, OIDCAuth)):
        manifests["mcpoidcconfig.yaml"] = render_mcpoidc_config(plan)
        if plan.auth.client_type == "confidential":
            manifests["secret-oauth.yaml"] = render_secret_oauth(plan)

    if plan.auth.type == "api_key":
        manifests["secret.yaml"] = render_secret(plan)

    logger.info("Generated %d manifest(s)", len(manifests))
    return manifests


# ---------------------------------------------------------------------------
# Individual manifest renderers
# ---------------------------------------------------------------------------


def render_mcpserver(plan: ServerPlan) -> str:
    """Render the MCPServer CRD manifest."""
    logger.debug(
        "Rendering MCPServer for '%s' (auth=%s)", plan.server_name, plan.auth.type
    )
    tmpl = _env.get_template("mcpserver.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        api_version=TOOLHIVE_API_VERSION,
        namespace=DEFAULT_NAMESPACE,
        has_auth=plan.auth.type != "none",
        is_embedded_auth=isinstance(plan.auth, _EMBEDDED_AUTH_CLASSES),
        audience_url=_resolve_auth_base_url(plan),
    )


def render_mcpoidc_config(plan: ServerPlan) -> str:
    """Render the MCPOIDCConfig CRD manifest.

    Emitted for oauth2 and oidc auth — both use the embedded OIDC auth
    server, which issues its own OIDC tokens to clients regardless of
    whether the upstream is OAuth2 or OIDC. MCPServer references this
    resource via spec.oidcConfigRef instead of carrying an inline block.

    Raises ValueError for api_key / none auth.
    """
    if not isinstance(plan.auth, _EMBEDDED_AUTH_CLASSES):
        raise ValueError(
            f"MCPOIDCConfig only applies to oauth2/oidc auth, got {plan.auth.type!r}"
        )
    logger.debug("Rendering MCPOIDCConfig for '%s'", plan.server_name)
    tmpl = _env.get_template("mcpoidcconfig.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        api_version=TOOLHIVE_API_VERSION,
        namespace=DEFAULT_NAMESPACE,
        external_url=_extract_external_url(plan),
        issuer_url=_resolve_auth_base_url(plan),
    )


def render_external_auth_config(plan: ServerPlan) -> str:
    """Render the MCPExternalAuthConfig CRD manifest.

    Routes by auth variant:
        - OAuth2Auth -> embeddedAuthServer with an oauth2 upstream provider
          (authorizationEndpoint / tokenEndpoint declared inline)
        - OIDCAuth -> embeddedAuthServer with an oidc upstream provider
          (upstream publishes its own discovery document)
        - APIKeyAuth -> bearerToken with a tokenSecretRef

    Raises ValueError for auth.type == "none".
    """
    if isinstance(plan.auth, OAuth2Auth):
        logger.debug("Rendering embedded OAuth2 auth config for '%s'", plan.server_name)
        return _render_embedded_oauth2(plan, plan.auth)

    if isinstance(plan.auth, OIDCAuth):
        logger.debug("Rendering embedded OIDC auth config for '%s'", plan.server_name)
        return _render_embedded_oidc(plan, plan.auth)

    if plan.auth.type == "api_key":
        logger.debug("Rendering bearer token auth config for '%s'", plan.server_name)
        return _render_bearer_token_auth(plan)

    raise ValueError(f"No external auth config for auth type {plan.auth.type!r}")


def render_secret(plan: ServerPlan) -> str:
    """Render the K8s Secret template for bearerToken auth.

    Only generated for api_key auth. OAuth auth does not need a
    user-provided secret — signing keys are auto-generated by ToolHive
    at runtime.

    Raises ValueError if called with a non-api_key auth type.
    """
    if plan.auth.type != "api_key":
        raise ValueError(
            f"Secret template is only for api_key auth, got {plan.auth.type!r}"
        )

    logger.debug("Rendering Secret template for '%s'", plan.server_name)
    tmpl = _env.get_template("secret.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        namespace=DEFAULT_NAMESPACE,
    )


def render_secret_oauth(plan: ServerPlan) -> str:
    """Render the K8s Secret template holding the upstream OAuth client_secret.

    Only generated for oauth2 or oidc auth with ``client_type == "confidential"``.
    The emitted Secret is referenced by the MCPExternalAuthConfig's
    ``upstreamProviders[0].*.clientSecretRef``. The user must fill in the
    actual secret value from the upstream IdP before applying.
    """
    if not isinstance(plan.auth, (OAuth2Auth, OIDCAuth)):
        raise ValueError(
            f"OAuth client_secret template only applies to oauth2/oidc auth, "
            f"got {plan.auth.type!r}"
        )
    if plan.auth.client_type != "confidential":
        raise ValueError(
            f"OAuth client_secret template is only for confidential clients, "
            f"got client_type={plan.auth.client_type!r}"
        )

    logger.debug("Rendering OAuth Secret template for '%s'", plan.server_name)
    tmpl = _env.get_template("secret_oauth.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        namespace=DEFAULT_NAMESPACE,
    )


def render_ingress(plan: ServerPlan) -> str:
    """Render the Kubernetes Ingress manifest for external access.

    When the plan carries a concrete external URL (oauth2/oidc auth with
    ``external_url_template`` set), the ingress host and path are derived
    from it. Otherwise, the manifest falls back to a ``REPLACE_ME_DOMAIN``
    host and ``/<server_name>`` path for deploy-assist to rewrite.
    """
    logger.debug("Rendering Ingress for '%s'", plan.server_name)
    external_url = _extract_external_url(plan)
    if external_url is not None:
        ingress_host, ingress_path = _split_external_url(external_url)
    else:
        ingress_host = "mcp.REPLACE_ME_DOMAIN"
        ingress_path = f"/{plan.server_name}"
    tmpl = _env.get_template("ingress.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        namespace=DEFAULT_NAMESPACE,
        external_url=external_url,
        ingress_host=ingress_host,
        ingress_path=ingress_path,
    )


# ---------------------------------------------------------------------------
# Auth-type-specific renderers
# ---------------------------------------------------------------------------


def _render_embedded_oidc(plan: ServerPlan, auth: OIDCAuth) -> str:
    """Render MCPExternalAuthConfig for OIDC upstream (issuer-based).

    Emits ``upstreamProviders[*].type: oidc`` with ``oidcConfig.issuerUrl``.
    Endpoint URLs come from the upstream's discovery document at runtime.
    """
    provider_name = _derive_provider_name(auth.issuer)
    # openid+email are always present for user identity.
    required_scopes = ["openid", "email"]
    scopes = required_scopes + [
        s for s in auth.scopes_required if s not in required_scopes
    ]

    base_url = _resolve_auth_base_url(plan)
    tmpl = _env.get_template("authconfig_embedded_oidc.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        api_version=TOOLHIVE_API_VERSION,
        namespace=DEFAULT_NAMESPACE,
        provider_name=provider_name,
        upstream_issuer_url=auth.issuer,
        scopes=scopes,
        external_url=_substitute_external_url(
            auth.external_url_template, plan.server_name
        ),
        client_type=auth.client_type,
        issuer_url=base_url,
        redirect_uri=f"{base_url}/oauth/callback",
    )


def _render_embedded_oauth2(plan: ServerPlan, auth: OAuth2Auth) -> str:
    """Render MCPExternalAuthConfig for OAuth2 upstream (endpoint-based).

    Emits ``upstreamProviders[*].type: oauth2`` with ``oauth2Config``
    carrying inline ``authorizationEndpoint``, ``tokenEndpoint``, and an
    optional ``userInfo`` endpoint. No discovery document is consulted.
    """
    # Provider name derived from the authorization URL's host — OAuth2 has
    # no issuer to key off of.
    provider_name = _derive_provider_name(auth.authorization_url)
    scopes = list(auth.scopes_required)

    base_url = _resolve_auth_base_url(plan)
    tmpl = _env.get_template("authconfig_embedded_oauth2.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        api_version=TOOLHIVE_API_VERSION,
        namespace=DEFAULT_NAMESPACE,
        provider_name=provider_name,
        authorization_url=auth.authorization_url,
        token_url=auth.token_url,
        userinfo_url=auth.userinfo_url,
        scopes=scopes,
        external_url=_substitute_external_url(
            auth.external_url_template, plan.server_name
        ),
        client_type=auth.client_type,
        issuer_url=base_url,
        redirect_uri=f"{base_url}/oauth/callback",
    )


def _render_bearer_token_auth(plan: ServerPlan) -> str:
    """Render MCPExternalAuthConfig for API key (bearerToken type)."""
    tmpl = _env.get_template("authconfig_bearer.yaml.jinja2")
    return tmpl.render(
        server_name=plan.server_name,
        api_version=TOOLHIVE_API_VERSION,
        namespace=DEFAULT_NAMESPACE,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_external_url(plan: ServerPlan) -> str | None:
    """Return the concrete external URL for this plan, if configured.

    Only OAuth2Auth/OIDCAuth carry an ``external_url_template``. For other
    auth variants, or when the template is absent, returns ``None``. Used
    by templates to branch the header-comment prose (concrete URL vs.
    "fill in before applying"). For the actual URL *values* rendered into
    manifest fields, use ``_resolve_auth_base_url`` — it always returns a
    concrete string (either the substituted template or the REPLACE_ME
    placeholder sentinel deploy-assist greps for).
    """
    if isinstance(plan.auth, (OAuth2Auth, OIDCAuth)):
        return _substitute_external_url(
            plan.auth.external_url_template, plan.server_name
        )
    return None


def _resolve_auth_base_url(plan: ServerPlan) -> str:
    """Return the base external URL used for issuer/audience/resourceUrl.

    When the scope captured ``auth.external_url_template``, returns the
    substituted URL. Otherwise returns the REPLACE_ME_DOMAIN placeholder
    shape that deploy-assist rewrites at deploy time. Callers append
    ``/oauth/callback`` for redirect URIs; the path component is handled
    by ``_split_external_url`` for ingress.
    """
    external_url = _extract_external_url(plan)
    if external_url is not None:
        return external_url
    return f"https://mcp.REPLACE_ME_DOMAIN/{plan.server_name}"


def _substitute_external_url(template: str | None, server_name: str) -> str | None:
    """Substitute the ``<server_name>`` placeholder in an external URL template.

    The template validator in ``schema.models`` guarantees that when the
    template is non-None it contains exactly one ``<server_name>`` occurrence,
    so a simple string replace is sufficient. Returns ``None`` passthrough
    for callers that didn't configure an external URL.
    """
    if template is None:
        return None
    return template.replace("<server_name>", server_name)


def _split_external_url(url: str) -> tuple[str, str]:
    """Split a concrete external URL into an ingress (host, path) pair.

    Examples:
        ``https://mcp.example.com/google-drive`` -> ``("mcp.example.com", "/google-drive")``
        ``https://example.com/google-drive/mcp`` -> ``("example.com", "/google-drive/mcp")``
        ``https://google-drive.example.com/mcp`` -> ``("google-drive.example.com", "/mcp")``

    A trailing slash on a non-root path is stripped so the ingress path
    doesn't accidentally double up (e.g., ``/google-drive/`` -> ``/google-drive``).
    An empty or root-only path becomes ``/``.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return host, path


def _derive_provider_name(issuer: str) -> str:
    """Derive a short provider name from an OAuth issuer URL.

    Extracts the domain and picks a recognizable short name when possible.
    Falls back to the second-level domain label.

    Examples:
        "https://accounts.google.com" -> "google"
        "https://login.microsoftonline.com/..." -> "microsoft"
        "https://auth.atlassian.com/..." -> "atlassian"
        "https://my-company.okta.com" -> "okta"
        "https://github.com/login/oauth" -> "github"
    """
    try:
        hostname = urlparse(issuer).hostname or issuer
    except Exception:
        hostname = issuer

    # Known provider patterns
    known: list[tuple[str, str]] = [
        ("google", "google"),
        ("microsoft", "microsoft"),
        ("okta", "okta"),
        ("auth0", "auth0"),
        ("atlassian", "atlassian"),
        ("github", "github"),
        ("gitlab", "gitlab"),
        ("slack", "slack"),
        ("amazon", "amazon"),
        ("apple", "apple"),
    ]
    hostname_lower = hostname.lower()
    for pattern, name in known:
        if pattern in hostname_lower:
            logger.debug("Matched known provider '%s' from issuer '%s'", name, issuer)
            return name

    # Fall back to second-level domain (e.g., "example" from "sso.example.com")
    parts = hostname_lower.split(".")
    if len(parts) >= 2:
        fallback = re.sub(r"[^a-z0-9-]", "", parts[-2])
        logger.info(
            "No known provider matched for issuer '%s'; using domain label '%s'",
            issuer,
            fallback,
        )
        return fallback

    logger.warning(
        "Could not derive provider name from issuer '%s'; using 'upstream'", issuer
    )
    return "upstream"
