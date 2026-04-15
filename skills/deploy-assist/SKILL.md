---
name: deploy-assist
description: Place generated MCP server deployment manifests into a cluster repo, fill in placeholders by inferring values from existing cluster configuration, and explain remaining manual steps. Use when you have a generated MCP server project and a cluster repo where you want to deploy it.
argument-hint: <generated-project-dir> <cluster-repo-path>
---

# Deploy Assist Skill

This skill handles the last mile of the mcp-builder pipeline: placing configured deployment manifests into a cluster repo. The pipeline transforms an OpenAPI spec into a ToolHive-ready MCP server across four phases — AI Scoping (Phase 1) produces a validated `mcp-scope.yaml`, Human Review (Phase 2) refines it, Deterministic Code Generation (Phase 3) scaffolds the complete server project, and AI Validation & Polish (Phase 4) verifies the generated code. This skill sits after that pipeline: it takes the generated project's deployment manifests, reads a cluster repo to understand its structure and environment, copies the manifests into the right location with placeholders filled, and explains what the user still needs to do.

The container image is assumed to already be built and pushed to a registry. This skill does not guide through docker build/push or run kubectl commands.

## Pipeline Context

Before starting, read `{skill_base_dir}/../ai-validation/assets/pipeline-context-phase4.md` for full pipeline context — it describes what mcp-builder is, the four phases, what the generated project looks like, what `mcp-scope.yaml` contains, and the deployment manifest structure with placeholder values. This skill's focus is the `deploy/` directory described in that doc.

## Startup

Before beginning the workflow:

1. Determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). The repo root is two levels up: `{skill_base_dir}/../..`. Do not share these internal paths with the user.

## Workflow

Given a generated project directory and a cluster repo path ($ARGUMENTS), execute the following steps:

1. Collect and verify inputs
2. Understand the cluster repo
3. Confirm inferred values (user gate)
4. Copy and configure manifests
5. Explain what's left

---

### Step 1: Collect and Verify Inputs

1. Parse $ARGUMENTS for two required paths:
   - **Generated project directory** — the Phase 3 output (e.g., `~/code/google-drive-mcp/`)
   - **Cluster repo path** — the repo where deployment manifests live (e.g., `~/code/poc-demo-deploy/`)

   If fewer than 2 arguments are provided, ask the user for the missing paths.

2. Verify the generated project directory exists and contains a `deploy/` subdirectory.

3. Catalog which deployment manifests exist in `deploy/`:
   - `mcpserver.yaml` — **must exist**. If missing, tell the user and exit.
   - `ingress.yaml` — expected but not fatal if missing.
   - `mcpexternalauthconfig.yaml` — present only if auth is configured.
   - `secret.yaml` — present only for api_key auth.

4. Read `deploy/mcpserver.yaml` and extract the server name from `metadata.name`.

5. Verify the cluster repo path exists.

---

### Step 2: Understand the Cluster Repo

Explore the cluster repo to answer three questions. Do not assume any particular repo structure — every cluster repo is organized differently.

**Question 1: Where should the new manifests go?**

Explore the repo's directory layout. Look for how existing services, apps, or MCP servers are organized. There is no single pattern — it might be directories per app, per namespace, per environment, or something else entirely. Understand the organizational pattern and determine where a new MCP server's manifests should be placed to be consistent with the rest of the repo.

**Question 2: What values should fill the placeholders?**

The generated manifests contain these placeholders that need real values:

| Placeholder | Files it appears in |
|---|---|
| `REPLACE_ME_DOMAIN` | mcpserver.yaml, ingress.yaml, mcpexternalauthconfig.yaml |
| `REPLACE_ME_OTEL_ENDPOINT` | mcpserver.yaml |
| `{server_name}-mcp:latest` (image needs registry prefix) | mcpserver.yaml |

The cluster repo likely contains existing deployments, config files, or values files that reveal the correct domain, OTEL endpoint, container registry, and namespace for this environment. Find them however makes sense for this repo — they might be in Kubernetes manifests, Helm values, Terraform configs, Kustomize overlays, environment files, or documentation.

**Question 3: How does deployment work here?**

Determine the deployment mechanism: Flux, ArgoCD, Helm, plain `kubectl apply`, or something else. This shapes the final guidance about how the user should trigger deployment after the manifests are in place.

---

### Step 3: Confirm Inferred Values (USER GATE)

Present what you found to the user:

1. **Server name** (from the generated project)
2. **Target directory** in the cluster repo where manifests will be placed
3. **Inferred values:**
   - Namespace
   - Container registry prefix (for the image reference)
   - Domain (for `REPLACE_ME_DOMAIN`)
   - OTEL endpoint (for `REPLACE_ME_OTEL_ENDPOINT`)
4. **Auth type** detected from the generated manifests (oauth_bearer / api_key / none)
5. **Deployment mechanism** (Flux, ArgoCD, plain manifests, etc.)
6. **Files to copy** (list of manifests from `deploy/`)

If any values could not be inferred from the cluster repo, ask the user to provide them.

**Do NOT proceed until the user confirms the values and target location.**

---

### Step 4: Copy and Configure Manifests

Create the target directory in the cluster repo if it does not exist.

For each manifest in the generated project's `deploy/` directory, read the file, perform the replacements below, and write it to the target directory.

**mcpserver.yaml:**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain
- Replace `REPLACE_ME_OTEL_ENDPOINT` with the confirmed OTEL endpoint (match the format expected by the template — typically `host:port` without protocol prefix)
- Update `spec.image` from `{server_name}-mcp:latest` to `{registry_prefix}{server_name}-mcp:latest`
- Update `metadata.namespace` if it differs from the confirmed namespace

**ingress.yaml:**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain
- Update `metadata.namespace` if needed
- Adjust annotations or `ingressClassName` if the cluster repo's existing Ingress resources use a different pattern

**mcpexternalauthconfig.yaml (if present):**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain
- Update `metadata.namespace` if needed
- **Leave `clientId: REPLACE_ME` as-is** — this is a secret the user must fill in

**secret.yaml (if present):**
- Update `metadata.namespace` if needed
- **Leave `token: REPLACE_ME` as-is** — this is a secret the user must fill in

If the cluster repo has other files that need updating to pick up the new manifests (e.g., a Kustomization file that lists resources, an ArgoCD Application, a Flux Kustomization), note this but do not modify them automatically — flag it for the user in Step 5.

---

### Step 5: Explain What's Left

Present a structured summary to the user.

**What was done:**
- List each file copied with its destination path in the cluster repo
- List each placeholder that was replaced and what value was used
- Show the final `spec.image` value so the user can verify the registry path

**What the user still needs to do:**

Present a checklist tailored to the auth type and deployment mechanism:

*Secret values (auth-dependent):*
- If **oauth_bearer**: fill in `clientId` in `mcpexternalauthconfig.yaml` with the OAuth client ID from the identity provider. Note the optional `clientSecretRef` for confidential clients.
- If **api_key**: fill in `token` in `secret.yaml` with the actual API key or bearer token.
- If **none**: no secrets to fill in.

*Always:*
- Verify the container image exists at the final image reference in the registry.
- Review the completed manifests for correctness.

*Deployment-mechanism-dependent:*
- Provide guidance specific to the deployment mechanism you identified in Step 2. For example: if GitOps, explain what to commit/push and how reconciliation picks it up. If there are Kustomization files or ArgoCD Applications that need updating, call that out specifically.

*Post-deploy verification:*
- Check that the MCPServer pod starts and is running.
- Check that the endpoint is reachable at the expected URL.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Generated project directory missing | Tell user, exit |
| No `deploy/` directory in generated project | Tell user (probably wrong directory or Phase 3 not run), exit |
| `deploy/mcpserver.yaml` missing | Tell user, exit |
| Cluster repo path doesn't exist | Tell user, exit |
| No existing deployments in cluster repo to infer values from | Ask user for all values explicitly |
| Some values inferred, some missing | Present what was found, ask for the rest |
| Target directory already exists in cluster repo | Warn user, ask if they want to overwrite |
| User rejects inferred values | Accept corrections and re-confirm |

## Important Notes

### No Docker Build/Push
This skill assumes the container image is already built and pushed to a registry. It only handles manifest placement and configuration.

### No Cluster-Side Commands
This skill does not run `kubectl apply`, `helm install`, or any commands against a live cluster. It only modifies files in the cluster repo.

### Secrets Are Never Filled In
Placeholder values for actual secrets (`clientId`, `token`) are always left as `REPLACE_ME` for the user to fill in manually. The skill only fills in infrastructure values (domain, OTEL endpoint, registry, namespace).

### Works Standalone
This skill does not require Phase 4 validation to have run first. Any generated MCP server project with a `deploy/` directory works.
