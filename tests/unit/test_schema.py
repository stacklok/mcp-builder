"""Tests for mcp-scope.yaml Pydantic models and YAML loader."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mcp_builder.schema.models import MCPScope, load_scope

FIXTURES = Path(__file__).parent / "fixtures"


# --- Helpers ---


def _minimal_scope(**overrides: object) -> dict:
    """Return a minimal valid scope dict, with optional overrides merged in."""
    base: dict = {
        "version": "1",
        "server": {"name": "test-api", "description": "Test"},
        "spec": {
            "source": "https://example.com/spec.json",
            "format": "openapi3",
            "base_url": "https://api.example.com",
        },
        "groups": [
            {
                "name": "default",
                "description": "Default group",
                "tools": [
                    {
                        "tool_name": "get_status",
                        "endpoint": "GET /status",
                        "description": "Get status.",
                        "response_kind": "json",
                    }
                ],
            }
        ],
        "auth": {"type": "none"},
    }
    base.update(overrides)
    return base


def _make_tool(**overrides: object) -> dict:
    """Return a minimal valid tool dict with optional overrides."""
    base: dict = {
        "tool_name": "get_item",
        "endpoint": "GET /items",
        "description": "Get items.",
        "response_kind": "json",
    }
    base.update(overrides)
    return base


# ===================================================================
# Valid inputs
# ===================================================================


class TestValidInputs:
    def test_google_drive_fixture(self) -> None:
        scope = load_scope(FIXTURES / "valid_google_drive.yaml")
        assert scope.server.name == "google-drive"
        assert len(scope.groups) == 2
        assert scope.auth.type == "oidc"
        # isinstance narrowing keeps the discriminated-union types honest.
        from mcp_builder.schema.models import OIDCAuth

        assert isinstance(scope.auth, OIDCAuth)
        assert scope.auth.issuer == "https://accounts.google.com"
        assert len(scope.auth.scopes_required) == 3
        assert "openid" in scope.auth.scopes_available

    def test_minimal_fixture(self) -> None:
        scope = load_scope(FIXTURES / "valid_minimal.yaml")
        assert scope.server.name == "minimal-api"
        assert scope.auth.type == "none"
        assert scope.workflows is None

    def test_api_key_fixture(self) -> None:
        scope = load_scope(FIXTURES / "valid_api_key_auth.yaml")
        assert scope.auth.type == "api_key"
        assert scope.auth.notes is not None

    def test_minimal_from_dict(self) -> None:
        scope = MCPScope.model_validate(_minimal_scope())
        assert scope.version == "1"

    def test_with_workflows(self) -> None:
        scope = MCPScope.model_validate(
            _minimal_scope(workflows=["Search for files", "Manage permissions"])
        )
        assert scope.workflows is not None
        assert len(scope.workflows) == 2

    def test_with_optional_spec_fields(self) -> None:
        data = _minimal_scope()
        data["spec"]["total_endpoints"] = 38
        data["spec"]["scoped_endpoints"] = 6
        scope = MCPScope.model_validate(data)
        assert scope.spec.total_endpoints == 38
        assert scope.spec.scoped_endpoints == 6

    def test_tool_with_parameters_and_hints(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["parameters"] = [
            {
                "name": "q",
                "description": "Query string.",
                "required": False,
                "location": "query",
            }
        ]
        data["groups"][0]["tools"][0]["hints"] = ["paginated"]
        scope = MCPScope.model_validate(data)
        tool = scope.groups[0].tools[0]
        assert tool.parameters is not None
        assert len(tool.parameters) == 1
        assert tool.hints == ["paginated"]

    def test_tool_name_exactly_40_chars(self) -> None:
        name = "a" * 40
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = name
        scope = MCPScope.model_validate(data)
        assert scope.groups[0].tools[0].tool_name == name

    def test_tool_name_with_digits(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "list_v2_items"
        scope = MCPScope.model_validate(data)
        assert scope.groups[0].tools[0].tool_name == "list_v2_items"

    def test_single_char_server_name(self) -> None:
        scope = MCPScope.model_validate(
            _minimal_scope(server={"name": "a", "description": "Test"})
        )
        assert scope.server.name == "a"

    def test_all_http_methods(self) -> None:
        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        for i, method in enumerate(methods):
            data = _minimal_scope()
            data["groups"][0]["tools"][0]["tool_name"] = f"op_{method.lower()}"
            data["groups"][0]["tools"][0]["endpoint"] = f"{method} /resource"
            MCPScope.model_validate(data)

    def test_multiple_groups_unique_tools(self) -> None:
        data = _minimal_scope()
        data["groups"] = [
            {
                "name": "group-a",
                "description": "Group A",
                "tools": [_make_tool(tool_name="list_items")],
            },
            {
                "name": "group-b",
                "description": "Group B",
                "tools": [_make_tool(tool_name="get_item")],
            },
        ]
        scope = MCPScope.model_validate(data)
        assert len(scope.groups) == 2


# ===================================================================
# Invalid inputs
# ===================================================================


class TestMissingRequiredFields:
    def test_missing_version(self) -> None:
        data = _minimal_scope()
        del data["version"]
        with pytest.raises(ValidationError, match="version"):
            MCPScope.model_validate(data)

    def test_missing_server(self) -> None:
        data = _minimal_scope()
        del data["server"]
        with pytest.raises(ValidationError, match="server"):
            MCPScope.model_validate(data)

    def test_missing_server_name(self) -> None:
        data = _minimal_scope(server={"description": "No name"})
        with pytest.raises(ValidationError, match="name"):
            MCPScope.model_validate(data)

    def test_missing_auth_type(self) -> None:
        data = _minimal_scope(auth={})
        with pytest.raises(ValidationError, match="type"):
            MCPScope.model_validate(data)

    def test_missing_groups(self) -> None:
        data = _minimal_scope()
        del data["groups"]
        with pytest.raises(ValidationError, match="groups"):
            MCPScope.model_validate(data)

    def test_missing_tool_name(self) -> None:
        data = _minimal_scope()
        del data["groups"][0]["tools"][0]["tool_name"]
        with pytest.raises(ValidationError, match="tool_name"):
            MCPScope.model_validate(data)

    def test_missing_tool_endpoint(self) -> None:
        data = _minimal_scope()
        del data["groups"][0]["tools"][0]["endpoint"]
        with pytest.raises(ValidationError, match="endpoint"):
            MCPScope.model_validate(data)

    def test_missing_tool_description(self) -> None:
        data = _minimal_scope()
        del data["groups"][0]["tools"][0]["description"]
        with pytest.raises(ValidationError, match="description"):
            MCPScope.model_validate(data)


class TestInvalidServerName:
    def test_uppercase(self) -> None:
        data = _minimal_scope(server={"name": "Google-Drive", "description": "T"})
        with pytest.raises(ValidationError, match="DNS label"):
            MCPScope.model_validate(data)

    def test_underscore(self) -> None:
        data = _minimal_scope(server={"name": "google_drive", "description": "T"})
        with pytest.raises(ValidationError, match="DNS label"):
            MCPScope.model_validate(data)

    def test_spaces(self) -> None:
        data = _minimal_scope(server={"name": "google drive", "description": "T"})
        with pytest.raises(ValidationError, match="DNS label"):
            MCPScope.model_validate(data)

    def test_starts_with_hyphen(self) -> None:
        data = _minimal_scope(server={"name": "-google-drive", "description": "T"})
        with pytest.raises(ValidationError, match="DNS label"):
            MCPScope.model_validate(data)

    def test_ends_with_hyphen(self) -> None:
        data = _minimal_scope(server={"name": "google-drive-", "description": "T"})
        with pytest.raises(ValidationError, match="DNS label"):
            MCPScope.model_validate(data)


class TestInvalidSpecFormat:
    def test_unsupported_format(self) -> None:
        data = _minimal_scope()
        data["spec"]["format"] = "swagger2"
        with pytest.raises(ValidationError, match="format"):
            MCPScope.model_validate(data)


class TestInvalidToolName:
    def test_too_long(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "a" * 41
        with pytest.raises(ValidationError, match="exceeds 40 characters"):
            MCPScope.model_validate(data)

    def test_hyphen(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "list-files"
        with pytest.raises(ValidationError, match="snake_case"):
            MCPScope.model_validate(data)

    def test_spaces(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "list files"
        with pytest.raises(ValidationError, match="snake_case"):
            MCPScope.model_validate(data)

    def test_uppercase(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "List_Files"
        with pytest.raises(ValidationError, match="snake_case"):
            MCPScope.model_validate(data)

    def test_starts_with_digit(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "1list_files"
        with pytest.raises(ValidationError, match="snake_case"):
            MCPScope.model_validate(data)


class TestDuplicateToolNames:
    def test_across_groups(self) -> None:
        data = _minimal_scope()
        data["groups"] = [
            {
                "name": "group-a",
                "description": "A",
                "tools": [_make_tool(tool_name="list_files")],
            },
            {
                "name": "group-b",
                "description": "B",
                "tools": [_make_tool(tool_name="list_files")],
            },
        ]
        with pytest.raises(ValidationError, match="Duplicate tool_name"):
            MCPScope.model_validate(data)

    def test_within_group(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"] = [
            _make_tool(tool_name="list_files"),
            _make_tool(tool_name="list_files", endpoint="POST /files"),
        ]
        with pytest.raises(ValidationError, match="Duplicate tool_name"):
            MCPScope.model_validate(data)


class TestInvalidAuth:
    def test_invalid_auth_type(self) -> None:
        data = _minimal_scope(auth={"type": "basic"})
        with pytest.raises(ValidationError, match="type"):
            MCPScope.model_validate(data)

    def test_oauth_bearer_no_longer_accepted(self) -> None:
        # The old catch-all type is gone — callers must pick oauth2 or oidc.
        data = _minimal_scope(auth={"type": "oauth_bearer"})
        with pytest.raises(ValidationError):
            MCPScope.model_validate(data)

    def test_oauth2_missing_required_endpoints(self) -> None:
        data = _minimal_scope(auth={"type": "oauth2", "flow": "authorizationCode"})
        with pytest.raises(ValidationError, match="authorization_url|token_url"):
            MCPScope.model_validate(data)

    def test_oauth2_valid(self) -> None:
        from mcp_builder.schema.models import OAuth2Auth

        data = _minimal_scope(
            auth={
                "type": "oauth2",
                "flow": "authorizationCode",
                "authorization_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "scopes_available": {"read": "Read items"},
                "scopes_required": ["read"],
            }
        )
        scope = MCPScope.model_validate(data)
        assert isinstance(scope.auth, OAuth2Auth)
        assert scope.auth.authorization_url == "https://auth.example.com/authorize"

    def test_oauth2_rejects_issuer(self) -> None:
        # Cross-over prevention: issuer is an OIDC concept, not OAuth2.
        data = _minimal_scope(
            auth={
                "type": "oauth2",
                "flow": "authorizationCode",
                "authorization_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "issuer": "https://auth.example.com",
            }
        )
        with pytest.raises(ValidationError, match="issuer"):
            MCPScope.model_validate(data)

    def test_oidc_valid(self) -> None:
        from mcp_builder.schema.models import OIDCAuth

        data = _minimal_scope(
            auth={
                "type": "oidc",
                "issuer": "https://accounts.google.com",
                "scopes_required": ["openid"],
            }
        )
        scope = MCPScope.model_validate(data)
        assert isinstance(scope.auth, OIDCAuth)
        assert scope.auth.issuer == "https://accounts.google.com"

    def test_oidc_missing_issuer(self) -> None:
        data = _minimal_scope(auth={"type": "oidc"})
        with pytest.raises(ValidationError, match="issuer"):
            MCPScope.model_validate(data)

    def test_oidc_rejects_oauth2_endpoints(self) -> None:
        # Cross-over prevention: OIDC discovery document carries endpoints,
        # not the scope file.
        data = _minimal_scope(
            auth={
                "type": "oidc",
                "issuer": "https://accounts.google.com",
                "authorization_url": "https://accounts.google.com/authorize",
            }
        )
        with pytest.raises(ValidationError, match="authorization_url"):
            MCPScope.model_validate(data)


class TestInvalidEndpoint:
    def test_missing_method(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "/drive/v3/files"
        with pytest.raises(ValidationError, match="METHOD /path"):
            MCPScope.model_validate(data)

    def test_bad_method(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "FETCH /drive/v3/files"
        with pytest.raises(ValidationError, match="METHOD /path"):
            MCPScope.model_validate(data)

    def test_method_only(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "GET"
        with pytest.raises(ValidationError, match="METHOD /path"):
            MCPScope.model_validate(data)


class TestEmptyCollections:
    def test_empty_groups(self) -> None:
        data = _minimal_scope(groups=[])
        with pytest.raises(ValidationError, match="groups"):
            MCPScope.model_validate(data)

    def test_empty_tools(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"] = []
        with pytest.raises(ValidationError, match="tools"):
            MCPScope.model_validate(data)


class TestExtraFields:
    def test_extra_top_level(self) -> None:
        data = _minimal_scope()
        data["unknown_field"] = "surprise"
        with pytest.raises(ValidationError, match="unknown_field"):
            MCPScope.model_validate(data)

    def test_extra_in_server(self) -> None:
        data = _minimal_scope(
            server={"name": "test-api", "description": "T", "extra": "bad"}
        )
        with pytest.raises(ValidationError, match="extra"):
            MCPScope.model_validate(data)

    def test_extra_in_tool(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["extra"] = "bad"
        with pytest.raises(ValidationError, match="extra"):
            MCPScope.model_validate(data)

    def test_extra_in_auth(self) -> None:
        data = _minimal_scope(auth={"type": "none", "extra": "bad"})
        with pytest.raises(ValidationError, match="extra"):
            MCPScope.model_validate(data)


class TestInvalidVersion:
    def test_wrong_version(self) -> None:
        data = _minimal_scope(version="2")
        with pytest.raises(ValidationError, match="version"):
            MCPScope.model_validate(data)

    def test_integer_version(self) -> None:
        data = _minimal_scope(version=1)
        with pytest.raises(ValidationError, match="version"):
            MCPScope.model_validate(data)


class TestErrorMessageQuality:
    def test_dns_label_message_contains_field_and_explanation(self) -> None:
        data = _minimal_scope(server={"name": "BAD NAME!", "description": "T"})
        with pytest.raises(ValidationError) as exc_info:
            MCPScope.model_validate(data)
        msg = str(exc_info.value)
        assert "BAD NAME!" in msg
        assert "DNS label" in msg

    def test_tool_name_message_contains_field_and_explanation(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["tool_name"] = "Not-Valid"
        with pytest.raises(ValidationError) as exc_info:
            MCPScope.model_validate(data)
        msg = str(exc_info.value)
        assert "Not-Valid" in msg
        assert "snake_case" in msg


# ===================================================================
# Path parameter validation
# ===================================================================


class TestPathParamValidation:
    """Tool.validate_path_params_declared catches missing path params at load time."""

    def test_missing_path_param_raises(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "GET /items/{itemId}"
        with pytest.raises(ValidationError, match="itemId"):
            MCPScope.model_validate(data)

    def test_path_params_present_passes(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "GET /items/{itemId}"
        data["groups"][0]["tools"][0]["parameters"] = [
            {
                "name": "itemId",
                "description": "Item ID.",
                "required": True,
                "location": "path",
            }
        ]
        MCPScope.model_validate(data)

    def test_no_path_placeholders_passes(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "GET /items"
        MCPScope.model_validate(data)

    def test_path_param_wrong_location_raises(self) -> None:
        data = _minimal_scope()
        data["groups"][0]["tools"][0]["endpoint"] = "GET /items/{itemId}"
        data["groups"][0]["tools"][0]["parameters"] = [
            {
                "name": "itemId",
                "description": "Item ID.",
                "required": True,
                "location": "query",
            }
        ]
        with pytest.raises(ValidationError, match="itemId"):
            MCPScope.model_validate(data)


# ===================================================================
# YAML loader
# ===================================================================


class TestLoader:
    def test_load_valid_file(self) -> None:
        scope = load_scope(FIXTURES / "valid_google_drive.yaml")
        assert scope.server.name == "google-drive"

    def test_load_string_path(self) -> None:
        scope = load_scope(str(FIXTURES / "valid_minimal.yaml"))
        assert scope.server.name == "minimal-api"

    def test_load_nonexistent_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_scope("/nonexistent/path.yaml")

    def test_load_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_scope(empty)

    def test_load_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(":\n  - :\n    bad: [unclosed")
        with pytest.raises(yaml.YAMLError):
            load_scope(bad)

    def test_load_yaml_with_validation_error(self, tmp_path: Path) -> None:
        invalid = tmp_path / "invalid.yaml"
        invalid.write_text("version: '2'\nserver:\n  name: test\n")
        with pytest.raises(ValidationError):
            load_scope(invalid)
