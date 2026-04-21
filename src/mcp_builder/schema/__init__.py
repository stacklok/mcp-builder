"""Schema package — the typed contract for mcp-scope.yaml.

Re-exports the root ``MCPScope`` model and the ``load_scope`` loader so
callers don't have to reach into ``schema.models`` directly. This is the
Phase-1/Phase-2 boundary: Phase 1 (AI scoping) produces a YAML file that
validates against ``MCPScope``; Phase 3 (codegen) reloads it here before
building the ServerPlan.
"""

from mcp_builder.schema.models import MCPScope, load_scope

__all__ = ["MCPScope", "load_scope"]
