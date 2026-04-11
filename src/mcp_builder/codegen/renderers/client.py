"""Render the async HTTP client module for a generated MCP server.

Pipeline stage: rendering (ServerPlan → source code string).
Called by: the pipeline orchestrator after scaffold_project().

The generated client uses httpx for async HTTP and delegates token
retrieval to the template's auth layer (get_bearer_token()), which is
copied into the project by the scaffold step.

Uses textwrap.dedent rather than Jinja2 because the template has only
two interpolation points (module_name, base_url) and no loops or
conditionals — a Jinja2 template would add overhead without benefit.
"""

from __future__ import annotations

import textwrap

from mcp_builder.codegen.plan import ServerPlan
from mcp_builder.codegen.renderers.escape import escape_python_string

_CLIENT_TEMPLATE = textwrap.dedent('''\
    """Async HTTP client for upstream API calls.

    Uses the project's auth middleware to obtain bearer tokens.
    """

    import httpx

    from {module_name}.auth import get_bearer_token


    class APIClient:
        """Async HTTP client with token passthrough for upstream API calls.

        Creates a new httpx.AsyncClient per request for simplicity.
        A future optimization could share a client instance across calls.
        """

        def __init__(self, base_url: str = "{base_url}") -> None:
            self._base_url = base_url

        async def request(
            self,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
        ) -> dict:
            """Send an HTTP request to the upstream API.

            Args:
                method: HTTP method (GET, POST, PUT, PATCH, DELETE).
                path: URL path (e.g., "/items/{{item_id}}").
                params: Query parameters.
                json_body: JSON request body.

            Returns:
                Parsed JSON response as a dict.
            """
            headers: dict[str, str] = {{}}
            token = get_bearer_token()
            if token:
                headers["Authorization"] = f"Bearer {{token}}"

            async with httpx.AsyncClient(base_url=self._base_url) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
''')


def render_client_module(plan: ServerPlan) -> str:
    """Generate the client.py module for the output project.

    Pipeline stage: rendering (plan → source code).
    Called by: the pipeline orchestrator.

    Example output (for base_url="https://api.example.com"):

        class APIClient:
            def __init__(self, base_url: str = "https://api.example.com"):
                ...
    """
    return _CLIENT_TEMPLATE.format(
        module_name=plan.module_name,
        base_url=escape_python_string(plan.base_url),
    )
