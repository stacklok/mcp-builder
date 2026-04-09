## Project

A pipeline for generating ToolHive-ready MCP servers from OpenAPI specs.

## Technical considerations
- Use uv as package manager. `uv add <package>` for adding a package. `uv add <package> --dev` for development packages for linting and testing.
- Use the Taskfile for running linting and formatting:
    - `task format` for running formatters
    - `task lint` for running linters
    - `task typecheck` for running typecheckers
    - `task test` for running tests
    - `task security` for running security checks
    - `task check` for running all checks
- Use `pydantic` for validating structured data.
- pyproject.toml should be the central place for configuring the project, i.e. linters, typecheckers, testing, etc.
- Always prefer native Python types over custom types, e.g. use `list` instead of `List`, `dict` instead of `Dict`.
- Prefer `uv run python -c "import this"` over `python -c "import this"` to ensure the correct environment is used.

## Code Structure
- The main module is located in `src/mcp_builder/`.
- Unit tests live in `tests/unit/`.
- Integration tests live in `tests/integration/`.

## Implementation guidelines

### Product code
- Use pydantic models for type safety, especially at API boundaries.
- Elicit feedback or confirmation when deciding to use a new framework or library.

### Test code
- Use pytest style tests, leveraging pytest-asyncio when appropriate.
- Unit tests should be in `tests/unit/` and should mock external dependencies.
- Integration tests should be in `tests/integration/` and should avoid mocking external dependencies. They can be skipped if requirements like configuration (e.g. API keys) are missing.
