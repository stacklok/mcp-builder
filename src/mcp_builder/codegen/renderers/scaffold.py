"""Scaffold a new MCP server project from the mcp-template-py template.

Pipeline stage: rendering (ServerPlan → project directory on disk).
Called by: the pipeline orchestrator after build_server_plan().

Copies the template directory, renames the Python package to match the
server name, and updates imports and pyproject.toml metadata.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import structlog

from mcp_builder.codegen.plan import ServerPlan
from mcp_builder.codegen.renderers.escape import escape_toml_string

logger = structlog.get_logger()

_TEMPLATE_MODULE = "mcp_template_py"
_TEMPLATE_PACKAGE = "mcp-template-py"


def scaffold_project(plan: ServerPlan, template_dir: Path, output_dir: Path) -> Path:
    """Copy template and rebrand it as a new MCP server project.

    Pipeline stage: rendering (plan → project on disk).
    Called by: the pipeline orchestrator.

    Args:
        plan: The server plan with module_name, server_name, description.
        template_dir: Path to mcp-template-py checkout.
        output_dir: Parent directory where the new project will be created.

    Returns:
        Path to the created project directory.
    """
    project_name = f"{plan.server_name}-mcp"
    project_dir = output_dir / project_name
    if project_dir.exists():
        raise FileExistsError(f"Output project directory already exists: {project_dir}")
    logger.info(
        "scaffolding project",
        project_name=project_name,
        template_dir=str(template_dir),
    )

    shutil.copytree(
        template_dir,
        project_dir,
        ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv", "*.pyc"),
    )
    logger.debug("copied template tree", project_dir=str(project_dir))

    # Rename the Python package directory.
    src_dir = project_dir / "src"
    old_module_dir = src_dir / _TEMPLATE_MODULE
    new_module_dir = src_dir / plan.module_name
    if not old_module_dir.exists():
        raise FileNotFoundError(
            f"Template is missing expected module directory: {old_module_dir}"
        )
    old_module_dir.rename(new_module_dir)
    logger.info(
        "renamed module",
        old_module=_TEMPLATE_MODULE,
        new_module=plan.module_name,
    )

    # Replace template references in all files that embed the module name.
    # .py files and Dockerfile were the original set; Taskfile.yml (run target),
    # CLAUDE.md (code-structure docs), and *.toml (pytest --cov) also contain
    # the template module name and must be rewritten.
    for pattern in ("*.py", "Dockerfile", "Taskfile.yml", "*.md", "*.toml"):
        _replace_in_files(project_dir, pattern, _TEMPLATE_MODULE, plan.module_name)
    logger.debug(
        "replaced module references in project files",
        old=_TEMPLATE_MODULE,
        new=plan.module_name,
    )

    # Update pyproject.toml.
    _update_pyproject(project_dir / "pyproject.toml", plan)

    # Rewrite integration test with actual tool names from the plan.
    _update_integration_test(project_dir, plan)

    logger.info("scaffold complete", project_dir=str(project_dir))
    return project_dir


def _replace_in_files(root: Path, glob_pattern: str, old: str, new: str) -> None:
    """Replace all occurrences of ``old`` with ``new`` in matching files."""
    for path in root.rglob(glob_pattern):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
            logger.debug(
                "replaced in file", file=str(path.relative_to(root)), old=old, new=new
            )


def _update_pyproject(pyproject_path: Path, plan: ServerPlan) -> None:
    """Update project name, description, and add httpx dependency."""
    text = pyproject_path.read_text(encoding="utf-8")

    # Replace package name.
    text = text.replace(
        f'name = "{_TEMPLATE_PACKAGE}"',
        f'name = "{plan.server_name}-mcp"',
    )
    logger.debug(
        "pyproject.toml: updated name",
        old=_TEMPLATE_PACKAGE,
        new=f"{plan.server_name}-mcp",
    )

    # Replace description (escape quotes for valid TOML).
    text = re.sub(
        r'description = ".*?"',
        f'description = "{escape_toml_string(plan.description)}"',
        text,
    )
    logger.debug("pyproject.toml: updated description")

    # Add httpx to dependencies if not already listed as a dependency.
    # Match only inside the dependencies array to avoid false positives
    # from the description or other fields mentioning "httpx".
    deps_match = re.search(r"dependencies\s*=\s*\[([^\]]*)\]", text, re.DOTALL)
    if deps_match and "httpx" not in deps_match.group(1):
        text = re.sub(
            r"(dependencies\s*=\s*\[)",
            r'\1\n    "httpx>=0.28",',
            text,
        )
        logger.debug("pyproject.toml: added httpx dependency")
    else:
        logger.debug("pyproject.toml: httpx already in dependencies, skipped")

    pyproject_path.write_text(text, encoding="utf-8")


def _update_integration_test(project_dir: Path, plan: ServerPlan) -> None:
    """Rewrite the template integration test with actual tool names.

    The template's test_mcp.py hardcodes a ``hello`` tool. This replaces it
    with assertions for the real tool names from the plan. If the template
    file doesn't exist, this is a no-op.
    """
    test_path = project_dir / "tests" / "integration" / "test_mcp.py"
    if not test_path.is_file():
        logger.debug("no integration test to update (file not found)")
        return

    tool_names = [t.tool_name for t in plan.tools]
    if not tool_names:
        logger.debug("no tools in plan, skipping integration test update")
        return

    first_tool = tool_names[0]
    tool_names_repr = repr(tool_names)

    test_path.write_text(
        f'''\
"""Integration tests for the MCP server.

These tests verify the MCP server works correctly using the official
MCP Python client library. They require a running server
(MCP_SERVER_URL environment variable).
"""

import os

import pytest

from tests.integration.conftest import get_mcp_client_session

# Skip MCP client tests if no server URL is configured
mcp_client = pytest.mark.skipif(
    not os.getenv("MCP_SERVER_URL"),
    reason="MCP_SERVER_URL environment variable not set. "
    "Set it to run MCP client integration tests against a live server.",
)

EXPECTED_TOOLS = {tool_names_repr}


@mcp_client
class TestMCPClient:
    """Integration tests using the official MCP Python client library.

    These tests require a running MCP server.
    Set MCP_SERVER_URL environment variable to run.

    Example:
        export MCP_SERVER_URL=http://localhost:8100/mcp
        pytest tests/integration/test_mcp.py -v
    """

    @pytest.mark.asyncio
    async def test_mcp_client_connection(self):
        """Test MCP client connection."""
        async with get_mcp_client_session() as session:
            result = await session.send_ping()
            assert result is not None

    @pytest.mark.asyncio
    async def test_mcp_client_list_tools(self):
        """Test listing MCP tools using the official client."""
        async with get_mcp_client_session() as session:
            tools_result = await session.list_tools()

            assert tools_result.tools is not None
            tool_names = [tool.name for tool in tools_result.tools]
            assert len(tool_names) > 0
            for expected in EXPECTED_TOOLS:
                assert expected in tool_names, (
                    f"Expected '{{expected}}' tool, found: {{tool_names}}"
                )

    @pytest.mark.asyncio
    async def test_mcp_client_call_tool(self):
        """Test calling the {first_tool} tool using the official client."""
        async with get_mcp_client_session() as session:
            result = await session.call_tool("{first_tool}", arguments={{}})

            assert result is not None
            assert len(result.content) > 0
''',
        encoding="utf-8",
    )
    logger.debug("updated integration test", tool_count=len(tool_names))
