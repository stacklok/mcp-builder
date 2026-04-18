"""Tests for codegen.spec_analyzer — OpenAPI spec analysis and survey."""

from mcp_builder.codegen.spec_analyzer import (
    AnalyzedParameter,
    AnalyzedRequestBody,
    QualityMetrics,
    SecuritySchemeInfo,
    SpecAnalysis,
    analyze_spec,
)


class TestAnalyzeSpec:
    def test_returns_spec_analysis(self, spec):
        result = analyze_spec(spec)
        assert isinstance(result, SpecAnalysis)

    def test_spec_version(self, spec):
        result = analyze_spec(spec)
        assert result.spec_version == "3.0.3"

    def test_base_url(self, spec):
        result = analyze_spec(spec)
        assert result.base_url == "https://api.example.com"

    def test_endpoint_count(self, spec):
        result = analyze_spec(spec)
        assert result.quality.endpoint_count == 14

    def test_endpoints_have_method_and_path(self, spec):
        result = analyze_spec(spec)
        methods_paths = {(e.method, e.path) for e in result.endpoints}
        assert ("GET", "/items/{itemId}") in methods_paths
        assert ("POST", "/items") in methods_paths

    def test_endpoint_has_operation_id(self, spec):
        result = analyze_spec(spec)
        get_item = next(
            e
            for e in result.endpoints
            if e.method == "GET" and e.path == "/items/{itemId}"
        )
        assert get_item.operation_id == "getItem"

    def test_endpoint_has_summary(self, spec):
        result = analyze_spec(spec)
        get_item = next(
            e
            for e in result.endpoints
            if e.method == "GET" and e.path == "/items/{itemId}"
        )
        assert get_item.summary == "Get an item by ID"

    def test_parameters_extracted(self, spec):
        result = analyze_spec(spec)
        get_item = next(
            e
            for e in result.endpoints
            if e.method == "GET" and e.path == "/items/{itemId}"
        )
        names = {p.name for p in get_item.parameters}
        assert "itemId" in names
        assert "fields" in names

    def test_parameter_details(self, spec):
        result = analyze_spec(spec)
        get_item = next(
            e
            for e in result.endpoints
            if e.method == "GET" and e.path == "/items/{itemId}"
        )
        item_id = next(p for p in get_item.parameters if p.name == "itemId")
        assert isinstance(item_id, AnalyzedParameter)
        assert item_id.location == "path"
        assert item_id.required is True
        assert item_id.schema_type == "string"

    def test_ref_parameters_skipped_gracefully(self, spec):
        """$ref params in analysis are skipped (not resolved), no crash."""
        result = analyze_spec(spec)
        issues_ep = next(
            e for e in result.endpoints if e.path == "/repos/{owner}/{repo}/issues"
        )
        names = {p.name for p in issues_ep.parameters}
        assert "repo" in names

    def test_request_body_present(self, spec):
        result = analyze_spec(spec)
        post_items = next(
            e for e in result.endpoints if e.method == "POST" and e.path == "/items"
        )
        assert post_items.request_body is not None
        assert isinstance(post_items.request_body, AnalyzedRequestBody)
        assert post_items.request_body.content_type == "application/json"
        assert post_items.request_body.required is True

    def test_request_body_null_for_get(self, spec):
        result = analyze_spec(spec)
        get_item = next(
            e
            for e in result.endpoints
            if e.method == "GET" and e.path == "/items/{itemId}"
        )
        assert get_item.request_body is None

    def test_quality_metrics_counts(self, spec):
        result = analyze_spec(spec)
        assert isinstance(result.quality, QualityMetrics)
        assert result.quality.endpoint_count > 0
        assert result.quality.total_parameters > 0
        # Raw counts, not percentages
        assert result.quality.endpoints_with_descriptions >= 0
        assert result.quality.parameters_with_descriptions >= 0

    def test_no_security_schemes(self, spec):
        result = analyze_spec(spec)
        assert result.security_schemes == {}

    def test_json_output_uses_aliases(self, spec):
        """JSON output should use 'in' and 'type', not 'location' and 'schema_type'."""
        result = analyze_spec(spec)
        json_str = result.model_dump_json(indent=2, by_alias=True)
        # Check that the aliases appear in JSON
        assert '"in":' in json_str
        assert '"type":' in json_str

    def test_json_roundtrip(self, spec):
        """Roundtrip through dict (Python field names) preserves data."""
        result = analyze_spec(spec)
        data = result.model_dump()
        roundtripped = SpecAnalysis.model_validate(data)
        assert roundtripped.spec_version == result.spec_version
        assert len(roundtripped.endpoints) == len(result.endpoints)


class TestAnalyzeSpecWithErrors:
    def test_bad_param_captured_in_errors(self, tmp_path):
        """A parameter with no schema captures the error, not raises."""
        import yaml

        from mcp_builder.spec import load_openapi_spec

        raw = {
            "openapi": "3.0.3",
            "info": {"title": "Bad Params", "version": "0.1"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "testOp",
                        "parameters": [
                            {
                                "name": "broken",
                                "in": "query",
                                "required": False,
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec_file = tmp_path / "bad.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        result = analyze_spec(spec)
        ep = result.endpoints[0]
        assert len(ep.errors) == 1
        assert "broken" in ep.errors[0]
        assert ep.parameters[0].name == "broken"
        assert ep.parameters[0].schema_type == "string"


class TestAnalyzeSpecSecuritySchemes:
    def test_extracts_api_key_scheme(self, tmp_path):
        import yaml

        from mcp_builder.spec import load_openapi_spec

        raw = {
            "openapi": "3.0.3",
            "info": {"title": "Sec Test", "version": "0.1"},
            "paths": {},
            "components": {
                "securitySchemes": {
                    "api_key": {
                        "type": "apiKey",
                        "name": "X-API-Key",
                        "in": "header",
                    }
                }
            },
        }
        spec_file = tmp_path / "sec.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        result = analyze_spec(spec)
        assert "api_key" in result.security_schemes
        scheme = result.security_schemes["api_key"]
        assert isinstance(scheme, SecuritySchemeInfo)
        assert scheme.type == "apiKey"
        assert scheme.parameter_name == "X-API-Key"
        assert scheme.location == "header"

    def test_extracts_oauth2_flows(self, tmp_path):
        import yaml

        from mcp_builder.spec import load_openapi_spec

        raw = {
            "openapi": "3.0.3",
            "info": {"title": "OAuth Test", "version": "0.1"},
            "paths": {},
            "components": {
                "securitySchemes": {
                    "oauth2": {
                        "type": "oauth2",
                        "flows": {
                            "authorizationCode": {
                                "authorizationUrl": "https://auth.example.com/authorize",
                                "tokenUrl": "https://auth.example.com/token",
                                "scopes": {
                                    "read": "Read access",
                                    "write": "Write access",
                                },
                            }
                        },
                    }
                }
            },
        }
        spec_file = tmp_path / "oauth.yaml"
        spec_file.write_text(yaml.dump(raw))
        spec = load_openapi_spec(spec_file)
        result = analyze_spec(spec)
        assert "oauth2" in result.security_schemes
        scheme = result.security_schemes["oauth2"]
        assert scheme.type == "oauth2"
        assert "authorizationCode" in scheme.flows
        flow = scheme.flows["authorizationCode"]
        assert flow.authorization_url == "https://auth.example.com/authorize"
        assert flow.scopes == {"read": "Read access", "write": "Write access"}
