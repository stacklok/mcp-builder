# Validation Report: {server_name}

**Date:** {YYYY-MM-DD}
**Project:** {project_dir}
**Scope:** {scope_yaml_path}

## Summary

- **Total checks:** {N}
- **Passed:** {N}
- **Failed:** {N} (errors: {N}, info: {N})
- **Warnings:** {N}

## Structural Correctness

| Check | Status | Severity | Details |
|-------|--------|----------|---------|
| S1: Tool completeness | {PASS/FAIL} | error | {details — list any missing or extra tools} |
| S3: Import resolution | {PASS/FAIL} | error | {details — list any broken imports} |
| S4: Tool registration | {PASS/FAIL} | error | {details — list any unregistered or extra tools} |

## Behavioral Correctness

| Check | Status | Severity | Details |
|-------|--------|----------|---------|
| B1: HTTP methods | {PASS/FAIL} | error | {details — list any method mismatches with expected vs actual} |
| B2: Path interpolation | {PASS/FAIL} | error | {details — list any incorrect path parameter handling} |
| B3: Required params | {PASS/FAIL} | error | {details — list any required params with Optional default} |
| B4: Response parsing | {PASS/FAIL} | info | {details — note any response handling concerns} |

## Auth Wiring

| Check | Status | Severity | Details |
|-------|--------|----------|---------|
| A1: Token passthrough | {PASS/FAIL} | error | {details} |
| A2: No hardcoded creds | {PASS/FAIL} | error | {details — list any suspicious strings found} |
| A3: Auth import chain | {PASS/FAIL} | error | {details} |

## ToolHive CRDs

| Check | Status | Severity | Details |
|-------|--------|----------|---------|
| T1: MCPServer CRD | {PASS/FAIL} | error | {details — verify apiVersion, kind, image, transport} |
| T2: Auth config match | {PASS/FAIL} | error | {details — verify auth type alignment between YAML and CRD} |
| T3: Secret template | {PASS/FAIL} | error | {details — verify correct keys and placeholder values} |

## Build Verification

| Check | Status | Severity | Details |
|-------|--------|----------|---------|
| D1: Docker build | {PASS/FAIL/SKIP} | error | {details or build output excerpt} |

## Deploy Review Notes

{Items requiring manual verification before deployment. This section is informational — no PASS/FAIL.}

| File | Manual Check | Notes |
|------|-------------|-------|
| mcpserver.yaml | Image registry resolution | {Does spec.image resolve in your target registry?} |
| mcpexternalauthconfig.yaml | Auth provider reachability | {Is the issuer URL correct and reachable for the target environment?} |
| secret.yaml | Replace placeholder values | {REPLACE_ME values must be filled in before deployment} |

## Detailed Findings

{For each FAIL check, add a detailed section below. Omit this section entirely if all checks pass.}

### {Check ID}: {Check Name} — FAIL

**Severity:** {error/info}
**Expected:** {what the code should contain or look like}
**Actual:** {what was found in the generated code}
**File:** {relative path within the generated project}
**Fix:** {specific description of what needs to change}
