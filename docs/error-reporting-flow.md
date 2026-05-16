# Error Reporting — How It Works (and the classify mismatch)

This document explains the structured error-reporting pipeline end to end:
how a script failure travels from the browser to the run-detail card, where
the classifier sits, and **why the current classifier can mismatch** a failure
into the wrong category. It complements `error-reporting-plan.md` (the plan)
and `error-reporting-plan.md §6` (the fix).

---

## Part 1 — The classify mismatch

### 1.1 The symptom

A real run on the `javascript_test` strategy produced this Playwright error:

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('#notificationRailBackdrop')
  - locator resolved to <div hidden id="notificationRailBackdrop" class="...">
  - attempting click action
  - 2 × waiting for element to be visible, enabled and stable
    - element is not visible
  ...
```

The failing line, as rendered by `@playwright/test` into **stderr**:

```
  39 |     await page.getByRole('button', { name: 'Login' }).click();
  40 |     await page.locator('.header-left').click();
> 41 |     await page.locator('#notificationRailBackdrop').click();
     |                                                     ^
  42 |     await expect(page.getByRole('heading', { name: 'Activity Stream' })).toBeVisible();
```

**Correct category:** `ELEMENT_NOT_FOUND` — a locator-call (`locator.click`)
timed out, and the Call log shows an actionability failure (`element is not
visible`). The element was found but stayed hidden.

**What the runner produced:** `ASSERTION_FAILED` — "Check did not pass".

That message is wrong *and* useless: there was no assertion. The real cause
(a hidden element) is nowhere in the output.

### 1.2 Root cause — two bugs compounding

**Bug A — the runner feeds source code into the classifier.**

`web/routes/runs.py` `_build_error_detail`, subprocess path, calls:

```python
detail = classify(
    raw_type=(artifacts_error or {}).get("raw_type"),
    raw_message=(artifacts_error or {}).get("raw_message"),
    stderr=stderr_txt, stdout=stdout_txt,   # <-- always passed
    kind="subprocess", ...
)
```

It passes **both** the harness's structured `error` (clean: `raw_type` +
`raw_message`) **and** the raw `stderr`/`stdout` blob. Inside `classify()`:

```python
msg = raw_message or ""
if not msg:
    msg = "\n".join(p for p in (stderr or "", stdout or "") if p).strip()
```

So `stderr` is only used **as a fallback** when `raw_message` is empty. When
the harness `error` is present, `stderr` is ignored — fine. **But when the
harness `error` is missing**, `msg` becomes the entire stderr blob — which
includes the rendered source-code snippet above. That snippet contains line 42:

```
await expect(page.getByRole('heading', ...)).toBeVisible();
```

**Bug B — `_is_assertion` matches a substring, not the error.**

`cli/error_classifier.py`:

```python
def _is_assertion(rt, msg):
    low = msg.lower()
    return (
        "assertionerror" in rt
        or "expect(" in low          # <-- matches the CODE SNIPPET
        or "expected to be" in low
        ...
    )
```

`"expect(" in low` is `True` because the stderr blob contains the *source code*
`await expect(...)` on line 42 — the line *after* the one that failed. The
classifier cannot tell "this is the error" from "this is a line of code printed
near the error". `ASSERTION_FAILED` is rule #5 in the ordered list, and it wins
before `ELEMENT_NOT_FOUND` (rule #7) ever gets a chance.

### 1.3 Why the harness `error` was missing in this run

With a correct harness `error` (`raw_type="TimeoutError"`,
`raw_message="locator.click: Timeout 30000ms exceeded.\nCall log:\n  - ...\n
  - element is not visible"`), `classify()` would use only `raw_message` —
which has **no** `expect(` substring — and `_is_element_not_found` would match
on `element is not visible`. Correct result.

The mismatch only happens on the **stderr-fallback path**: a `*_test` per-test
timeout, a compile failure, or any case where `test.afterAll` did not write the
artifacts `error`. Those paths are exactly where the stderr blob — full of
source code — is the only input. So the fallback path is fragile by design.

### 1.4 The fix (see plan §6.2)

1. **Runner (Bug A):** when `artifacts_error` has a `raw_message`, call
   `classify()` with `raw_type`/`raw_message` **only** — do not pass
   `stderr`/`stdout`. This protects every run that *has* a harness `error`.
2. **Classifier (Bug B):** Bug A does nothing when the harness `error` is
   missing — and that path is permanent (compile-fail, 300s-kill, lost
   `error`). So the classifier must survive raw stderr. New helper
   `strip_code_snippet(blob)` drops every line that matches the
   `@playwright/test` source gutter `^\s*>?\s*\d+\s*\|`. After stripping, the
   `await expect(...)` on line 42 is gone — only Playwright's real error text
   and `Call log:` remain. `_is_element_not_found` then matches `element is
   not visible` and wins.

Bug A covers the common case; Bug B is the one that fixes **this** run, where
no harness `error` existed at all.

---

## Part 2 — Full pipeline, step by step

### Components

| Stage | File | Role |
|---|---|---|
| Harness | `cli/script_strategies/*_strategy.py` | Runs the test, catches the live exception, writes artifacts JSON |
| Runner | `web/routes/runs.py` `execute_run` | Spawns one subprocess per script, reads artifacts, builds the error detail, writes the DB |
| Classifier | `cli/error_classifier.py` | Pure offline pattern matcher: raw fields → structured category |
| DB | `cli/db.py` `script_runs` | `error_message` (raw blob) + `error_detail` (JSON) columns |
| API | `web/routes/runs.py` `GET /api/runs/<id>` | Parses `error_detail` JSON, returns it to the SPA |
| UI | `web/static/app.js` `showRunResults` | Renders the error card |
| Report | `cli/report.py` | Offline HTML report |
| CLI | `cli/commands/runs.py` `runs show` | Terminal output |

### The flow

```
 ┌─────────┐   artifacts.json    ┌────────┐   classify()   ┌────────────┐
 │ HARNESS │ ──{console,network, │ RUNNER │ ─────────────▶ │ CLASSIFIER │
 │         │      error}──────▶  │        │ ◀───detail──── │            │
 └─────────┘                     └───┬────┘                └────────────┘
   subprocess                        │ INSERT script_runs
                                      │  error_message = raw blob
                                      │  error_detail   = JSON(detail)
                                      ▼
                              ┌──────────────┐
                              │  script_runs │
                              └──────┬───────┘
                            ┌────────┼─────────┐
                            ▼        ▼         ▼
                       GET /api   runs show  report.py
                          │
                          ▼
                       app.js error card
```

### Step 1 — Harness runs and writes artifacts

Each strategy renders a self-contained harness. It registers console / page-error
/ request-failed listeners, runs the recorded actions, and on exit writes a JSON
file to `QACLAN_ARTIFACTS_PATH`:

```json
{
  "console_errors": [ ... ],
  "network_failures": [ ... ],
  "error": { "raw_type": "TimeoutError", "raw_message": "locator.click: Timeout 30000ms exceeded.\nCall log:\n  - ..." }
}
```

- `python` / `javascript` / `typescript` — the live `err` is in scope at the
  `finally` / `.catch(err)` write site; `error` is written directly.
- `javascript_test` / `typescript_test` — `test.afterAll` writes artifacts but
  has no access to the thrown `err`. The `catch` block stashes it in a
  module-level `_scriptError`; `afterAll` reads it.
- `error` is **best-effort**. A per-test timeout or a compile failure can skip
  the `catch` / `afterAll` entirely — then there is no `error` key, or no
  artifacts file at all.
- The harness only emits **raw** fields (`raw_type`, `raw_message`). It does
  **not** classify — the classifier is Python and cannot be imported by JS/TS
  subprocesses. One classifier, runner-side. (See plan §5 session notes.)

### Step 2 — Runner reads artifacts

`web/routes/runs.py`:

```python
console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)
```

`_read_artifacts` returns `(console_errors, network_failures, error)`. A missing
or malformed file degrades to `([], [], None)` — a crashed script may have
written nothing.

### Step 3 — Runner classifies — three failure paths

`execute_run` has three `except`/branch paths, each calling `_build_error_detail`
with a different `kind`:

| Path | `kind` | When |
|---|---|---|
| `proc.returncode != 0` | `"subprocess"` | Script ran and exited non-zero (incl. Playwright per-test 30s timeout) |
| `subprocess.TimeoutExpired` | `"timeout"` | Whole subprocess exceeded `PER_SCRIPT_TIMEOUT_SEC` (300s) and was killed |
| generic `except Exception` | `"internal"` | Runner-side bug — before/after the subprocess |

`_build_error_detail` returns `(detail, raw)`:

- `detail` — structured dict from `classify()` → stored in `error_detail`.
- `raw` — the unchanged raw blob (`[stderr]\n...\n\n[stdout]\n...`, or
  `traceback.format_exc()`, or `Script timed out after 300s`) → stored in
  `error_message`. The raw blob is stored **once**; it is not duplicated inside
  `detail`.

### Step 4 — The classifier

`cli/error_classifier.py` `classify()` is pure pattern matching — no I/O, no
network, no LLM (hard offline constraint).

1. Pick the message to match: `raw_message` if present, else the stderr/stdout
   blob (the fragile fallback — see Part 1).
2. Branch on `kind`:
   - `internal` → environment rules (`SCRIPT_MISSING` / `CONFIG_ERROR` /
     `SETUP_ERROR`), else `RUNTIME_ERROR`.
   - `timeout` → `TIMEOUT`.
   - `subprocess` → the **ordered rule list, first match wins**:
     ```
     SCRIPT_MISSING → SETUP_ERROR → CONFIG_ERROR → BROWSER_CRASHED →
     ASSERTION_FAILED → NAVIGATION_FAILED → ELEMENT_NOT_FOUND →
     TIMEOUT → SCRIPT_ERROR → (NETWORK_ERROR | UNKNOWN)
     ```
3. Look up the category's `title` / `message` / `next_step` / `severity`.
4. Extract side fields: `selector`, `timeout_ms` (and, after §6, `action`,
   `actionability`, `element_state`, `match_count`, `url`, `net_error`).

Output dict:

```json
{
  "category": "ELEMENT_NOT_FOUND",
  "title": "Element not found",
  "message": "Could not find or interact with an element ...",
  "next_step": "The page layout may have changed — re-record the script.",
  "severity": "error",
  "raw_type": "TimeoutError",
  "selector": "locator('#notificationRailBackdrop')",
  "timeout_ms": 30000
}
```

> Order is part of the spec because categories overlap. `BROWSER_CRASHED`
> precedes `TIMEOUT` (a closed target otherwise reads as a timeout);
> environment rules precede every page-level rule.

### Step 5 — DB write

`INSERT INTO script_runs (..., error_message, error_detail, ...)`:

- `error_message TEXT` — the raw blob. Backward compatible, used by cloud sync.
- `error_detail TEXT` — `json.dumps(detail)`. Added by migration
  `_migrate_error_detail`. Old rows have `NULL`.

The in-memory `script_results` dict also carries `error_detail` so the live UI
gets it without a re-fetch.

### Step 6 — API serves it

`GET /api/runs/<id>` selects `scr.error_detail` and `json.loads()` the string
back into an object before returning JSON to the SPA. Old rows → `None`.

### Step 7 — Surfaces render it

- **Web** — `app.js` `showRunResults` renders an `error-card`: severity-coloured
  badge, `title`, `message`, `next_step`, failing selector, screenshot, and a
  collapsible "Technical details" holding the raw `error_message`. Runs without
  `error_detail` fall back to the old friendly-error block.
- **CLI** — `runs show` prints `[category] title`, the plain `message`, the
  `next_step`, and the selector. `-v/--verbose` reveals the raw blob.
- **Report** — `cli/report.py` `generate_html_report` embeds the same fields in
  a self-contained offline HTML file (screenshots inlined as base64).

---

## Part 3 — Worked example (the run from Part 1)

| Stage | What happens |
|---|---|
| Harness | `locator.click` times out after 30s. `@playwright/test` per-test catch stashes the error; `afterAll` writes `error: {raw_type:"TimeoutError", raw_message:"locator.click: Timeout 30000ms exceeded.\nCall log:\n  - ...element is not visible"}`. |
| Runner | `proc.returncode != 0` → `kind="subprocess"`. `_read_artifacts` → `artifacts_error` present. |
| **Bug now** | `_build_error_detail` passes `raw_message` **and** `stderr`. `raw_message` present, so `classify()` uses it — **but** if `error` had been missing it would use stderr (with the `expect(` snippet) → `ASSERTION_FAILED`. |
| Classifier (with `raw_message`) | `_is_element_not_found` matches `element is not visible` → `ELEMENT_NOT_FOUND`. Correct. |
| Classifier (stderr fallback) | `_is_assertion` matches `expect(` from the line-42 code snippet → `ASSERTION_FAILED`. **Wrong.** |

### After the §6 fix

```json
{
  "category": "ELEMENT_NOT_FOUND",
  "title": "Couldn't click the element",
  "message": "The script tried to click `#notificationRailBackdrop` but gave up after 30s. The element exists on the page, but it stayed hidden the whole time — so the click never happened.",
  "next_step": "A step that opens or reveals it may be missing — check the recording. If it should already be visible, the page changed — re-record.",
  "severity": "error",
  "raw_type": "TimeoutError",
  "action": "locator.click",
  "selector": "#notificationRailBackdrop",
  "timeout_ms": 30000,
  "actionability": "not visible",
  "element_state": "found-but-hidden"
}
```

- Runner no longer passes `stderr` when `raw_message` is present → code
  snippets can never reach the classifier.
- `_is_assertion` requires the `expect` action prefix → a code snippet cannot
  impersonate an assertion even on the fallback path.
- `message` / `next_step` are built dynamically from `action` + `selector` +
  `timeout_ms` + `element_state` → readable for both tech and non-tech users.

---

## Related docs

- `error-reporting-plan.md` — the full 8-step plan and §6 revision.
- `expect-timeout-strategy-plan.md` — Layer 4 (reactive fix-after-failure)
  depends on the `error` object and `error_detail` column built here.
