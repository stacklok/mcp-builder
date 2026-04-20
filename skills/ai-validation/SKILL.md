---
name: ai-validation
description: Validate a generated MCP server project against the mcp-scope.yaml and OpenAPI spec that drove its generation, then suggest hint-driven improvements. Part of the mcp-builder pipeline that transforms an OpenAPI 3.x spec into a ToolHive-ready MCP server across four phases — AI Scoping, Human Review, Deterministic Code Generation, and AI Validation & Polish (this skill). Use when a user has a generated MCP server project (Phase 3 output) and wants to validate it before deployment.
argument-hint: <generated-project-dir> <mcp-scope-yaml> <openapi-spec-path>
---

# AI Validation & Polish Skill

This skill orchestrates Phase 4 of the mcp-builder pipeline: validating deterministically-generated MCP server code for correctness and suggesting hint-driven improvements. The pipeline transforms an OpenAPI spec into a ToolHive-ready MCP server across four phases — AI Scoping (Phase 1) produces a validated `mcp-scope.yaml`, Human Review (Phase 2) refines it, Deterministic Code Generation (Phase 3) scaffolds the server, and this skill (Phase 4) validates the generated code against the YAML and spec, then suggests improvements driven by hints from the scoping phase.

## Startup

Before beginning the workflow:

1. Determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). The repo root is two levels up: `{skill_base_dir}/../..`. Agent files are at `{repo_root}/agents/{agent-name}.md`. Assets are at `{skill_base_dir}/assets/`. Do not share these internal paths with the user.

2. All `uv` and `task` commands must run from `{repo_root}` (where `pyproject.toml` lives).

3. Clone or locate the reference repos that agents need for grounding their checks:

   - **ToolHive** (`stacklok/toolhive`) — CRD schemas, auth patterns. Check if a local clone exists nearby (e.g., sibling directory). If not, clone to a temp directory:
     ```bash
     gh repo clone stacklok/toolhive /tmp/toolhive-ref -- --depth 1
     ```
   - **mcp-template-py** (`stacklok/mcp-template-py`) — the base Python MCP server template. Same approach:
     ```bash
     gh repo clone stacklok/mcp-template-py /tmp/mcp-template-py-ref -- --depth 1
     ```

   Record the absolute paths to both repos. These will be passed to agents.

## Workflow

Given a generated project directory, mcp-scope.yaml, and OpenAPI spec path ($ARGUMENTS), execute the following steps:

1. Collect and verify inputs
2. Code validation (agent)
3. Validation gate (user gate)
4. Polish suggestions (agent)
5. Polish application gate (user gate)
6. Present results

---

### Step 1: Collect and Verify Inputs

1. Parse $ARGUMENTS for three required paths:
   - **Generated project directory** — output from Phase 3 code generation
   - **mcp-scope.yaml** — the scope file that drove generation
   - **OpenAPI spec** — the original spec file

   If fewer than 3 arguments are provided, ask the user for the missing paths.

2. Verify all three paths exist. If any is missing, tell the user and exit.

3. Read the `server.name` from `mcp-scope.yaml`. Derive the module name: replace hyphens with underscores, append `_mcp` (e.g., `google-drive` → `google_drive_mcp`).

4. Verify the generated project has the expected structure by checking these files exist:
   - `src/{module_name}/api/tools.py`
   - `src/{module_name}/api/mcp_builder.py`
   - `src/{module_name}/client.py`
   - `deploy/mcpserver.yaml`
   - `pyproject.toml`
   - `Dockerfile`

   If key files are missing, note which ones and continue — the validator will report them as failures.

5. Create a working directory for output files: `{cwd}/validation-output-{date}/`

---

### Step 2: Code Validation (Agent)

Spawn a **code-validator** sub-agent using the Agent tool. Pass file paths — do NOT read or paste file contents into the prompt. The agent reads everything itself.

```
Agent tool parameters:
- subagent_type: [path to code-validator agent: {repo_root}/agents/code-validator.md]
- description: "Validate generated MCP server code"
- prompt: |
    Validate the generated MCP server code for correctness.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/../ai-scoping/assets/pipeline-context.md]
    Report template path: [absolute path to {skill_base_dir}/assets/validation-report-template.md]
    Working directory: [absolute path to validation-output/]

    SERVER METADATA:
    Server name: [from YAML server.name]
    Module name: [derived module name]

    FILE PATHS:
    Project directory: [absolute path to generated project]
    MCP scope YAML: [absolute path to mcp-scope.yaml]
    OpenAPI spec: [absolute path to spec file]

    REFERENCE REPOS:
    ToolHive repo: [absolute path to toolhive clone]
    mcp-template-py repo: [absolute path to mcp-template-py clone]
- mode: acceptEdits
- run_in_background: false
```

The code-validator agent will read all files, run the Docker build check, and write `{working_dir}/validation-report.md`.

---

### Step 3: Validation Gate

1. Read `{working_dir}/validation-report.md` — pay particular attention to the `Build Verification` row and any error-severity failures.

2. Present the validation summary to the user using the structure below. **Build status is a first-class block, not a footnote** — it must be visible at a glance even when the rest of the report is green.

   ```markdown
   ## Validation Summary

   **Report:** {path to validation-report.md}

   - Total checks: {X} passed, {Y} failed, {Z} skipped

   ### 🏗️ Docker build: {✅ PASS / ❌ FAIL / ⏭️ SKIP}

   {Copy the reason from the Build Verification row's Details column verbatim.
    If the status is FAIL, render any multi-line error output as a fenced code
    block so it stays readable. If the status is SKIP, state the concrete cause
    the validator recorded.}

   **This is not a blocker for proceeding** — polish suggestions and
   deployment review still work regardless of build status. But you
   should know it happened.
   ```

   If there are `error`-severity failures from other checks, list each one prominently under a separate `### ❌ Errors` heading with the check ID, file, and one-line fix description from Detailed Findings.

3. Run the appropriate user gate based on what the report contains:

   **Case A — error-severity failures exist (USER GATE — wait for response):**

   Use AskUserQuestion:
   ```
   Validation found {N} error(s) that would cause runtime or deployment failures.
   {If build also failed/skipped: "Build status: FAIL/SKIP — {one-line reason}."}

   Options:
   1. Have AI fix the errors — spawns an agent to edit the generated code, then re-validates
   2. Proceed to polish — continue to polish suggestions despite errors (all issues presented together)
   3. Fix manually — you fix the errors and re-run the skill later
   ```

   **Do NOT proceed past this step until the user responds.**

   **Case B — no error-severity failures, but build is FAIL or SKIP (USER GATE — wait for response):**

   Use AskUserQuestion:
   ```
   All code-correctness checks passed, but the Docker build is {FAIL / SKIP}.

   Reason: {reason copied from the Build Verification row}

   This is fine — we can keep going. What would you like to do?

   Options:
   1. Retry the build — re-run the build step (useful if you just fixed the underlying issue, e.g. ran `docker login`)
   2. Have AI investigate / fix — spawn an agent to diagnose the build failure and attempt a fix, then re-validate (only offer this when FAIL, not SKIP)
   3. Acknowledge and continue to polish — accept the {FAIL / SKIP}, proceed to Step 4
   4. Stop here — exit the skill; you'll rebuild in an authenticated environment later
   ```

   For SKIP, drop option 2 (there's nothing to fix if the build wasn't attempted). Offer only retry / acknowledge / stop.

   If the user picks "Retry the build", re-run the code-validator agent (Step 2) but pass an additional directive in the prompt: `"RE-RUN MODE: only re-run the Docker build check; reuse the existing report for other checks, updating only the build row and the Summary counts."`. Then loop back to this step with the updated report.

   If the user picks "Have AI investigate / fix", spawn the fix agent (Step 3b) with a note that the Docker build is the thing to fix — after it completes, re-run validation.

   **Do NOT proceed past this step until the user responds.**

   **Case C — no errors and build is PASS:**

   Tell the user all checks passed (including build) and automatically proceed to Step 4 (polish suggestions). No gate needed.

---

### Step 3b: AI Error Fixing (conditional)

If the user chose "Have AI fix the errors":

1. Spawn a sub-agent to fix the errors. Pass file paths — do NOT paste file contents.

```
Agent tool parameters:
- description: "Fix validation errors in generated code"
- prompt: |
    Fix the validation errors in the generated MCP server project.

    PROJECT DIRECTORY: [absolute path]
    MODULE NAME: [module name]

    Read the validation report at: [absolute path to {working_dir}/validation-report.md]
    Read the mcp-scope.yaml at: [absolute path to mcp-scope.yaml]

    For each FAIL item in the Detailed Findings section:
    1. Read the file mentioned in the finding
    2. Apply the fix described
    3. Verify the fix is consistent with the YAML and the rest of the codebase

    Only fix items marked FAIL. Do not make other changes.
- mode: acceptEdits
- run_in_background: false
```

2. After the agent completes, re-run validation by looping back to Step 2 (re-spawn the code-validator agent).

3. Present the updated results. If errors remain, ask the user again (same choices). Do not loop more than 2 fix attempts — if errors persist after 2 rounds, ask the user to fix manually.

---

### Step 4: Polish Suggestions (Agent)

Spawn a **polish-suggester** sub-agent using the Agent tool. Pass file paths — do NOT read or paste file contents into the prompt.

```
Agent tool parameters:
- subagent_type: [path to polish-suggester agent: {repo_root}/agents/polish-suggester.md]
- description: "Suggest hint-driven code improvements"
- prompt: |
    Analyze the generated MCP server code and suggest improvements based on YAML hints.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/../ai-scoping/assets/pipeline-context.md]
    Working directory: [absolute path to validation-output/]
    Validation report path: [absolute path to {working_dir}/validation-report.md]

    SERVER METADATA:
    Server name: [from YAML]
    Module name: [derived module name]

    FILE PATHS:
    Project directory: [absolute path to generated project]
    MCP scope YAML: [absolute path to mcp-scope.yaml]
    OpenAPI spec: [absolute path to spec file]

    REFERENCE REPOS:
    ToolHive repo: [absolute path to toolhive clone]
    mcp-template-py repo: [absolute path to mcp-template-py clone]
- mode: acceptEdits
- run_in_background: false
```

The polish-suggester agent will read all files and write `{working_dir}/polish-suggestions.md`.

---

### Step 5: Polish Application Gate (USER GATE)

1. Read `{working_dir}/polish-suggestions.md`.

2. Present the suggestions to the user. **Do not flatten the report into one-line bullets** — the user needs to be able to judge severity and decide fix-or-skip from the chat output alone. Render the report in chat using the format below.

   **2a. Overview block** — a severity-count table plus an at-a-glance index table:

   ```markdown
   ## Polish Suggestions ({N} total)

   **Report:** {path to polish-suggestions.md}

   | Severity | Count | What it means |
   |----------|-------|---------------|
   | 🔴 blocker  | {N} | Functional bug — MUST fix before deploy |
   | 🟠 high     | {N} | LLM likely to misuse the tool without this |
   | 🟡 medium   | {N} | Robustness / quality improvement |
   | ⚪ low      | {N} | Minor polish |

   | #  | Severity | Category | Tool(s) | Summary |
   |----|----------|----------|---------|---------|
   | P1 | 🔴 blocker | response-shaping | `export_file` | Client `.json()` breaks raw-bytes endpoints |
   | P2 | 🟠 high    | pagination       | `list_files`  | Docstring missing nextPageToken guidance    |
   | …  | …        | …        | …       | …       |
   ```

   **2b. Per-suggestion detail** — for EACH suggestion in the report, render:

   ```markdown
   ### P{n}: {title}  —  {severity emoji} {severity}

   | Field | Value |
   |-------|-------|
   | Category | {category} |
   | Affected | `{tool(s)}` |
   | File(s)  | `{paths}` |
   | Hint     | {hint text or "AI-analyzed"} |

   **Problem:** {copy the Problem paragraph from the report verbatim}

   **Impact if unfixed:** {copy verbatim}

   **Proposed fix:** {copy verbatim}

   <details><summary>View diff</summary>

   ```python
   # Before
   {before snippet}
   ```

   ```python
   # After
   {after snippet}
   ```
   </details>
   ```

   **Required fields per suggestion:** severity, category, affected tool(s), file(s), problem, impact, proposed fix. If the report is missing any of these fields, say so explicitly to the user instead of silently omitting — it means the polish-suggester agent produced an incomplete suggestion and should be re-run.

   **Ordering:** render blocker suggestions first, then high, then medium, then low. Within a severity tier, preserve the P-number order from the report.

   **Length:** do not truncate Problem / Impact / Proposed fix — they are the whole point. DO wrap long diffs in `<details>` so the chat stays scannable.

   If there are no suggestions, say so briefly and skip to Step 6.

3. Use AskUserQuestion to offer choices:

   ```
   {N} polish suggestions generated ({B} blocker, {H} high, {M} medium, {L} low).

   Options:
   1. Have AI apply all suggestions — spawns an agent to edit the generated code
   2. Have AI apply selected suggestions — choose which ones to apply (e.g. "P1, P3")
   3. Review manually — apply the diffs yourself
   4. Skip — no polish needed
   ```

   If there are any `blocker` suggestions, explicitly note in the question prompt that skipping them will likely leave the server broken at runtime.

**Do NOT proceed past this step until the user responds.**

---

### Step 5b: AI Polish Application (conditional)

If the user chose to have AI apply suggestions (all or selected):

1. If "selected", ask the user which suggestion IDs to apply (e.g., "P1, P3, P5").

2. Spawn a sub-agent to apply the suggestions. Pass file paths — do NOT paste suggestion contents.

```
Agent tool parameters:
- description: "Apply polish suggestions to generated code"
- prompt: |
    Apply polish suggestions to the generated MCP server project.

    PROJECT DIRECTORY: [absolute path]
    MODULE NAME: [module name]

    Read the suggestions at: [absolute path to {working_dir}/polish-suggestions.md]
    [If selected: "Only apply suggestions: P1, P3, P5"]

    For each suggestion to apply:
    1. Read the target file listed in the suggestion
    2. Find the "Before" code pattern
    3. Replace it with the "After" code
    4. Verify the change is syntactically valid

    Only apply the listed suggestions. Do not make other changes.
- mode: acceptEdits
- run_in_background: false
```

---

### Step 6: Present Results

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
| Reference repos can't be cloned | Warn the user, continue — agent checks will be less grounded but still functional |
| Docker not installed | Agent records build check as SKIP, continues |
| Docker build fails | Agent records as FAIL, continues to user gate |
| Code-validator agent fails | Present error to user, ask if they want to proceed to manual review |
| Polish-suggester agent fails | Present error to user, note that validation report is still valid |
| Fix agent fails | Present error to user, ask them to fix manually |

## Important Notes

### Sub-Agent Invocation
- Use the Agent tool with the appropriate subagent_type for code-validator and polish-suggester
- Fix/apply agents use inline prompts (no dedicated agent file) since they're straightforward edit tasks
- Always set `run_in_background: false` and `mode: acceptEdits`
- Pass file paths in the prompt — agents read files themselves. Never paste file contents into agent prompts.

### Working Directory
- All output files go in `{cwd}/validation-output-{date}/`
- This includes `validation-report.md` and `polish-suggestions.md`

### Read-Only by Default
- The skill only modifies the generated project if the user explicitly chooses "Have AI fix" or "Have AI apply"
- Validation and suggestion generation are entirely read-only operations
