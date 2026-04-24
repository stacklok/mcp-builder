"""Render the async HTTP client module for a generated MCP server.

Pipeline stage: rendering (ServerPlan → source code string).

The generated client uses httpx for async HTTP and delegates token
retrieval to the template's auth layer (get_bearer_token()), which is
copied into the project by the scaffold step.

Uses textwrap.dedent rather than Jinja2 because the template has only
two interpolation points (module_name, base_url) and no loops or
conditionals — a Jinja2 template would add overhead without benefit.
"""

from __future__ import annotations

import textwrap

import structlog

from mcp_builder.generate.plan import ServerPlan
from mcp_builder.generate.renderers.escape import escape_python_string

logger = structlog.get_logger()

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
            """Send an HTTP request to a JSON endpoint.

            Args:
                method: HTTP method (GET, POST, PUT, PATCH, DELETE).
                path: URL path (e.g., "/items/{{item_id}}").
                params: Query parameters.
                json_body: JSON request body.

            Returns:
                Parsed JSON response as a dict. For 204 / empty-body
                2xx responses, returns an empty dict so void endpoints
                don't raise ``JSONDecodeError`` on a zero-length body.
            """
            params = _strip_none(params)
            headers = _auth_headers()
            headers["Accept"] = "application/json"
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                response.raise_for_status()
                if not response.content:
                    return {{}}
                return response.json()

        async def request_text(
            self,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
        ) -> str:
            """Send an HTTP request to a text endpoint and return the decoded body.

            Used for endpoints whose success responses declare a ``text/*``
            media type (plain text, HTML, CSV, Markdown, XML, exported
            Google Docs). httpx decodes the body using the response's
            declared charset, falling back to UTF-8.
            """
            params = _strip_none(params)
            headers = _auth_headers()
            headers["Accept"] = "text/*, */*;q=0.8"
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                response.raise_for_status()
                return response.text

        async def request_bytes(
            self,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
        ) -> bytes:
            """Send an HTTP request to a binary endpoint and return the raw bytes.

            Used for endpoints whose success responses declare an opaque
            binary media type (images, PDFs, octet-streams). The caller is
            responsible for any further encoding (e.g. base64 for MCP
            transport).
            """
            params = _strip_none(params)
            headers = _auth_headers()
            headers["Accept"] = "*/*"
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                response.raise_for_status()
                return response.content


    def _strip_none(params: dict | None) -> dict | None:
        """Drop query params whose value is None.

        Unset optional args would otherwise be sent as empty strings
        (e.g. ``driveId=&pageToken=``) which some APIs reject with 400.
        Body payloads are left untouched: some APIs distinguish an
        explicit ``null`` from an absent field.
        """
        if not params:
            return params
        return {{k: v for k, v in params.items() if v is not None}}


    def _auth_headers() -> dict[str, str]:
        """Build the Authorization header from the project's auth layer.

        Returns an empty dict when no bearer token is available so the
        call still reaches unauthenticated endpoints.
        """
        headers: dict[str, str] = {{}}
        token = get_bearer_token()
        if token:
            headers["Authorization"] = f"Bearer {{token}}"
        return headers
''')


def render_client_module(plan: ServerPlan) -> str:
    """Generate the client.py module for the output project.

    Pipeline stage: rendering (plan → source code).

    Example output (for base_url="https://api.example.com"):

        class APIClient:
            def __init__(self, base_url: str = "https://api.example.com"):
                ...
    """
    logger.info("rendering client module", base_url=plan.base_url)
    result = _CLIENT_TEMPLATE.format(
        module_name=plan.module_name,
        base_url=escape_python_string(plan.base_url),
    )
    logger.debug("client module rendered", chars=len(result))
    return result
