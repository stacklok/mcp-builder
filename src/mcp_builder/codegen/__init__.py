"""Code generation pipeline for MCP servers.

This package transforms an MCPScope (validated mcp-scope.yaml) and an OpenAPI
spec into a complete, deployable MCP server project.

Reading order:
    1. spec_parser — loads and types the OpenAPI spec
    2. plan — builds a ServerPlan (the typed intermediate representation)
    3. renderers/ — each renderer takes a ServerPlan and emits one output file
"""
