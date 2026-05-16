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
    "action_index": 4,
    "action_text": "expect(page.locator('#submit-btn')).to_be_visible()",
    "timeout_ms": 7000,
    "raw_traceback": "Traceback (most recent call last): ..."
  }
}
```

- Wrap `{ACTIONS}` so each action is numbered; on exception the harness records the index + source line of the failing action. Strategies already template `{ACTIONS}` — emit a small action manifest at render time so the index maps back to a readable step.
- Harness classifies the exception locally (see 2.2) and writes `error` into the artifacts file. The runner reads it instead of scraping stderr.
- Must be done in **all 4 strategies** (`python`, `javascript`, `javascript_test`, `typescript_test`) — keep the JSON shape identical across languages so the runner/report are language-agnostic.
- `raw_traceback` is still kept for the technical "Details" view.

### 2.2 Error classifier (shared, offline)

New module `cli/error_classifier.py` — pure pattern matching, no I/O. Maps a raw exception type + message to:

| Category | Trigger pattern | Plain-language message |
|---|---|---|
| `ASSERTION_FAILED` | `AssertionError`, `expect(...)` | "A check did not pass: the page was not in the expected state." |
| `ELEMENT_NOT_FOUND` | `TimeoutError` + locator wait | "Could not find an element on the page (e.g. a button or field)." |
| `TIMEOUT` | `TimeoutError`, subprocess timeout | "The page took too long to respond." |
| `NAVIGATION_FAILED` | `goto`/`net::ERR` | "The page or website could not be opened." |
| `NETWORK_ERROR` | request-failed dominates | "A network request failed while loading the page." |
| `SCRIPT_ERROR` | syntax / import errors | "The test script itself has a problem." |
| `RUNTIME_ERROR` | internal runner exception | "The test could not be run due to an internal error." |
| `UNKNOWN` | fallback | "The test failed for an unknown reason." |

Each category carries: a short title, a plain message, a suggested next step ("Check the screenshot", "Verify the URL in the environment"), and a severity.

Used by **both** the harness (to classify the script exception) and the runner (to classify timeout / internal-error paths where there is no harness output).

### 2.3 Runner changes (`web/routes/runs.py`)

Replace the ad-hoc `error_msg` construction in all three paths with one helper:

```python
def _build_error_detail(*, returncode, stdout, stderr, artifacts, kind):
    # kind: "subprocess" | "timeout" | "internal"
    # 1. prefer artifacts["error"] (harness already classified)
    # 2. else classify(stderr/stdout) or the timeout/internal kind
    # returns dict: {category, title, message, next_step, severity,
    #                raw_message, raw_traceback}
```

- L373–398 → call `_build_error_detail(kind="subprocess")`.
- L426 (timeout) → `_build_error_detail(kind="timeout")` (still read artifacts — partial console/network data may exist).
- L462 (internal) → `_build_error_detail(kind="internal")`.

All three paths now produce the **same structured dict**.

### 2.4 DB schema

Add one column via `_run_migrations()` in `cli/db.py`:

- `error_detail TEXT` — JSON of the structured dict above.

Keep `error_message TEXT` as-is (raw text, backward compatible, used by cloud sync). `error_detail` is the new primary field; `error_message` becomes the `raw_message` for legacy/sync consumers. No breaking change — old rows simply have `error_detail = NULL` and the UI falls back to `error_message`.

`script_results` in-memory dict gains `error_detail` so the live UI gets it too.

---

## 3. Making errors visible / structured in the UI

- **Run detail view** — per failed script, render a card:
  - Category badge + plain-language title (color by severity).
  - One-line message + suggested next step.
  - Failing step (`action_text`, selector) when available.
  - Screenshot thumbnail (already saved at `screenshot_path`).
  - Collapsible "Technical details" → `raw_traceback`, console errors, network failures.
- **Suite run summary** — group failures by category ("3 timeouts, 1 element-not-found") so a user sees the pattern at a glance.
- **CLI** (`cli/commands/runs.py`) — print category + plain message instead of nothing, raw traceback behind `--verbose`.

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

1. `cli/error_classifier.py` — classifier + category table (unit-testable, no deps).
2. Extend Python harness to emit `error` in artifacts; verify shape.
3. Repeat for the 3 JS/TS strategies (identical JSON shape).
4. DB migration: add `error_detail`.
5. Runner: `_build_error_detail` helper, wire all 3 failure paths.
6. UI run-detail card + suite summary grouping.
7. `cli/report.py` + `report.html` template; CLI command + web download button.
8. CLI `runs` output uses plain messages.

Steps 1–5 are the structural core; 6–8 are presentation and can ship after.
