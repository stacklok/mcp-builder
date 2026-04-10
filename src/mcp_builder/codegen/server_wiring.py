"""Patch scaffolded mcp_builder.py and app_builder.py with tool/client wiring."""

from __future__ import annotations

import re

from mcp_builder.schema.models import MCPScope


def patch_mcp_builder(content: str, scope: MCPScope, module_name: str) -> str:
    """Patch scaffolded mcp_builder.py to wire in the generated APIClient and tools.

    Performs five targeted string replacements:
    1. Adds APIClient import before Settings import.
    2. Fixes the FastMCP server name to match scope.server.name.
    3. Adds a client parameter to build_mcp().
    4. Passes client to Tools() constructor.
    5. Replaces template tool registrations with generated ones.

    Args:
        content: The scaffolded mcp_builder.py source text.
        scope: Validated MCP scope used to derive server name and tool list.
        module_name: Python module name (e.g. ``test_api_mcp``).

    Returns:
        Patched source text.
    """
    # 1. Add APIClient import before the Settings import line.
    client_import = f"from {module_name}.client import APIClient\n"
    settings_import = f"from {module_name}.settings import Settings"
    content = content.replace(settings_import, client_import + settings_import)

    # 2. Fix FastMCP server name.
    content = re.sub(r'FastMCP\("[^"]*"', f'FastMCP("{scope.server.name}"', content)

    # 3. Add client param to build_mcp() signature.
    old_sig = "settings: Settings | None = None,\n    ) -> FastMCP:"
    new_sig = (
        "settings: Settings | None = None,\n"
        "        client: APIClient | None = None,\n"
        "    ) -> FastMCP:"
    )
    content = content.replace(old_sig, new_sig)

    # 4. Pass client to Tools constructor.
    content = content.replace("tools = Tools()", "tools = Tools(client)")

    # 5. Replace all template tool registrations with generated ones.
    content = re.sub(r"        mcp\.add_tool\(tools\.\w+\)\n", "", content)
    tool_names = [tool.tool_name for group in scope.groups for tool in group.tools]
    registrations = "".join(
        f"        mcp.add_tool(tools.{name})\n" for name in tool_names
    )
    content = content.replace(
        "        return mcp", registrations + "        return mcp"
    )

    return content


def patch_app_builder(content: str, module_name: str) -> str:
    """Patch scaffolded app_builder.py to create and close an APIClient.

    Performs three targeted string replacements:
    1. Adds APIClient import after the TokenPassthroughMiddleware import.
    2. Creates an APIClient and passes it to MCPBuilder.build_mcp().
    3. Closes the client at the end of the lifespan context.

    Args:
        content: The scaffolded app_builder.py source text.
        module_name: Python module name (e.g. ``test_api_mcp``).

    Returns:
        Patched source text.
    """
    # 1. Add APIClient import after the TokenPassthroughMiddleware import line.
    middleware_import = f"from {module_name}.auth import TokenPassthroughMiddleware"
    client_import = f"from {module_name}.client import APIClient"
    content = content.replace(
        middleware_import,
        middleware_import + "\n" + client_import,
    )

    # 2. Replace bare build_mcp(settings) call with client creation + wired call.
    #    The template has: mcp = MCPBuilder.build_mcp(settings)
    old_build = "mcp = MCPBuilder.build_mcp(settings)"
    new_build = (
        "client = APIClient()\n        mcp = MCPBuilder.build_mcp(settings, client)"
    )
    content = content.replace(old_build, new_build)

    # Guard against accidental double-assignment if template was already partially patched.
    content = content.replace("mcp = client = APIClient()", "client = APIClient()")

    # 3. Insert client.close() before the "MCP session manager stopped" log line.
    stopped_log = 'AppBuilder.logger.info("MCP session manager stopped")'
    content = content.replace(
        stopped_log,
        "await client.close()\n            " + stopped_log,
    )

    return content
