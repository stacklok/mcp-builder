"""CLI entrypoint for the MCP server generation pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for mcp-builder.

    Returns:
        Configured ArgumentParser with four required path arguments.
    """
    parser = argparse.ArgumentParser(
        prog="mcp-builder",
        description="Generate a ToolHive-ready MCP server from an OpenAPI spec.",
    )
    parser.add_argument(
        "--scope-yaml",
        required=True,
        help="Path to the mcp-scope.yaml file.",
    )
    parser.add_argument(
        "--openapi-spec",
        required=True,
        help="Path to the OpenAPI spec file.",
    )
    parser.add_argument(
        "--template-dir",
        required=True,
        help="Path to the mcp-template-py template directory.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Parent directory for the generated project.",
    )
    return parser


def run_pipeline(
    *,
    scope_yaml: str | Path,
    openapi_spec: str | Path,
    template_dir: str | Path,
    output_dir: str | Path,
) -> Path:
    """Run the full code generation pipeline.

    Args:
        scope_yaml: Path to the mcp-scope.yaml file.
        openapi_spec: Path to the OpenAPI spec file.
        template_dir: Path to the mcp-template-py template directory.
        output_dir: Parent directory where the generated project will be written.

    Returns:
        Path to the generated project directory.

    Raises:
        SystemExit: If any of the required input paths do not exist.
    """
    from mcp_builder.codegen.client import generate_client
    from mcp_builder.codegen.manifests import (
        generate_auth_config,
        generate_mcpserver,
        generate_secret,
    )
    from mcp_builder.codegen.models import generate_models_file
    from mcp_builder.codegen.scaffold import scaffold_project, server_name_to_module
    from mcp_builder.codegen.server_wiring import patch_app_builder, patch_mcp_builder
    from mcp_builder.codegen.spec_parser import load_openapi_spec
    from mcp_builder.codegen.tools import generate_tools
    from mcp_builder.schema.models import load_scope

    scope_yaml = Path(scope_yaml)
    openapi_spec = Path(openapi_spec)
    template_dir = Path(template_dir)
    output_dir = Path(output_dir)

    # Validate that required input paths exist.
    for path in (scope_yaml, openapi_spec, template_dir):
        if not path.exists():
            print(f"Error: '{path}' does not exist", file=sys.stderr)
            raise SystemExit(f"'{path}' does not exist")

    scope = load_scope(scope_yaml)
    spec = load_openapi_spec(openapi_spec)
    module_name = server_name_to_module(scope.server.name)

    # Step 1: Scaffold project from template.
    project_dir = scaffold_project(scope, template_dir, output_dir)
    module_dir = project_dir / "src" / module_name

    # Step 2: Generate models.py.
    models_content = generate_models_file(scope, spec, openapi_spec, project_dir)
    (module_dir / "api" / "models.py").write_text(models_content)

    # Step 3: Generate client.py.
    client_content = generate_client(scope, module_name)
    (module_dir / "client.py").write_text(client_content)

    # Step 4: Generate tools.py.
    tools_content = generate_tools(scope, spec, module_name)
    (module_dir / "api" / "tools.py").write_text(tools_content)

    # Step 5: Patch mcp_builder.py.
    mcp_builder_path = module_dir / "api" / "mcp_builder.py"
    mcp_builder_content = mcp_builder_path.read_text()
    mcp_builder_content = patch_mcp_builder(mcp_builder_content, scope, module_name)
    mcp_builder_path.write_text(mcp_builder_content)

    # Step 6: Patch app_builder.py.
    app_builder_path = module_dir / "api" / "app_builder.py"
    app_builder_content = app_builder_path.read_text()
    app_builder_content = patch_app_builder(app_builder_content, module_name)
    app_builder_path.write_text(app_builder_content)

    # Step 7: Write deployment manifests.
    deploy_dir = project_dir / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "mcpserver.yaml").write_text(generate_mcpserver(scope))

    # Step 8: Optionally write auth config manifest.
    auth_config = generate_auth_config(scope)
    if auth_config is not None:
        (deploy_dir / "mcpexternalauthconfig.yaml").write_text(auth_config)

    # Step 9: Optionally write secret manifest.
    secret = generate_secret(scope)
    if secret is not None:
        (deploy_dir / "secret.yaml").write_text(secret)

    return project_dir


def main() -> None:
    """Parse CLI args and run the generation pipeline."""
    parser = build_parser()
    args = parser.parse_args()
    project_dir = run_pipeline(
        scope_yaml=args.scope_yaml,
        openapi_spec=args.openapi_spec,
        template_dir=args.template_dir,
        output_dir=args.output_dir,
    )
    print(f"Generated project: {project_dir}")
