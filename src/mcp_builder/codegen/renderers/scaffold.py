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

    # Replace template references in Python files and Dockerfile.
    _replace_in_files(project_dir, "*.py", _TEMPLATE_MODULE, plan.module_name)
    logger.debug(
        "replaced module references in .py files",
        old=_TEMPLATE_MODULE,
        new=plan.module_name,
    )
    _replace_in_files(project_dir, "Dockerfile", _TEMPLATE_MODULE, plan.module_name)
    logger.debug(
        "replaced module references in Dockerfile",
        old=_TEMPLATE_MODULE,
        new=plan.module_name,
    )

    # Update pyproject.toml.
    _update_pyproject(project_dir / "pyproject.toml", plan)

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
