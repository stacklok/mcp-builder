"""Renderers that convert a ServerPlan into output files.

Each module in this package is a leaf node in the pipeline: it reads from
the ServerPlan (built by codegen.plan) and produces file content (source code
or YAML). Renderers never access the raw OpenAPI spec directly.

Naming conventions:
    render_*  — returns source code or YAML as a string
    patch_*   — takes existing source text and returns modified text
    scaffold_* — copies/renames template files on disk
"""
