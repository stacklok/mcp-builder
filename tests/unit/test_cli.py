"""Tests for cli.py — argument parsing and subcommand dispatch."""

import json

import pytest
import structlog.testing

from mcp_builder.cli import build_parser


class TestBuildParser:
    def test_generate_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(
            ["generate", "scope.yaml", "spec.yaml", "/tmp/template"]
        )
        assert args.command == "generate"
        assert hasattr(args, "func")

    def test_generate_with_output_dir(self):
        parser = build_parser()
        args = parser.parse_args(
            ["generate", "scope.yaml", "spec.yaml", "/tmp/template", "-o", "/out"]
        )
        assert str(args.output_dir) == "/out"

    def test_analyze_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["analyze", "spec.yaml"])
        assert args.command == "analyze"
        assert hasattr(args, "func")

    def test_validate_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["validate", "scope.yaml"])
        assert args.command == "validate"
        assert hasattr(args, "func")

    def test_validate_with_spec_flag(self):
        parser = build_parser()
        args = parser.parse_args(
            ["validate", "scope.yaml", "--openapi-spec", "spec.yaml"]
        )
        assert args.command == "validate"
        assert str(args.openapi_spec) == "spec.yaml"

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-v", "analyze", "spec.yaml"])
        assert args.verbose is True

    def test_no_subcommand_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestCmdAnalyze:
    def test_analyze_prints_json(self, tmp_path, capsys):
        import yaml

        from mcp_builder.cli import _cmd_analyze

        raw = {
            "openapi": "3.0.3",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.test.com"}],
            "paths": {
                "/ping": {
                    "get": {
                        "operationId": "ping",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(yaml.dump(raw))

        parser = build_parser()
        args = parser.parse_args(["analyze", str(spec_file)])
        with structlog.testing.capture_logs():
            _cmd_analyze(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["spec_version"] == "3.0.3"
        assert data["base_url"] == "https://api.test.com"
        assert len(data["endpoints"]) == 1
        assert data["endpoints"][0]["method"] == "GET"
        assert data["endpoints"][0]["request_body"] is None
        assert data["security_schemes"] == {}

    def test_analyze_parameter_aliases(self, tmp_path, capsys):
        """JSON output uses 'in' and 'type' aliases."""
        import yaml

        from mcp_builder.cli import _cmd_analyze

        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0"},
            "paths": {
                "/x/{id}": {
                    "get": {
                        "operationId": "getX",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(yaml.dump(raw))

        parser = build_parser()
        args = parser.parse_args(["analyze", str(spec_file)])
        with structlog.testing.capture_logs():
            _cmd_analyze(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        param = data["endpoints"][0]["parameters"][0]
        assert param["in"] == "path"
        assert param["type"] == "string"
        # The Python field names should not appear
        assert "location" not in param
        assert "schema_type" not in param


class TestCmdValidate:
    def _make_scope(self, tmp_path, tools=None):
        import yaml

        if tools is None:
            tools = [
                {
                    "tool_name": "get_thing",
                    "endpoint": "GET /things",
                    "description": "Get a thing",
                    "response_kind": "json",
                }
            ]
        scope_data = {
            "version": "1",
            "server": {"name": "test-svc", "description": "A test server"},
            "spec": {
                "source": "https://example.com/spec.yaml",
                "format": "openapi3",
                "base_url": "https://api.example.com",
            },
            "groups": [
                {
                    "name": "default",
                    "description": "Default group",
                    "tools": tools,
                }
            ],
            "auth": {"type": "none"},
        }
        scope_file = tmp_path / "scope.yaml"
        scope_file.write_text(yaml.dump(scope_data))
        return scope_file

    def _make_spec(self, tmp_path, paths=None):
        import yaml

        if paths is None:
            paths = {
                "/things": {
                    "get": {
                        "operationId": "getThings",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        raw = {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0"},
            "paths": paths,
        }
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(yaml.dump(raw))
        return spec_file

    def test_validate_no_spec(self, tmp_path, capsys):
        from mcp_builder.cli import _cmd_validate

        scope_file = self._make_scope(tmp_path)

        parser = build_parser()
        args = parser.parse_args(["validate", str(scope_file)])
        with structlog.testing.capture_logs():
            _cmd_validate(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["errors"] == []
        assert data["warnings"] == []

    def test_cross_validate_passes(self, tmp_path, capsys):
        from mcp_builder.cli import _cmd_validate

        scope_file = self._make_scope(tmp_path)
        spec_file = self._make_spec(tmp_path)

        parser = build_parser()
        args = parser.parse_args(
            ["validate", str(scope_file), "--openapi-spec", str(spec_file)]
        )
        with structlog.testing.capture_logs():
            _cmd_validate(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["errors"] == []

    def test_cross_validate_catches_bad_path(self, tmp_path, capsys):
        from mcp_builder.cli import _cmd_validate

        scope_file = self._make_scope(tmp_path)
        # Spec has /items but scope references /things
        spec_file = self._make_spec(
            tmp_path,
            paths={
                "/items": {
                    "get": {
                        "operationId": "getItems",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        )

        parser = build_parser()
        args = parser.parse_args(
            ["validate", str(scope_file), "--openapi-spec", str(spec_file)]
        )
        with structlog.testing.capture_logs(), pytest.raises(SystemExit) as exc_info:
            _cmd_validate(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["errors"]) == 1
        assert "/things" in data["errors"][0]
