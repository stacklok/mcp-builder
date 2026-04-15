---
name: ai-scoping
description: Transform an OpenAPI 3.x spec and workflow descriptions into a validated mcp-scope.yaml that ultimately gets used to generate an MCP server. Guides the AI through spec analysis, semantic grouping, tool naming, description writing, and auth detection with interactive user gates. Use when a user wants to scope an API for MCP server generation.
argument-hint: <openapi-spec-path>
---

# AI Scoping Skill

This skill orchestrates Phase 1 of the mcp-builder pipeline: transforming an OpenAPI spec and workflow descriptions into a validated `mcp-scope.yaml` and a `scoping-summary.md` documenting the AI's reasoning. The `scoping-summary.md` provides a human-readable explanation of the AI's decisions used in Phase 2 for the human to approve the MCP scoping doc. Once approved, the `mcp-scope.yaml` serves as the contract for deterministic code generation in Phase 3 that generates an MCP server. 

## Startup

Before beginning the workflow:

1. Determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). The repo root is two levels up: `{skill_base_dir}/../..`. Agent files are at `{repo_root}/agents/{agent-name}.md`. Assets are at `{skill_base_dir}/assets/`. Do not share these internal paths with the user.

2. All `uv` and `task` commands must run from `{repo_root}` (where `pyproject.toml` lives).

3. Ensure the JSON schema is current by running from `{repo_root}`:
   ```bash
   task generate-schema
   ```
   This writes `mcp-scope-schema.json` and prints the absolute path. You will need this path for validation in Step 6.

## Workflow

Given an OpenAPI spec path ($ARGUMENTS), execute the following steps:

1. Collect inputs
2. Spec analysis (deterministic extraction + agent)
3. Group selection (user gate)
4. Tool scoping (agent)
5. Tool approval (user gate)
6. Output assembly

---

### Step 1: Collect Inputs

1. Verify the OpenAPI spec file exists at the provided path. If it does not exist, tell the user and exit.

2. Collect workflow descriptions from the user. **Minimum 3 workflows required.** Workflows describe what users need to accomplish with the API — they should capture different personas or use cases to ensure broad coverage of the API surface. Iterate with the user until you have at least 3 workflows.

   If the user provided workflows alongside the spec path, count them. If fewer than 3, use AskUserQuestion to ask for more:

   ```
   The scoping skill requires at least 3 workflow descriptions to ensure good
   API surface coverage. Each workflow should describe a specific task a user
   performs with this API, from a specific persona's perspective.

   Example workflows for Google Drive:
   - "Engineers search for and read design docs and specs"
   - "Team members create shared documents and leave review comments"
   - "Managers organize files into project folders and manage access"

   Please provide your workflow descriptions (at least 3).
   ```

3. Ask the user about authentication requirements. Add an auth hint if the user talks about the spec's auth.

4. Create a working directory for intermediate files: `{cwd}/scoping-output-{date}/`

---

### Step 2: Spec Analysis

#### 2.1: Run deterministic extraction

Run the CLI to parse the spec into structured JSON:

```bash
uv run mcp-builder analyze <spec-path>
```

This outputs JSON with all endpoints, security schemes, and quality metrics. Capture the full output.

If the command fails (invalid spec, unsupported format), present the error to the user and exit.

Save the JSON output to `{working_dir}/analyze.json` for reference.

#### 2.2: Spawn spec-analyzer agent

Spawn a **spec-analyzer** sub-agent using the Agent tool:

```
Agent tool parameters:
- subagent_type: [path to spec-analyzer agent: {repo_root}/agents/spec-analyzer.md]
- description: "Analyze OpenAPI spec"
- prompt: |
    Analyze the following OpenAPI spec data and propose semantic endpoint groups.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/assets/pipeline-context.md]
    Working directory: [absolute path to scoping-output/]

    WORKFLOWS:
    1. [workflow 1]
    2. [workflow 2]
    3. [workflow 3]
    ...

    SPEC ANALYSIS JSON PATH:
    [absolute path to {working_dir}/analyze.json]
- mode: acceptEdits
- run_in_background: false
```

The spec-analyzer agent will:
- Assess spec quality (description coverage, flagged issues)
- Propose semantic endpoint groups based on tags, path prefixes, and domain semantics
- Annotate each group with workflow relevance
- Write `spec-analysis.md` to the working directory

---

### Step 3: Group Selection (USER GATE)

Once the spec-analyzer agent completes:

1. Read `{working_dir}/spec-analysis.md`
2. Present the quality report to the user
3. Present all proposed groups in a clear format:
   - Group name and description
   - Number of endpoints in the group
   - Workflow relevance rating (high/medium/low) with brief reason
4. Recommend which groups to include based on workflow alignment (suggest all high-relevance groups, optionally medium)
5. Ask the user which groups to include using AskUserQuestion

**Do NOT proceed to Step 4 until the user has selected their groups.**

After selection, extract the endpoint details for the selected groups from `spec-analysis.md`. You will pass this filtered data to the endpoint-scoper agent.

---

### Step 4: Tool Scoping

Spawn an **endpoint-scoper** sub-agent using the Agent tool:

```
Agent tool parameters:
- subagent_type: [path to endpoint-scoper agent: {repo_root}/agents/endpoint-scoper.md]
- description: "Scope tools for selected groups"
- prompt: |
    Perform tool scoping for the selected endpoint groups: naming, descriptions, hints.

    CONTEXT:
    Pipeline context path: [absolute path to {skill_base_dir}/assets/pipeline-context.md]
    Working directory: [absolute path to scoping-output/]
    Server name: [derived from API — e.g., "google-drive"]
    Base URL: [from analyze JSON — e.g., "https://www.googleapis.com/drive/v3"]
    OpenAPI spec file path: [absolute path to the downloaded OpenAPI spec file]

    WORKFLOWS:
    1. [workflow 1]
    2. [workflow 2]
    3. [workflow 3]
    ...

    SPEC ANALYSIS PATH:
    [absolute path to {working_dir}/spec-analysis.md]

    SELECTED GROUPS:
    [comma-separated list of selected group names]
- mode: acceptEdits
- run_in_background: false
```

The endpoint-scoper agent will:
- Flag questionable endpoints for user review (does NOT auto-remove anything)
- Assign tool names — keeping originals when possible, renaming only bad ones
- Write LLM-optimized descriptions focused on separability between tools
- Add hints for pagination, large responses, quirks
- Write `tool-scoping.md` to the working directory

---

### Step 5: Tool Approval (USER GATE)

Once the endpoint-scoper agent completes:

1. Read `{working_dir}/tool-scoping.md`
2. Present to the user:
   - **Flagged endpoints**: which endpoints are flagged for potential exclusion and why — the user decides whether to remove them
   - **Tool list**: for each tool, show the tool name, endpoint, description, parameters, and hints
   - **Renamed tools**: highlight any tools where the name was changed from the original operationId
3. Ask the user to approve the tool list or request changes (including which flagged endpoints to remove, if any)

**Do NOT proceed to Step 6 until the user approves.**

If the user requests changes:
- For minor edits (rename a tool, tweak a description), apply them directly
- For significant rework (add/remove multiple tools, restructure groups), re-spawn the endpoint-scoper agent with updated instructions

---

### Step 6: Output Assembly

#### 6.1: Auth Detection

Read the `security_schemes` from `{working_dir}/analyze.json` and map to MCPScope auth types:

| OpenAPI Security Scheme | MCPScope `auth.type` | Notes |
|------------------------|---------------------|-------|
| `oauth2` (authorization code flow) | `oauth_bearer` | Extract issuer from token URL domain. Extract scopes from the flow definition. |
| `http` (bearer) | `oauth_bearer` | Static token pattern. Issuer may need user input. |
| `apiKey` (header: `X-API-Key`, `Authorization`) | `api_key` | |
| `apiKey` (query parameter) | `none` | **Not supported** — flag in notes |
| `http` (basic) | `none` | **Not supported** — flag in notes |
| No security schemes | `none` | |

If multiple security schemes exist, select the most ToolHive-compatible one and document alternatives in `auth.notes`.

For OAuth scopes: pull from the spec when available. If scopes look incomplete or are missing, add a note flagging this for human review.

Present the auth detection result to the user for confirmation before assembling the YAML.

#### 6.2: Determine Server Metadata

Derive the following from the analyze JSON and user context:
- `server.name`: DNS-label version of the API name (lowercase, hyphens, e.g., `google-drive`). Must match regex `[a-z0-9]([a-z0-9-]*[a-z0-9])?` and be <=63 chars.
- `server.description`: One-line description of what the MCP server does
- `spec.source`: The original spec path or URL
- `spec.format`: `openapi3` or `openapi3.1` (from analyze JSON)
- `spec.base_url`: From analyze JSON
- `spec.total_endpoints`: Total count from analyze JSON
- `spec.scoped_endpoints`: Count of tools in the approved list

#### 6.3: Assemble `mcp-scope.yaml`

Build the YAML following the MCPScope schema exactly. The formal JSON schema was generated when you ran `task generate-schema`.

```yaml
version: "1"

server:
  name: {server_name}
  description: "{description}"

spec:
  source: "{source}"
  format: {format}
  base_url: "{base_url}"
  total_endpoints: {total}
  scoped_endpoints: {scoped}

workflows:
  - "{workflow 1}"
  - "{workflow 2}"
  - "{workflow 3}"

groups:
  - name: {group-name}
    description: "{group description}"
    tools:
      - tool_name: {name}
        endpoint: {METHOD} {/path}
        description: >
          {LLM-optimized description}
        parameters:
          - name: {param_name}
            description: "{param description}"
            required: {true|false}
        hints:
          - "{hint}"

auth:
  type: {oauth_bearer|api_key|none}
  oauth:  # only if type is oauth_bearer
    issuer: "{issuer_url}"
    scopes:
      - {scope}
  notes: >
    {auth notes — how the auth works, any caveats}
```

Write the YAML to `{working_dir}/mcp-scope.yaml`.

#### 6.4: Validate

Run validation from the working directory:

```bash
uv run mcp-builder validate {working_dir}/mcp-scope.yaml --spec <openapi-spec-path>
```

This checks:
- Schema compliance (tool names unique, snake_case, <=40 chars; server name is DNS label; auth config valid)
- Cross-validation (every endpoint in the scope exists in the spec's paths)

If validation fails:
1. Read the error output
2. Fix the YAML (common issues: tool name too long, endpoint path doesn't match spec, missing required auth config)
3. Re-validate
4. Repeat up to 3 times. If still failing after 3 attempts, present the errors to the user and ask for help.

#### 6.5: Write Scoping Summary

Read the template at `{skill_base_dir}/assets/scoping-summary-template.md` and fill it in with:
- Quality report from spec-analysis.md
- Group inclusion/exclusion decisions and rationale
- Tool name changes (original -> new) with rationale
- Inferred descriptions flagged for review
- Auth detection reasoning
- Any flagged issues for Phase 2 human review

Write the filled template to `{working_dir}/scoping-summary.md`.

#### 6.6: Present Results

Read `{working_dir}/scoping-summary.md` and present the user with a comprehensive completion summary:

**What was generated:**
- Server name and description
- N tools across M groups (list each group name with its tool count)
- Auth type detected (with issuer if OAuth)

**Key decisions made:**
- Tools renamed from their original operationId (original → new, with one-line rationale), or "No tools renamed" if all kept originals
- Endpoints that were flagged and their disposition (kept or excluded)
- Descriptions that were inferred (not sourced from the spec) and should be reviewed for accuracy

**Parameter highlights:**
- For each tool with explicit parameters in the YAML: note how many parameters were included vs. how many the spec defines, and list any excluded parameters
- Flag any tools where all spec parameters were kept without curation

**Phase 2 review checklist:**
- Pull the "Flagged for Phase 2 Review" checklist items from `scoping-summary.md` and present them inline so the user sees what needs attention
- Remind the user that Phase 2 (human review) should review the YAML before code generation

**Output files:**
- Path to `mcp-scope.yaml`
- Path to `scoping-summary.md`

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| `mcp-builder analyze` fails | Present error to user, exit |
| Spec has 500+ endpoints | Proceed normally — spec-analyzer handles large catalogs via grouping |
| Spec has no descriptions | Proceed — endpoint-scoper infers descriptions and flags 100% for review |
| Auth scheme unsupported | Set auth type to `none`, flag in notes and scoping summary |
| Validation fails after 3 retries | Present errors to user, ask for manual fix |
| User rejects groups/tools repeatedly | Apply changes and re-present; do not loop indefinitely |

## Important Notes

### Sub-Agent Invocation
- Use the Agent tool with the appropriate subagent_type to spawn sub-agents
- Always set `run_in_background: false` and `mode: acceptEdits` so agents can interact with the user if needed
- Pass all context in the prompt CONTEXT section — agents do not share memory with the orchestrator

### Working Directory
- All files (intermediate and final) go in `{cwd}/scoping-output/`
- This includes `analyze.json`, `spec-analysis.md`, `tool-scoping.md`, `mcp-scope.yaml`, and `scoping-summary.md`

### Reference Examples
- `e2e/fixtures/real/google_drive.yaml` — 5 tools, 2 groups, OAuth bearer auth
- `e2e/fixtures/real/github.yaml` — 8 tools, 3 groups, OAuth bearer auth
