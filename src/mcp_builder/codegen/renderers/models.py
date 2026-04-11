"""Render Pydantic parameter models for tool request bodies.

Pipeline stage: rendering (ServerPlan → source code string).
Called by: the pipeline orchestrator after scaffold_project().

Generates one Pydantic model per tool that has body fields. Tools with
only path/query parameters (no request body) produce no model.

Template: renderers/templates/parameter_model.py.jinja2
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from mcp_builder.codegen.plan import ServerPlan
from mcp_builder.codegen.renderers.escape import escape_python_string

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_parameter_models(plan: ServerPlan) -> str:
    """Generate parameter model classes for tools with request bodies.

    Pipeline stage: rendering (plan → source code).
    Called by: the pipeline orchestrator.

    Only tools with non-empty body_fields produce a model class.
    The class is named ``{ToolClassName}Params`` (e.g., ``CreateItemParams``).

    Args:
        plan: The server plan containing tool definitions.

    Returns:
        Python source code string with Pydantic model classes,
        or an empty string if no tools have body fields.
    """
    tools_with_body = [t for t in plan.tools if t.body_fields]
    if not tools_with_body:
        return ""

    env = Environment(  # nosec B701 — generating Python source, not HTML
        loader=FileSystemLoader(_TEMPLATES_DIR),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["py_string"] = escape_python_string
    template = env.get_template("parameter_model.py.jinja2")
    return template.render(tools=tools_with_body)
