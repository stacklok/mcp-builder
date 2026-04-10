"""Generate ToolHive deployment manifests (MCPServer CRD, AuthConfig, Secret)."""

from __future__ import annotations

import yaml

from mcp_builder.schema.models import MCPScope


def generate_mcpserver(scope: MCPScope) -> str:
    """Generate the MCPServer CRD manifest YAML for the given scope.

    Args:
        scope: The validated MCPScope describing the server and auth.

    Returns:
        YAML string for the MCPServer custom resource.
    """
    name = scope.server.name
    manifest: dict = {
        "apiVersion": "mcp.toolhive.stacklok.dev/v1alpha1",
        "kind": "MCPServer",
        "metadata": {"name": name},
        "spec": {
            "image": f"{name}-mcp:latest",
            "transport": "streamablehttp",
        },
    }
    if scope.auth.type != "none":
        manifest["spec"]["externalAuthConfig"] = {"name": f"{name}-auth"}
    return yaml.dump(manifest, default_flow_style=False, sort_keys=False)


def generate_auth_config(scope: MCPScope) -> str | None:
    """Generate the AuthConfig CRD manifest YAML for the given scope.

    Args:
        scope: The validated MCPScope describing the server and auth.

    Returns:
        YAML string for the AuthConfig custom resource, or None if auth type is "none".
    """
    if scope.auth.type == "none":
        return None

    name = scope.server.name
    manifest: dict = {
        "apiVersion": "mcp.toolhive.stacklok.dev/v1alpha1",
        "kind": "AuthConfig",
        "metadata": {"name": f"{name}-auth"},
        "spec": {},
    }

    if scope.auth.type == "oauth_bearer":
        assert scope.auth.oauth is not None  # validated by model
        manifest["spec"] = {
            "type": "embeddedAuthServer",
            "embeddedAuthServer": {
                "issuer": scope.auth.oauth.issuer,
                "scopes": list(scope.auth.oauth.scopes),
            },
        }
    else:
        # api_key
        manifest["spec"] = {
            "type": "bearerToken",
            "bearerToken": {
                "secretRef": {"name": f"{name}-secret"},
                "key": "api-key",
            },
        }

    return yaml.dump(manifest, default_flow_style=False, sort_keys=False)


def generate_secret(scope: MCPScope) -> str | None:
    """Generate the Kubernetes Secret manifest YAML for the given scope.

    Placeholder values ("REPLACE_ME") are used — never real credentials.

    Args:
        scope: The validated MCPScope describing the server and auth.

    Returns:
        YAML string for the Kubernetes Secret, or None if auth type is "none".
    """
    if scope.auth.type == "none":
        return None

    name = scope.server.name
    manifest: dict = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": f"{name}-secret"},
    }

    if scope.auth.type == "oauth_bearer":
        manifest["stringData"] = {
            "client-id": "REPLACE_ME",
            "client-secret": "REPLACE_ME",
        }
    else:
        # api_key
        manifest["stringData"] = {"api-key": "REPLACE_ME"}

    return yaml.dump(manifest, default_flow_style=False, sort_keys=False)
