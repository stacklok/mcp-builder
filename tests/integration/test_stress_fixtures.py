"""Integration stress tests for pipeline edge cases.

Each test uses a synthetic OpenAPI spec + scope YAML designed to exercise a
specific weak spot: type coverage, name collision resolution, or selective
scoping over a large spec. Fixtures live in tests/integration/fixtures/.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

from mcp_builder.cli import run_pipeline
from mcp_builder.codegen.plan import build_server_plan
from mcp_builder.schema.models import load_scope
from mcp_builder.spec.loader import load_openapi_spec

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE_DIR = Path(__file__).parent.parent / "unit" / "fixtures" / "template"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_plan(fixture_name: str):
    scope = load_scope(FIXTURES / f"{fixture_name}_scope.yaml")
    spec = load_openapi_spec(FIXTURES / f"{fixture_name}_openapi.yaml")
    return build_server_plan(scope, spec)


# ---------------------------------------------------------------------------
# Type matrix — every supported type in every param location
# ---------------------------------------------------------------------------


class TestTypeMatrix:
    @pytest.fixture()
    def plan(self):
        return _load_plan("type_matrix")

    def test_tool_count(self, plan) -> None:
        assert len(plan.tools) == 1

    def test_path_types(self, plan) -> None:
        tool = plan.tools[0]
        path_types = {p.py_name: p.py_type for p in tool.path_params}
        assert path_types == {"str_param": "str", "int_param": "int"}

    def test_query_types(self, plan) -> None:
        tool = plan.tools[0]
        query_types = {p.py_name: p.py_type for p in tool.query_params}
        assert query_types == {
            "num_query": "float",
            "bool_query": "bool",
            "arr_query": "list",
            "obj_query": "dict",
        }

    def test_body_types(self, plan) -> None:
        tool = plan.tools[0]
        body_types = {p.py_name: p.py_type for p in tool.body_fields}
        assert body_types == {
            "field_string": "str",
            "field_integer": "int",
            "field_number": "float",
            "field_boolean": "bool",
            "field_array": "list",
            "field_object": "dict",
        }

    def test_all_six_python_types_present(self, plan) -> None:
        tool = plan.tools[0]
        all_params = tool.path_params + tool.query_params + tool.body_fields
        types_seen = {p.py_type for p in all_params}
        assert types_seen == {"str", "int", "float", "bool", "list", "dict"}

    def test_pipeline_produces_valid_python(self, tmp_path: Path) -> None:
        project = run_pipeline(
            FIXTURES / "type_matrix_scope.yaml",
            FIXTURES / "type_matrix_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        for py_file in project.rglob("*.py"):
            py_compile.compile(str(py_file), doraise=True)


# ---------------------------------------------------------------------------
# Collision explosion — adversarial param naming
# ---------------------------------------------------------------------------


class TestCollisionResolution:
    @pytest.fixture()
    def plan(self):
        return _load_plan("collision")

    def test_tool_count(self, plan) -> None:
        assert len(plan.tools) == 2

    def test_get_resource_all_unique(self, plan) -> None:
        tool = next(t for t in plan.tools if t.tool_name == "get_resource")
        all_params = tool.path_params + tool.query_params + tool.body_fields
        py_names = [p.py_name for p in all_params]
        assert len(py_names) == len(set(py_names)), f"Duplicate py_names: {py_names}"

    def test_get_resource_cross_location(self, plan) -> None:
        """id in path and query should resolve to id_path / id_query."""
        tool = next(t for t in plan.tools if t.tool_name == "get_resource")
        all_params = tool.path_params + tool.query_params
        id_params = {p.py_name: p.location for p in all_params if "id" in p.py_name}
        assert "id_path" in id_params
        assert "id_query" in id_params

    def test_list_filters_all_unique(self, plan) -> None:
        tool = next(t for t in plan.tools if t.tool_name == "list_filters")
        all_params = tool.path_params + tool.query_params + tool.body_fields
        py_names = [p.py_name for p in all_params]
        assert len(py_names) == len(set(py_names)), f"Duplicate py_names: {py_names}"

    def test_list_filters_triple_collision(self, plan) -> None:
        """a.b, a-b, a[b] should all get unique names."""
        tool = next(t for t in plan.tools if t.tool_name == "list_filters")
        a_b_params = [p for p in tool.query_params if p.py_name.startswith("a_b")]
        assert len(a_b_params) == 3
        originals = {p.original_name for p in a_b_params}
        assert originals == {"a.b", "a-b", "a[b]"}

    def test_list_filters_keyword_collision(self, plan) -> None:
        """from (keyword) and from_ should both get unique names."""
        tool = next(t for t in plan.tools if t.tool_name == "list_filters")
        from_params = [p for p in tool.query_params if p.py_name.startswith("from_")]
        assert len(from_params) == 2
        originals = {p.original_name for p in from_params}
        assert originals == {"from", "from_"}

    def test_pipeline_produces_valid_python(self, tmp_path: Path) -> None:
        project = run_pipeline(
            FIXTURES / "collision_scope.yaml",
            FIXTURES / "collision_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        for py_file in project.rglob("*.py"):
            py_compile.compile(str(py_file), doraise=True)


# ---------------------------------------------------------------------------
# Selective scoping — large spec, narrow scope
# ---------------------------------------------------------------------------


class TestSelectiveScoping:
    def test_only_scoped_tools_generated(self, tmp_path: Path) -> None:
        project = run_pipeline(
            FIXTURES / "selective_scope.yaml",
            FIXTURES / "selective_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        tools_py = project / "src" / "selective_api_mcp" / "api" / "tools.py"
        content = tools_py.read_text()
        # Scoped tools should appear
        assert "get_ep1" in content
        assert "get_ep5" in content
        assert "get_ep10" in content
        # Unscoped tools (including the allOf one) should NOT appear
        assert "get_ep2" not in content
        assert "get_ep21" not in content
        assert "createEp21" not in content

    def test_plan_has_exactly_three_tools(self) -> None:
        plan = _load_plan("selective")
        assert len(plan.tools) == 3
        names = {t.tool_name for t in plan.tools}
        assert names == {"get_ep1", "get_ep5", "get_ep10"}

    def test_generated_code_is_valid_python(self, tmp_path: Path) -> None:
        project = run_pipeline(
            FIXTURES / "selective_scope.yaml",
            FIXTURES / "selective_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        for py_file in project.rglob("*.py"):
            py_compile.compile(str(py_file), doraise=True)


# ---------------------------------------------------------------------------
# Binary responses — image/jpeg endpoint renders the bytes path (#81 Phase 2)
# ---------------------------------------------------------------------------


class TestBinaryResponses:
    @pytest.fixture()
    def plan(self):
        return _load_plan("binary")

    def test_binary_tool_flagged_in_plan(self, plan) -> None:
        photo = next(t for t in plan.tools if t.tool_name == "get_employee_photo")
        assert photo.returns_binary is True
        assert photo.response_content_type == "image/jpeg"

    def test_json_tool_unaffected(self, plan) -> None:
        item = next(t for t in plan.tools if t.tool_name == "get_item")
        assert item.returns_binary is False
        assert item.response_content_type == "application/json"

    def test_generated_code_is_valid_python(self, tmp_path: Path) -> None:
        """End-to-end: run the pipeline and ensure every generated file
        compiles. Guards against JSONDecodeError-at-runtime regressions
        from shipping the JSON path for an image/jpeg endpoint."""
        project = run_pipeline(
            FIXTURES / "binary_scope.yaml",
            FIXTURES / "binary_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        for py_file in project.rglob("*.py"):
            py_compile.compile(str(py_file), doraise=True)

    def test_tools_module_has_both_paths(self, tmp_path: Path) -> None:
        """The generated tools.py must wire the binary tool through
        request_bytes + base64, while leaving the JSON tool on request."""
        project = run_pipeline(
            FIXTURES / "binary_scope.yaml",
            FIXTURES / "binary_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        tools_py = project / "src" / "binary_api_mcp" / "api" / "tools.py"
        content = tools_py.read_text()
        assert "import base64" in content
        assert "request_bytes(" in content
        assert "base64.b64encode" in content
        # JSON path still present for get_item.
        get_item_section = content.split("async def get_item")[1].split("async def")[0]
        assert "self._client.request(" in get_item_section
        assert "-> dict:" in get_item_section

    def test_client_module_has_request_bytes(self, tmp_path: Path) -> None:
        project = run_pipeline(
            FIXTURES / "binary_scope.yaml",
            FIXTURES / "binary_openapi.yaml",
            TEMPLATE_DIR,
            tmp_path,
        )
        client_py = project / "src" / "binary_api_mcp" / "client.py"
        content = client_py.read_text()
        assert "async def request_bytes(" in content
        assert "return response.content" in content
