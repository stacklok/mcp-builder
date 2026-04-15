# mcp-builder Pipeline Context

This document provides shared context for AI agents working on the mcp-builder pipeline. Read this before starting your task.

## What is mcp-builder?

mcp-builder is a pipeline that transforms an OpenAPI 3.x spec and plain-English workflow descriptions into a production-quality, ToolHive-ready MCP server. It has four phases:

1. **Phase 1 — AI Scoping** (you are here): Parse the spec, semantically group endpoints, assign LLM-optimized tool names and descriptions, detect auth, and emit a validated `mcp-scope.yaml` + `scoping-summary.md`.
2. **Phase 2 — Human Review**: A human edits the YAML and summary, fixing any issues flagged in Phase 1.
3. **Phase 3 — Deterministic Code Generation**: Reads the YAML + OpenAPI spec and scaffolds a complete MCP server. No AI involved — this is a pure function of the config.
4. **Phase 4 — AI Validation**: Reviews the generated code for correctness, makes improvements guided by hints in the config, and verifies the build succeeds.

## What is mcp-scope.yaml?

`mcp-scope.yaml` is the contract between the AI/human world (Phases 1-2) and the deterministic code generator (Phase 3). It defines:

- **Server identity**: name (DNS label), description
- **Spec metadata**: source URL/path, format (OpenAPI 3.0 or 3.1), base URL, endpoint counts
- **Workflows**: plain-English descriptions of what users do with this API (minimum 3)
- **Groups**: semantic clusters of related tools (e.g., "file-operations", "comments")
- **Tools**: individual API endpoints with LLM-optimized names, descriptions, parameter overrides, and hints
- **Auth**: authentication type (oauth_bearer, api_key, none) with OAuth details if applicable

The formal JSON schema is at `docs/mcp-scope-schema.json` (auto-generated from the Pydantic models via `task generate-schema`).

### Key constraints enforced by the schema

- Server name must be a valid DNS label: `[a-z0-9]([a-z0-9-]*[a-z0-9])?`, max 63 chars
- Tool names must be snake_case: `[a-z][a-z0-9_]*`, max 40 chars
- Tool names must be globally unique across all groups
- Each group must have at least one tool
- Endpoint format: `METHOD /path` (e.g., `GET /files/{fileId}`)
- Endpoint paths must match the spec's `paths` exactly — do not prepend the base URL path
- OAuth config is required when auth type is `oauth_bearer`

### Parameter semantics

When a tool in `mcp-scope.yaml` defines a `parameters` list, those parameters act as an **allowlist**: only the listed parameters are included in the generated MCP tool. Parameters present in the OpenAPI spec but absent from the YAML list are excluded from code generation.

- **Path parameters are always included** regardless of the allowlist, because they are required for URL construction.
- When `parameters` is omitted (null), ALL spec parameters are used (backward compatible).
- The `description` and `required` fields in the YAML override the spec values for matching parameters.
- Each parameter should include a `location` field (`query` or `body`) indicating where it belongs in the HTTP request. Path parameters don't need a location. When `location` is omitted, codegen infers it from the OpenAPI spec — but explicit is preferred.

This means the endpoint-scoper agent should actively curate parameters — including only what's useful for the described workflows and excluding noise.

### Reference examples

- `e2e/fixtures/real/google_drive.yaml` — 5 tools, 2 groups, OAuth bearer
- `e2e/fixtures/real/github.yaml` — 8 tools, 3 groups, OAuth bearer

## What is your role?

You are an AI agent working on **Phase 1 — AI Scoping**. The orchestrator skill (`skills/ai-scoping/SKILL.md`) coordinates the overall flow. You are one of two agents:

- **spec-analyzer**: Processes structured JSON from `mcp-builder analyze`, assesses spec quality, and proposes semantic endpoint groups with workflow relevance ratings.
- **endpoint-scoper**: Takes user-selected groups and refines them into polished tool definitions — naming, descriptions, hints — ready for the final YAML.

Your output feeds into user-facing approval gates. The user makes all final decisions about what to include, what to name, and what to describe. Your job is to provide high-quality recommendations.
