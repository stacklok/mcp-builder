"""E2E tests that generate MCP servers, start them, and verify tool registration over HTTP.

These tests use the real mcp-template-py template, install dependencies, start
the server, and talk MCP protocol over HTTP. They are slow (network + install +
startup) and meant to be run manually, not in CI.

Usage:
    # Run all fixtures (requires /Users/laurel/Documents/code/mcp-template-py):
    uv run pytest tests/e2e/test_server_startup.py -v -s

    # Run a single fixture:
    uv run pytest tests/e2e/test_server_startup.py -v -s -k google-drive

    # Keep generated projects for inspection (written to tests/e2e/output/):
    uv run pytest tests/e2e/test_server_startup.py -v -s --keep-generated

After a test passes, the output shows how to connect each server to Claude Code.
"""

from __future__ import annotations

import json
import shutil
import signal
import socket
import subprocess
import textwrap
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from mcp_builder.schema.models import load_scope

REAL_TEMPLATE = Path("/Users/laurel/Documents/code/mcp-template-py")
INTEGRATION_FIXTURES = Path(__file__).parent.parent / "integration" / "fixtures"
OPENAPI_FIXTURES = INTEGRATION_FIXTURES / "openapi"
E2E_OUTPUT = Path(__file__).parent / "output"


@dataclass(frozen=True)
class E2EFixture:
    scope_yaml: str
    openapi_yaml: str
    server_name: str
    module_name: str
    tool_count: int
    port: int


ALL_E2E = [
    E2EFixture(
        "google_drive.yaml",
        "google_drive_openapi.yaml",
        "google-drive",
        "google_drive_mcp",
        5,
        8201,
    ),
    E2EFixture("github.yaml", "github_openapi.yaml", "github", "github_mcp", 8, 8202),
    E2EFixture(
        "bamboohr.yaml", "bamboohr_openapi.yaml", "bamboohr", "bamboohr_mcp", 8, 8203
    ),
    E2EFixture(
        "jira.yaml", "jira_openapi.yaml", "jira-cloud", "jira_cloud_mcp", 7, 8204
    ),
    E2EFixture("slack.yaml", "slack_openapi.yaml", "slack", "slack_mcp", 7, 8205),
    E2EFixture(
        "weather_api.yaml",
        "weather_api_openapi.yaml",
        "weather-api",
        "weather_api_mcp",
        1,
        8206,
    ),
    E2EFixture(
        "minimal_api.yaml",
        "minimal_api_openapi.yaml",
        "minimal-api",
        "minimal_api_mcp",
        1,
        8207,
    ),
]

E2E_IDS = [f.server_name for f in ALL_E2E]


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_free(port):
            return
        time.sleep(0.3)
    raise TimeoutError(f"Server never started on port {port}")


def _generate_project(fixture: E2EFixture, output_dir: Path) -> Path:
    from mcp_builder.cli import run_pipeline

    return run_pipeline(
        scope_yaml=INTEGRATION_FIXTURES / fixture.scope_yaml,
        openapi_spec=OPENAPI_FIXTURES / fixture.openapi_yaml,
        template_dir=REAL_TEMPLATE,
        output_dir=output_dir,
    )


def _install_deps(project_dir: Path) -> None:
    # Remove stale venv/lockfile copied from template
    for stale in (".venv", "uv.lock"):
        p = project_dir / stale
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()

    subprocess.run(
        ["uv", "venv"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["uv", "sync"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )


def _start_server(project_dir: Path, fixture: E2EFixture) -> subprocess.Popen:
    env = {
        "PATH": subprocess.check_output(
            ["bash", "-c", "echo $PATH"], text=True
        ).strip(),
        "HOME": str(Path.home()),
        "REQUIRE_BEARER_TOKEN": "false",
        "MCP_PORT": str(fixture.port),
    }
    return subprocess.Popen(
        ["uv", "run", "python", "-m", fixture.module_name],
        cwd=project_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _mcp_request(
    port: int,
    method: str,
    params: dict | None = None,
    request_id: int = 1,
    session_id: str | None = None,
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }

    resp = httpx.post(
        f"http://127.0.0.1:{port}/mcp",
        json=body,
        headers=headers,
        timeout=10.0,
    )
    resp.raise_for_status()

    # Parse SSE response — find the data: line with JSON
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])

    raise ValueError(f"No SSE data in response: {resp.text}")


def _initialize(port: int) -> str:
    """Send initialize and return the session ID."""
    resp = httpx.post(
        f"http://127.0.0.1:{port}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "0.1"},
            },
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.headers["mcp-session-id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not REAL_TEMPLATE.exists(),
    reason=f"Real template not found at {REAL_TEMPLATE}",
)


@pytest.fixture(params=ALL_E2E, ids=E2E_IDS)
def running_server(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[tuple[E2EFixture, Path, list[dict]]]:
    """Generate, install, start a server, list tools, then tear down.

    Yields (fixture_config, project_dir, tools_list).
    """
    fixture: E2EFixture = request.param
    keep = request.config.getoption("--keep-generated", default=False)

    if keep:
        output_dir = E2E_OUTPUT
        output_dir.mkdir(exist_ok=True)
        project_dir = output_dir / f"{fixture.server_name}-mcp"
        if project_dir.exists():
            shutil.rmtree(project_dir)
    else:
        output_dir = tmp_path

    assert _port_free(fixture.port), f"Port {fixture.port} already in use"

    # Generate
    project_dir = _generate_project(fixture, output_dir)

    # Install
    _install_deps(project_dir)

    # Start server
    proc = _start_server(project_dir, fixture)
    try:
        _wait_for_port(fixture.port)

        # Initialize MCP session
        session_id = _initialize(fixture.port)

        # List tools
        data = _mcp_request(
            fixture.port, "tools/list", request_id=2, session_id=session_id
        )
        tools = data["result"]["tools"]

        yield fixture, project_dir, tools
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)


class TestServerStartup:
    """Verify generated servers start and register the correct tools."""

    def test_correct_tool_count(
        self, running_server: tuple[E2EFixture, Path, list[dict]]
    ) -> None:
        fixture, _project_dir, tools = running_server
        assert len(tools) == fixture.tool_count, (
            f"Expected {fixture.tool_count} tools, got {len(tools)}: "
            f"{[t['name'] for t in tools]}"
        )

    def test_tool_names_match_yaml(
        self, running_server: tuple[E2EFixture, Path, list[dict]]
    ) -> None:
        fixture, _project_dir, tools = running_server
        scope = load_scope(INTEGRATION_FIXTURES / fixture.scope_yaml)
        expected = {t.tool_name for g in scope.groups for t in g.tools}
        actual = {t["name"] for t in tools}
        assert actual == expected

    def test_tools_have_descriptions(
        self, running_server: tuple[E2EFixture, Path, list[dict]]
    ) -> None:
        _fixture, _project_dir, tools = running_server
        for tool in tools:
            assert tool.get("description"), f"Tool {tool['name']} has no description"

    def test_tools_have_input_schema(
        self, running_server: tuple[E2EFixture, Path, list[dict]]
    ) -> None:
        _fixture, _project_dir, tools = running_server
        for tool in tools:
            assert "inputSchema" in tool, f"Tool {tool['name']} has no inputSchema"
            assert tool["inputSchema"].get("type") == "object"


class TestClaudeConnection:
    """Print instructions for connecting each server to Claude Code."""

    def test_print_claude_config(
        self,
        running_server: tuple[E2EFixture, Path, list[dict]],
        request: pytest.FixtureRequest,
    ) -> None:
        fixture, project_dir, tools = running_server
        keep = request.config.getoption("--keep-generated", default=False)

        tool_names = [t["name"] for t in tools]

        print()  # noqa: T201
        print("=" * 70)  # noqa: T201
        print(f"  {fixture.server_name} MCP server — {len(tools)} tools")  # noqa: T201
        print(f"  Tools: {', '.join(tool_names)}")  # noqa: T201
        print("=" * 70)  # noqa: T201
        print()  # noqa: T201

        if keep:
            print(  # noqa: T201
                textwrap.dedent(f"""\
                To run this server standalone:

                    cd {project_dir}
                    REQUIRE_BEARER_TOKEN=false MCP_PORT={fixture.port} uv run python -m {fixture.module_name}

                To add to Claude Code (~/.claude/settings.json), add under "mcpServers":

                    "{fixture.server_name}": {{
                        "command": "uv",
                        "args": ["run", "--directory", "{project_dir}", "python", "-m", "{fixture.module_name}"],
                        "env": {{
                            "REQUIRE_BEARER_TOKEN": "false",
                            "MCP_PORT": "{fixture.port}"
                        }}
                    }}

                Or to connect to an already-running server (streamable HTTP):

                    "{fixture.server_name}": {{
                        "type": "streamablehttp",
                        "url": "http://localhost:{fixture.port}/mcp"
                    }}
                """)
            )
        else:
            print(  # noqa: T201
                "  (Run with --keep-generated to get persistent project paths)\n"
            )
