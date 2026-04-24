"""Tests for scope validation against an OpenAPI spec."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mcp_builder.spec.media import is_json_media_type
from mcp_builder.validate import validate_scope
from mcp_builder.schema.models import (
    APIKeyAuth,
    Group,
    MCPScope,
    OAuth2Auth,
    OIDCAuth,
    ParamLocation,
    Parameter,
    Tool,
    load_scope,
)
from mcp_builder.spec import OpenAPISpec, load_openapi_spec

FIXTURES = Path(__file__).parent / "fixtures"


def _scope_with_tool(tool: Tool) -> MCPScope:
    """Build a minimal scope wrapping a single tool for testing."""
    scope = load_scope(FIXTURES / "test_scope.yaml")
    scope.groups = [
        Group(
            name="focus",
            description="Group under test.",
            tools=[tool],
        )
    ]
    return scope


def _mini_spec(tmp_path: Path, paths: dict) -> OpenAPISpec:
    """Write and load a tiny OpenAPI spec with the given paths block."""
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "servers": [{"url": "https://x"}],
        "paths": paths,
    }
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(doc))
    return load_openapi_spec(path)


class TestParameterCoverage:
    """Warnings when YAML params don't exist in the spec."""

    def test_body_param_missing_from_spec_warns(self, spec):
        """Body params on an endpoint with no requestBody get the
        'spec may be incomplete' warning."""
        # POST /files has no requestBody in the test spec.
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="name",
                    description="File name.",
                    required=True,
                    location=ParamLocation.BODY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        matching = [w for w in result.warnings if "name" in w and "requestBody" in w]
        assert matching, result.warnings
        assert any("spec may be incomplete" in w for w in matching)
        # The mismatched-properties wording must NOT fire when the spec
        # has no declared properties.
        assert not any("available:" in w for w in matching)

    def test_body_param_mismatch_lists_available_fields(self, spec):
        """When the spec has declared requestBody properties but the YAML
        body param doesn't match any of them, the warning lists the
        available field names and does not claim the spec is incomplete."""
        # POST /items has a requestBody with CreateItemRequest
        # (properties: name, description).
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_item",
            endpoint="POST /items",
            description="Create an item.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="body",
                    description="Catch-all body.",
                    required=True,
                    location=ParamLocation.BODY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        matching = [
            w
            for w in result.warnings
            if "create_item" in w and "body parameter 'body'" in w
        ]
        assert matching, result.warnings
        (warning,) = matching
        assert "available: description, name" in warning
        assert "per-field body parameters" in warning
        assert "spec may be incomplete" not in warning

    def test_all_params_in_spec_no_warnings(self, spec):
        """When all YAML params exist in the spec, no param warnings."""
        scope = load_scope(FIXTURES / "test_scope.yaml")
        result = validate_scope(scope, spec)
        param_warnings = [w for w in result.warnings if "default to str" in w]
        assert param_warnings == []

    def test_query_param_missing_from_spec_warns(self, spec):
        """Query params not in spec's parameters produce a warning."""
        scope = load_scope(FIXTURES / "test_scope.yaml")
        group = scope.groups[0]
        group.tools[1] = Tool(
            tool_name="create_file",
            endpoint="POST /files",
            description="Create a file.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="nonexistent_query",
                    description="Not in spec.",
                    required=False,
                    location=ParamLocation.QUERY,
                ),
            ],
        )
        result = validate_scope(scope, spec)
        assert any("nonexistent_query" in w for w in result.warnings)


class TestResponseKindSchema:
    """Pydantic-level rejection of scopes missing response_kind.

    Having this enforced at load time means the CLI's generate/validate
    commands can't silently fall through to a default decode path.
    """

    def test_missing_response_kind_fails_at_load(self):
        # Model instantiation via dict bypasses the static-type check so
        # the runtime Pydantic validation is what we're exercising.
        with pytest.raises(ValidationError):
            Tool.model_validate(
                {
                    "tool_name": "no_kind",
                    "endpoint": "GET /items",
                    "description": "Tool missing response_kind.",
                    "parameters": [],
                }
            )

    def test_invalid_response_kind_fails_at_load(self):
        with pytest.raises(ValidationError):
            Tool.model_validate(
                {
                    "tool_name": "bad_kind",
                    "endpoint": "GET /items",
                    "description": "Tool with bogus response_kind.",
                    "response_kind": "maybe",
                    "parameters": [],
                }
            )


class TestResponseKindSpecCompatibility:
    """Validator cross-checks scope's response_kind against the spec's 2xx.

    Errors surface a mismatch now so the scope author either drops the
    endpoint or fixes the decode choice — no silent base64 of JSON
    responses, no runtime crash on ``response.json()`` of a PDF.
    """

    def test_binary_scope_with_non_json_spec_passes(self, spec):
        """binary scope against an image/jpeg-only endpoint is the intended
        happy path."""
        tool = Tool(
            tool_name="get_employee_photo",
            endpoint="GET /employees/{employeeId}/photo",
            description="Fetch the employee photo.",
            response_kind="binary",
            parameters=[
                Parameter(
                    name="employeeId",
                    description="Employee ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        assert not any("get_employee_photo" in e for e in result.errors)

    def test_json_scope_against_non_json_endpoint_errors(self, spec):
        """Declaring json against a PDF/image-only endpoint would crash at
        runtime when the generated tool calls ``response.json()``."""
        tool = Tool(
            tool_name="get_employee_photo",
            endpoint="GET /employees/{employeeId}/photo",
            description="Fetch the employee photo.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="employeeId",
                    description="Employee ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        matching = [e for e in result.errors if "get_employee_photo" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='json'" in msg
        assert "image/jpeg" in msg

    def test_binary_scope_against_json_endpoint_errors(self, spec):
        """Declaring binary against a JSON-only endpoint would base64-wrap a
        JSON body, handing the caller opaque bytes."""
        tool = Tool(
            tool_name="get_item",
            endpoint="GET /items/{itemId}",
            description="Get an item.",
            response_kind="binary",
            parameters=[
                Parameter(
                    name="itemId",
                    description="Item ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        matching = [e for e in result.errors if "get_item" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='binary'" in msg
        assert "application/json" in msg

    def test_same_status_mixed_passes_with_json_kind(self, spec):
        """A single 2xx declaring both JSON and non-JSON media types
        (/reports/{reportId}/download returns application/json + pdf) is
        safe under ``response_kind=json``: the generated client sends
        ``Accept: application/json`` so the server negotiates JSON."""
        tool = Tool(
            tool_name="download_report",
            endpoint="GET /reports/{reportId}/download",
            description="Download a report.",
            response_kind="json",
            parameters=[
                Parameter(
                    name="reportId",
                    description="Report ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        assert not any("download_report" in e for e in result.errors), result.errors

    def test_same_status_mixed_errors_with_binary_kind(self, spec):
        """Same endpoint under ``response_kind=binary`` is unsafe: the
        generated client sends ``Accept: */*`` and a JSON-capable server
        may return JSON that would be base64-wrapped into opaque bytes."""
        tool = Tool(
            tool_name="download_report",
            endpoint="GET /reports/{reportId}/download",
            description="Download a report.",
            response_kind="binary",
            parameters=[
                Parameter(
                    name="reportId",
                    description="Report ID.",
                    required=True,
                    location=ParamLocation.PATH,
                ),
            ],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        matching = [e for e in result.errors if "download_report" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='binary'" in msg
        assert "include JSON" in msg
        assert "application/json" in msg
        assert "application/pdf" in msg
        assert "Update the scope" in msg

    def test_no_content_block_passes(self, spec):
        """2xx with no 'content' block is a legitimate empty response
        (204-style); must not error regardless of response_kind."""
        # GET /items declares 200 without a content block.
        tool = Tool(
            tool_name="list_items",
            endpoint="GET /items",
            description="List items.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), spec)
        assert not any("list_items" in e for e in result.errors)
        assert not any("list_items" in w and "no 2xx" in w for w in result.warnings)

    def test_missing_2xx_warns(self, tmp_path):
        """An operation with no 2xx responses declared produces a
        'spec may be incomplete' warning, not an error — we can't prove
        it's broken."""
        small_spec = _mini_spec(
            tmp_path,
            {
                "/only-errors": {
                    "get": {
                        "responses": {
                            "500": {"description": "server error"},
                        }
                    }
                }
            },
        )
        tool = Tool(
            tool_name="only_errors",
            endpoint="GET /only-errors",
            description="Only errors declared.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), small_spec)
        assert not any("only_errors" in e for e in result.errors)
        assert any("only_errors" in w and "no 2xx" in w for w in result.warnings)

    def test_vendor_json_type_accepted(self, tmp_path):
        """RFC 6839 structured-suffix +json types (e.g. application/vnd.api+json)
        are JSON-decodable, so they should not error with response_kind=json."""
        small_spec = _mini_spec(
            tmp_path,
            {
                "/vendor": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/vnd.api+json": {},
                                },
                            },
                        }
                    }
                }
            },
        )
        tool = Tool(
            tool_name="get_vendor",
            endpoint="GET /vendor",
            description="Vendor JSON response.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(tool), small_spec)
        assert not any("get_vendor" in e for e in result.errors)

    def test_mixed_status_2xx_errors_regardless_of_response_kind(self, tmp_path):
        """Spec that returns PDF on 200 and JSON on 201 is unsafe for
        single-tool codegen under either response_kind: ``json`` can't
        decode the PDF status, ``binary`` would base64-wrap the JSON
        status."""
        paths = {
            "/mixed": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "pdf",
                            "content": {"application/pdf": {}},
                        },
                        "201": {
                            "description": "json",
                            "content": {"application/json": {}},
                        },
                    }
                }
            }
        }

        small_spec = _mini_spec(tmp_path, paths)

        json_tool = Tool(
            tool_name="get_mixed",
            endpoint="GET /mixed",
            description="Mixed statuses.",
            response_kind="json",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(json_tool), small_spec)
        matching = [e for e in result.errors if "get_mixed" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='json'" in msg
        assert "no JSON content type" in msg
        assert "application/pdf" in msg

        binary_tool = Tool(
            tool_name="get_mixed",
            endpoint="GET /mixed",
            description="Mixed statuses.",
            response_kind="binary",
            parameters=[],
        )
        result = validate_scope(_scope_with_tool(binary_tool), small_spec)
        matching = [e for e in result.errors if "get_mixed" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "response_kind='binary'" in msg
        assert "include JSON" in msg
        assert "application/json" in msg


class TestIsJsonMediaType:
    """Direct coverage of the JSON-media-type predicate.

    The validator's error/pass decision hinges on this predicate. If it
    miscategorizes a type, validate_scope silently passes a scope that
    should have errored (or vice versa) — the existing validator tests
    only exercise two media types transitively.
    """

    @pytest.mark.parametrize(
        "media_type",
        [
            "application/json",
            "text/json",  # legacy
            "Application/JSON",  # case-insensitive
            "APPLICATION/JSON",
            "application/json; charset=utf-8",  # parameter stripped
            "application/json ; charset=utf-8",  # whitespace ok
            "application/vnd.api+json",  # RFC 6839 structured suffix
            "application/problem+json",  # RFC 7807
            "application/ld+json",
            "text/foo+json",
        ],
    )
    def test_accepts(self, media_type):
        assert is_json_media_type(media_type) is True

    @pytest.mark.parametrize(
        "media_type",
        [
            "application/xml",
            "application/octet-stream",
            "image/jpeg",
            "text/plain",
            "multipart/form-data",
            "application/jsonl",  # JSON Lines, not JSON
            "application/json-seq",  # JSON text sequences
            "application/json-patch",  # not +json suffixed
            "application/+json",  # malformed: empty prefix before +
        ],
    )
    def test_rejects(self, media_type):
        assert is_json_media_type(media_type) is False


# ===================================================================
# Tenant placeholder check (V-TENANT-01)
# ===================================================================


def _scope_with_auth(auth) -> MCPScope:
    """Build a minimal scope with the given auth block."""
    scope = load_scope(FIXTURES / "test_scope.yaml")
    scope.auth = auth
    return scope


class TestUnresolvedPlaceholders:
    """V-TENANT-01: any ``{name}`` left in a URL field fails validation.

    Substitution belongs in scoping; if validate sees a placeholder the
    scope was never tenant-resolved and a downstream HTTP client would
    SSL-error on the literal hostname.
    """

    def test_base_url_with_placeholder_errors(self):
        scope = load_scope(FIXTURES / "test_scope.yaml")
        scope.spec.base_url = "https://{companyDomain}.bamboohr.com"
        result = validate_scope(scope)
        matching = [e for e in result.errors if "V-TENANT-01" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "spec.base_url" in msg
        assert "{companyDomain}" in msg

    def test_oauth2_authorization_url_with_placeholder_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://{companyDomain}.bamboohr.com/authorize.php",
                token_url="https://example.com/token",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-TENANT-01" in e and "authorization_url" in e
        ]
        assert matching, result.errors

    def test_oauth2_token_url_with_placeholder_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://{companyDomain}.bamboohr.com/token.php",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-TENANT-01" in e and "auth.token_url" in e
        ]
        assert matching, result.errors

    def test_oauth2_userinfo_url_with_placeholder_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                userinfo_url="https://{companyDomain}.bamboohr.com/me",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-TENANT-01" in e and "auth.userinfo_url" in e
        ]
        assert matching, result.errors

    def test_oidc_issuer_with_placeholder_errors(self):
        scope = _scope_with_auth(
            OIDCAuth(
                type="oidc",
                issuer="https://{tenant}.example.com",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-TENANT-01" in e and "auth.issuer" in e
        ]
        assert matching, result.errors

    def test_multiple_placeholders_each_reported(self):
        """Two placeholders in different fields produce two distinct errors,
        so the user fixes both in one cycle."""
        scope = load_scope(FIXTURES / "test_scope.yaml")
        scope.spec.base_url = "https://{companyDomain}.bamboohr.com"
        scope.auth = OAuth2Auth(
            type="oauth2",
            flow="authorizationCode",
            authorization_url="https://{companyDomain}.bamboohr.com/authorize.php",
            token_url="https://example.com/token",
        )
        result = validate_scope(scope)
        tenant_errors = [e for e in result.errors if "V-TENANT-01" in e]
        assert len(tenant_errors) == 2, tenant_errors

    def test_placeholder_in_notes_does_not_error(self):
        """Free-form prose fields are not URL fields; placeholders there are
        documentation, not unresolved configuration."""
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                notes="Replace {companyDomain} with the customer subdomain.",
            )
        )
        result = validate_scope(scope)
        assert not any("V-TENANT-01" in e for e in result.errors)

    def test_clean_scope_no_tenant_errors(self, scope):
        result = validate_scope(scope)
        assert not any("V-TENANT-01" in e for e in result.errors)


# ===================================================================
# Auth schema consistency
# ===================================================================


class TestAuthScopesSubset:
    """V-AUTH-01: scopes_required must be a subset of scopes_available.

    Pydantic enforces shape; this catches a soft authoring bug — asking
    the IdP for a scope you never declared as available.
    """

    def test_oauth2_required_not_in_available_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                scopes_available={"read": "Read", "write": "Write"},
                scopes_required=["admin"],
            )
        )
        result = validate_scope(scope)
        matching = [e for e in result.errors if "V-AUTH-01" in e]
        assert matching, result.errors
        (msg,) = matching
        assert "admin" in msg
        assert "scopes_required" in msg
        assert "scopes_available" in msg

    def test_oidc_required_not_in_available_errors(self):
        scope = _scope_with_auth(
            OIDCAuth(
                type="oidc",
                issuer="https://example.com",
                scopes_available={"openid": "Sign-in"},
                scopes_required=["openid", "profile"],
            )
        )
        result = validate_scope(scope)
        matching = [e for e in result.errors if "V-AUTH-01" in e]
        assert matching, result.errors
        assert "profile" in matching[0]

    def test_required_subset_of_available_passes(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                scopes_available={"read": "Read", "write": "Write"},
                scopes_required=["read"],
            )
        )
        result = validate_scope(scope)
        assert not any("V-AUTH-01" in e for e in result.errors)

    def test_empty_available_with_required_errors(self):
        """No scopes declared at all but required asks for one — still a
        subset violation."""
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                scopes_required=["read"],
            )
        )
        result = validate_scope(scope)
        assert any("V-AUTH-01" in e for e in result.errors)

    def test_empty_required_passes(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                scopes_available={"read": "Read"},
            )
        )
        result = validate_scope(scope)
        assert not any("V-AUTH-01" in e for e in result.errors)

    def test_api_key_no_subset_check(self):
        """api_key has no scopes block; the check is silently skipped."""
        scope = _scope_with_auth(APIKeyAuth(type="api_key"))
        result = validate_scope(scope)
        assert not any("V-AUTH-01" in e for e in result.errors)


class TestAuthAbsoluteUrls:
    """V-AUTH-02: every URL in the auth block must be absolute.

    Scoping resolves relative paths against ``spec.base_url``. A relative
    URL in the auth block at validate time means scoping skipped resolution
    and the generated client would assemble a broken IdP request.
    """

    def test_oauth2_relative_authorization_url_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="/oauth/authorize",
                token_url="https://example.com/token",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-AUTH-02" in e and "authorization_url" in e
        ]
        assert matching, result.errors

    def test_oauth2_relative_token_url_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="/oauth/token",
            )
        )
        result = validate_scope(scope)
        matching = [e for e in result.errors if "V-AUTH-02" in e and "token_url" in e]
        assert matching, result.errors

    def test_oauth2_relative_userinfo_url_errors(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="https://example.com/token",
                userinfo_url="/me",
            )
        )
        result = validate_scope(scope)
        matching = [
            e for e in result.errors if "V-AUTH-02" in e and "userinfo_url" in e
        ]
        assert matching, result.errors

    def test_oidc_relative_issuer_errors(self):
        scope = _scope_with_auth(
            OIDCAuth(type="oidc", issuer="example.com"),
        )
        result = validate_scope(scope)
        matching = [e for e in result.errors if "V-AUTH-02" in e and "issuer" in e]
        assert matching, result.errors

    def test_absolute_urls_pass(self):
        scope = _scope_with_auth(
            OAuth2Auth(
                type="oauth2",
                flow="authorizationCode",
                authorization_url="https://example.com/authorize",
                token_url="http://example.com/token",
                userinfo_url="https://example.com/me",
            )
        )
        result = validate_scope(scope)
        assert not any("V-AUTH-02" in e for e in result.errors)
