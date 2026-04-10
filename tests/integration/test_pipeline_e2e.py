"""End-to-end tests for the full code generation pipeline.

Runs the generator against all 7 integration fixture pairs (scope YAML +
OpenAPI spec) and validates the generated output structure, code validity,
tool registration, and deployment manifests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from .conftest import ALL_FIXTURES, FixtureConfig, pipeline_available, run_generator

_google_drive = next(c for c in ALL_FIXTURES if c.server_name == "google-drive")
requires_google_drive_pipeline = pytest.mark.skipif(
    not pipeline_available(_google_drive),
    reason="Codegen not installed or Google Drive OpenAPI spec not downloaded",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_names_from_scope(config: FixtureConfig) -> list[str]:
    """Load the scope YAML and return all tool names."""
    from mcp_builder.schema.models import load_scope

    from .conftest import INTEGRATION_FIXTURES

    scope = load_scope(INTEGRATION_FIXTURES / config.scope_yaml)
    return [t.tool_name for g in scope.groups for t in g.tools]


def _all_py_files(project_dir: Path) -> list[Path]:
    """Return all Python files in the generated project."""
    return list(project_dir.rglob("*.py"))


# ---------------------------------------------------------------------------
# Fixture: generate project once per config, shared across tests in a class
# ---------------------------------------------------------------------------

_AVAILABLE_FIXTURES = [c for c in ALL_FIXTURES if pipeline_available(c)]
_FIXTURE_IDS = [c.server_name for c in _AVAILABLE_FIXTURES]


@pytest.fixture(params=_AVAILABLE_FIXTURES, ids=_FIXTURE_IDS)
def generated_project(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[FixtureConfig, Path]:
    """Run the generator pipeline and return (config, project_dir).

    Fixtures whose OpenAPI spec hasn't been downloaded are automatically
    skipped. Run scripts/download_openapi_specs.sh to fetch them.
    """
    config: FixtureConfig = request.param
    project_dir = run_generator(config, tmp_path)
    return config, project_dir


# ---------------------------------------------------------------------------
# Common tests — parametrized across all 7 fixtures
# ---------------------------------------------------------------------------


class TestProjectStructure:
    """Verify the generated project has the expected directory layout."""

    def test_project_dir_exists(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        assert project_dir.exists()
        assert project_dir.name == f"{config.server_name}-mcp"

    def test_module_dir_exists(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        module_dir = project_dir / "src" / config.module_name
        assert module_dir.is_dir()

    def test_api_files_exist(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        api_dir = project_dir / "src" / config.module_name / "api"
        for filename in ("tools.py", "models.py", "mcp_builder.py", "app_builder.py"):
            assert (api_dir / filename).is_file(), f"Missing {filename}"

    def test_client_exists(self, generated_project: tuple[FixtureConfig, Path]) -> None:
        config, project_dir = generated_project
        assert (project_dir / "src" / config.module_name / "client.py").is_file()

    def test_deploy_dir_exists(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        assert (project_dir / "deploy").is_dir()

    def test_dockerfile_present(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        assert (project_dir / "Dockerfile").is_file()

    def test_pyproject_present(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        assert (project_dir / "pyproject.toml").is_file()


class TestCodeValidity:
    """Verify all generated Python files are syntactically valid."""

    def test_all_python_files_compile(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        py_files = _all_py_files(project_dir)
        assert len(py_files) > 0, "No Python files found"
        for py_file in py_files:
            content = py_file.read_text()
            try:
                compile(content, str(py_file), "exec")
            except SyntaxError as exc:
                pytest.fail(
                    f"Syntax error in {py_file.relative_to(project_dir)}: {exc}"
                )

    def test_no_template_references_remain(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        for py_file in _all_py_files(project_dir):
            content = py_file.read_text()
            assert "mcp_template_py" not in content, (
                f"Template reference in {py_file.relative_to(project_dir)}"
            )


class TestToolGeneration:
    """Verify tool functions match the YAML scope definition."""

    def test_tool_count_matches_yaml(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        tools_path = project_dir / "src" / config.module_name / "api" / "tools.py"
        content = tools_path.read_text()
        async_defs = re.findall(r"async def (\w+)\(", content)
        assert len(async_defs) == config.tool_count, (
            f"Expected {config.tool_count} tools, found {len(async_defs)}: {async_defs}"
        )

    def test_tool_names_match_yaml(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        tools_path = project_dir / "src" / config.module_name / "api" / "tools.py"
        content = tools_path.read_text()
        expected_names = _tool_names_from_scope(config)
        for name in expected_names:
            assert f"async def {name}(" in content, f"Missing tool method: {name}"

    def test_all_tools_registered_in_mcp_builder(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        mcp_builder_path = (
            project_dir / "src" / config.module_name / "api" / "mcp_builder.py"
        )
        content = mcp_builder_path.read_text()
        expected_names = _tool_names_from_scope(config)
        for name in expected_names:
            assert f"mcp.add_tool(tools.{name})" in content, (
                f"Tool {name} not registered in mcp_builder.py"
            )


class TestProjectConfig:
    """Verify pyproject.toml is correctly configured."""

    def test_server_name_in_pyproject(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        content = (project_dir / "pyproject.toml").read_text()
        assert f'name = "{config.server_name}-mcp"' in content

    def test_httpx_dependency(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        content = (project_dir / "pyproject.toml").read_text()
        assert "httpx" in content


class TestClientGeneration:
    """Verify the generated HTTP client."""

    def test_client_has_base_url(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        client_path = project_dir / "src" / config.module_name / "client.py"
        content = client_path.read_text()
        # All clients should reference the base URL from scope
        from mcp_builder.schema.models import load_scope

        from .conftest import INTEGRATION_FIXTURES

        scope = load_scope(INTEGRATION_FIXTURES / config.scope_yaml)
        assert scope.spec.base_url in content


class TestDeploymentManifests:
    """Verify deployment manifests match the auth configuration."""

    def test_mcpserver_yaml_exists(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        assert (project_dir / "deploy" / "mcpserver.yaml").is_file()

    def test_mcpserver_image_name(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = generated_project
        content = (project_dir / "deploy" / "mcpserver.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert manifest["spec"]["image"] == f"{config.server_name}-mcp:latest"

    def test_mcpserver_transport(
        self, generated_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = generated_project
        content = (project_dir / "deploy" / "mcpserver.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert manifest["spec"]["transport"] == "streamablehttp"


# ---------------------------------------------------------------------------
# Auth-specific manifest tests
# ---------------------------------------------------------------------------


OAUTH_FIXTURES = [
    c for c in ALL_FIXTURES if c.auth_type == "oauth_bearer" and pipeline_available(c)
]
OAUTH_IDS = [c.server_name for c in OAUTH_FIXTURES]


@pytest.fixture(params=OAUTH_FIXTURES, ids=OAUTH_IDS)
def oauth_project(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[FixtureConfig, Path]:
    config: FixtureConfig = request.param
    project_dir = run_generator(config, tmp_path)
    return config, project_dir


class TestOAuthManifests:
    """Verify OAuth bearer auth produces correct deployment manifests."""

    def test_auth_config_exists(
        self, oauth_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = oauth_project
        assert (project_dir / "deploy" / "mcpexternalauthconfig.yaml").is_file()

    def test_auth_config_type(self, oauth_project: tuple[FixtureConfig, Path]) -> None:
        _config, project_dir = oauth_project
        content = (project_dir / "deploy" / "mcpexternalauthconfig.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert manifest["spec"]["type"] == "embeddedAuthServer"

    def test_auth_config_issuer(
        self, oauth_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = oauth_project
        from mcp_builder.schema.models import load_scope

        from .conftest import INTEGRATION_FIXTURES

        scope = load_scope(INTEGRATION_FIXTURES / config.scope_yaml)
        assert scope.auth.oauth is not None
        content = (project_dir / "deploy" / "mcpexternalauthconfig.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert (
            manifest["spec"]["embeddedAuthServer"]["issuer"] == scope.auth.oauth.issuer
        )

    def test_auth_config_scopes(
        self, oauth_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = oauth_project
        from mcp_builder.schema.models import load_scope

        from .conftest import INTEGRATION_FIXTURES

        scope = load_scope(INTEGRATION_FIXTURES / config.scope_yaml)
        assert scope.auth.oauth is not None
        content = (project_dir / "deploy" / "mcpexternalauthconfig.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert manifest["spec"]["embeddedAuthServer"]["scopes"] == list(
            scope.auth.oauth.scopes
        )

    def test_secret_has_oauth_placeholders(
        self, oauth_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = oauth_project
        secret_path = project_dir / "deploy" / "secret.yaml"
        assert secret_path.is_file()
        manifest = yaml.safe_load(secret_path.read_text())
        assert manifest["stringData"]["client-id"] == "REPLACE_ME"
        assert manifest["stringData"]["client-secret"] == "REPLACE_ME"

    def test_mcpserver_references_auth_config(
        self, oauth_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = oauth_project
        content = (project_dir / "deploy" / "mcpserver.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert "externalAuthConfig" in manifest["spec"]
        assert (
            manifest["spec"]["externalAuthConfig"]["name"]
            == f"{config.server_name}-auth"
        )


_api_key_config = next(c for c in ALL_FIXTURES if c.auth_type == "api_key")


@pytest.mark.skipif(
    not pipeline_available(_api_key_config),
    reason="Codegen not installed or api_key spec not available",
)
class TestApiKeyManifests:
    """Verify api_key auth produces correct deployment manifests."""

    @pytest.fixture
    def api_key_project(self, tmp_path: Path) -> tuple[FixtureConfig, Path]:
        project_dir = run_generator(_api_key_config, tmp_path)
        return _api_key_config, project_dir

    def test_auth_config_type(
        self, api_key_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = api_key_project
        content = (project_dir / "deploy" / "mcpexternalauthconfig.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert manifest["spec"]["type"] == "bearerToken"

    def test_auth_config_secret_ref(
        self, api_key_project: tuple[FixtureConfig, Path]
    ) -> None:
        config, project_dir = api_key_project
        content = (project_dir / "deploy" / "mcpexternalauthconfig.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert (
            manifest["spec"]["bearerToken"]["secretRef"]["name"]
            == f"{config.server_name}-secret"
        )

    def test_secret_has_api_key_placeholder(
        self, api_key_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = api_key_project
        secret_path = project_dir / "deploy" / "secret.yaml"
        assert secret_path.is_file()
        manifest = yaml.safe_load(secret_path.read_text())
        assert manifest["stringData"]["api-key"] == "REPLACE_ME"


_no_auth_config = next(c for c in ALL_FIXTURES if c.auth_type == "none")


@pytest.mark.skipif(
    not pipeline_available(_no_auth_config),
    reason="Codegen not installed or no-auth spec not available",
)
class TestNoAuthManifests:
    """Verify auth type 'none' produces no auth config or secret."""

    @pytest.fixture
    def no_auth_project(self, tmp_path: Path) -> tuple[FixtureConfig, Path]:
        project_dir = run_generator(_no_auth_config, tmp_path)
        return _no_auth_config, project_dir

    def test_no_auth_config(self, no_auth_project: tuple[FixtureConfig, Path]) -> None:
        _config, project_dir = no_auth_project
        assert not (project_dir / "deploy" / "mcpexternalauthconfig.yaml").exists()

    def test_no_secret(self, no_auth_project: tuple[FixtureConfig, Path]) -> None:
        _config, project_dir = no_auth_project
        assert not (project_dir / "deploy" / "secret.yaml").exists()

    def test_mcpserver_no_auth_ref(
        self, no_auth_project: tuple[FixtureConfig, Path]
    ) -> None:
        _config, project_dir = no_auth_project
        content = (project_dir / "deploy" / "mcpserver.yaml").read_text()
        manifest = yaml.safe_load(content)
        assert "externalAuthConfig" not in manifest["spec"]


# ---------------------------------------------------------------------------
# Targeted tests
# ---------------------------------------------------------------------------


@requires_google_drive_pipeline
class TestParameterOverrides:
    """Verify YAML parameter overrides are applied in generated code."""

    def test_google_drive_file_id_description(self, tmp_path: Path) -> None:
        """The get_file tool should use the YAML description for fileId, not the spec default."""
        config = _google_drive
        project_dir = run_generator(config, tmp_path)
        tools_path = project_dir / "src" / config.module_name / "api" / "tools.py"
        content = tools_path.read_text()
        # YAML says: "The ID of the file to retrieve."
        assert "The ID of the file to retrieve." in content


@requires_google_drive_pipeline
class TestHintsNotInGeneratedCode:
    """Verify hints from the YAML are not present in generated Python code."""

    def test_no_hints_in_tools(self, tmp_path: Path) -> None:
        config = _google_drive
        project_dir = run_generator(config, tmp_path)
        tools_path = project_dir / "src" / config.module_name / "api" / "tools.py"
        content = tools_path.read_text()
        # Exact hint strings from the google_drive.yaml fixture should not appear
        assert "uses pageToken/nextPageToken cursor pattern" not in content
        assert "use fields param to limit returned data" not in content
        assert "consider field selection" not in content


@requires_google_drive_pipeline
class TestDeterminism:
    """Verify the generator produces identical output for identical inputs."""

    def test_pipeline_is_deterministic(self, tmp_path: Path) -> None:
        config = _google_drive

        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        project_a = run_generator(config, dir_a)
        project_b = run_generator(config, dir_b)

        files_a = sorted(
            p.relative_to(project_a) for p in project_a.rglob("*") if p.is_file()
        )
        files_b = sorted(
            p.relative_to(project_b) for p in project_b.rglob("*") if p.is_file()
        )

        assert files_a == files_b, "Generated file sets differ"

        for rel_path in files_a:
            content_a = (project_a / rel_path).read_bytes()
            content_b = (project_b / rel_path).read_bytes()
            assert content_a == content_b, f"File {rel_path} differs between runs"
