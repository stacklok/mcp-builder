# Generator Contract

Authoritative reference for what the mcp-builder code generator actually
produces. Agents and humans working on `mcp-scope.yaml` read this instead
of opening the generator templates. When the generator changes, update
this file in the same PR.

## Response kinds

A tool's `response_kind` is a required field in `mcp-scope.yaml` and
commits the generated tool to exactly one decode path. There are three
kinds.

| `response_kind` | Generated tool returns | Client method | Accept header | Use for |
|---|---|---|---|---|
| `json` | `dict` | `request()` | `application/json` | Endpoints that return parsed JSON |
| `text` | `str` (decoded text) | `request_text()` | `text/*, */*;q=0.8` | Endpoints that return `text/*` (plain text, HTML, CSV, Markdown, XML, exported Google Docs) |
| `binary` | `str` (base64-encoded) | `request_bytes()` | `*/*` | Endpoints that return opaque bytes (PDF, images, `application/octet-stream`) |

### What each kind actually does at runtime

- `json`: client calls `response.json()`. Empty 2xx bodies (204-style)
  return `{}` rather than raising `JSONDecodeError`.
- `text`: client returns `response.text`. httpx decodes using the
  response's declared charset, falling back to UTF-8. The model sees
  the text directly.
- `binary`: client returns `response.content`; the tool base64-encodes
  it to ASCII so the bytes survive MCP transport. The model sees a
  base64 blob, which is only useful if downstream tooling decodes it.

### Picking a kind from the spec

Inspect the operation's 2xx responses in the OpenAPI spec and pick the
kind whose media type fits:

- Every 2xx response declares at least one `application/json` (or every
  2xx is 204-style with no body) → `json`.
- Every 2xx response declares a `text/*` media type (and no JSON) →
  `text`.
- Every 2xx response declares an opaque binary media type (PDF, image,
  `application/octet-stream`) and no JSON or text → `binary`.
- Mixed — some 2xx are JSON and some are not, or the spec simultaneously
  offers JSON and non-JSON on the same status — **do not guess**. Flag
  the endpoint so the user picks the kind during the approval gate.

### Known gotchas

- `text` on a spec that only declares JSON will fail validation — the
  client sends `Accept: text/*` and a JSON-only server returns 406 (or
  the wrong content type).
- `binary` silently mangles readable text. If the spec declares
  `text/plain`, `text/html`, `text/csv`, `text/markdown`, or any other
  `text/*`, pick `text`, not `binary`. Wrapping text in base64 forces
  the consumer to decode it before use and hides human-readable content
  from the model.
- `json` on a spec that mixes JSON and non-JSON media types may
  succeed through content negotiation (the `Accept: application/json`
  header coaxes the server into JSON) but the validator still flags
  this as mixed-media so the scope author confirms intent.

### Validator rules

The validator cross-checks `response_kind` against the spec's 2xx
media types and errors (not warns) on mismatch:

- `json`: error if any 2xx response with content has no JSON media
  type — the tool would fail at runtime.
- `text`: error if any 2xx response with content has no `text/*` media
  type — same reason.
- `binary`: error if any 2xx response with content declares JSON — the
  client's `Accept: */*` could return JSON, which would then be
  base64-wrapped and returned as opaque bytes.
- No 2xx responses declared in the spec → warning (can't verify); the
  scope passes but the author should confirm.
- All 2xx responses are 204-style (no body) → silent pass regardless
  of kind.

## Auth types

A scope's `auth.type` picks the auth shape emitted by the generator.
Only these four are supported today.

| `auth.type` | What the generator emits | Required fields |
|---|---|---|
| `oidc` | Token exchange against an OIDC discovery document | `issuer`, `scopes_available`, `scopes_required` |
| `oauth2` | Explicit authorization-code OAuth2 with inline URLs | `flow`, `authorization_url`, `token_url`, `scopes_available`, `scopes_required` |
| `api_key` | Static bearer token in the `Authorization` header | none (token supplied at deploy time) |
| `none` | No auth layer | none |

Prefer `oauth2` over `oidc` when uncertain. OIDC requires a real
discovery document at `{issuer}/.well-known/openid-configuration`. If
the provider does not publish one, or the scopes are API scopes rather
than identity scopes (no `openid`/`profile`/`email`), stay with
`oauth2` and populate `authorization_url` / `token_url` inline.

## Known generator gaps

Things the generator does **not** do today. If a scope needs one of
these, flag it explicitly so the user knows the limitation rather than
shipping a broken tool.

- **Streaming responses.** All responses are read to completion before
  the tool returns.
- **Multipart / file uploads.** `multipart/form-data` request bodies
  fall back to a single opaque `body` parameter and usually do not work.
- **Custom Accept headers per tool.** The Accept header is fixed per
  `response_kind` as shown in the table above.
- **Per-tool base URLs.** The whole server uses one `base_url`.
- **Pagination auto-iteration.** Paginated endpoints return one page.
  Add a `hints` entry noting the cursor field so Phase 4 can flag it.
- **Response field projection / shaping.** The tool returns whatever
  the server sends. Trimming happens in Phase 4 via hints, not in
  codegen.

## Update rule

When the generator's contract changes — a new `response_kind`, a new
auth type, a removed gap — update this file in the same PR. The
`ai-scoping` skill and the `endpoint-scoper` agent treat this document
as the authoritative source for what the generator actually produces.
Drift here causes silent scoping bugs.
