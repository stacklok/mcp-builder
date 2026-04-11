"""Render ToolHive deployment manifests from a ServerPlan.

Pipeline stage: rendering (plan → YAML strings).
Produces three Kubernetes-style manifests for deploying a generated MCP
server on ToolHive:

    - MCPServer CRD — always generated
    - MCPExternalAuthConfig CRD — only when auth is configured
    - Secret template — only when auth is configured

Each render_* function returns a YAML string. The convenience function
render_manifests() returns a dict mapping filenames to content, handling
the conditional logic for auth-dependent manifests.

Reading guide:
    render_manifests() is the entry point called by cli.run_pipeline().
    The three render_* functions are the leaf renderers.
"""

from __future__ import annotations

import logging

import yaml

from mcp_builder.codegen.plan import ServerPlan

logger = logging.getLogger(__name__)

TOOLHIVE_API_VERSION = "mcp.toolhive.stacklok.dev/v1alpha1"


def render_manifests(plan: ServerPlan) -> dict[str, str]:
    """Render all deployment manifests as a filename → content mapping.

    Pipeline stage: rendering (plan → {filename: YAML string}).
    Called by: cli.run_pipeline().

    Returns a dict with 1–3 entries depending on auth type:
        - "mcpserver.yaml" — always present
        - "mcpexternalauthconfig.yaml" — present when auth.type != "none"
        - "secret.yaml" — present when auth.type != "none"
    """
    logger.info("Rendering deployment manifests for '%s'", plan.server_name)

    manifests: dict[str, str] = {
        "mcpserver.yaml": render_mcpserver(plan),
    }

    if plan.auth.type != "none":
        manifests["mcpexternalauthconfig.yaml"] = render_external_auth_config(plan)
        manifests["secret.yaml"] = render_secret(plan)

    logger.info("Generated %d manifest(s)", len(manifests))
    return manifests


# ---------------------------------------------------------------------------
# Individual manifest renderers
# ---------------------------------------------------------------------------


def render_mcpserver(plan: ServerPlan) -> str:
    """Render the MCPServer CRD manifest.

    Pipeline stage: rendering (plan → YAML string).
    Called by: render_manifests().

    Always generated regardless of auth type. References the external auth
    config by name when auth is configured.

    Example output (server_name="google-drive", auth.type="oauth_bearer"):

        apiVersion: mcp.toolhive.stacklok.dev/v1alpha1
        kind: MCPServer
        metadata:
          name: google-drive
        spec:
          image: google-drive-mcp:latest
          transport: streamablehttp
          externalAuthConfig:
            name: google-drive-auth
    """
    spec: dict = {
        "image": f"{plan.server_name}-mcp:latest",
        "transport": "streamablehttp",
    }
    if plan.auth.type != "none":
        spec["externalAuthConfig"] = {"name": f"{plan.server_name}-auth"}

    doc = {
        "apiVersion": TOOLHIVE_API_VERSION,
        "kind": "MCPServer",
        "metadata": {"name": plan.server_name},
        "spec": spec,
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False)


def render_external_auth_config(plan: ServerPlan) -> str:
    """Render the MCPExternalAuthConfig CRD manifest.

    Pipeline stage: rendering (plan → YAML string).
    Called by: render_manifests() when auth.type != "none".

    For oauth_bearer: type=embeddedAuthServer with issuer and scopes.
    For api_key: type=bearerToken with a secretRef pointing to the K8s Secret.

    Raises ValueError if called with auth.type == "none" (programming error).
    """
    if plan.auth.type == "none":
        raise ValueError("No auth config to render when auth.type is 'none'")

    if plan.auth.type == "oauth_bearer":
        spec: dict = {
            "type": "embeddedAuthServer",
            "embeddedAuthServer": {
                "issuer": plan.auth.issuer,
                "scopes": list(plan.auth.scopes or []),
            },
        }
    elif plan.auth.type == "api_key":
        spec = {
            "type": "bearerToken",
            "bearerToken": {
                "secretRef": {
                    "name": f"{plan.server_name}-secret",
                    "key": "api-key",
                },
            },
        }
    else:
        raise ValueError(f"Unexpected auth type: {plan.auth.type!r}")

    doc = {
        "apiVersion": TOOLHIVE_API_VERSION,
        "kind": "MCPExternalAuthConfig",
        "metadata": {"name": f"{plan.server_name}-auth"},
        "spec": spec,
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False)


def render_secret(plan: ServerPlan) -> str:
    """Render the K8s Secret template with placeholder values.

    Pipeline stage: rendering (plan → YAML string).
    Called by: render_manifests() when auth.type != "none".

    For oauth_bearer: placeholders for client-id and client-secret.
    For api_key: placeholder for api-key.
    All placeholder values are "REPLACE_ME" — operators fill these in at
    deploy time.

    Raises ValueError if called with auth.type == "none" (programming error).

    Uses ``stringData`` (not ``data``) so operators can paste plaintext
    values directly; Kubernetes base64-encodes them on create.
    """
    if plan.auth.type == "none":
        raise ValueError("No secret to render when auth.type is 'none'")

    if plan.auth.type == "oauth_bearer":
        string_data = {
            "client-id": "REPLACE_ME",
            "client-secret": "REPLACE_ME",
        }
    elif plan.auth.type == "api_key":
        string_data = {
            "api-key": "REPLACE_ME",
        }
    else:
        raise ValueError(f"Unexpected auth type: {plan.auth.type!r}")

    doc = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": f"{plan.server_name}-secret"},
        "type": "Opaque",
        "stringData": string_data,
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False)
