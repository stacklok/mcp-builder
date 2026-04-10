"""HTTP client code generation."""

from __future__ import annotations

import textwrap

from mcp_builder.schema.models import MCPScope


def generate_client(scope: MCPScope, module_name: str) -> str:
    """Generate an async httpx-based client module with token passthrough.

    Uses get_bearer_token() from the template's auth module (PR #40 API)
    to forward Bearer tokens to the upstream API.

    Args:
        scope: Validated MCP scope configuration.
        module_name: Python module name (e.g., 'google_drive_mcp').

    Returns:
        Python source code for the client module.
    """
    base_url = scope.spec.base_url
    return textwrap.dedent(f'''\
        """Generated async HTTP client with token passthrough."""

        from __future__ import annotations

        import httpx

        from {module_name}.auth import get_bearer_token


        class APIClient:
            """Async HTTP client that forwards Bearer tokens to the upstream API."""

            def __init__(self, base_url: str = "{base_url}") -> None:
                self._client = httpx.AsyncClient(base_url=base_url)

            async def request(
                self,
                method: str,
                path: str,
                *,
                params: dict | None = None,
                json_body: dict | None = None,
            ) -> httpx.Response:
                """Make an authenticated request to the upstream API."""
                headers: dict[str, str] = {{}}
                token = get_bearer_token()
                if token is not None:
                    headers["Authorization"] = f"Bearer {{token}}"
                return await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )

            async def close(self) -> None:
                """Close the underlying HTTP client."""
                await self._client.aclose()
    ''')
