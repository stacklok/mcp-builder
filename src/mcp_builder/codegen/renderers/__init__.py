"""Renderers that convert a ServerPlan into output files.

Each module in this package is a leaf node in the pipeline: it reads from
the ServerPlan (built by codegen.plan) and produces file content (source code
or YAML). Renderers never access the raw OpenAPI spec directly.

Modules:
    client         — render_client_module() (textwrap.dedent)
    manifests      — render_manifests() (yaml.dump, ToolHive deployment CRDs)
    models         — render_parameter_models() (Jinja2)
    scaffold       — scaffold_project() (copy template + rename)
    server_wiring  — patch_mcp_builder(), patch_app_builder()
    tools          — render_tools_module() (Jinja2)

Naming conventions:
    render_*  — returns source code or YAML as a string
    patch_*   — takes existing source text and returns modified text
    scaffold_* — copies/renames template files on disk
"""
