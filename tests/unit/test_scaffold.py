"""Tests for project scaffolding."""

from pathlib import Path

from mcp_builder.codegen.scaffold import scaffold_project, server_name_to_module
from mcp_builder.schema.models import MCPScope


def test_server_name_to_module_simple() -> None:
    assert server_name_to_module("google-drive") == "google_drive_mcp"


def test_server_name_to_module_no_hyphens() -> None:
    assert server_name_to_module("slack") == "slack_mcp"


def test_server_name_to_module_multiple_hyphens() -> None:
    assert server_name_to_module("my-cool-api") == "my_cool_api_mcp"


def test_scaffold_creates_project_dir(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    assert result == tmp_path / "test-api-mcp"
    assert result.is_dir()


def test_scaffold_renames_module(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    assert (result / "src" / "test_api_mcp").is_dir()
    assert not (result / "src" / "mcp_template_py").exists()


def test_scaffold_module_has_expected_files(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    module = result / "src" / "test_api_mcp"
    assert (module / "__init__.py").exists()
    assert (module / "__main__.py").exists()
    assert (module / "settings.py").exists()
    assert (module / "api" / "app_builder.py").exists()
    assert (module / "auth" / "__init__.py").exists()


def test_scaffold_updates_imports(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    for py_file in result.rglob("*.py"):
        content = py_file.read_text()
        assert "mcp_template_py" not in content, f"Old import in {py_file.name}"


def test_scaffold_new_imports_present(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    main = (result / "src" / "test_api_mcp" / "__main__.py").read_text()
    assert "test_api_mcp" in main


def test_scaffold_updates_pyproject_name(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    content = (result / "pyproject.toml").read_text()
    assert 'name = "test-api-mcp"' in content


def test_scaffold_updates_pyproject_description(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    content = (result / "pyproject.toml").read_text()
    assert 'description = "Test API MCP server"' in content


def test_scaffold_adds_httpx_dependency(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    content = (result / "pyproject.toml").read_text()
    assert "httpx" in content


def test_scaffold_preserves_non_python_files(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    result = scaffold_project(minimal_scope, template_dir, tmp_path)
    original = (template_dir / "Dockerfile").read_text()
    generated = (result / "Dockerfile").read_text()
    assert generated == original


def test_scaffold_deterministic(
    minimal_scope: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    out1.mkdir()
    out2.mkdir()
    r1 = scaffold_project(minimal_scope, template_dir, out1)
    r2 = scaffold_project(minimal_scope, template_dir, out2)
    for f1 in sorted(r1.rglob("*")):
        if f1.is_file():
            f2 = r2 / f1.relative_to(r1)
            assert f1.read_bytes() == f2.read_bytes(), f"Mismatch: {f1.name}"
