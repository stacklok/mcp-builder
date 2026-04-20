# Polish Suggestions: {server_name}

**Date:** {YYYY-MM-DD}
**Total suggestions:** {N}

## Summary

| Severity | Count | What it means |
|----------|-------|---------------|
| high     | {N}   | Tool is broken OR LLM callers are very likely to misuse it / get unusable output. |
| medium   | {N}   | Noticeable robustness / quality-of-life improvement. |
| low      | {N}   | Minor polish — wording, formatting, small defaults. |

| #  | Severity | Category | Tool(s) | One-line summary |
|----|----------|----------|---------|------------------|
| P1 | high   | ...      | ...     | ... |
| P2 | medium | ...      | ...     | ... |
| P3 | ...    | ...      | ...     | ... |

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
| **Severity**         | `{high / medium / low}` |
| **Category**         | {pagination / response-shaping / error-normalization / api-quirks} |
| **Affected tool(s)** | `{tool_name}` (or `all` for shared-client changes) |
| **File(s)**          | `{relative path(s)}` |
| **Hint source**      | {triggering hint text, or "AI-analyzed" if not hint-driven} |

**Problem**
{2–4 sentences stating exactly what is wrong or suboptimal in the generated
code today. Reference concrete behavior. If this is a functional bug (runtime
failure, broken deployment assumption), open the paragraph by saying so
explicitly — the severity stays `high`, but the prose carries the bug signal.}

**Impact if unfixed**
{1–2 sentences on the concrete consequence — what breaks, how the LLM
misuses the tool, or what quality degrades. Match the detail level to the
severity tier.}

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
