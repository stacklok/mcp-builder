"""Patch scaffolded server files with tool and client wiring.

Pipeline stage: rendering (source text + ServerPlan -> patched source text).
Called by: the pipeline orchestrator after scaffold_project().

The scaffold step copies the template and renames the module, but leaves
placeholder tool registrations (``mcp.add_tool(tools.hello)``). This
module replaces those placeholders with the actual generated tools.
"""

from __future__ import annotations

import re

from mcp_builder.codegen.plan import ServerPlan


def patch_mcp_builder(source: str, plan: ServerPlan) -> str:
    """Patch the scaffolded mcp_builder.py to wire generated tools.

    Pipeline stage: rendering (post-scaffold source -> patched source).
    Called by: the pipeline orchestrator.

    Performs four targeted replacements on the post-scaffold source:
    1. Adds ``APIClient`` import before the ``Settings`` import.
    2. Fixes the FastMCP server name from the template placeholder.
    3. Replaces ``Tools()`` with ``Tools(APIClient())`` to inject the client.
    4. Replaces the template tool registration with one per generated tool.

    Args:
        source: The scaffolded mcp_builder.py content (already has the
                correct module name from the scaffold step).
        plan: The server plan containing tool definitions.

    Returns:
        Patched source text.
    """
    # 1. Add APIClient import before Settings import.
    settings_import = f"from {plan.module_name}.settings import Settings"
    client_import = f"from {plan.module_name}.client import APIClient\n"
    source = source.replace(settings_import, client_import + settings_import)

    # 2. Fix FastMCP server name from template placeholder.
    source = re.sub(r'FastMCP\("[^"]*"', f'FastMCP("{plan.server_name}"', source)

    # 3. Inject client into Tools constructor.
    # APIClient() uses the default base_url baked into the generated client module.
    source = source.replace("tools = Tools()", "tools = Tools(APIClient())")

    # 4. Replace template tool registrations with generated ones.
    source = re.sub(r"^ *mcp\.add_tool\(tools\.\w+\)\n", "", source, flags=re.MULTILINE)
    registrations = "".join(
        f"        mcp.add_tool(tools.{t.tool_name})\n" for t in plan.tools
    )
    source = source.replace(
        "        return mcp", registrations + "\n        return mcp"
    )

    return source


def patch_app_builder(source: str, plan: ServerPlan) -> str:
    """Patch the scaffolded app_builder.py.

    Pipeline stage: rendering (post-scaffold source -> patched source).
    Called by: the pipeline orchestrator.

    Currently a no-op. The scaffold step already handles module name
    replacement, and app_builder.py contains only framework boilerplate
    with no server-specific content that needs modification.

    Args:
        source: The scaffolded app_builder.py content.
        plan: The server plan (unused, kept for interface consistency).

    Returns:
        Source text unchanged.
    """
    return source
