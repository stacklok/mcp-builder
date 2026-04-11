"""Conftest for e2e tests — registers custom CLI options and auto-downloads specs."""

import subprocess
from pathlib import Path

DOWNLOAD_SCRIPT = Path(__file__).parent / "download_openapi_specs.sh"


def pytest_addoption(parser):
    parser.addoption(
        "--keep-generated",
        action="store_true",
        default=False,
        help="Keep generated projects in e2e/output/ after test run",
    )


def pytest_configure(config):
    """Download real OpenAPI specs if any are missing."""
    real_dir = Path(__file__).parent / "fixtures" / "real"
    scope_yamls = list(real_dir.glob("*.yaml"))
    # Check if any scope YAML is missing its companion OpenAPI spec
    needs_download = any(
        not _find_openapi_spec(real_dir, scope.stem) for scope in scope_yamls
    )
    if needs_download and DOWNLOAD_SCRIPT.exists():
        subprocess.run(
            ["bash", str(DOWNLOAD_SCRIPT)],
            check=False,
            capture_output=True,
        )


def _find_openapi_spec(directory: Path, stem: str) -> bool:
    """Check if an OpenAPI spec exists for a given scope YAML stem."""
    return (directory / f"{stem}_openapi.yaml").exists() or (
        directory / f"{stem}_openapi.json"
    ).exists()
