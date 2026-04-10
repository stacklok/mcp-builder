"""Project scaffolding from mcp-template-py."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from mcp_builder.schema.models import MCPScope


def server_name_to_module(name: str) -> str:
    """Convert a server name (DNS label) to a Python module name.

    Example: 'google-drive' -> 'google_drive_mcp'
    """
    return name.replace("-", "_") + "_mcp"


def scaffold_project(
    scope: MCPScope,
    template_dir: Path,
    output_dir: Path,
) -> Path:
    """Copy the template project and rename to match the server config.

    Args:
        scope: Validated MCP scope configuration.
        template_dir: Path to the mcp-template-py template directory.
        output_dir: Parent directory for the generated project.

    Returns:
        Path to the generated project directory.
    """
    module_name = server_name_to_module(scope.server.name)
    project_dir = output_dir / f"{scope.server.name}-mcp"

    shutil.copytree(template_dir, project_dir)

    # Rename module directory
    old_module = project_dir / "src" / "mcp_template_py"
    new_module = project_dir / "src" / module_name
    if old_module.exists():
        old_module.rename(new_module)

    # Update Python imports
    _update_imports(project_dir, "mcp_template_py", module_name)

    # Update pyproject.toml
    _update_pyproject(project_dir / "pyproject.toml", scope)

    return project_dir


def _update_imports(project_dir: Path, old_module: str, new_module: str) -> None:
    """Replace import references in all Python files."""
    for py_file in project_dir.rglob("*.py"):
        content = py_file.read_text()
        updated = content.replace(old_module, new_module)
        if updated != content:
            py_file.write_text(updated)


def _update_pyproject(pyproject_path: Path, scope: MCPScope) -> None:
    """Update pyproject.toml with server name, description, and httpx dependency."""
    content = pyproject_path.read_text()

    content = re.sub(
        r'^name = ".*"',
        f'name = "{scope.server.name}-mcp"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r'^description = ".*"',
        f'description = "{scope.server.description}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if '"httpx' not in content:
        content = content.replace(
            "dependencies = [",
            'dependencies = [\n    "httpx",',
        )

    pyproject_path.write_text(content)
