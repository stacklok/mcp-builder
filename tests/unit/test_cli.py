"""Unit tests for the CLI entrypoint and pipeline orchestration."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
import yaml

from mcp_builder.cli import build_parser, run_pipeline
from mcp_builder.schema.models import MCPScope


def test_parser_requires_scope_yaml() -> None:
    """Parser exits with error when no arguments are provided."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_all_args() -> None:
    """Parser correctly parses all four required arguments."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "--scope-yaml",
            "scope.yaml",
            "--openapi-spec",
            "api.yaml",
            "--template-dir",
            "/tmp/template",
            "--output-dir",
            "/tmp/output",
        ]
    )
    assert args.scope_yaml == "scope.yaml"
    assert args.openapi_spec == "api.yaml"
    assert args.template_dir == "/tmp/template"
    assert args.output_dir == "/tmp/output"


def test_run_pipeline_validates_missing_scope(tmp_path: Path) -> None:
    """run_pipeline exits with error when the scope YAML file does not exist."""
    with pytest.raises(SystemExit, match="does not exist"):
        run_pipeline(
            scope_yaml=tmp_path / "nonexistent.yaml",
            openapi_spec=tmp_path / "api.yaml",
            template_dir=tmp_path / "template",
            output_dir=tmp_path / "output",
        )


def test_run_pipeline_produces_output(
    tmp_path: Path,
    scope_with_tools: MCPScope,
    openapi_spec_path: Path,
    template_dir: Path,
) -> None:
    """run_pipeline generates a project directory with all key files."""
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(yaml.dump(scope_with_tools.model_dump()))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    project_dir = run_pipeline(
        scope_yaml=scope_file,
        openapi_spec=openapi_spec_path,
        template_dir=template_dir,
        output_dir=output_dir,
    )

    assert project_dir.exists()

    module_name = "test_api_mcp"
    module_dir = project_dir / "src" / module_name

    assert (module_dir / "api" / "tools.py").exists()
    assert (module_dir / "api" / "mcp_builder.py").exists()
    assert (module_dir / "api" / "app_builder.py").exists()
    assert (module_dir / "api" / "models.py").exists()
    assert (module_dir / "client.py").exists()


def test_run_pipeline_tools_content(
    tmp_path: Path,
    scope_with_tools: MCPScope,
    openapi_spec_path: Path,
    template_dir: Path,
) -> None:
    """Generated tools.py contains async def declarations for each tool."""
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(yaml.dump(scope_with_tools.model_dump()))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    project_dir = run_pipeline(
        scope_yaml=scope_file,
        openapi_spec=openapi_spec_path,
        template_dir=template_dir,
        output_dir=output_dir,
    )

    tools_py = project_dir / "src" / "test_api_mcp" / "api" / "tools.py"
    content = tools_py.read_text()

    assert "async def get_item" in content
    assert "async def create_item" in content


def test_run_pipeline_deploys_for_no_auth(
    tmp_path: Path,
    scope_with_tools: MCPScope,
    openapi_spec_path: Path,
    template_dir: Path,
) -> None:
    """For auth.type='none', only mcpserver.yaml is written to deploy/."""
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(yaml.dump(scope_with_tools.model_dump()))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    project_dir = run_pipeline(
        scope_yaml=scope_file,
        openapi_spec=openapi_spec_path,
        template_dir=template_dir,
        output_dir=output_dir,
    )

    deploy_dir = project_dir / "deploy"
    assert (deploy_dir / "mcpserver.yaml").exists()
    assert not (deploy_dir / "mcpexternalauthconfig.yaml").exists()
    assert not (deploy_dir / "secret.yaml").exists()


def test_run_pipeline_deterministic(
    tmp_path: Path,
    scope_with_tools: MCPScope,
    openapi_spec_path: Path,
    template_dir: Path,
) -> None:
    """Running the pipeline twice produces byte-for-byte identical output."""
    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(yaml.dump(scope_with_tools.model_dump()))

    output_a = tmp_path / "output_a"
    output_a.mkdir()
    output_b = tmp_path / "output_b"
    output_b.mkdir()

    project_a = run_pipeline(
        scope_yaml=scope_file,
        openapi_spec=openapi_spec_path,
        template_dir=template_dir,
        output_dir=output_a,
    )
    project_b = run_pipeline(
        scope_yaml=scope_file,
        openapi_spec=openapi_spec_path,
        template_dir=template_dir,
        output_dir=output_b,
    )

    # Collect relative paths from both projects and compare each file.
    files_a = {p.relative_to(project_a) for p in project_a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(project_b) for p in project_b.rglob("*") if p.is_file()}

    assert files_a == files_b, (
        f"File sets differ: {files_a.symmetric_difference(files_b)}"
    )

    for rel_path in sorted(files_a):
        file_a = project_a / rel_path
        file_b = project_b / rel_path
        assert filecmp.cmp(file_a, file_b, shallow=False), (
            f"File content differs: {rel_path}"
        )
