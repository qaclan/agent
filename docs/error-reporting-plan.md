# Structured Error Reporting Plan

## Goal

Today a failed script produces a raw, language-specific blob (`error_message` = stderr + stdout dump). A non-technical user cannot read a Python traceback or a Node stack. This plan makes failures **classified, structured, and human-readable**, and adds an **offline report**.

Hard constraint: agent runs offline. No network calls, no LLM, no external services. All classification is local pattern matching.

---

## 1. How it currently works

### Execution path (`web/routes/runs.py`)

- **L304** — per-script `try` block opens.
- **L361** — `subprocess.run(cmd, ...)` runs the rendered harness, captures stdout/stderr.
- **L371** — `_read_artifacts(artifacts_path)` reads the harness-written JSON → `console_errors`, `network_failures` (lists of dicts).
- **L373–398** — branch on `proc.returncode`:
  - `0` → `PASSED`, `error_msg = None`.
  - non-zero → `FAILED`. `error_msg` built by concatenating `[stderr]\n...` + `[stdout]\n...` (L390) — **raw, unstructured**.
- **L400** — `INSERT INTO script_runs` with `error_message`, `console_errors`/`network_failures` (counts), `console_log`/`network_log` (JSON).
- **L426** — `subprocess.TimeoutExpired` → `FAILED`, `error_msg = "Script timed out after Ns"`.
- **L462** — generic `Exception` → `FAILED`, `error_msg = traceback.format_exc()` — **full Python traceback of the runner itself**.

### What the harness produces (`cli/script_strategies/*`)

- Each strategy harness registers listeners (`_on_console`, `_on_pageerror`, `_on_requestfailed`) and writes `{console_errors, network_failures}` to `QACLAN_ARTIFACTS_PATH` in a `finally` (`python_strategy.py` L69–79, L138–147).
- On a script exception the harness only does `traceback.print_exc()` + `sys.exit(1)` (L142–144). The **structured exception is lost** — runner re-scrapes it from stderr.

### DB schema (`cli/db.py` ~L100, ~L300)

`script_runs` columns: `error_message TEXT`, `console_errors INTEGER`, `network_failures INTEGER`, `console_log TEXT`(json), `network_log TEXT`(json), `screenshot_path`.

### Problems

1. `error_message` is a raw traceback / stderr dump — language-specific, unreadable for non-tech users.
2. No **classification** — assertion failure vs. element-not-found vs. timeout vs. navigation error all look identical.
3. No **step context** — which action failed (line, selector, expected value) is buried in the stack.
4. Three failure paths produce three different `error_message` shapes (subprocess fail / timeout / internal error).
5. `console_errors` / `network_failures` are captured but never surfaced in a digestible way.

---

## 2. Plan — structured error capture

### 2.1 Harness emits a structured error object

The harness owns the live exception — it is the right place to classify. Extend the artifacts JSON written by every strategy:

```json
{
  "console_errors": [...],
  "network_failures": [...],
  "error": {
    "category": "ASSERTION_FAILED",
    "raw_type": "AssertionError",
    "raw_message": "Locator expected to be visible ...",
    "selector": "#submit-btn",
    "timeout_ms": 7000
  }
}
```

- Harness classifies the exception locally (see 2.2) and writes `error` into the artifacts file. The runner reads it instead of scraping stderr.
- `error` is **optional** — `_read_artifacts` already uses `.get()`, so old artifacts without the key still parse. No migration needed for the artifacts format.
- The raw traceback stays in `error_message` only (see 2.4) — **not** duplicated inside `error`. `error` holds the structured/classified fields; the raw blob lives in one place.
- Must be done in **all 4 strategies** — but the write mechanism differs:
  - **`python`, `javascript`** (plain harnesses) — already write artifacts in their own `finally` / `.catch(err)`. The live `err` is in scope there → classify and write `error` directly.
  - **`javascript_test`, `typescript_test`** (`@playwright/test` harnesses) — artifacts are written in `test.afterAll`, which has **no access to the thrown `err`**. The `catch (err) { throw err }` re-throws into the Playwright test runner. Fix: stash the error in a module-level var before re-throwing, then `afterAll` reads it:
    ```js
    let _scriptError = null;
    // ...
    } catch (err) { /* screenshot */ _scriptError = err; throw err; }
    // test.afterAll: classify _scriptError, write into artifacts
    ```
    **Caveat:** the `catch` relay only fires for *thrown* exceptions. A `@playwright/test` **per-test timeout** aborts the test without running the `catch` block — `_scriptError` stays null and `afterAll` writes `error: null`. That case is fine: the subprocess still exits non-zero and the runner classifies `TIMEOUT` from stderr (`Test timeout of NNNNms exceeded`). Likewise a **TypeScript/compile failure** in `typescript_test` means the test file never loads, `afterAll` never runs, and *no artifacts file* is produced — the runner must classify `SCRIPT_ERROR` purely from stderr. Both are handled by the classifier's stderr-fallback path; the harness `error` is best-effort, not guaranteed.
- Keep the JSON shape identical across all 4 languages so the runner/report stay language-agnostic.

> **Optional / phase-2 — failing-step context.** `action_index` + `action_text` (which numbered action failed) require an action manifest emitted at render time. This touches the recording/render pipeline and is awkward for the `*_test` strategies (actions nested inside a `test()` callback). The core plan works without it — treat as a later enhancement, not a blocker.

### 2.2 Error classifier (shared, offline)

New module `cli/error_classifier.py` — pure pattern matching, no I/O.

> **Classify by the message prefix, not just the exception type.** Playwright embeds the failing API call at the start of every error message — `locator.click:`, `page.goto:`, `expect(locator).toBeVisible:`, `browserType.launch:`, etc. The *same* `TimeoutError` type maps to three different categories depending on that prefix (a `goto` timeout → `NAVIGATION_FAILED`, a locator wait → `ELEMENT_NOT_FOUND`, an `expect` → `ASSERTION_FAILED`, bare → `TIMEOUT`). So the classifier keys on **(exception type, message-prefix, message-body keywords)**, with an explicit ordered rule list — first match wins. Type alone is insufficient.

| Category | Trigger pattern | Plain-language message | Suggested next step |
|---|---|---|---|
| `ASSERTION_FAILED` | `AssertionError`; message starts `expect(` / contains `expected to` | "A check did not pass: the page was not in the expected state." | Check the screenshot |
| `ELEMENT_NOT_FOUND` | locator wait timeout; `strict mode violation ... resolved to N elements`; actionability fail (`not visible` / `not enabled` / `not stable` / `intercepts pointer events` / `outside of the viewport`) | "Could not find or interact with an element (e.g. a button or field)." | Page layout may have changed — re-record |
| `TIMEOUT` | bare Playwright `TimeoutError`, Playwright-test per-test timeout, **or** subprocess kill | "The page took too long to respond." | Check the site is reachable |
| `NAVIGATION_FAILED` | `page.goto:` / `net::ERR` / `Execution context was destroyed ... navigation` | "The page or website could not be opened." | Verify the URL in the environment |
| `NETWORK_ERROR` | request-failed dominates | "A network request failed while loading the page." | Check network / the API being called |
| `BROWSER_CRASHED` | `TargetClosedError`; `Target ... has been closed`; `Browser has been closed`; worker process crash | "The browser stopped unexpectedly during the test." | Re-run; if it repeats, report it |
| `CONFIG_ERROR` | unresolved `{{KEY}}` placeholder, missing env var, bad `var_keys` | "A required setting or value is missing." | Edit the environment, add the missing value |
| `SETUP_ERROR` | broken runtime, Chromium missing (`Executable doesn't exist`), `validate_runtime()` fail | "The test tools are not installed correctly." | Run `qaclan setup` |
| `SCRIPT_MISSING` | `FileNotFoundError` — script file gone (runs.py:311) | "The test script file could not be found." | The script may have been deleted |
| `SCRIPT_ERROR` | syntax / import / TypeScript-compile errors inside the script body | "The test script itself has a problem." | Re-record or edit the script |
| `RUNTIME_ERROR` | internal runner exception | "The test could not be run due to an internal error." | Report this — internal bug |
| `UNKNOWN` | fallback | "The test failed for an unknown reason." | See technical details |

Each category carries: a short title, a plain message, a suggested next step, and a severity.

`ELEMENT_NOT_FOUND` deliberately covers three Playwright failure shapes that all mean "the script could not use a target element": **0 matches** (locator timeout), **N>1 matches** (strict-mode violation), and **found-but-unusable** (actionability failures during `click`/`fill`). Splitting them would not change the user's next step (re-record), so they share one category; the `raw_type` field preserves the distinction for the technical view.

Rationale for the extra categories: the original 8 assumed every failure is *in the page*. But `SETUP_ERROR` (run `qaclan setup`), `CONFIG_ERROR` (fix the environment), `SCRIPT_MISSING`, and `BROWSER_CRASHED` (not the user's fault) need different advice. Folding them into `SCRIPT_ERROR` would give the user wrong next steps.

**Ordered rule list (first match wins)** — overlap is real, so order is part of the spec:
1. `SCRIPT_MISSING`, `SETUP_ERROR`, `CONFIG_ERROR` — environment problems, checked before any page-level rule.
2. `BROWSER_CRASHED` — target/browser closed (otherwise misreads as a timeout).
3. `ASSERTION_FAILED` — message prefix `expect(`.
4. `NAVIGATION_FAILED` — prefix `page.goto:` / `net::ERR`.
5. `ELEMENT_NOT_FOUND` — locator-call prefix + (timeout | strict-mode | actionability).
6. `TIMEOUT` — any remaining `TimeoutError` / subprocess kill.
7. `NETWORK_ERROR` — only if no exception but request failures dominate.
8. `SCRIPT_ERROR` — syntax / import / compile signatures.
9. `RUNTIME_ERROR` → `UNKNOWN` — fallbacks.

Used by **both** the harness (to classify the script exception) and the runner (to classify timeout / internal-error paths where there is no harness output).

**Two distinct timeout sources** feed `TIMEOUT`:
1. **Playwright timeout inside the harness** — a locator wait / `page.setDefaultTimeout(30000)` expires, *or* (for `*_test` strategies) the `@playwright/test` per-test timeout (default 30s) expires. The harness exits non-zero with artifacts written — handled by the `subprocess` path.
2. **Subprocess kill** — the whole process exceeds `PER_SCRIPT_TIMEOUT_SEC` (300s) and is killed. No harness `error`, possibly partial artifacts — handled by the `timeout` path.

The classifier handles both; the runner just picks the right `kind`.

### 2.3 Runner changes (`web/routes/runs.py`)

Replace the ad-hoc `error_msg` construction in all three paths with one helper:

```python
def _build_error_detail(*, returncode, stdout, stderr, artifacts, kind):
    # kind: "subprocess" | "timeout" | "internal"
    # 1. prefer artifacts["error"] (harness already classified)
    # 2. else classify(stderr/stdout) or the timeout/internal kind
    # returns (detail, raw): detail = structured dict written to the
    #   error_detail column; raw = the raw blob written to error_message.
    # The raw blob is NOT embedded in detail — stored once (see 2.4).
```

- L373–398 → call `_build_error_detail(kind="subprocess")`. Note: a Playwright-test per-test timeout (default 30s) lands **here**, not in the timeout path — the subprocess exits non-zero on its own. The classifier still resolves it to `TIMEOUT` via the harness `error` or stderr pattern.
- L426 (timeout) → `_build_error_detail(kind="timeout")` — this path only fires on the 300s `PER_SCRIPT_TIMEOUT_SEC` subprocess kill. Still read artifacts — partial console/network data may exist.
- L462 (internal) → `_build_error_detail(kind="internal")`.

All three paths now produce the **same structured dict**.

### 2.4 DB schema

Add one column via `_run_migrations()` in `cli/db.py`:

- `error_detail TEXT` — JSON of the structured dict: `{category, title, message, next_step, severity, raw_type, selector, timeout_ms}`.

Keep `error_message TEXT` as-is — it holds the **raw** traceback / stderr blob (backward compatible, used by cloud sync). The raw blob is stored **once**, here — `error_detail` does **not** repeat it. UI/report show `error_detail` by default and reveal `error_message` under "Technical details". No breaking change — old rows have `error_detail = NULL` and the UI falls back to `error_message`.

`script_results` in-memory dict gains `error_detail` so the live UI gets it too.

---

## 3. Making errors visible / structured in the UI

- **Run detail view** — per failed script, render a card:
  - Category badge + plain-language title (color by severity).
  - One-line message + suggested next step.
  - Failing step (selector, and `action_text` if the phase-2 manifest exists) when available.
  - Screenshot thumbnail (already saved at `screenshot_path`).
  - Collapsible "Technical details" → raw `error_message`, console errors/warnings, network failures.
- **Suite run summary** — group failures by category ("3 timeouts, 1 element-not-found") so a user sees the pattern at a glance.
- **CLI** (`cli/commands/runs.py`) — print category + plain message instead of nothing, raw `error_message` behind `--verbose`.

> **Wording note.** The harness captures `msg.type in ("error", "warning")` — the `console_errors` count therefore includes console **warnings**, not only errors. Label it "console errors/warnings" everywhere in the UI, report, and CLI so the number isn't misread.

---

## 4. Offline report

New: `qaclan runs report <run_id>` + a "Download report" button in the web UI.

- Generate a **self-contained HTML file** (single file, screenshots inlined as base64 data URIs) — opens in any browser with no server, no internet. This is the offline-safe choice over a hosted dashboard.
- Optional plain-text / Markdown variant for sharing.
- Report sections:
  1. **Header** — suite name, date, environment, browser, total duration, pass/fail/skip counts.
  2. **Summary** — pass-rate bar; failures grouped by category.
  3. **Per-script** — status, duration, and for failures: category badge, plain message, next step, failing step, **embedded screenshot**, collapsible technical details.
  4. **Footer** — agent version, run id.
- Implementation: a Jinja-style template rendered from `script_runs` rows. No new dependencies beyond what Flask already pulls in; if avoiding Jinja, a plain `.format()` template works.
- Template lives in `web/templates/report.html`; generator in `cli/report.py` so both CLI and web reuse it.

---

## 5. Suggested order of work

1. `cli/error_classifier.py` — classifier + 11-category table (unit-testable, no deps).
2. Extend Python + plain JavaScript harnesses to emit `error` in artifacts (live `err` in scope at the existing write site).
3. `javascript_test` + `typescript_test` — add the module-var error relay (`catch` stashes, `afterAll` writes). Keep JSON shape identical to step 2.
4. DB migration: add `error_detail`.
5. Runner: `_build_error_detail` helper, wire all 3 failure paths.
6. UI run-detail card + suite summary grouping.
7. `cli/report.py` + `report.html` template; CLI command + web download button.
8. CLI `runs` output uses plain messages.

Steps 1–5 are the structural core; 6–8 are presentation and can ship after.

---

## Session notes

- 2026-05-16: Implemented all 8 steps. Deviations from the plan, all
  deliberate:
  - **Classifier runs only in the runner, not the harness.** `cli/error_classifier.py`
    is Python and cannot be imported by the JS/TS harness subprocesses.
    Duplicating the ordered rule list into three harness templates was rejected.
    Instead each harness emits only the raw exception fields
    (`error: {raw_type, raw_message}`) into the artifacts JSON; the runner runs
    the one classifier on those fields. Single source of truth, same JSON shape
    across all 4 strategies. Stderr fallback (timeout / compile-fail / missing
    artifacts) unchanged.
  - **Report template inlined in `cli/report.py`** instead of a separate
    `web/templates/report.html`. Keeping it inline avoids adding another
    `--include-data-dir` to `build.sh` + the Windows workflow for Nuitka.
  - **Phase-2 action manifest** (`action_index` / `action_text`) not built —
    plan marks it optional. `error_detail.selector` is extracted from the
    Playwright message by the classifier, which covers the failing-step view.
  - New column `script_runs.error_detail` (migration `_migrate_error_detail`).
    `error_detail` is parsed to an object in `GET /api/runs/<id>`; the live
    `script_results` dict also carries it. Runner helper `_build_error_detail`
    drives all 3 failure paths. Report: `qaclan runs report <id>` +
    `GET /api/runs/<id>/report` + web "Download report" button.
  - This unblocks Layer 4 (reactive fix-after-failure) in
    `docs/expect-timeout-strategy-plan.md` — its required `error` object and
    `error_detail` column now exist.

---

## 6. Revision — dynamic, information-rich messages (2026-05-16)

### 6.1 Why

Real run, `javascript_test` strategy:

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('#notificationRailBackdrop')
  - locator resolved to <div hidden id="notificationRailBackdrop" ...>
  - attempting click action
  - 2 × waiting for element to be visible, enabled and stable
    - element is not visible
```

Two failures:

1. **Misclassified.** Came out `ASSERTION_FAILED`. Correct = `ELEMENT_NOT_FOUND`
   (locator-call timeout + actionability fail). Cause: the runner fell back to
   the **stderr blob**, which contains the rendered code snippet (`> 41 | .click()`
   plus the *next* line `42 | await expect(...).toBeVisible()`). `_is_assertion`
   does a loose `"expect(" in low` — it matched the **source code**, not the error.
2. **Generic message.** Even classified right, `CATEGORIES[*]["message"]` is one
   frozen sentence. `selector` / `timeout_ms` are extracted but sit in side
   fields — the message never says *what* element, *which* action, *how long*,
   or that the element **was found but stayed hidden**. Non-tech and tech users
   both learn nothing.

### 6.2 Classification fixes (correctness)

- **Trust the harness `error` exclusively when present.** In `_build_error_detail`
  subprocess path, when `artifacts_error` has a `raw_message`, classify on
  `raw_type`/`raw_message` **only** — do not also pass `stderr`/`stdout`. The
  stderr blob carries rendered source code and fools keyword rules. Stderr is
  the fallback for the *no-artifacts* case only (timeout / compile-fail).
- **Strip code-snippet gutter lines before classifying the stderr blob.**
  Bug A only helps when a harness `error` exists. The stderr-fallback path is
  permanent (compile-fail, 300s-kill, or a missing harness `error` never have
  one) — so the classifier itself must survive raw stderr. `@playwright/test`
  renders the failing source with a line-number gutter; every snippet line
  matches `^\s*>?\s*\d+\s*\|`. New helper `strip_code_snippet(blob)` drops those
  lines. After stripping, only Playwright's real error text + `Call log:`
  remain — no stray `await expect(...)` source for `_is_assertion` to match.
  The classifier runs keyword rules on the stripped text.
- Rule order unchanged; this is input sanitisation + Bug A, not a re-order.

### 6.3 Richer field extraction

The classifier extracts these from `raw_message` (Playwright embeds an identical
`<api>: <reason>` + `Call log:` block in every language — all 5 strategies):

| Field | Source | Example |
|---|---|---|
| `action` | message API prefix | `locator.click`, `page.goto`, `expect` |
| `selector` | already extracted | `#notificationRailBackdrop` |
| `timeout_ms` | already extracted | `30000` |
| `actionability` | Call-log `element is not <state>` / `intercepts pointer events` / `outside of the viewport` / `not attached` | `not visible` |
| `element_state` | Call-log `locator resolved to <…>` present? `hidden`/`display:none` in it? | `found-but-hidden` \| `never-appeared` |
| `match_count` | `resolved to N elements` (strict mode) | `3` |
| `url` | `navigating to "…"` / `page.goto` arg | `https://…` |
| `net_error` | `net::ERR_[A-Z_]+` | `ERR_NAME_NOT_RESOLVED` |

All optional — absent fields just don't render.

### 6.4 Dynamic title / message / next_step

`CATEGORIES` frozen strings become **fallback defaults**. Add per-category
builder functions: `describe(category, fields) -> (title, message, next_step)`.
The builder interpolates extracted fields into plain sentences; when a field is
missing it degrades to the static default. One sentence, two audiences — plain
words for non-tech, with the exact selector/action/timeout inline for tech.

Examples (`ELEMENT_NOT_FOUND`, one category, message varies by `element_state`):

- *found-but-hidden* — "The script tried to **click** `#notificationRailBackdrop`
  but gave up after 30s. The element exists on the page but stayed **hidden** —
  so the click never happened." → next: "A step that opens/reveals it may be
  missing. If it should already be visible, the page changed — re-record."
- *never-appeared* — "The script waited 30s for `#submit` to **appear** but it
  never showed up." → next: "The page layout may have changed — re-record."
- *strict-mode* (`match_count=3`) — "The selector `.row` matched **3 elements**
  but the script needs exactly one." → next: "Make the selector specific to a
  single element, then re-record."

`TIMEOUT` / `NAVIGATION_FAILED` / `ASSERTION_FAILED` / `SETUP_ERROR` etc. get
the same treatment — interpolate `action`, `url`, `net_error`, `timeout_ms`.

### 6.5 Scope

- **No strategy changes.** All 5 strategies already emit `{raw_type, raw_message}`;
  classifier is runner-side and language-agnostic.
- `classify()` return dict gains the new optional keys (`action`, `actionability`,
  `element_state`, `match_count`, `url`, `net_error`). Backward compatible —
  `category`/`title`/`message`/`next_step`/`severity`/`raw_type`/`selector`/
  `timeout_ms` keys all stay.
- `error_detail` JSON column already stores the whole dict — no migration.
- UI card / report / CLI: render the new fields as a small "Diagnostics" line
  (action · selector · timeout · element state). Raw blob stays collapsible.

### 6.6 Work items

1. `cli/error_classifier.py` — new extraction helpers; `describe()` builders per
   category; tighten `_is_assertion`; keep ordered rule list.
2. `web/routes/runs.py` `_build_error_detail` — drop `stderr`/`stdout` from the
   `classify()` call when `artifacts_error` has a `raw_message`.
3. `web/static/app.js` + `style.css` — diagnostics line in the error card.
4. `cli/report.py` — diagnostics line in the per-script block.
5. `cli/commands/runs.py` — diagnostics line in `runs show`.

Steps 1–2 are correctness; 3–5 presentation.
