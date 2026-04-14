# mcp-builder Pipeline Context — Phase 4

This document provides shared context for AI agents working on Phase 4 of the mcp-builder pipeline. Read this before starting your task.

## What is mcp-builder?

mcp-builder is a pipeline that transforms an OpenAPI 3.x spec and plain-English workflow descriptions into a production-quality, ToolHive-ready MCP server. It has four phases:

1. **Phase 1 — AI Scoping**: Parse the spec, semantically group endpoints, assign LLM-optimized tool names and descriptions, detect auth, and emit a validated `mcp-scope.yaml` + `scoping-summary.md`.
2. **Phase 2 — Human Review**: A human edits the YAML and summary, fixing any issues flagged in Phase 1.
3. **Phase 3 — Deterministic Code Generation**: Reads the YAML + OpenAPI spec and scaffolds a complete MCP server. No AI involved — this is a pure function of the config.
4. **Phase 4 — AI Validation & Polish** (you are here): Reviews the generated code for correctness and suggests improvements guided by hints in the YAML.

## What is mcp-scope.yaml?

`mcp-scope.yaml` is the contract between the AI/human world (Phases 1-2) and the deterministic code generator (Phase 3). It defines:

- **Server identity**: name (DNS label), description
- **Spec metadata**: source URL/path, format, base URL, endpoint counts
- **Workflows**: plain-English descriptions of what users do with this API
- **Groups**: semantic clusters of related tools
- **Tools**: individual API endpoints with names, descriptions, parameter overrides, and **hints**
- **Auth**: authentication type (oauth_bearer, api_key, none) with OAuth details if applicable

### Hints

Hints are free-text annotations on tools that communicate known patterns from Phase 1/2 to Phase 4. Common patterns:

- `"paginated: uses pageToken/nextPageToken cursor pattern"` — endpoint returns paginated results
- `"response has 50+ fields — consider field selection"` — large response payload
- `"file content is base64 encoded — decode before displaying"` — encoding quirk
- `"rate limited to N requests per minute"` — rate limiting

Hints drive the polish suggestions in Phase 4. The deterministic generator (Phase 3) ignores them — they appear only as comments in the generated code.

## What does the generated project look like?

Phase 3 produces a complete MCP server project with this structure:

```
{server_name}-mcp/
├── src/{module_name}/
│   ├── api/
│   │   ├── tools.py         # Tool methods (async, one per YAML tool)
│   │   ├── mcp_builder.py   # FastMCP wiring (imports, tool registration)
│   │   └── ...
│   ├── client.py             # HTTP client (base URL, auth forwarding)
│   ├── models.py             # Pydantic models for request bodies
│   ├── auth.py               # Auth helpers (get_bearer_token)
│   ├── settings.py           # Configuration
│   └── ...
├── deploy/
│   ├── mcpserver.yaml                 # ToolHive MCPServer CRD (always)
│   ├── mcpexternalauthconfig.yaml     # Auth config CRD (if auth != none)
│   └── secret.yaml                    # K8s Secret template (if auth != none)
├── pyproject.toml
├── Dockerfile
└── ...
```

The module name is derived from the server name: hyphens become underscores, append `_mcp`. Example: `google-drive` → `google_drive_mcp`.

## Source-of-truth repositories

Validation checks should be grounded in the actual source code of these repos, not hardcoded assumptions. Agents receive local paths (or clone URLs) and should read the relevant files directly.

| Repo | What it contains | Key paths to read |
|------|-----------------|-------------------|
| **stacklok/toolhive** | CRD schemas, auth patterns, runtime behavior | `pkg/api/v1alpha1/` (CRD Go types), `deploy/crds/` (CRD YAML schemas) |
| **stacklok/mcp-template-py** | The base Python MCP server template that generated projects are built on | `src/` (module structure), `Dockerfile`, `pyproject.toml`, `deploy/` (manifest templates) |

When checking CRD correctness (T1-T3), read the actual CRD definitions from `toolhive` rather than assuming `apiVersion`, `kind`, or field names. When checking generated code patterns (S1-S4, B1-B4), read `mcp-template-py` to understand the template structure the generator builds on.

## Generated code patterns

### tools.py

Each tool is an async method on a `Tools` class. Parameters are flattened (not wrapped in a model) so FastMCP can introspect them for the tool's input schema.

```python
class Tools:
    def __init__(self, client: APIClient) -> None:
        self._client = client

    async def list_files(self, q: str | None = None, page_size: int | None = None) -> dict:
        """List files in the user's Drive..."""
        # Hint: paginated: uses pageToken/nextPageToken cursor pattern
        return await self._client.request(
            "GET",
            "/files",
            params={"q": q, "pageSize": page_size},
        )

    async def get_file(self, file_id: str, fields: str | None = None) -> dict:
        """Get metadata for a single file by ID."""
        return await self._client.request(
            "GET",
            f"/files/{file_id}",
            params={"fields": fields},
        )
```

Key patterns:
- Required params have no default; optional params have `| None = None`
- Path params use f-string interpolation: `f"/files/{file_id}"`
- Query params passed as dict to `params=`
- Body fields passed as dict to `json_body=`
- HTTP method is a string literal: `"GET"`, `"POST"`, etc.
- Hints appear as `# Hint:` comments

### client.py

```python
class APIClient:
    def __init__(self, base_url: str = "{base_url}"):
        self._base_url = base_url

    async def request(self, method, path, *, params=None, json_body=None):
        token = await get_bearer_token()
        headers = {"Authorization": f"Bearer {token}"}
        # ... httpx request with self._base_url + path
```

Key patterns:
- Calls `get_bearer_token()` from the auth module
- Sets `Authorization: Bearer {token}` header
- Base URL from the YAML's `spec.base_url`

### mcp_builder.py

```python
from {module_name}.client import APIClient
from {module_name}.settings import Settings
from {module_name}.api.tools import Tools

mcp = FastMCP("{server_name}")
tools = Tools(APIClient())

mcp.add_tool(tools.list_files)
mcp.add_tool(tools.get_file)
# ... one per tool
```

Key patterns:
- Imports APIClient, Settings, Tools
- FastMCP name matches server name from YAML
- Tools constructed with APIClient instance
- One `mcp.add_tool()` per tool in the YAML

### models.py

Only generated for tools with request bodies (POST/PUT/PATCH with JSON body):

```python
class CreateFileParams(BaseModel):
    name: str = Field(..., description="The name of the file")
    mime_type: str = Field(..., description="MIME type")
    parents: list[str] | None = Field(default=None, description="Parent folder IDs")
```

### Deployment manifests

**mcpserver.yaml** (always present):
```yaml
apiVersion: mcp.toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: {server_name}
spec:
  image: {server_name}-mcp:latest
  transport: streamablehttp
  externalAuthConfig:          # only if auth != none
    name: {server_name}-auth
```

**mcpexternalauthconfig.yaml** (only when auth != none):
- For `oauth_bearer`: `type: embeddedAuthServer` with `issuer` and `scopes`
- For `api_key`: `type: bearerToken` with `secretRef` pointing to `{server_name}-secret`

**secret.yaml** (only when auth != none):
- For `oauth_bearer`: keys `client-id`, `client-secret` with value `REPLACE_ME`
- For `api_key`: key `api-key` with value `REPLACE_ME`

## Severity classification

Phase 4 validation uses two severity levels:

- **error** — the generated code is incorrect and will cause runtime failures or deployment issues. These block deployment.
- **info** — the code works but could be improved. These are the developer's choice.

Be precise about severity. A wrong HTTP method is an error. A missing field selection hint is info.

## What is your role?

You are an AI agent working on **Phase 4 — AI Validation & Polish**. The orchestrator skill (`skills/ai-validation/SKILL.md`) coordinates the overall flow. You are one of two agents:

- **code-validator**: Adversarial reviewer. Systematically checks generated code against the YAML and spec for structural, behavioral, auth, and CRD correctness. Produces a structured pass/fail report.
- **polish-suggester**: Improvement advisor. Reads hints from the YAML and code patterns, then proposes concrete improvements with code diffs. Only runs after validation passes.

Your output feeds into user-facing approval gates. The user decides whether to apply fixes and suggestions. Your job is to be thorough, precise, and actionable.
