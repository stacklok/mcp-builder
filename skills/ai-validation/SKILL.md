---
name: ai-validation
description: Review generated MCP server code for correctness against mcp-scope.yaml and OpenAPI spec, then suggest hint-driven polish improvements. Use when a user has generated an MCP server project (Phase 3) and wants to validate it before deployment.
argument-hint: <generated-project-dir> <mcp-scope-yaml> <openapi-spec-path>
---

# AI Validation & Polish Skill

This skill orchestrates Phase 4 of the mcp-builder pipeline: validating deterministically-generated MCP server code for correctness and suggesting hint-driven improvements. It reads the generated project, the `mcp-scope.yaml` that drove generation, and the original OpenAPI spec, then produces a structured validation report and optional polish suggestions with code diffs.

## Startup

Before beginning the workflow:

1. Determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). The repo root is two levels up: `{skill_base_dir}/../..`. Agent files are at `{repo_root}/agents/{agent-name}.md`. Assets are at `{skill_base_dir}/assets/`. Do not share these internal paths with the user.

2. All `uv` and `task` commands must run from `{repo_root}` (where `pyproject.toml` lives).

## Workflow

Given a generated project directory, mcp-scope.yaml, and OpenAPI spec path ($ARGUMENTS), execute the following steps:

1. Collect and verify inputs
2. Pre-read inputs
3. Code validation (agent)
4. Build verification
5. Validation gate (user gate)
6. Polish suggestions (agent)
7. Polish application gate (user gate)
8. Present results

---

### Step 1: Collect and Verify Inputs

1. Parse $ARGUMENTS for three required paths:
   - **Generated project directory** — output from Phase 3 code generation
   - **mcp-scope.yaml** — the scope file that drove generation
   - **OpenAPI spec** — the original spec file

   If fewer than 3 arguments are provided, ask the user for the missing paths.

2. Verify all three paths exist. If any is missing, tell the user and exit.

3. Read the `server.name` from `mcp-scope.yaml`. Derive the module name: replace hyphens with underscores, append `_mcp` (e.g., `google-drive` → `google_drive_mcp`).

4. Verify the generated project has the expected structure by checking for these files:
   - `src/{module_name}/api/tools.py`
   - `src/{module_name}/api/mcp_builder.py`
   - `src/{module_name}/client.py`
   - `deploy/mcpserver.yaml`
   - `pyproject.toml`
   - `Dockerfile`

   If key files are missing, note which ones and continue — the validator will report them as failures.

5. Create a working directory for output files: `{cwd}/validation-output-{date}/`

---

### Step 2: Pre-read Inputs

Read and collect all inputs that will be passed to agents:

1. **Read mcp-scope.yaml** — capture the full content.

2. **Read generated source files** — read the content of each file in the generated project:
   - `src/{module_name}/api/tools.py`
   - `src/{module_name}/api/mcp_builder.py`
   - `src/{module_name}/client.py`
   - `src/{module_name}/models.py` (may not exist if no tools have request bodies)
   - `deploy/mcpserver.yaml`
   - `deploy/mcpexternalauthconfig.yaml` (may not exist if auth.type is none)
   - `deploy/secret.yaml` (may not exist if auth.type is none)
   - `pyproject.toml`
   - `Dockerfile`

   For files that don't exist, note "NOT PRESENT" — the validator will check whether absence is correct.

3. **Read the OpenAPI spec** — capture the full content for cross-referencing.

No analysis happens in this step. This is purely data collection.

---

### Step 3: Code Validation (Agent)

Spawn a **code-validator** sub-agent using the Agent tool:

```
Agent tool parameters:
- subagent_type: [path to code-validator agent: {repo_root}/agents/code-validator.md]
- description: "Validate generated MCP server code"
- prompt: |
    Validate the generated MCP server code for correctness.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/assets/pipeline-context-phase4.md]
    Report template path: [absolute path to {skill_base_dir}/assets/validation-report-template.md]
    Working directory: [absolute path to validation-output/]

    SERVER METADATA:
    Server name: [from YAML server.name]
    Module name: [derived module name]
    Project directory: [absolute path to generated project]

    MCP SCOPE YAML:
    [paste the full content of mcp-scope.yaml]

    GENERATED FILES:
    === src/{module_name}/api/tools.py ===
    [file content]

    === src/{module_name}/api/mcp_builder.py ===
    [file content]

    === src/{module_name}/client.py ===
    [file content]

    === src/{module_name}/models.py ===
    [file content, or "NOT PRESENT"]

    === deploy/mcpserver.yaml ===
    [file content]

    === deploy/mcpexternalauthconfig.yaml ===
    [file content, or "NOT PRESENT (auth.type = none)"]

    === deploy/secret.yaml ===
    [file content, or "NOT PRESENT (auth.type = none)"]

    === pyproject.toml ===
    [file content]

    === Dockerfile ===
    [file content]

    OPENAPI SPEC:
    [paste the full content of the OpenAPI spec]
- mode: acceptEdits
- run_in_background: false
```

The code-validator agent will write `{working_dir}/validation-report.md`.

---

### Step 4: Build Verification

After the code-validator agent completes, run the Docker build check:

```bash
cd {project_dir} && docker build -t {server_name}-mcp:validation-test . 2>&1
```

Record the result:
- **PASS** — build succeeded (exit code 0)
- **FAIL** — build failed (capture the error output)
- **SKIP** — Docker is not available (`command not found` or similar)

Read `{working_dir}/validation-report.md` and append a "Build Verification" row to the report. If the build verification section already exists from the agent's template, update it with the actual result.

---

### Step 5: Validation Gate (USER GATE)

1. Read `{working_dir}/validation-report.md`

2. Present the validation summary to the user:
   - Total checks: X passed, Y failed
   - Build status: PASS/FAIL/SKIP
   - If there are `error`-severity failures, highlight each one prominently

3. Based on the results, use AskUserQuestion to offer choices:

   **If there are error-severity failures:**
   ```
   Validation found {N} error(s) that would cause runtime or deployment failures.

   Options:
   1. Have AI fix the errors (recommended) — spawns an agent to edit the generated code
   2. Fix manually — you fix the errors and re-run the skill later
   3. Proceed to polish anyway — continue despite errors
   ```

   **If all checks pass (no errors):**
   ```
   All validation checks passed.

   Options:
   1. Generate polish suggestions (recommended) — analyze hints for improvements
   2. Done — validation is complete, no polish needed
   ```

**Do NOT proceed past this step until the user responds.**

---

### Step 5b: AI Error Fixing (conditional)

If the user chose "Have AI fix the errors":

1. Spawn a sub-agent to fix the errors:

```
Agent tool parameters:
- description: "Fix validation errors in generated code"
- prompt: |
    Fix the following validation errors in the generated MCP server project.

    PROJECT DIRECTORY: [absolute path]
    MODULE NAME: [module name]

    VALIDATION REPORT:
    [paste the full validation-report.md content]

    MCP SCOPE YAML:
    [paste the full mcp-scope.yaml content]

    For each FAIL item in the Detailed Findings section:
    1. Read the file mentioned
    2. Apply the fix described
    3. Verify the fix is consistent with the YAML and the rest of the codebase

    Only fix items marked FAIL. Do not make other changes.
- mode: acceptEdits
- run_in_background: false
```

2. After the agent completes, re-run validation by looping back to Step 3 (re-read the updated files, re-spawn the code-validator agent).

3. Present the updated results. If errors remain, ask the user again (same choices). Do not loop more than 2 fix attempts — if errors persist after 2 rounds, ask the user to fix manually.

---

### Step 6: Polish Suggestions (Agent)

Spawn a **polish-suggester** sub-agent using the Agent tool:

```
Agent tool parameters:
- subagent_type: [path to polish-suggester agent: {repo_root}/agents/polish-suggester.md]
- description: "Suggest hint-driven code improvements"
- prompt: |
    Analyze the generated MCP server code and suggest improvements based on YAML hints.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/assets/pipeline-context-phase4.md]
    Working directory: [absolute path to validation-output/]
    Validation report path: [absolute path to {working_dir}/validation-report.md]

    SERVER METADATA:
    Server name: [from YAML]
    Module name: [derived module name]
    Project directory: [absolute path]

    MCP SCOPE YAML:
    [paste the full content of mcp-scope.yaml]

    GENERATED FILES:
    [same file listing as Step 3, re-read if files were modified in Step 5b]

    OPENAPI SPEC:
    [paste the full content of the OpenAPI spec]
- mode: acceptEdits
- run_in_background: false
```

The polish-suggester agent will write `{working_dir}/polish-suggestions.md`.

---

### Step 7: Polish Application Gate (USER GATE)

1. Read `{working_dir}/polish-suggestions.md`

2. Present the suggestions to the user:
   - Summary: N suggestions across M categories
   - Each suggestion with its category, priority, affected tool(s), and the code diff
   - If there are no suggestions, skip to Step 8

3. Use AskUserQuestion to offer choices:

   ```
   {N} polish suggestions generated.

   Options:
   1. Have AI apply all suggestions — spawns an agent to edit the generated code
   2. Have AI apply selected suggestions — choose which ones to apply
   3. Review manually — apply the diffs yourself
   4. Skip — no polish needed
   ```

**Do NOT proceed past this step until the user responds.**

---

### Step 7b: AI Polish Application (conditional)

If the user chose to have AI apply suggestions (all or selected):

1. If "selected", ask the user which suggestion IDs to apply (e.g., "P1, P3, P5").

2. Spawn a sub-agent to apply the suggestions:

```
Agent tool parameters:
- description: "Apply polish suggestions to generated code"
- prompt: |
    Apply the following polish suggestions to the generated MCP server project.

    PROJECT DIRECTORY: [absolute path]
    MODULE NAME: [module name]

    SUGGESTIONS TO APPLY:
    [paste the selected suggestions from polish-suggestions.md, each with its
     Before/After code blocks and target file]

    For each suggestion:
    1. Read the target file
    2. Find the "Before" code pattern
    3. Replace it with the "After" code
    4. Verify the change is syntactically valid

    Only apply the listed suggestions. Do not make other changes.
- mode: acceptEdits
- run_in_background: false
```

---

### Step 8: Present Results

Present the user with:

- Path to `{working_dir}/validation-report.md`
- Path to `{working_dir}/polish-suggestions.md` (if generated)
- Summary:
  - Validation: X checks passed, Y failed
  - Build: PASS/FAIL/SKIP
  - Polish: N suggestions generated, M applied (if any)
  - Files modified (if any fixes or polish were applied)

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Project directory doesn't exist | Tell the user, exit |
| Expected files missing from project | Note as missing, continue — validator reports as FAIL |
| mcp-scope.yaml fails to parse | Tell the user, exit |
| Docker not installed | Record build check as SKIP, continue |
| Docker build fails | Record as FAIL, continue to user gate |
| Code-validator agent fails | Present error to user, ask if they want to proceed to manual review |
| Polish-suggester agent fails | Present error to user, note that validation report is still valid |
| Fix agent fails | Present error to user, ask them to fix manually |

## Important Notes

### Sub-Agent Invocation
- Use the Agent tool with the appropriate subagent_type for code-validator and polish-suggester
- Fix/apply agents use inline prompts (no dedicated agent file) since they're straightforward edit tasks
- Always set `run_in_background: false` and `mode: acceptEdits`
- Pass all context in the prompt — agents do not share memory with the orchestrator

### Working Directory
- All output files go in `{cwd}/validation-output-{date}/`
- This includes `validation-report.md` and `polish-suggestions.md`

### Read-Only by Default
- The skill only modifies the generated project if the user explicitly chooses "Have AI fix" or "Have AI apply"
- Validation and suggestion generation are entirely read-only operations
