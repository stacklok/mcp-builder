"""Code generation pipeline for MCP servers.

This package transforms an MCPScope (validated mcp-scope.yaml) and an OpenAPI
spec into a complete, deployable MCP server project.

Reading order:
    1. plan — builds a ServerPlan (the typed intermediate representation)
       (OpenAPI parsing lives in mcp_builder.spec, not here)
    2. renderers/ — each renderer takes a ServerPlan and emits one output file
"""
