"""Conftest for e2e tests — registers custom CLI options."""


def pytest_addoption(parser):
    parser.addoption(
        "--keep-generated",
        action="store_true",
        default=False,
        help="Keep generated projects in e2e/output/ after test run",
    )
