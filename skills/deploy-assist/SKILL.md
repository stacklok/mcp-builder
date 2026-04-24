---
name: deploy-assist
description: Place generated MCP server deployment manifests into a cluster repo, fill in placeholders by inferring values from existing cluster configuration, and explain remaining manual steps. Use when you have a generated MCP server project and a cluster repo where you want to deploy it.
argument-hint: <generated-project-dir> <cluster-repo-path>
---

# Deploy Assist Skill

This skill handles the last mile of the mcp-builder pipeline: placing configured deployment manifests into a cluster repo. The pipeline transforms an OpenAPI spec into a ToolHive-ready MCP server across four phases — AI Scoping (Phase 1) produces a validated `mcp-scope.yaml`, Human Review (Phase 2) refines it, Deterministic Code Generation (Phase 3) scaffolds the complete server project, and AI Validation & Polish (Phase 4) verifies the generated code. This skill sits after that pipeline: it takes the generated project's deployment manifests, reads a cluster repo to understand its structure and environment, copies the manifests into the right location with placeholders filled, and explains what the user still needs to do.

The container image is assumed to already be built and pushed to a registry. This skill does not guide through docker build/push or run kubectl commands.

## Pipeline Context

Before starting, read `{skill_base_dir}/../ai-scoping/assets/pipeline-context.md` for full pipeline context — it describes what mcp-builder is, the four phases, and what `mcp-scope.yaml` contains. This skill's focus is the `deploy/` directory of the generated project.

## Startup

Before beginning the workflow:

1. Determine the base directory for this skill (the absolute path to the directory containing this SKILL.md). The repo root is two levels up: `{skill_base_dir}/../..`. Do not share these internal paths with the user.

## Workflow

Given a generated project directory and a cluster repo path ($ARGUMENTS), execute the following steps:

1. Collect and verify inputs
2. Understand the cluster repo (emits a preflight artifact)
3. Confirm inferred values (user gate)
4. Copy and configure manifests
5. Post-apply assertions
6. Explain what's left

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

Explore the cluster repo to answer five questions (Q1–Q5 below), then emit the preflight artifact described at the end of this step. Do not assume any particular repo structure — every cluster repo is organized differently.

**Question 1: Where should the new manifests go?**

Explore the repo's directory layout. Look for how existing services, apps, or MCP servers are organized. There is no single pattern — it might be directories per app, per namespace, per environment, or something else entirely. Understand the organizational pattern and determine where a new MCP server's manifests should be placed to be consistent with the rest of the repo.

**Question 2: What values should fill the placeholders?**

The generated manifests contain these placeholders that need real values:

| Placeholder | Files it appears in |
|---|---|
| `REPLACE_ME_DOMAIN` | mcpserver.yaml, ingress.yaml, mcpexternalauthconfig.yaml, mcpoidcconfig.yaml (only when the scope did not capture `auth.external_url_template`; if it did, these fields are already concrete and must not be rewritten) |
| `REPLACE_ME_OTEL_ENDPOINT` | mcpserver.yaml |
| `client-secret: REPLACE_ME` | secret-oauth.yaml (emitted only when the scope captured `auth.client_type: confidential`; must be filled by the user from the upstream IdP) |
| `{server_name}-mcp:latest` (image needs registry prefix) | mcpserver.yaml |

The cluster repo likely contains existing deployments, config files, or values files that reveal the correct domain, OTEL endpoint, container registry, and namespace for this environment. Find them however makes sense for this repo — they might be in Kubernetes manifests, Helm values, Terraform configs, Kustomize overlays, environment files, or documentation.

**Question 3: How does deployment work here?**

Determine the deployment mechanism: Flux, ArgoCD, Helm, plain `kubectl apply`, or something else. This shapes the final guidance about how the user should trigger deployment after the manifests are in place.

**Question 4: What shape do existing MCPServer resources in this repo use?**

The generator emits manifests against a known CRD version, but the target cluster may pin a different operator version or follow local conventions (shared-ALB ingress, telemetryConfigRef, oidcConfigRef patterns, etc.). Silent mismatches here are the single largest source of first-deploy failures.

**Find candidate siblings deterministically.** Do not rely on directory intuition:

```
find {cluster_repo} -type f \( -name '*.yaml' -o -name '*.yml' \) \
  -exec grep -l 'kind: MCPServer' {} \;
```

- **If >0 results:** pick the file whose path has the smallest edit-distance to the proposed target directory from Question 1. That file is the "nearest sibling". Record its path (relative to the cluster repo root) as `sibling_used` in the preflight artifact below.
- **If 0 results:** record `sibling_used: ""`, note "first MCPServer in repo — no sibling-diff possible", and skip the field extraction and diff below. Proceed with the rest of Question 4 marked as N/A in the preflight artifact (empty lists / empty strings per the schema).

From the chosen sibling, extract:

- The set of top-level keys under `spec` (e.g. `image`, `transport`, `oidcConfigRef`, `telemetryConfigRef`, `externalAuthConfigRef`).
- The set of sibling CRD kinds referenced — e.g. does this repo use a shared `MCPTelemetryConfig`, standalone `MCPOIDCConfig`, inline blocks, or something else?
- Any ingress pattern differences (shared ALB group, URL-rewrite transforms, backend service naming — operator-managed `mcp-{name}-proxy` vs. plain `{name}`, whether a separate authinfo ingress exists, whether paths/audiences end with `/mcp`).
- If a sibling `MCPExternalAuthConfig` exists, the shape of its `spec.embeddedAuthServer.upstreamProviders[*]`: `type` (`oidc` vs. `oauth2`), which config block is populated (`oidcConfig` vs. `oauth2Config`), and field-mapping patterns under `userInfo`. Don't stop at the top-level `spec` — descend into this subtree.

Diff those sets against what's in the generated `deploy/` directory and populate the preflight artifact's `sibling_diff` block (see the "Preflight artifact" subsection at the end of Step 2). Each of these categories must be represented as an explicit (possibly empty) list — absence of a list is the signal that the check was skipped:

- **Keys present in generated but NOT in sibling** (`spec_keys_only_in_generated`) — likely to be rejected by the cluster's CRD. Most common class of failure.
- **Keys present in sibling but NOT in generated** (`spec_keys_only_in_sibling`) — the cluster expects something the generator didn't emit. Usually requires adding a ref or annotation.
- **Kinds referenced by sibling but NOT emitted by generator** (`kinds_only_in_sibling`) — e.g. sibling uses `telemetryConfigRef: shared-telemetry` and the generator emits an inline `telemetry:` block. Requires an adapter rewrite.
- **Ingress shape mismatches** (`sibling_diff.ingress.*`) — each of `sibling_service_name_pattern` vs `generated_service_name`, `sibling_has_authinfo_ingress`, and `sibling_path_has_mcp_suffix` is recorded explicitly.
- **Upstream provider `type` mismatch** (`sibling_diff.external_auth.*`) — e.g. generated uses `type: oidc` but all siblings use `type: oauth2` with explicit endpoints. Note this; Question 5 will confirm whether a rewrite is required.


**Question 5: Does the upstream IdP's OIDC discovery doc actually conform?**

Only applies when the generated `mcpexternalauthconfig.yaml` has `upstreamProviders[*].type: oidc` with a non-empty `issuerUrl`. The embedded auth server performs strict OIDC discovery validation at startup and crash-loops on non-compliant docs — this is the single most common silent first-deploy failure after the sibling-diff class.

Record the probe outcome in the preflight artifact's `oidc_discovery` block. There are exactly three outcomes:

1. **Unresolvable issuer URL** (contains template literal like `{companyDomain}`, DNS failure, or network error). Record `resolvable: false` with `failure` set to the reason. Add `replace_template_literal` to `rewrites_planned` and add the literal's name to `user_inputs_required`. Do not mark `oidc_to_oauth2` yet — the user must supply the tenant first.

2. **Resolvable but non-compliant** — fetch `{issuerUrl}/.well-known/openid-configuration` and confirm all of these fields are present:
   - `response_types_supported`
   - `id_token_signing_alg_values_supported`
   - `subject_types_supported`
   - `authorization_endpoint`
   - `token_endpoint`
   - `jwks_uri`

   If any are missing, record `resolvable: true`, `failure: "non-compliant discovery doc: missing <fields>"`, and add `oidc_to_oauth2` to `rewrites_planned`. The rewrite will be performed in Step 4 by the `rewrite_upstream_oidc_to_oauth2` subroutine defined below.

3. **Resolvable and compliant** — record `resolvable: true`, empty `failure`, and leave `rewrites_planned` untouched. No rewrite needed.

Skip this check entirely when `type: oauth2` is already in use, when there is no `mcpexternalauthconfig.yaml`, or when auth type is `none`/`api_key`. In the skipped case, still emit the `oidc_discovery` block with `resolvable: false` and `failure: "skipped: <reason>"` so the preflight artifact's shape is uniform.

---

### Subroutine: `rewrite_upstream_oidc_to_oauth2`

Extracted from the former Step 2 Q5 / Step 4 prose into a named, independently verifiable routine. Called from Step 4 when `oidc_to_oauth2` is in `rewrites_planned`. Clear contract so the rewrite is testable in isolation, even once the upstream auth-schema-alignment work lands and most OIDC scopes stop needing it — this remains the escape hatch for `oidc`-declared IdPs whose discovery docs don't conform.

**Signature:**

```
rewrite_upstream_oidc_to_oauth2(
  discovery_doc:        dict | None,
  sibling_fieldmapping: dict | None,
  user_provided_tenant: str  | None,
) -> patched_yaml
```

**Inputs — three explicit branches, do not collapse:**

- `discovery_doc`:
  - **dict** — the parsed `.well-known/openid-configuration`. Use its `authorization_endpoint`, `token_endpoint`, and `userinfo_endpoint` verbatim.
  - **None** — the issuer URL was unresolvable (template literal, DNS failure). The subroutine cannot invent endpoints; caller must either supply `user_provided_tenant` so the literal can be substituted and the doc re-fetched, or abort.

- `sibling_fieldmapping`:
  - **dict** — the nearest sibling's `spec.embeddedAuthServer.upstreamProviders[*].oauth2Config.userInfo.fieldMapping`. Use verbatim.
  - **None** — no sibling exists or none have `oauth2Config`. Default to `{subjectFields: [sub], nameFields: [name], emailFields: [email]}`.

- `user_provided_tenant`:
  - **str** — the value the user confirmed at the Step 3 gate for a template literal in the issuer URL (e.g. `stacklok` for `{companyDomain}`). If set, substitute it across the issuer URL and across every matching literal in the generated project's source tree (grep the generated project for the same literal and replace everywhere). Note in Step 6 that the container image must be rebuilt and the `spec.image` digest updated after substitution.
  - **None** — no template literal present, or literal already resolved.

**Output — `patched_yaml`:** the modified `mcpexternalauthconfig.yaml` contents, with:

- `upstreamProviders[*].type` changed from `oidc` to `oauth2`.
- The `oidcConfig:` block replaced by an `oauth2Config:` block.
- `authorizationEndpoint`, `tokenEndpoint`, and `userInfo.endpointUrl` populated from the discovery doc.
- `userInfo.fieldMapping` populated from `sibling_fieldmapping` or the default above.
- `clientId`, `clientSecretRef`, `redirectUri`, and `scopes` preserved verbatim from the original `oidcConfig` block.

**Verification contract:** the returned YAML parses cleanly, contains no `oidcConfig` key, and every endpoint URL is absolute (starts with `https://`).

---

### Preflight artifact

Before presenting findings to the user, the skill writes a structured preflight file to `{cluster_repo}/.deploy-assist-preflight.yaml`. The shape is pinned by `{skill_base_dir}/assets/preflight-schema.yaml` — every top-level key is required; leaf fields default to empty string, empty list, or `false`. An absent or empty required field is the signal to the user that the skill skipped work, which Step 3 then flags.

**Purpose:** force Q1–Q5 findings into a machine-checkable shape before the user gate. Prose summaries let LLMs skim past tedious cross-reference steps (wrong ingress service names, missing authinfo ingress, unresolved template literals, fabricated endpoints). A structured artifact makes absence of a check visible.

**Content:** populate each field from the answers to Q1–Q5. Concretely:

- `sibling_used` — path recorded in Q4 (or `""` if 0 candidates).
- `sibling_diff.spec_keys_only_in_generated`, `spec_keys_only_in_sibling`, `kinds_only_in_sibling` — from Q4.
- `sibling_diff.ingress.*` — from Q4's ingress comparison. Each subfield is explicit; do not omit.
- `sibling_diff.external_auth.*` — from Q4 when a sibling `MCPExternalAuthConfig` exists; otherwise both `sibling_upstream_type` and `generated_upstream_type` are `""`.
- `oidc_discovery.*` — from Q5, with the three outcomes (unresolvable / non-compliant / compliant / skipped) encoded as described there.
- `rewrites_planned` — ordered list of rewrite tokens the skill will apply in Step 4. Known tokens: `oidc_to_oauth2`, `replace_template_literal`, `ingress_service_rename`, `add_authinfo_ingress`, `add_mcp_suffix`.
- `user_inputs_required` — any values the user must supply before Step 4. Each entry is `"name: description"` (e.g. `"companyDomain: concrete value for {companyDomain}"`).

Do not proceed to Step 3 until the file is written and its content matches the schema. Treat this as the exit criterion of Step 2.

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
4. **Auth type** detected from the generated manifests (oauth2 / oidc / api_key / none)
5. **Deployment mechanism** (Flux, ArgoCD, plain manifests, etc.)
6. **Files to copy** (list of manifests from `deploy/`)
7. **Preflight artifact**: show the path `{cluster_repo}/.deploy-assist-preflight.yaml` and either display its content inline or summarize each section (`sibling_used`, `sibling_diff`, `oidc_discovery`, `rewrites_planned`, `user_inputs_required`). For each planned rewrite, state what the skill will do and why:
   - `oidc_to_oauth2` — rewrite required because the upstream IdP's discovery doc is non-compliant (list missing fields). This is a proposed rewrite, not an open question — the server won't start otherwise — but the user may override.
   - `replace_template_literal` — the issuer URL contains an unresolved template (show the exact literal). Ask the user for the concrete value.
   - `ingress_service_rename`, `add_authinfo_ingress`, `add_mcp_suffix` — show what the sibling expects vs what the generator emitted, and confirm the rewrite.
   - Each sibling-diff divergence not already covered above should be labeled **keep as-generated**, **rewrite to match sibling**, or **ask user**. Default to rewriting when the sibling uses a cluster-wide convention (shared-ALB ingress, shared telemetry/OIDC refs); ask when it could be either a generator bug or a sibling convention.

If any entries in `user_inputs_required` were not resolved by inference, ask the user to provide them now.

**Do NOT proceed until the user confirms the values, the target location, and every rewrite in `rewrites_planned`.**

---

### Step 4: Copy and Configure Manifests

Create the target directory in the cluster repo if it does not exist.

For each manifest in the generated project's `deploy/` directory, read the file, perform the replacements below, and write it to the target directory.

**mcpserver.yaml:**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain **only if** the token appears in the file. When the scope captured `auth.external_url_template`, `audience` and `resourceUrl` are already concrete and do not carry the token — leave them untouched and treat them as user-authoritative.
- Replace `REPLACE_ME_OTEL_ENDPOINT` with the confirmed OTEL endpoint (match the format expected by the template — typically `host:port` without protocol prefix)
- Update `spec.image` from `{server_name}-mcp:latest` to `{registry_prefix}{server_name}-mcp:latest`
- Update `metadata.namespace` if it differs from the confirmed namespace

**ingress.yaml:**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain **only if** the token appears in the file. When the scope captured `auth.external_url_template`, `host` and the rule's `path` were derived from it at generation time — leave them untouched.
- Update `metadata.namespace` if needed
- Adjust annotations or `ingressClassName` if the cluster repo's existing Ingress resources use a different pattern

**mcpexternalauthconfig.yaml (if present):**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain **only if** the token appears in the file. When the scope captured `auth.external_url_template`, `issuer` and `redirectUri` are already concrete and do not carry the token — leave them untouched.
- Update `metadata.namespace` if needed
- **Leave `clientId: REPLACE_ME` as-is** — this is a secret the user must fill in
- **If `rewrites_planned` contains `oidc_to_oauth2`**, call the `rewrite_upstream_oidc_to_oauth2` subroutine defined after Step 2. Pass:
  - `discovery_doc` — the dict fetched in Step 2 Q5, or `None` if the issuer URL is still unresolvable.
  - `sibling_fieldmapping` — the nearest sibling's `oauth2Config.userInfo.fieldMapping`, or `None`.
  - `user_provided_tenant` — the value the user confirmed at the Step 3 gate for any template literal, or `None`.

  Apply the returned `patched_yaml` in place of the in-memory file contents before writing. If `user_provided_tenant` was used, also grep the generated project's source tree for the same literal and substitute it everywhere — note in Step 6 that the container image must be rebuilt and `spec.image` digest updated.

**mcpoidcconfig.yaml (if present):**
- Replace `REPLACE_ME_DOMAIN` with the confirmed domain **only if** the token appears in the file. When the scope captured `auth.external_url_template`, `spec.inline.issuer` is already concrete — leave it untouched.
- Update `metadata.namespace` if needed

**secret.yaml (if present):**
- Update `metadata.namespace` if needed
- **Leave `token: REPLACE_ME` as-is** — this is a secret the user must fill in

**secret-oauth.yaml (if present):**
This file is emitted when the scope's `auth.client_type == "confidential"`. It holds the upstream OAuth `client_secret`.
- Update `metadata.namespace` if needed
- **Leave `client-secret: REPLACE_ME` as-is** — this is a secret the user must fill in from the upstream IdP (Google Cloud Console, GitHub app settings, Okta admin, etc.). Flag in Step 6 that the user owes this value before first login works.

If the cluster repo has other files that need updating to pick up the new manifests (e.g., a Kustomization file that lists resources, an ArgoCD Application, a Flux Kustomization), note this but do not modify them automatically — flag it for the user in Step 6.

---

### Step 5: Post-Apply Assertions

After every file in Step 4 has been written, re-read the files from disk (not from the in-memory pre-write state) and run each assertion below. Every assertion must pass before the skill can exit cleanly. An assertion failure blocks Step 6 — report the specific failure to the user and stop.

Re-reading from disk matters: the skill's self-report of "I replaced X" is not evidence. These assertions are the evidence.

**Placeholder assertions** (run against every copied file):

1. **No stray `{…}` placeholders remain.** Grep each file for the pattern `\{[a-zA-Z_][a-zA-Z0-9_]*\}`. Allowed exceptions (do not fail on these):
   - `${domain_name}`, `${acm_certificate_arn}` and other documented Flux substitution variables (any `${...}` with a `$` prefix).
   - Go-template-style `{{ .Foo }}` expressions inside Helm charts.
   Anything else (e.g. `{companyDomain}`, `{tenant}`) is a failure — the template-literal substitution in Step 4 was incomplete.

2. **No `REPLACE_ME_*` placeholders remain** except the explicit secret placeholders:
   - `clientId: REPLACE_ME` in `mcpexternalauthconfig.yaml` is allowed.
   - `token: REPLACE_ME` in `secret.yaml` is allowed.
   - `client-secret: REPLACE_ME` in `secret-oauth.yaml` is allowed.
   Any other `REPLACE_ME_DOMAIN`, `REPLACE_ME_OTEL_ENDPOINT`, or `REPLACE_ME_*` token is a failure.

**Ingress shape assertions** (run against `ingress.yaml` when present):

3. **`backend.service.name` matches the sibling's naming pattern.** If `sibling_diff.ingress.sibling_service_name_pattern` was `"mcp-{name}-proxy"`, the generated service name must be `mcp-{server_name}-proxy`. If the sibling pattern was `"{name}"`, the generated service name must be `{server_name}`. If `sibling_used` was `""` (first MCPServer in repo), skip this assertion.

4. **Authinfo ingress present if the sibling has one.** If `sibling_has_authinfo_ingress` was `true`, the written ingress manifests must include a separate ingress resource for `/.well-known/oauth-*` paths. Missing authinfo ingress breaks OAuth protected-resource discovery.

**OAuth2 endpoint probe** (run against `mcpexternalauthconfig.yaml` when `upstreamProviders[*].type == oauth2` after Step 4's rewrites):

5. **`authorizationEndpoint` does not 302 to a vendor marketing page.** Probe it with a fake code and confirm the response is neither a 200 nor a 302 redirecting to `https://www.<vendor>.com/` (or any other root marketing URL). Example shape of the probe:

   ```
   curl -sI -o /dev/null -w '%{http_code} %{redirect_url}\n' \
     "{authorizationEndpoint}?response_type=code&client_id=probe&code=invalid"
   ```

   A real OAuth authorization endpoint returns 400/401/302-to-login for an invalid code. A fabricated or marketing URL typically returns 200 or a 302 to the vendor's homepage. Treat a 200 or a marketing-root 302 as a failure — the endpoint is almost certainly wrong.

**On failure:**

- Report which assertion failed, which file, and the offending value (e.g. `"Assertion 1 failed: ingress.yaml line 18 still contains {companyDomain}"`).
- Do not proceed to Step 6. The user must either correct the input or mark the assertion as a known false-positive before re-running.

---

### Step 6: Explain What's Left

Present a structured summary to the user.

**What was done:**
- List each file copied with its destination path in the cluster repo
- List each placeholder that was replaced and what value was used
- Show the final `spec.image` value so the user can verify the registry path

**What the user still needs to do:**

Present a checklist tailored to the auth type and deployment mechanism:

*Secret values (auth-dependent):*
- If **oauth2** or **oidc**: fill in `clientId` in `mcpexternalauthconfig.yaml` with the OAuth client ID from the identity provider. Note the optional `clientSecretRef` for confidential clients.
- If **api_key**: fill in `token` in `secret.yaml` with the actual API key or bearer token.
- If **none**: no secrets to fill in.

*Always:*
- Verify the container image exists at the final image reference in the registry.
- Review the completed manifests for correctness.
- If Step 4 substituted a template literal into the generated project's source code (via `rewrite_upstream_oidc_to_oauth2` with `user_provided_tenant`), rebuild the container image and update `spec.image` to the new digest.

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
| Step 5 assertion failure | Report which assertion failed, which file, and the offending value. Do not exit cleanly. User corrects inputs or marks the failure as a known false-positive, then re-runs. |

## Important Notes

### No Docker Build/Push
This skill assumes the container image is already built and pushed to a registry. It only handles manifest placement and configuration.

### No Cluster-Side Commands
This skill does not run `kubectl apply`, `helm install`, or any commands against a live cluster. It only modifies files in the cluster repo.

### Secrets Are Never Filled In
Placeholder values for actual secrets (`clientId`, `token`) are always left as `REPLACE_ME` for the user to fill in manually. The skill only fills in infrastructure values (domain, OTEL endpoint, registry, namespace).

### Works Standalone
This skill does not require Phase 4 validation to have run first. Any generated MCP server project with a `deploy/` directory works.
