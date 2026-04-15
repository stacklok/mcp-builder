"""Integration tests for the CLI orchestrator (run_pipeline).

These tests exercise the full pipeline end-to-end: load scope + spec,
build plan, scaffold project, render source, patch wiring, write manifests.
They hit the filesystem (copy template, write generated files) so they
live in tests/integration/ rather than tests/unit/.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mcp_builder.cli import run_pipeline

UNIT_FIXTURES = Path(__file__).parent.parent / "unit" / "fixtures"
TEMPLATE_DIR = UNIT_FIXTURES / "template"
SCOPE_YAML = UNIT_FIXTURES / "test_scope.yaml"
SCOPE_OAUTH = UNIT_FIXTURES / "test_scope_oauth.yaml"
OPENAPI_SPEC = UNIT_FIXTURES / "test_openapi.yaml"


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Run the pipeline with the api_key test fixtures and return the project dir."""
    return run_pipeline(SCOPE_YAML, OPENAPI_SPEC, TEMPLATE_DIR, tmp_path)


class TestRunPipeline:
    def test_returns_existing_path(self, project_dir: Path) -> None:
        assert project_dir.exists()

    def test_project_dir_name(self, project_dir: Path) -> None:
        assert project_dir.name == "test-api-mcp"

    def test_creates_module_dir(self, project_dir: Path) -> None:
        assert (project_dir / "src" / "test_api_mcp").is_dir()

    def test_writes_client(self, project_dir: Path) -> None:
        client = project_dir / "src" / "test_api_mcp" / "client.py"
        assert client.exists()
        assert "APIClient" in client.read_text()

    def test_writes_tools(self, project_dir: Path) -> None:
        tools = project_dir / "src" / "test_api_mcp" / "api" / "tools.py"
        assert tools.exists()
        assert "class Tools" in tools.read_text()

    def test_writes_models(self, project_dir: Path) -> None:
        models = project_dir / "src" / "test_api_mcp" / "api" / "models.py"
        assert models.exists()

    def test_patches_mcp_builder(self, project_dir: Path) -> None:
        mcp_builder = project_dir / "src" / "test_api_mcp" / "api" / "mcp_builder.py"
        content = mcp_builder.read_text()
        assert "APIClient" in content
        assert "get_item" in content

    def test_creates_deploy_dir(self, project_dir: Path) -> None:
        assert (project_dir / "deploy").is_dir()

    def test_creates_mcpserver_yaml(self, project_dir: Path) -> None:
        mcpserver = project_dir / "deploy" / "mcpserver.yaml"
        assert mcpserver.exists()
        doc = yaml.safe_load(mcpserver.read_text())
        assert doc["kind"] == "MCPServer"
        assert doc["metadata"]["name"] == "test-api"

    def test_creates_auth_config_for_api_key(self, project_dir: Path) -> None:
        auth_config = project_dir / "deploy" / "mcpexternalauthconfig.yaml"
        assert auth_config.exists()
        doc = yaml.safe_load(auth_config.read_text())
        assert doc["spec"]["type"] == "bearerToken"

    def test_creates_secret_for_api_key(self, project_dir: Path) -> None:
        secret = project_dir / "deploy" / "secret.yaml"
        assert secret.exists()
        doc = yaml.safe_load(secret.read_text())
        assert doc["stringData"]["token"] == "REPLACE_ME"

    def test_creates_ingress_yaml(self, project_dir: Path) -> None:
        ingress = project_dir / "deploy" / "ingress.yaml"
        assert ingress.exists()
        doc = yaml.safe_load(ingress.read_text())
        assert doc["kind"] == "Ingress"
        assert doc["metadata"]["name"] == "test-api-ingress"


class TestRunPipelineOAuth:
    def test_creates_oauth_auth_config(self, tmp_path: Path) -> None:
        project_dir = run_pipeline(SCOPE_OAUTH, OPENAPI_SPEC, TEMPLATE_DIR, tmp_path)
        auth_config = project_dir / "deploy" / "mcpexternalauthconfig.yaml"
        doc = yaml.safe_load(auth_config.read_text())
        assert doc["spec"]["type"] == "embeddedAuthServer"
        providers = doc["spec"]["embeddedAuthServer"]["upstreamProviders"]
        assert len(providers) == 1
        assert providers[0]["oidcConfig"]["issuerUrl"] == "https://accounts.google.com"

    def test_no_secret_for_oauth(self, tmp_path: Path) -> None:
        project_dir = run_pipeline(SCOPE_OAUTH, OPENAPI_SPEC, TEMPLATE_DIR, tmp_path)
        secret = project_dir / "deploy" / "secret.yaml"
        assert not secret.exists()


class TestRunPipelineNoAuth:
    def test_no_auth_manifests_when_none(self, tmp_path: Path) -> None:
        # Create a temporary scope with auth.type=none
        scope_content = SCOPE_YAML.read_text().replace(
            "auth:\n  type: api_key", "auth:\n  type: none"
        )
        scope_path = tmp_path / "scope_none.yaml"
        scope_path.write_text(scope_content)

        project_dir = run_pipeline(scope_path, OPENAPI_SPEC, TEMPLATE_DIR, tmp_path)
        deploy = project_dir / "deploy"
        assert (deploy / "mcpserver.yaml").exists()
        assert not (deploy / "mcpexternalauthconfig.yaml").exists()
        assert not (deploy / "secret.yaml").exists()


class TestRunPipelineErrors:
    def test_missing_scope_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_pipeline(
                tmp_path / "nonexistent.yaml", OPENAPI_SPEC, TEMPLATE_DIR, tmp_path
            )

    def test_missing_spec_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_pipeline(
                SCOPE_YAML, tmp_path / "nonexistent.yaml", TEMPLATE_DIR, tmp_path
            )
