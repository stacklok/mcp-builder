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

import structlog

from mcp_builder.codegen.plan import ServerPlan
from mcp_builder.codegen.renderers.escape import escape_python_string

logger = structlog.get_logger()

_CLIENT_TEMPLATE = textwrap.dedent('''\
    """Async HTTP client for upstream API calls.

    Uses the project's auth middleware to obtain bearer tokens.
    """

    import os

    import httpx

    from {module_name}.auth import get_bearer_token


    # Cap on binary response size. Set MCP_MAX_BINARY_RESPONSE_BYTES to
    # override. Base64 encoding expands payload ~1.33x, so a 32 MiB body
    # becomes a ~43 MiB MCP message before transport overhead — callers
    # hitting the cap should split the endpoint or stream out-of-band.
    _DEFAULT_MAX_BINARY_BYTES = 32 * 1024 * 1024


    def _max_binary_bytes() -> int:
        raw = os.environ.get("MCP_MAX_BINARY_RESPONSE_BYTES")
        if not raw:
            return _DEFAULT_MAX_BINARY_BYTES
        try:
            value = int(raw)
        except ValueError:
            return _DEFAULT_MAX_BINARY_BYTES
        return value if value > 0 else _DEFAULT_MAX_BINARY_BYTES


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
                Parsed JSON response as a dict. For 204 / empty-body
                2xx responses, returns an empty dict so void endpoints
                don't raise ``JSONDecodeError`` on a zero-length body.
            """
            params = _strip_none(params)
            headers = _auth_headers()
            # Force JSON on servers that honor content negotiation so an
            # ambiguous spec like 200 returning application/json or
            # application/pdf doesn't silently hand us PDF bytes.
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

        async def request_bytes(
            self,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
        ) -> bytes:
            """Stream a binary response body, bounded by a size cap.

            Used for endpoints whose success responses declare a
            non-JSON media type (images, PDFs, octet-streams). Streams
            the body via ``aiter_bytes`` so responses larger than the
            cap are rejected before they OOM the process, even when
            the server omits Content-Length (chunked transfer).

            Returns the raw bytes; the caller is responsible for any
            further encoding (e.g. base64 for MCP transport). Note that
            base64 expands the payload ~1.33x, so the effective transport
            size is larger than the returned bytes.

            Raises:
                ValueError: if the response body exceeds the configured
                    cap (32 MiB by default; override with the
                    ``MCP_MAX_BINARY_RESPONSE_BYTES`` env var).
            """
            params = _strip_none(params)
            max_bytes = _max_binary_bytes()
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                async with client.stream(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=_auth_headers(),
                ) as response:
                    response.raise_for_status()
                    declared = _parse_content_length(
                        response.headers.get("content-length")
                    )
                    if declared is not None and declared > max_bytes:
                        raise ValueError(
                            f"Response body too large: Content-Length "
                            f"{{declared}} exceeds cap {{max_bytes}}"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(
                                f"Response body too large: exceeded cap "
                                f"{{max_bytes}} while streaming"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)


    def _strip_none(params: dict | None) -> dict | None:
        # Strip None query params so unset optional args aren't sent
        # as empty strings (e.g. driveId=&pageToken=) which cause 400s.
        # Body is left as-is: some APIs distinguish null from absent.
        if not params:
            return params
        return {{k: v for k, v in params.items() if v is not None}}


    def _auth_headers() -> dict[str, str]:
        headers: dict[str, str] = {{}}
        token = get_bearer_token()
        if token:
            headers["Authorization"] = f"Bearer {{token}}"
        return headers


    def _parse_content_length(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
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
    logger.info("rendering client module", base_url=plan.base_url)
    result = _CLIENT_TEMPLATE.format(
        module_name=plan.module_name,
        base_url=escape_python_string(plan.base_url),
    )
    logger.debug("client module rendered", chars=len(result))
    return result
