"""Code generation pipeline for MCP servers.

This package transforms an MCPScope (validated mcp-scope.yaml) and an OpenAPI
spec into a complete, deployable MCP server project.

Reading order:
    1. analyzer — summarizes an OpenAPI spec (spec → SpecAnalysis)
    2. validator — checks a scope against an optional spec (scope → ValidationResult)
    3. plan — builds a ServerPlan (scope + spec → ServerPlan)
    4. renderers/ — each renderer takes a ServerPlan and emits one output file

OpenAPI parsing lives in mcp_builder.spec, not here.
"""
