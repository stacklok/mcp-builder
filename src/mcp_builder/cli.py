"""CLI entry point and pipeline orchestrator for mcp-builder.

Subcommands:
    generate  — run the full codegen pipeline (scope + spec + template → project)
    analyze   — parse an OpenAPI spec and dump structured JSON
    validate  — check an mcp-scope.yaml against the Pydantic schema

Usage:
    uv run mcp-builder generate scope.yaml openapi.yaml /path/to/template
    uv run mcp-builder analyze openapi.yaml
    uv run mcp-builder validate scope.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from mcp_builder.codegen.plan import ServerPlan, build_server_plan
from mcp_builder.codegen.renderers.client import render_client_module
from mcp_builder.codegen.renderers.manifests import render_manifests
from mcp_builder.codegen.renderers.models import render_parameter_models
from mcp_builder.codegen.renderers.scaffold import scaffold_project
from mcp_builder.codegen.renderers.server_wiring import (
    patch_app_builder,
    patch_mcp_builder,
)
from mcp_builder.codegen.renderers.tools import render_tools_module
from mcp_builder.codegen.spec_analyzer import analyze_spec
from mcp_builder.codegen.spec_parser import load_openapi_spec, parse_endpoint
from mcp_builder.schema.models import load_scope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline orchestrator (used by the ``generate`` subcommand)
# ---------------------------------------------------------------------------


def run_pipeline(
    scope_yaml: Path,
    openapi_spec: Path,
    template_dir: Path,
    output_dir: Path,
) -> Path:
    """Run the full MCP server generation pipeline.

    Pipeline stage: orchestration (this is the top-level function).
    Called by: _cmd_generate() and e2e tests.

    Steps:
        1. Load and validate the mcp-scope.yaml and OpenAPI spec.
        2. Build the typed ServerPlan from scope + spec.
        3. Scaffold the project from the template directory.
        4. Render and write generated source files (models, client, tools).
        5. Patch scaffolded server wiring files.
        6. Write deployment manifests to deploy/.

    Args:
        scope_yaml: Path to mcp-scope.yaml.
        openapi_spec: Path to the OpenAPI spec (YAML or JSON).
        template_dir: Path to the mcp-template-py checkout.
        output_dir: Directory where the generated project will be created.

    Returns:
        Path to the generated project directory.
    """
    logger.info("Loading scope from %s", scope_yaml)
    scope = load_scope(scope_yaml)

    logger.info("Loading OpenAPI spec from %s", openapi_spec)
    spec = load_openapi_spec(openapi_spec)

    logger.info("Building server plan for '%s'", scope.server.name)
    plan = build_server_plan(scope, spec)

    logger.info("Scaffolding project into %s", output_dir)
    project_dir = scaffold_project(plan, template_dir, output_dir)
    module_dir = project_dir / "src" / plan.module_name

    # Render and write generated source files
    _write_file(module_dir / "api" / "models.py", render_parameter_models(plan))
    _write_file(module_dir / "client.py", render_client_module(plan))
    _write_file(module_dir / "api" / "tools.py", render_tools_module(plan))

    # Patch scaffolded wiring files
    _patch_file(module_dir / "api" / "mcp_builder.py", patch_mcp_builder, plan)
    _patch_file(module_dir / "api" / "app_builder.py", patch_app_builder, plan)

    # Write deployment manifests
    deploy_dir = project_dir / "deploy"
    deploy_dir.mkdir(exist_ok=True)
    for filename, content in render_manifests(plan).items():
        _write_file(deploy_dir / filename, content)

    logger.info("Generated project at %s", project_dir)
    return project_dir


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("Wrote %s", path)


def _patch_file(
    path: Path,
    patch_fn: Callable[[str, ServerPlan], str],
    plan: ServerPlan,
) -> None:
    """Read a file, apply a patch function, and write the result back."""
    source = path.read_text(encoding="utf-8")
    patched = patch_fn(source, plan)
    path.write_text(patched, encoding="utf-8")
    logger.debug("Patched %s", path)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_generate(args: argparse.Namespace) -> None:
    project_dir = run_pipeline(
        scope_yaml=args.scope_yaml,
        openapi_spec=args.openapi_spec,
        template_dir=args.template_dir,
        output_dir=args.output_dir,
    )
    print(project_dir)


def _cmd_analyze(args: argparse.Namespace) -> None:
    spec = load_openapi_spec(args.openapi_spec)
    analysis = analyze_spec(spec)
    print(analysis.model_dump_json(indent=2, by_alias=True))


class ValidationResult(BaseModel):
    """Typed output for the ``validate`` subcommand."""

    valid: bool
    server_name: str
    group_count: int
    tool_count: int
    auth_type: str
    errors: list[str] = []


def _cmd_validate(args: argparse.Namespace) -> None:
    scope = load_scope(args.scope_yaml)
    errors: list[str] = []

    # Cross-validate scope endpoints against the spec if --spec provided
    if hasattr(args, "openapi_spec") and args.openapi_spec is not None:
        spec = load_openapi_spec(args.openapi_spec)
        spec_paths = set(spec.paths or {})
        for group in scope.groups:
            for tool in group.tools:
                _method, path = parse_endpoint(tool.endpoint)
                if path not in spec_paths:
                    errors.append(
                        f"Tool '{tool.tool_name}': path '{path}' "
                        f"not found in spec (endpoint: {tool.endpoint})"
                    )

    result = ValidationResult(
        valid=len(errors) == 0,
        server_name=scope.server.name,
        group_count=len(scope.groups),
        tool_count=sum(len(g.tools) for g in scope.groups),
        auth_type=scope.auth.type,
        errors=errors,
    )
    print(result.model_dump_json(indent=2))
    if errors:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the mcp-builder CLI."""
    parser = argparse.ArgumentParser(
        prog="mcp-builder",
        description="Generate a ToolHive-ready MCP server from an OpenAPI spec.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- generate ---
    gen = subparsers.add_parser("generate", help="Run the codegen pipeline")
    gen.add_argument("scope_yaml", type=Path, help="Path to mcp-scope.yaml")
    gen.add_argument(
        "openapi_spec", type=Path, help="Path to the OpenAPI spec (YAML or JSON)"
    )
    gen.add_argument("template_dir", type=Path, help="Path to mcp-template-py checkout")
    gen.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory (default: current directory)",
    )
    gen.set_defaults(func=_cmd_generate)

    # --- analyze ---
    ana = subparsers.add_parser(
        "analyze", help="Analyze an OpenAPI spec and print structured JSON"
    )
    ana.add_argument(
        "openapi_spec", type=Path, help="Path to the OpenAPI spec (YAML or JSON)"
    )
    ana.set_defaults(func=_cmd_analyze)

    # --- validate ---
    val = subparsers.add_parser(
        "validate", help="Validate an mcp-scope.yaml and print typed JSON"
    )
    val.add_argument("scope_yaml", type=Path, help="Path to mcp-scope.yaml")
    val.add_argument(
        "--spec",
        dest="openapi_spec",
        type=Path,
        default=None,
        help="OpenAPI spec to cross-validate scope endpoints against",
    )
    val.set_defaults(func=_cmd_validate)

    return parser


def main() -> None:
    """CLI entry point for mcp-builder."""
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValidationError as exc:
        print(f"Validation error:\n{exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
