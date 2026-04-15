"""Tests for the scaffold renderer."""

from pathlib import Path

import pytest

from mcp_builder.codegen.plan import AuthPlan, ServerPlan, ToolPlan
from mcp_builder.codegen.renderers.scaffold import scaffold_project

from .conftest import TEMPLATE_DIR


@pytest.fixture()
def scaffolded(plan: ServerPlan, tmp_path: Path) -> Path:
    return scaffold_project(plan, TEMPLATE_DIR, tmp_path)


class TestScaffoldProject:
    def test_creates_project_dir(self, scaffolded: Path) -> None:
        assert scaffolded.exists()
        assert scaffolded.name == "test-api-mcp"

    def test_renames_module(self, scaffolded: Path) -> None:
        assert (scaffolded / "src" / "test_api_mcp").is_dir()
        assert not (scaffolded / "src" / "mcp_template_py").exists()

    def test_updates_imports(self, scaffolded: Path) -> None:
        for py_file in scaffolded.rglob("*.py"):
            text = py_file.read_text()
            assert "mcp_template_py" not in text, (
                f"{py_file.relative_to(scaffolded)} still contains mcp_template_py"
            )

    def test_module_imports_use_new_name(self, scaffolded: Path) -> None:
        tools_py = scaffolded / "src" / "test_api_mcp" / "api" / "tools.py"
        text = tools_py.read_text()
        assert "from test_api_mcp.api.models import" in text

    def test_updates_pyproject_name(self, scaffolded: Path) -> None:
        text = (scaffolded / "pyproject.toml").read_text()
        assert 'name = "test-api-mcp"' in text
        assert 'name = "mcp-template-py"' not in text

    def test_updates_pyproject_description(self, scaffolded: Path) -> None:
        text = (scaffolded / "pyproject.toml").read_text()
        assert 'description = "A test API server."' in text

    def test_adds_httpx_dependency(self, scaffolded: Path) -> None:
        text = (scaffolded / "pyproject.toml").read_text()
        assert "httpx" in text

    def test_returns_project_path(self, plan: ServerPlan, tmp_path: Path) -> None:
        result = scaffold_project(plan, TEMPLATE_DIR, tmp_path)
        assert result == tmp_path / "test-api-mcp"

    def test_preserves_dockerfile(self, scaffolded: Path) -> None:
        assert (scaffolded / "Dockerfile").is_file()

    def test_preserves_auth_module(self, scaffolded: Path) -> None:
        auth_init = scaffolded / "src" / "test_api_mcp" / "auth" / "__init__.py"
        text = auth_init.read_text()
        assert "get_bearer_token" in text
        assert "test_api_mcp.auth" in text

    def test_updates_dockerfile_module(self, scaffolded: Path) -> None:
        text = (scaffolded / "Dockerfile").read_text()
        assert "mcp_template_py" not in text
        assert "test_api_mcp" in text

    def test_missing_template_module_raises(self, tmp_path: Path) -> None:
        plan = ServerPlan(
            module_name="test_api_mcp",
            server_name="test-api",
            description="A test API server.",
            base_url="https://api.example.com",
            auth=AuthPlan(type="api_key"),
            tools=[],
            groups=[],
        )
        # Create a template dir without the expected src/mcp_template_py/.
        bad_template = tmp_path / "bad_template"
        bad_template.mkdir()
        (bad_template / "src").mkdir()
        (bad_template / "pyproject.toml").write_text('name = "mcp-template-py"')
        output = tmp_path / "output"
        output.mkdir()
        with pytest.raises(FileNotFoundError, match="missing expected module"):
            scaffold_project(plan, bad_template, output)

    def test_description_with_quotes(self, tmp_path: Path) -> None:
        plan = ServerPlan(
            module_name="test_api_mcp",
            server_name="test-api",
            description='A server for "widgets" and stuff.',
            base_url="https://api.example.com",
            auth=AuthPlan(type="api_key"),
            tools=[],
            groups=[],
        )
        project = scaffold_project(plan, TEMPLATE_DIR, tmp_path)
        text = (project / "pyproject.toml").read_text()
        assert 'description = "A server for \\"widgets\\" and stuff."' in text

    def test_output_dir_already_exists_raises(
        self, plan: ServerPlan, tmp_path: Path
    ) -> None:
        (tmp_path / "test-api-mcp").mkdir()
        with pytest.raises(FileExistsError, match="already exists"):
            scaffold_project(plan, TEMPLATE_DIR, tmp_path)

    def test_updates_pyproject_cov_target(self, scaffolded: Path) -> None:
        text = (scaffolded / "pyproject.toml").read_text()
        assert "--cov=test_api_mcp" in text
        assert "mcp_template_py" not in text

    def test_updates_taskfile_run_target(self, scaffolded: Path) -> None:
        text = (scaffolded / "Taskfile.yml").read_text()
        assert "test_api_mcp" in text
        assert "mcp_template_py" not in text

    def test_updates_claude_md(self, scaffolded: Path) -> None:
        text = (scaffolded / "CLAUDE.md").read_text()
        assert "test_api_mcp" in text
        assert "mcp_template_py" not in text

    def test_updates_integration_test_with_tool_names(self, tmp_path: Path) -> None:
        plan = ServerPlan(
            module_name="google_drive_mcp",
            server_name="google-drive",
            description="Google Drive MCP server.",
            base_url="https://www.googleapis.com",
            auth=AuthPlan(type="api_key"),
            tools=[
                ToolPlan(
                    tool_name="list_files",
                    class_name="ListFiles",
                    http_method="GET",
                    path="/files",
                    description="List files.",
                    path_params=[],
                    query_params=[],
                    body_fields=[],
                    hints=[],
                    group_name="files",
                ),
                ToolPlan(
                    tool_name="get_file",
                    class_name="GetFile",
                    http_method="GET",
                    path="/files/{fileId}",
                    description="Get a file.",
                    path_params=[],
                    query_params=[],
                    body_fields=[],
                    hints=[],
                    group_name="files",
                ),
            ],
            groups=[],
        )
        project = scaffold_project(plan, TEMPLATE_DIR, tmp_path)
        text = (project / "tests" / "integration" / "test_mcp.py").read_text()
        assert "hello" not in text
        assert "list_files" in text
        assert "get_file" in text
        assert "call_tool" not in text

    def test_empty_tools_produces_agnostic_integration_test(
        self, plan: ServerPlan, tmp_path: Path
    ) -> None:
        """With no tools in plan, the integration test should still be
        rewritten to remove the template 'hello' reference."""
        project = scaffold_project(plan, TEMPLATE_DIR, tmp_path)
        text = (project / "tests" / "integration" / "test_mcp.py").read_text()
        assert "hello" not in text
        assert "call_tool" not in text
        assert "EXPECTED_TOOLS" not in text
        # Should still have the connection and list_tools tests.
        assert "test_mcp_client_connection" in text
        assert "test_mcp_client_list_tools" in text

    def test_no_template_leftovers_in_any_file(self, scaffolded: Path) -> None:
        """Verify mcp_template_py does not appear in any text file."""
        for path in scaffolded.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            assert "mcp_template_py" not in text, (
                f"{path.relative_to(scaffolded)} still contains mcp_template_py"
            )
