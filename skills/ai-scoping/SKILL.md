---
name: ai-scoping
description: Transform an OpenAPI 3.x spec and workflow descriptions into a validated mcp-scope.yaml. Guides the AI through spec analysis, semantic grouping, tool naming, description writing, and auth detection with interactive user gates. Use when a user wants to scope an API for MCP server generation.
argument-hint: <openapi-spec-path>
---

# AI Scoping Skill

This skill orchestrates Phase 1 of the mcp-builder pipeline: transforming an OpenAPI spec and workflow descriptions into a validated `mcp-scope.yaml` and a `scoping-summary.md` documenting the AI's reasoning.

## Startup

Before beginning the workflow, determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). Agent directories are at `{skill_base_dir}/agents/{agent-name}`. You will need these paths when spawning sub-agents. Do not share these with the user.

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

2. Collect workflow descriptions from the user. **Minimum 3 workflows required.** Workflows describe what users need to accomplish with the API — they should capture different personas or use cases to ensure broad coverage of the API surface.

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

3. Optionally accept an auth hint if the user mentions the spec's auth is unusual or incomplete.

4. Create a working directory for intermediate files: `{cwd}/scoping-output/`

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
- subagent_type: [path to spec-analyzer agent]
- description: "Analyze OpenAPI spec"
- prompt: |
    Analyze the following OpenAPI spec data and propose semantic endpoint groups.

    CONTEXT:
    Base directory: [absolute path to the spec-analyzer agent's directory]
    Working directory: [absolute path to scoping-output/]

    WORKFLOWS:
    1. [workflow 1]
    2. [workflow 2]
    3. [workflow 3]
    ...

    SPEC ANALYSIS JSON:
    [paste the full JSON output from mcp-builder analyze]
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
- subagent_type: [path to endpoint-scoper agent]
- description: "Scope tools for selected groups"
- prompt: |
    Perform tool scoping for the selected endpoint groups: naming, descriptions, hints.

    CONTEXT:
    Base directory: [absolute path to the endpoint-scoper agent's directory]
    Working directory: [absolute path to scoping-output/]
    Server name: [derived from API — e.g., "google-drive"]
    Base URL: [from analyze JSON — e.g., "https://www.googleapis.com/drive/v3"]

    WORKFLOWS:
    1. [workflow 1]
    2. [workflow 2]
    3. [workflow 3]
    ...

    SELECTED GROUPS AND ENDPOINTS:
    [paste the filtered endpoint data for selected groups only — include method, path,
     operationId, summary, description, parameters with types/descriptions, tags,
     deprecated status, and request body info for each endpoint]
- mode: acceptEdits
- run_in_background: false
```

The endpoint-scoper agent will:
- Filter out unnecessary endpoints within selected groups
- Assign tool names following `verb_noun` convention (snake_case, unique, <=40 chars)
- Write LLM-optimized descriptions for tools and parameters
- Add hints for pagination, large responses, quirks
- Write `tool-scoping.md` to the working directory

---

### Step 5: Tool Approval (USER GATE)

Once the endpoint-scoper agent completes:

1. Read `{working_dir}/tool-scoping.md`
2. Present to the user:
   - **Dropped endpoints**: which endpoints were filtered out and why
   - **Tool list**: for each tool, show the tool name, endpoint, description, parameters, and hints
   - **Renamed tools**: highlight any tools where the name was changed from the original operationId
   - **Inferred descriptions**: flag any descriptions that were inferred (not from the spec)
3. Ask the user to approve the tool list or request changes

**Do NOT proceed to Step 6 until the user approves.**

If the user requests changes:
- For minor edits (rename a tool, tweak a description), apply them directly
- For significant rework (add/remove multiple tools, restructure groups), re-spawn the endpoint-scoper agent with updated instructions

---

### Step 6: Output Assembly

The orchestrator handles this step directly — no sub-agent needed.

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

Build the YAML following the MCPScope schema exactly. Reference the structure in `e2e/fixtures/real/google_drive.yaml` for formatting conventions:

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

Write the YAML to `{cwd}/mcp-scope.yaml`.

#### 6.4: Validate

Run validation:

```bash
uv run mcp-builder validate mcp-scope.yaml --spec <openapi-spec-path>
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

Write the filled template to `{cwd}/scoping-summary.md`.

#### 6.6: Present Results

Present the user with:
- Path to the generated `mcp-scope.yaml`
- Path to the generated `scoping-summary.md`
- Quick summary: N tools across M groups, auth type detected
- Reminder that Phase 2 (human review) should review the YAML before code generation

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
- All intermediate files go in `{cwd}/scoping-output/`
- Final outputs (`mcp-scope.yaml`, `scoping-summary.md`) go in `{cwd}/`
- The working directory can be cleaned up after successful completion

### Reference Examples
- `e2e/fixtures/real/google_drive.yaml` — 5 tools, 2 groups, OAuth bearer auth
- `e2e/fixtures/real/github.yaml` — 8 tools, 3 groups, OAuth bearer auth
- These show the target quality and format for the generated YAML
