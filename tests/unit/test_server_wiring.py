"""Unit tests for server_wiring patch functions."""

from __future__ import annotations

from pathlib import Path


from mcp_builder.codegen.server_wiring import patch_app_builder, patch_mcp_builder
from mcp_builder.schema.models import MCPScope


# ---------------------------------------------------------------------------
# patch_mcp_builder
# ---------------------------------------------------------------------------


def test_patch_mcp_builder_adds_client_import(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert "from test_api_mcp.client import APIClient" in patched


def test_patch_mcp_builder_fixes_server_name(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert 'FastMCP("test-api"' in patched
    assert "mcp-template-py" not in patched


def test_patch_mcp_builder_adds_client_param(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert "client: APIClient" in patched


def test_patch_mcp_builder_passes_client_to_tools(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert "Tools(client)" in patched
    assert "Tools()" not in patched


def test_patch_mcp_builder_registers_generated_tools(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert "mcp.add_tool(tools.get_item)" in patched
    assert "mcp.add_tool(tools.create_item)" in patched
    assert "tools.hello" not in patched


def test_patch_mcp_builder_multi_group(
    scope_multi_group: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_multi_group, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_multi_group, "test_api_mcp")
    assert "mcp.add_tool(tools.get_item)" in patched
    assert "mcp.add_tool(tools.create_item)" in patched
    assert "tools.hello" not in patched


def test_patch_mcp_builder_produces_valid_python(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    patched = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    compile(patched, "<test>", "exec")


def test_patch_mcp_builder_deterministic(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    mcp_builder_path = project / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
    original = mcp_builder_path.read_text()
    first = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    second = patch_mcp_builder(original, scope_with_tools, "test_api_mcp")
    assert first == second


# ---------------------------------------------------------------------------
# patch_app_builder
# ---------------------------------------------------------------------------


def test_patch_app_builder_adds_client_import(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    patched = patch_app_builder(original, "test_api_mcp")
    assert "from test_api_mcp.client import APIClient" in patched


def test_patch_app_builder_creates_client(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    patched = patch_app_builder(original, "test_api_mcp")
    assert "client = APIClient()" in patched


def test_patch_app_builder_passes_client_to_build_mcp(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    patched = patch_app_builder(original, "test_api_mcp")
    assert "build_mcp(settings, client)" in patched


def test_patch_app_builder_closes_client(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    patched = patch_app_builder(original, "test_api_mcp")
    assert "await client.close()" in patched


def test_patch_app_builder_produces_valid_python(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    patched = patch_app_builder(original, "test_api_mcp")
    compile(patched, "<test>", "exec")


def test_patch_app_builder_deterministic(
    scope_with_tools: MCPScope, template_dir: Path, tmp_path: Path
) -> None:
    from mcp_builder.codegen.scaffold import scaffold_project

    project = scaffold_project(scope_with_tools, template_dir, tmp_path)
    app_builder_path = project / "src" / "test_api_mcp" / "api" / "app_builder.py"
    original = app_builder_path.read_text()
    first = patch_app_builder(original, "test_api_mcp")
    second = patch_app_builder(original, "test_api_mcp")
    assert first == second
