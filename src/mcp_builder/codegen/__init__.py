"""Code generation pipeline for MCP servers.

This package transforms an MCPScope (validated mcp-scope.yaml) and an OpenAPI
spec into a complete, deployable MCP server project.

There are two distinct jobs that read an OpenAPI spec, and they have
different requirements:

    spec_parser — strict extraction for the codegen pipeline. Extracts
        only the endpoints/parameters the scope selects, and raises on
        anything unresolvable. Bad input to code generation must fail fast.

    spec_analyzer — broad survey for the ``analyze`` CLI command. Walks
        every endpoint in the spec and produces structured JSON so that
        humans and AI agents can understand the API without reading raw
        OpenAPI YAML. Captures errors per-endpoint instead of raising,
        because one bad endpoint shouldn't block the whole survey.

They live in separate modules because they serve different consumers
(codegen pipeline vs. CLI/AI tooling) and have opposite error policies
(strict vs. tolerant).

Reading order:
    1. spec_parser — loads and types the OpenAPI spec
    2. spec_analyzer — surveys the full spec for the ``analyze`` command
    3. plan — builds a ServerPlan (the typed intermediate representation)
    4. renderers/ — each renderer takes a ServerPlan and emits one output file
"""
