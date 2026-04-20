# Polish Suggestions: {server_name}

**Date:** {YYYY-MM-DD}
**Total suggestions:** {N}

## Summary

| Severity | Count | What it means |
|----------|-------|---------------|
| blocker  | {N}   | Functional bug — tool fails or a deployment-critical assumption is wrong. MUST fix before deploy. |
| high     | {N}   | Tool works, but LLM callers are likely to misuse it or get unusable output. |
| medium   | {N}   | Noticeable robustness / quality-of-life improvement. |
| low      | {N}   | Minor polish — wording, formatting, small defaults. |

| #  | Severity | Category               | Tool(s)       | One-line summary                                     |
|----|----------|------------------------|---------------|------------------------------------------------------|
| P1 | blocker  | response-shaping       | `export_file` | Shared client `.json()` call breaks raw-bytes endpoints |
| P2 | high     | pagination             | `list_files`  | Docstring missing nextPageToken cursor guidance      |
| P3 | ...      | ...                    | ...           | ...                                                  |

## Suggestions

<!--
For EACH suggestion, use the block below. All three prose fields
(Problem / Impact if unfixed / Proposed fix) are required. The skill's
chat presentation renders them directly — terse one-liners will leave
the user guessing what the issue actually is.
-->

### P{n}: {Short imperative title}

|  |  |
|---|---|
| **Severity**         | `{blocker / high / medium / low}` |
| **Category**         | {pagination / response-shaping / error-normalization / api-quirks} |
| **Affected tool(s)** | `{tool_name}` (or `all` for shared-client changes) |
| **File(s)**          | `{relative path(s)}` |
| **Hint source**      | {triggering hint text, or "AI-analyzed" if not hint-driven} |

**Problem**
{2–4 sentences stating exactly what is wrong or suboptimal in the generated
code today. Reference concrete behavior — e.g. "the shared client calls
`response.json()` unconditionally, but this endpoint returns raw bytes" —
not vague "could be better". If this is a `blocker`, explicitly call that
out here so the reader knows it isn't just a style nit.}

**Impact if unfixed**
{1–2 sentences on the concrete consequence.
  - `blocker`: what breaks and when (e.g. "every call raises JSONDecodeError").
  - `high`: how the LLM misuses the tool (e.g. "LLM won't page through results").
  - `medium` / `low`: what degrades (e.g. "error messages lose structure").}

**Proposed fix**
{2–4 sentences describing the change at a conceptual level — what function
to add, what behavior to switch to, what docstring content to add. A reader
should be able to decide yes/no from this paragraph alone, without reading
the diff.}

**Before**
```python
{existing code snippet — keep minimal, just the affected lines}
```

**After**
```python
{improved code snippet}
```

---
