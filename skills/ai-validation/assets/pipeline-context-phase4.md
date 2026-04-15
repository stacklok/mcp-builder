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

Rather than duplicating code here (which gets out of date), agents should read the actual source files from the **mcp-template-py** repo for the canonical patterns. Below are the rules and guidelines the generator follows — use these as validation criteria and cross-reference with the template repo for exact syntax.

### tools.py — read `src/` in mcp-template-py for the template pattern

Rules:
- Each tool is an `async def` method on a `Tools` class, one method per YAML tool
- Every tool method must have a docstring
- Parameters are flattened (not wrapped in a model) so FastMCP can introspect them for the tool's input schema
- Required params have no default value; optional params have `| None = None`
- Path params use f-string interpolation (not string concatenation)
- Query params are passed as a dict to `params=`
- Body fields are passed as a dict to `json_body=`
- HTTP method is a string literal matching the YAML endpoint: `"GET"`, `"POST"`, etc.
- Hints from the YAML appear as `# Hint:` comments
- Return type is `-> dict`, returning the result of `self._client.request(...)`

### client.py — read `src/` in mcp-template-py for the template pattern

Rules:
- Calls `get_bearer_token()` (or equivalent) from the auth module
- Sets `Authorization: Bearer {token}` header on requests
- Base URL comes from the YAML's `spec.base_url`
- Uses httpx for HTTP requests

### mcp_builder.py — read `src/` in mcp-template-py for the template pattern

Rules:
- Imports `APIClient` from `{module_name}.client`
- Imports `Settings` from `{module_name}.settings`
- Imports `Tools` from `{module_name}.api.tools`
- Creates a `FastMCP` instance with the server name from YAML
- Registers one `mcp.add_tool(tools.{tool_name})` per tool in the YAML

### models.py

Rules:
- Only generated for tools with request bodies (POST/PUT/PATCH with JSON body)
- Each model is a Pydantic `BaseModel` subclass named `{ToolNamePascalCase}Params`
- Fields use `Field(...)` with descriptions from the spec
- Required fields have no default; optional fields have `Field(default=None, ...)`

### Deployment manifests — read `deploy/` in both mcp-template-py and toolhive CRD definitions

Rules for **mcpserver.yaml** (always present):
- `apiVersion` and `kind` must match the ToolHive MCPServer CRD definition (read from toolhive repo, do not hardcode)
- `metadata.name` matches the server name from YAML
- `spec.image` is `{server_name}-mcp:latest`
- `spec.transport` is set to a valid value per ToolHive source
- If auth != none: `spec.externalAuthConfig.name` is `{server_name}-auth`
- If auth == none: no `externalAuthConfig` field

Rules for **mcpexternalauthconfig.yaml** (only when auth != none):
- Structure must match ToolHive's MCPExternalAuthConfig CRD definition (read from toolhive repo)
- For `oauth_bearer`: type, issuer, and scopes must match the YAML auth config
- For `api_key`: type and secret reference must match

Rules for **secret.yaml** (only when auth != none):
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
