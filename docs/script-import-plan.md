# Script Import — Plan

Import existing Playwright script files into QAClan and normalize them into the language strategy's harness so they execute under the same `QACLAN_*` runtime contract as recorded scripts.

Scope: Python, JavaScript (plain), TypeScript (plain), JavaScript `@playwright/test`, TypeScript `@playwright/test`. No .py.spec dialect.

Status: planning only. No code changes yet.

---

## 1. Goals

- Accept a user-provided `.py` / `.js` / `.ts` / `.spec.js` / `.spec.ts` file.
- Show raw content first so user confirms what's being imported.
- Backend normalizes to the matching strategy's harness (BEGIN/END markers, env-driven config, artifacts JSON, screenshot on failure, storage state load/save).
- Land the normalized result in the existing script editor modal so the user can keep editing, scan & bind, save.
- Surface conflicts and dropped content explicitly — never silently rewrite logic.

## 2. Why backend

Confirmed: processing belongs in the backend.

- Each strategy already owns `post_process_recording` / `_extract_actions` / `_render_harness` / `starter_template`. Calling that from JS would duplicate the harness templates and the action-extraction regexes — two copies that drift the moment a strategy changes.
- `_shared.scan_var_keys` and `_HARNESS_TEMPLATE` constants live in Python only.
- Future linting / AST parsing (e.g. detect top-level `sync_playwright()` blocks, `test.use()` calls) is much easier in Python.

New endpoint: `POST /api/scripts/import-preview`. Pure function — does not write to DB or disk. Returns normalized harness + diagnostics. The existing `POST /api/scripts` continues to handle persistence; the import flow just feeds its body.

## 3. UX flow

```
[Scripts page]
  └─ "+ Import Script" button  (sibling of "+ New Script")
        └─ File picker → reads file as text in browser
            └─ Modal A "Imported file preview"
                 ├─ filename, detected language (editable dropdown), size
                 ├─ read-only CM6 viewer of the raw file
                 ├─ Cancel  |  Process & Open Editor
                 └─ on Process:
                      POST /api/scripts/import-preview { content, filename, language? }
                      └─ Modal A closes
                      └─ Modal B opens — same shape as createScriptModal
                            ├─ pre-filled name (filename stem)
                            ├─ feature picker (required, blank by default)
                            ├─ language locked to the resolved language
                            ├─ editor pre-loaded with normalized harness
                            ├─ diagnostics banner (warnings list, see §6)
                            └─ Create Script button → POST /api/scripts
```

Two-modal flow (preview → editor) keeps the import audit visible without forcing a feature/name decision before the user has even seen the parsed body. Closes cleanly on Cancel from either step.

### 3.1 Where the Import button lives

- Primary: Scripts page header, next to `+ New Script`.
- Secondary: a small "Import from file…" link inside the Create Script modal header (covers the "I already opened New Script and realized I want to import" case).

### 3.2 Should scan-and-bind auto-open?

Recommendation: **no auto-open, yes auto-banner**.

- After Modal B renders, run a quick client-side `_parseFillCalls()` on the normalized content.
- If any `.fill()` calls exist OR any literal matches a sensitive pattern, show a yellow banner inside Modal B: `"N fillable fields detected. [Scan & Bind]"`.
- User clicks the banner button to open the existing scan-and-bind overlay. Same path as `scanAndBindFromEditor()`.

Why not auto-open: importing should feel reversible. Stacking another modal on top before the user has seen the editor content makes "what just happened to my script" hard to follow. Banner is one click away and respects user pace.

## 4. Language detection

Backend resolves language with this precedence (first match wins):

1. Explicit `language` from request body (user override in Modal A's dropdown).
2. Filename suffix:
   - `.spec.ts` → `typescript_test`
   - `.spec.js` → `javascript_test`
   - `.test.ts` → `typescript_test`
   - `.test.js` → `javascript_test`
   - `.ts` / `.tsx` → `typescript`
   - `.js` / `.mjs` / `.cjs` → `javascript`
   - `.py` → `python`
3. Content sniff (when extension ambiguous or missing):
   - `from playwright.sync_api` → `python`
   - `require('@playwright/test')` or `from '@playwright/test'` → `*_test` variant
   - `require('playwright')` or `from 'playwright'` → plain variant
   - presence of TypeScript-only syntax (`: string`, `as const`, generics in declarations) → ts variant

Returned `language_inferred` plus `language_source` (`extension|content|user`) so the UI can show "Detected from filename" vs "Detected from content".

If detection fails: backend returns 400 with `error: "Could not determine language"` and the suggested manual choices. UI surfaces this in Modal A and forces the user to pick before retrying.

## 5. Normalization algorithm (per strategy)

The import pipeline is one function with three branches keyed off what the file already looks like:

```
detect_layout(content, strategy) →
  "qaclan_harness"      already has BEGIN/END markers
  "playwright_codegen"  matches the strategy's codegen output shape
  "freeform"            anything else — playwright script not matching either
```

### Branch A — qaclan_harness

Already shaped like our harness.

- Verify the markers are intact and match the strategy.
- Re-render through `_render_harness(extracted_actions)` to:
  - Refresh scaffold to the current template (in case our template evolved since the file was exported).
  - Discard anything outside markers.
- Warn if scaffold lines were modified (compare imported scaffold against `starter_template()`'s scaffold; report a diff summary, not a full diff).

### Branch B — playwright_codegen

Raw output from `playwright codegen --target {python|javascript|playwright-test}`.

- Reuse `strategy.post_process_recording(raw)` — this is exactly what the recording flow already does. Single code path keeps recorded vs imported scripts byte-identical for equivalent input.

### Branch C — freeform

The hard case. Everything that is neither QAClan harness nor codegen exhaust. Strategy:

1. **Extract the action body** with strategy-specific heuristics:
   - **python**: find a `with sync_playwright() as <name>:` block, descend to the `page = ...new_page()` line, capture lines until the matching context manager close or an explicit `browser.close()` / `page.close()`.
   - **javascript / typescript** (plain): find `await ... .newContext(` then `newPage()`, capture until `await context.close()` / `await browser.close()` / end of the async IIFE.
   - **javascript_test / typescript_test**: find the *first* `test(<title>, async ({ page, ... }) => {`, capture body up to the matching `});`. Multiple `test()` blocks → only the first becomes the action body; the rest are listed in warnings (§6).
2. Re-indent and feed through `strategy._render_harness(actions)`.
3. If extraction fails entirely (no recognizable boundary), fall back to: render `starter_template()` with the original file pasted into a `# IMPORTED — REVIEW` comment block above the BEGIN marker. User sees it, makes a manual decision. Mark `needs_manual_review: true` so the UI banner is loud.

### Per-strategy quirks

| Strategy | Notes |
|---|---|
| python | Indent normalization critical — `_render_harness` re-indents to 12 spaces inside `try:`. Tab-indented input must be expanded first (`textwrap.dedent` → `expandtabs(4)`). |
| javascript | Plain-JS harness uses `'use strict'` + CJS require. ESM imports (`import {chromium} from 'playwright'`) get rewritten to `require()` calls in the action region only — top-level imports are dropped (harness already has them). Warn user if their imports referenced packages we don't bundle. |
| typescript | Inherits from JS. Strip type annotations from extracted actions only if they would not parse under tsx — actually, leave them; tsx handles them. Warn if `import type` lines appear in actions (will fail at runtime — they should be top-level). |
| javascript_test | Body is a `test()` callback. If user has `test.beforeAll` / `test.afterAll` / fixtures, those are dropped (warned). Multiple tests → first one wins. `test.use({...})` at module scope is dropped (harness uses shared `playwright.config.js`). |
| typescript_test | Same as javascript_test plus: ES `import` lines outside the action body are dropped — harness owns the imports. |

## 5.5 URL templating (parity with recording)

Recording flow: user picks a URL **key** + **value** before launching codegen, then `strategy.rewrite_url_template(content, base_value, key_name)` swaps the literal for `{{KEY}}` and DB stores `start_url_key` / `start_url_value`. Import must reach the same end state — otherwise imported scripts run against hardcoded URLs and ignore env switching.

Pipeline:

1. **Detect** — after normalization, scan the harness body for `page.goto("…")` literals (Python + JS share the call shape; one regex per strategy that returns the literal). Return a list `detected_urls: [{ url, occurrences }]` ordered by occurrence count desc, deduped.
2. **Choose** — Modal A grows a "Start URL" section once language is resolved:
   - Radio list of detected URLs (most-frequent preselected). Empty list → section hidden.
   - "URL key" combobox: dropdown of existing env-variable keys for the active project (fetched via existing env API) plus free-text input. Default value `BASE_URL`. Empty = skip templating.
   - "Skip" radio so user can opt out without typing.
3. **Apply** — when user clicks Process, the request to `/api/scripts/import-preview` carries `url_key` + `url_value`. If both present, backend calls `strategy.rewrite_url_template()` after normalization and adds the chosen key to `var_keys`. Response includes `start_url_key` + `start_url_value` (echoed) so the frontend can pass them to `POST /api/scripts`.
4. **Persist** — `POST /api/scripts` is extended to accept optional `start_url_key` + `start_url_value` and write them to the row. Mirrors recording flow exactly.

If `url_key` collides with one of our scaffold names (`_BROWSER`, etc.), refuse with `error` severity `qaclan_var_collision` (existing rule).

Edge cases:

- URL has trailing path/query (e.g. `https://app/login?next=/x`) — strip path before storing as `start_url_value`; rewrite preserves the path under the placeholder (existing behavior of `rewrite_url_template`).
- Multiple base hosts in body — only one becomes the templated `BASE_URL`. Others remain literal; emit `info` warning `multiple_base_urls_detected` listing the leftovers so user can templatize manually post-import.
- No `page.goto()` at all (rare; e.g. test starts from already-open page) — section hidden; no warning.

## 6. Conflicts & warnings (the §6 spec)

The backend returns `warnings: [{ severity, code, message, range? }]`. UI shows them as a list in Modal B's diagnostics banner, color-coded by severity.

Severity ladder:

- **error** — script will not run as imported. Block save until user fixes (UI disables Create button, but allows editing).
- **warn** — script should run but something was dropped or rewritten. Save allowed.
- **info** — purely descriptive (e.g. "language detected from content").

### Warning catalog

| code | severity | trigger |
|---|---|---|
| `lang_mismatch_extension` | warn | user override differs from extension-derived guess |
| `harness_marker_missing` | info | Branch B/C path taken (expected, but visible) |
| `harness_scaffold_modified` | warn | imported file was QAClan-shaped but scaffold edits exist outside markers |
| `multiple_tests_dropped` | warn | `*_test` strategy: more than one `test(...)` block — only first kept |
| `test_use_dropped` | warn | `*_test`: a module-scope `test.use({...})` was removed (harness owns config) |
| `hook_dropped` | warn | `test.beforeAll/beforeEach/afterAll/afterEach` removed |
| `fixture_definition_dropped` | warn | `test.extend({...})` removed |
| `top_level_imports_dropped` | info | top-level `import`/`require` removed (harness re-imports playwright) |
| `unsupported_import` | warn | dropped import referenced a non-`playwright` package — user code may fail |
| `qaclan_var_collision` | error | user defined `_BROWSER` / `_HEADLESS` / `_STATE` / `_ARTIFACTS` / `_SCREENSHOT` / `_consoleErrors` / `_networkFailures` / `_writeArtifacts` / `_contextOpts` / `run` (Python) at module/script scope |
| `manual_browser_lifecycle` | warn | user calls `browser.close()` / `playwright.stop()` inside extracted actions — will run inside our `try` block and break the `finally` cleanup |
| `storage_state_override` | warn | user passes `storageState` / `storage_state` in their own `newContext` call — overrides QAClan's shared state.json |
| `viewport_override` | info | user passes `viewport` in their own `newContext` call — fine, just informational |
| `sensitive_literal` | warn | hardcoded value in `.fill(...)` matches a sensitive pattern (password/email/token) — strong hint to scan-and-bind |
| `var_keys_detected` | info | `{{KEY}}` placeholders found in body — included in `var_keys` response field |
| `extraction_failed` | error | freeform fallback hit — content placed under `IMPORTED — REVIEW` block, user must rewrite |
| `binary_or_huge` | error | content > 256 KB or contains NULs — refuse |
| `multiple_base_urls_detected` | info | more than one distinct host in `page.goto()`; only the chosen one was templated |
| `start_url_templated` | info | URL templating applied — echoes `key` and `value` for transparency |

### Variable-collision rule (the hard one)

Reject these names anywhere at module scope (Python) / file scope (JS/TS) — they're our scaffold's identifiers:

- Python: `_BROWSER`, `_HEADLESS`, `_VIEWPORT`, `_STATE`, `_ARTIFACTS`, `_SCREENSHOT`, `_console_errors`, `_network_failures`, `_context_opts`, `_write_artifacts`, `_on_console`, `_on_pageerror`, `_on_requestfailed`, `run`
- JS/TS: `_BROWSER`, `_HEADLESS`, `_VIEWPORT`, `_STATE`, `_ARTIFACTS`, `_SCREENSHOT`, `_consoleErrors`, `_networkFailures`, `_contextOpts`, `_writeArtifacts`, `run`, `_browsers`, `_browserType`

Detection: regex against extracted top-level lines (the part we're about to discard) AND against the action body. Inside the action body these would shadow our scaffold's vars and break it — that's the `error` severity case.

## 7. Backend API

```
POST /api/scripts/import-preview
Content-Type: application/json

Request:
{
  "content":  "<file text>",
  "filename": "login_test.py",     // optional, used for language hint
  "language": "python",            // optional override
  "url_key":   "BASE_URL",         // optional — apply rewrite_url_template
  "url_value": "https://app.example.com"  // required if url_key set
}

Response 200:
{
  "ok": true,
  "language":         "python",
  "language_source":  "extension|content|user",
  "layout":           "qaclan_harness|playwright_codegen|freeform",
  "content":          "<normalized harness>",
  "var_keys":         ["BASE_URL", "USERNAME"],
  "detected_urls":    [{ "url": "https://app.example.com", "occurrences": 3 }],
  "start_url_key":    "BASE_URL",          // echoed when url_key applied
  "start_url_value":  "https://app.example.com",
  "warnings": [
    { "severity": "warn", "code": "test_use_dropped", "message": "...", "line": 12 },
    ...
  ],
  "needs_manual_review": false
}

Response 400:
{ "ok": false, "error": "...", "code": "language_undetectable|too_large|empty" }
```

No DB write. No disk write. Pure transform.

## 8. Backend code touchpoints

- `cli/script_strategies/base.py` — add abstract `extract_actions_freeform(self, raw: str) -> tuple[str, list[Warning]]`. Default impl does best-effort extraction; subclasses override for their grammar.
- `cli/script_strategies/_shared.py` — add `Warning` dataclass and `detect_qaclan_harness(content) -> bool` (cheap regex against BEGIN/END markers).
- `cli/script_strategies/python_strategy.py`, `javascript_strategy.py`, `javascript_test_strategy.py`, `typescript_test_strategy.py` — implement `extract_actions_freeform`. (TypeScript inherits JS unless quirks above mandate override.)
- `web/routes/scripts.py` — add `import-preview` route. New free function `_normalize_imported_script(content, language)` that does the layout dispatch and returns `(normalized, warnings, var_keys, layout, needs_manual_review)`. Reuses existing `get_strategy`, `scan_var_keys`.

No schema changes. No new DB columns. `var_keys` is already populated by `_scan_var_keys` on POST `/api/scripts`.

## 9. Frontend code touchpoints

- `web/static/app.js`:
  - Scripts page header: add `+ Import Script` button → `importScriptModal()`.
  - New `importScriptModal()`: file picker → reads text via `File.text()` → opens Modal A.
  - Modal A: read-only CM6 viewer (reuse `_createScriptEditor(host, content, { readOnly: true, language })`), language dropdown, Cancel/Process buttons.
  - On Process: `POST /api/scripts/import-preview` → close Modal A → open Modal B which is a thin variant of `createScriptModal()` that pre-fills content, locks language, renders the diagnostics banner.
  - Diagnostics banner component: list `warnings` grouped by severity, plus a `[Scan & Bind]` button that calls `scanAndBindFromEditor()` if any `.fill()` exists.
  - Reuse `_parseFillCalls`, `_categorizeField`, `_showFieldReviewModalCore` for the bind step — already overlay-aware.
- No new CSS module needed; existing modal/banner styles cover it.

## 10. Edge cases / risk register

1. **User imports their own QAClan export of a different strategy** (e.g. dropped a Python script and selected JavaScript). Detection: language sniff says `python`, user override says `javascript` → return `error` severity `lang_mismatch_extension` and refuse to normalize until they fix the dropdown. Don't try to translate.
2. **Multi-file test** (user's script `require()`s a helper module). We import only the entry file; `require()` to a relative path will fail at runtime. Warn `unsupported_import`; user can paste helper inline or put it next to the script (currently no facility for that — out of scope for this plan, file as follow-up).
3. **`async function` declared at module scope and called in actions** — JS/TS only. Drop the declaration, lose the function. Warn `top_level_imports_dropped` (rename code: `top_level_decls_dropped`).
4. **`@playwright/test` script with `expect.configure(...)` or `test.describe` blocks** — describe blocks containing one test get flattened (extract the inner `test()`); multi-test describe blocks → `multiple_tests_dropped`.
5. **Recorded against absolute URL the user wants templated** — out of scope for import (user can use the existing URL templating after import). But: after import, if `var_keys` is empty AND content has any literal http:// URL, banner suggests "Use Insert Variable to template URLs".
6. **Huge file / binary** — guard at request size (256 KB) plus null-byte check. Reject early.
7. **Encoding** — read as UTF-8, `errors="replace"` on read; warn `non_utf8_chars_replaced` if any replacement occurred. Same as existing GET `/api/scripts/<id>` does.
8. **Tabs vs spaces (Python)** — expand tabs to 4 spaces in extracted actions before re-indenting. The `_render_harness` step assumes space-only indentation.
9. **`@playwright/test` calls `request.newContext()` / API testing** — extracted body keeps the calls; harness already provides `page` and `context` fixtures, but user's `request` API code uses a different fixture. Warn `unsupported_fixture` if the action body references `({ page, context, request, ... })` destructuring beyond `page` and `context`.
10. **Trailing semicolons / single-quote vs double-quote** — leave alone. Don't reformat.
11. **`page.pause()` left in by user** — don't strip. Warn `pause_call_present` so headless runs don't hang silently.
12. **QAClan harness re-import round-trip** — exporting then re-importing must be idempotent (same content out as in). Add a unit test for this once implementation lands.

## 11. Out of scope (deferred)

- Importing a directory / zip of scripts. Single file only.
- Cross-language conversion (python → js).
- Importing the `playwright.config.js` of an existing project.
- Auto-creating env vars from sniffed URLs/secrets.
- Importing into an existing script (overwrite). For now, every import creates a new script.

## 12. Open questions

- Should the diagnostics banner persist across the editor session until dismissed, or auto-clear once the user starts editing? Lean: auto-clear on first edit, with a "show again" link.
- Should we offer a "View original" button in Modal B that re-opens the raw file from Modal A? Probably yes — single state held in `window._qcImportRaw` until Modal B closes.
- Default behavior for `*_test` files imported as plain `javascript`/`typescript`: refuse, or auto-promote to the test variant? Lean: auto-promote, with `info` warning. Filename `.spec.ts` is unambiguous.

---

End of plan. Implementation order when greenlit: (1) `_shared.detect_qaclan_harness` + warning dataclass, (2) per-strategy `extract_actions_freeform`, (3) `import-preview` route, (4) Modal A, (5) Modal B + banner, (6) end-to-end smoke test per strategy with one real-world script each.
