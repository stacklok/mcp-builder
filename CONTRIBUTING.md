# Contributing to mcp-builder

Thanks for your interest! `mcp-builder` is a pipeline that turns an OpenAPI
spec into a ToolHive-ready MCP server. Contributions range from generator and
CLI improvements to the AI scoping/validation skills and docs.

## Development setup

```bash
# Prerequisites: Python 3.13+, uv, and Task (see README for install links)
task install
uv run mcp-builder --help
```

The AI skills and agents live in `skills/` and `agents/`; see the README for
how to symlink them into Claude Code or Gemini CLI.

## Before opening a PR

Run the full check suite locally. It mirrors CI:

```bash
task check      # lint + format + typecheck + test + security
```

Individual tasks (`task lint`, `task typecheck`, `task test`, ...) are listed
in `README.md` and the `Taskfile.yml`. All of them must pass before CI will.

## PR conventions

- **Title format:** [Conventional Commits](https://www.conventionalcommits.org/). Examples:
  - `feat(scope): detect query-parameter API keys`
  - `fix(generate): handle empty response schemas`
  - `docs: clarify the Phase 3 generate step`
  - `chore: bump dependencies`
- **Scope:** keep PRs focused. Smaller PRs review faster.
- **Tests:** unit tests in `tests/unit/` (mock external dependencies), integration
  tests in `tests/integration/` (no mocking; skipped when required config is absent).

## Developer Certificate of Origin (DCO)

All commits must be signed off, certifying that you have the right to submit the
contribution:

```bash
git commit -s -m "your message"
```

The `-s` flag appends a `Signed-off-by` trailer. See the
[DCO](https://developercertificate.org/) for the full text.

## Reporting issues

- **Bugs / feature requests:** open an issue.
- **Security vulnerabilities:** see [SECURITY.md](SECURITY.md) — do not file a public issue.

## Code of Conduct

By participating in this project, you agree to abide by the
[Stacklok Code of Conduct](https://github.com/stacklok/.github/blob/main/CODE_OF_CONDUCT.md).
