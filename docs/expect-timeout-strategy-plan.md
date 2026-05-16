# Expect Timeout Strategy Plan

## Problem

`execute_run()` ([web/routes/runs.py:148-150](../web/routes/runs.py#L148-L150)) reads a single
`expect_timeout` from the request body and applies it — via `QACLAN_EXPECT_TIMEOUT`
([runs.py:353](../web/routes/runs.py#L353)) — uniformly to **every assertion in every script of
the suite**. Client reports that some components legitimately take longer to settle than that flat
ceiling, so their assertions time out and the script fails even though the app is healthy.

Rejected approach: per-component timeout pickers in the UI. A script can have tens of assertions;
a grid of dropdowns is unusable and unmaintainable.

This plan defines a universal, strategy-agnostic model that needs **no per-component UI**.

---

## Core insight: a high expect timeout is (almost) free

Playwright's `expect` does **not** sleep for the timeout. It polls the condition (~100 ms cadence)
and returns the instant the assertion passes. The timeout is only an *upper bound on patience*.

Consequence:

- For a **passing** assertion, raising the timeout from 7 s to 30 s costs nothing — a component
  that settles in 400 ms still reports in ~400 ms.
- The **only** cost of a high timeout is on a **genuinely failing** assertion: it now takes
  `timeout` ms to report the failure instead of failing fast.

So the flat 7 s value is not protecting passing runs — it is only buying faster *failure*
reporting, at the price of false negatives on slow-but-healthy components. That tradeoff is wrong
for QAClan's audience (functional correctness matters more than how quickly a failure is printed).

This reframes the fix: **separate the "patience ceiling" from the "fail-fast budget"** and make the
ceiling generous by default.

---

## Current state across the strategies

| Strategy | Engine | Honors `QACLAN_EXPECT_TIMEOUT`? | Where |
|---|---|---|---|
| `python` | `playwright` sync API | ✅ | `expect.set_options(timeout=_EXPECT_TIMEOUT)` — [python_strategy.py:105](../cli/script_strategies/python_strategy.py#L105) |
| `javascript_test` | `@playwright/test` | ✅ | config `expect: { timeout: _EXPECT_TIMEOUT }` — [javascript_test_strategy.py:303-305](../cli/script_strategies/javascript_test_strategy.py#L303-L305) |
| `typescript_test` | `@playwright/test` | ✅ | inherits `_render_config` from `JavaScriptTestStrategy` — same `expect: { timeout: _EXPECT_TIMEOUT }` config |
| `javascript` | raw `playwright` lib | n/a — no `expect` | `setDefaultTimeout(30000)` — [javascript_strategy.py:77](../cli/script_strategies/javascript_strategy.py#L77) |
| `typescript` | raw `playwright` lib | n/a — no `expect` | inherits JS harness |

Two distinct timeout concepts are in play and must not be conflated:

- **Action timeout** — `page.set_default_timeout(30000)` / `setDefaultTimeout(30000)`. Governs
  `click`, `fill`, `waitForSelector`, `waitFor`, etc. Hardcoded to 30000 in all five harnesses.
  This is what governs assertions in the raw-`playwright` strategies (`javascript`, `typescript`),
  which have no `expect`.
- **Expect/assertion timeout** — the run-level `QACLAN_EXPECT_TIMEOUT`. Governs `expect(...)`
  matchers. Only the three `expect`-based strategies have it.

A slow component can therefore stall either an `expect` matcher *or* a raw `waitFor`/`click`. The
plan must cover both.

---

## The plan: three layers

### Layer 1 — Generous, consistent, decoupled defaults

1. **Raise the default expect timeout** from 7000 to **15000**. Per the core insight this does not
   slow passing runs; it just stops flagging slow-but-healthy components.

2. **Widen the allowed set.** `_ALLOWED_EXPECT_TIMEOUTS` ([runs.py:148](../web/routes/runs.py#L148))
   becomes `{5000, 10000, 15000, 30000, 45000, 60000}`. The hard ceiling stays bounded by
   `PER_SCRIPT_TIMEOUT_SEC = 300s` — a single subprocess is killed at 300 s regardless.

3. **Bump the `expect`-config default.** `javascript_test` / `typescript_test` share one
   `_render_config` — change its `_EXPECT_TIMEOUT` default `7000` → `15000`. (An earlier draft
   listed a `typescript_test` *gap* here; there is none — `TypeScriptTestStrategy` inherits
   `setup_run_dir` / `_render_config` from `JavaScriptTestStrategy`, so it already honors
   `QACLAN_EXPECT_TIMEOUT` through the shared `playwright.config.js`.)

4. **Make the action timeout configurable too**, not just expect. Introduce
   `QACLAN_ACTION_TIMEOUT` (default 30000). All five harnesses replace the hardcoded `30000` in
   `set_default_timeout` with this env var. This is what fixes slow components in the
   raw-`playwright` `javascript`/`typescript` strategies, which have no `expect` to tune.

5. **One knob in the UI, two env vars under the hood.** The action timeout and expect timeout are
   distinct *harness* concepts (see table above) but QAClan's non-technical audience should not be
   asked to reason about the difference. A single picker — **"Wait limit"** — sets *both* env vars
   to the same value:
   ```
   QACLAN_ACTION_TIMEOUT = QACLAN_EXPECT_TIMEOUT = <picked value>
   ```
   Each harness still reads whichever var(s) it can use; the user sees one number. Helper text:
   *"How long QAClan waits for a component before failing. Higher = more patient with slow pages;
   only slows down reporting of genuine failures."* A per-assertion split remains available via the
   inline `timeout=` override (Layer 3).

> After Layer 1, the env contract per subprocess is `QACLAN_EXPECT_TIMEOUT` (assertions) and
> `QACLAN_ACTION_TIMEOUT` (clicks/fills/waits). Both are driven by the single "Wait limit" value.

### Layer 2 — Per-script override (the granularity knob)

The unit of override is the **script**, not the component. Rationale: a script is already the unit
a user opens and edits; "this login flow hits a slow dashboard" is a per-script statement. Tens of
components inside that script all simply inherit the script's higher ceiling — no grid of pickers.

1. **Schema.** Add **one** nullable column to the `scripts` table via `_run_migrations()` in
   [cli/db.py](../cli/db.py):
   - `wait_timeout INTEGER` (nullable)
   `NULL` means "inherit the run-level value." One column, matching the single UI knob — no split
   between action/expect at the script level; the inline override (Layer 3) covers the rare case
   that needs finer control.

2. **Resolution order**, computed per script inside the suite loop in `execute_run()`
   (~[runs.py:133](../web/routes/runs.py#L133) onward, where each `item` is processed):
   ```
   effective = script.wait_timeout  or  run.wait_timeout  or  DEFAULT (15000)
   ```
   The loop already builds `child_env` per subprocess ([runs.py:353](../web/routes/runs.py#L353)),
   so it sets both `QACLAN_EXPECT_TIMEOUT` and `QACLAN_ACTION_TIMEOUT` to `effective` per script
   with no structural change — just move the value computation inside the loop.

3. **API.** Add `wait_timeout` to the script create/update endpoints in
   [web/routes/](../web/routes/) and to the script-detail JSON.

4. **UI.** One control in the script editor header (not per component): a single dropdown
   "Wait limit: [Inherit suite default ▾]". `Inherit` writes `NULL`. This is the entire UI surface
   — O(1) per script.

This handles "this whole flow runs against a slow environment / a heavy dashboard."

### Layer 3 — Per-assertion inline override (already supported; document it)

For the rare *single* slow component inside an otherwise fast script, the override already exists
and needs **no new feature** — every generated assertion is one editable line in the harness action
block, and every Playwright matcher accepts a per-call `timeout`:

```python
# python — bump just this one assertion
expect(page.get_by_test_id("report-grid")).to_be_visible(timeout=45000)
```
```javascript
// javascript_test / typescript_test
await expect(page.getByTestId('report-grid')).toBeVisible({ timeout: 45000 });
```
```javascript
// javascript / typescript (raw playwright) — action timeout per call
await page.locator('#report-grid').waitFor({ state: 'visible', timeout: 45000 });
```

Action items (documentation, not code):
- Add a short "Slow components" section to the script-editor help / harness comment block
  explaining the inline `timeout` argument.
- This is the precise, scalable answer to the rejected option 1: per-component control lives in
  the script source — the user touches *only* the one slow line, and the other tens of components
  keep inheriting the script/suite default.

### Layer 3+ (optional, later) — Auto-escalation

Zero-config automation, deferred until Layers 1–2 are proven insufficient: post-process codegen so
each emitted `expect(...)` is routed through a `qa_expect` wrapper. On a `TimeoutError` the wrapper
retries that one assertion once with an extended timeout (e.g. `3×`, capped) and records the slow
assertion into the artifacts JSON as a `slow_assertions` warning so the user learns which component
to optimize. Cost: a genuinely-broken assertion pays `base + extended` once. Implementation touches
`post_process_recording` / `_extract_actions` in all `expect`-based strategies — non-trivial, hence
deferred.

### Layer 4 — Reactive fix-after-failure (depends on structured error reporting)

Layers 1–3 are **proactive** — the user guesses a timeout *before* the run. Layer 4 is
**reactive**: the user never guesses; when a step does time out, the failure report itself offers
a one-click fix. This is the precise, non-technical answer to rejected option 1 — per-component
control with **zero upfront UI**, surfaced only for the one component that actually needed it.

**Hard dependency:** this layer is built *on top of* [`docs/error-reporting-plan.md`](./error-reporting-plan.md).
It needs that plan's structured `error` object and `error_detail` column — it adds no new error
plumbing of its own. Do not start Layer 4 until structured error reporting (that plan's steps 1–5)
has shipped.

1. **Signal — already produced by the error-reporting plan.** A timed-out assertion is classified
   `ASSERTION_FAILED`, an element wait `ELEMENT_NOT_FOUND`, a bare wait `TIMEOUT`. The structured
   `error` object already carries `category`, `raw_type`, `selector`, and `timeout_ms`. Layer 4
   consumes those fields — it does **not** add to the classifier.

2. **Phase-2 dependency for line-precise fixes.** Patching *one* assertion line (Layer 3 inline
   `timeout=`) requires knowing *which* line failed — that is the error-reporting plan's optional
   phase-2 `action_index` / `action_text` manifest. Until that ships, Layer 4 degrades gracefully:
   it offers the **script-level** bump (Layer 2 `wait_timeout`) instead of the line-level patch.
   So Layer 4 has two tiers, unlocked independently:
   - **Tier A (needs only error-reporting steps 1–5):** report shows a *"Give this script more
     time & re-run"* action → sets the script's `wait_timeout` (Layer 2 column) one notch higher
     and re-runs. Coarse but immediate.
   - **Tier B (needs phase-2 manifest):** report pinpoints the failing line → *"Give this step
     30 s & re-run"* action → patches the inline `timeout=` argument on exactly that one line
     (Layer 3 mechanism), leaving the other assertions untouched, then re-runs.

3. **UI surface.** No new pickers anywhere. The control lives **inside the failure card** the
   error-reporting plan already specifies (its §3 run-detail card). For a timeout-category
   failure, the card renders one extra button. The user sees a timeout option *only* on a run
   that actually timed out, *only* for the component that failed — the grid of dropdowns from
   rejected option 1 never exists.

4. **Bound.** The bump is one notch on the same `_ALLOWED_*` ladder (Layer 1) and still capped by
   `PER_SCRIPT_TIMEOUT_SEC = 300s`. A repeated timeout after the highest notch is reported as a
   genuine failure, not bumped forever.

> Sequencing: Layers 1–3 ship first (this plan). Layer 4 Tier A ships after error-reporting
> steps 1–5. Layer 4 Tier B and Layer 3+ auto-escalation both wait on the phase-2 action manifest
> and can share it.

---

## Why this is the universal answer

- **No per-component UI.** Granularity is achieved by script-level override (Layer 2) for whole
  flows and by inline `timeout=` (Layer 3) for the rare individual component.
- **Strategy-agnostic.** Both timeout concepts (`QACLAN_EXPECT_TIMEOUT`, `QACLAN_ACTION_TIMEOUT`)
  are env vars resolved identically by all five harnesses; raw-`playwright` strategies are covered
  via the action timeout, `expect`-based strategies via both.
- **Free by default.** The generous default (Layer 1) eliminates most false timeouts outright,
  because a higher ceiling does not slow passing assertions.
- **Bounded.** `PER_SCRIPT_TIMEOUT_SEC = 300s` remains the hard backstop — no configuration can
  hang a run indefinitely.

---

## File checklist

**`web/routes/runs.py`**
- Default `7000` → `15000`; widen `_ALLOWED_EXPECT_TIMEOUTS`.
- Move per-script timeout resolution into the suite loop; set `QACLAN_EXPECT_TIMEOUT` and new
  `QACLAN_ACTION_TIMEOUT` in `child_env` per script.

**`cli/db.py`**
- Migration: `scripts.wait_timeout INTEGER` (nullable, single column).

**`cli/script_strategies/`**
- `python_strategy.py` — read `QACLAN_ACTION_TIMEOUT`; feed `page.set_default_timeout(...)`.
- `javascript_strategy.py`, `typescript_strategy.py` — `setDefaultTimeout` from `QACLAN_ACTION_TIMEOUT`.
- `javascript_test_strategy.py` — add `QACLAN_ACTION_TIMEOUT` for `setDefaultTimeout`; bump the
  shared `_render_config` `_EXPECT_TIMEOUT` default `7000` → `15000`; raise the config per-test
  `timeout` so a high expect budget is not clipped by the test-level timeout.
- `typescript_test_strategy.py` — add `QACLAN_ACTION_TIMEOUT` for `setDefaultTimeout` in its
  harness. Expect config is inherited (no separate gap to close).

**`web/routes/` (script endpoints)**
- Accept/return `wait_timeout` on script create/update/detail.

**`web/static/app.js`**
- Relabel run-modal picker → "Wait limit" + helper text.
- Add single per-script "Wait limit" dropdown to the script editor (Inherit / values).

**Docs**
- Script-editor help: "Slow components" section covering the inline `timeout=` override.

---

## Acceptance criteria

- A suite run with default settings tolerates a component that settles in ~12 s (previously failed
  at 7 s).
- A script with `wait_timeout = 45000` set in the editor uses 45 s for its actions and assertions
  while other scripts in the same suite keep the run default.
- `typescript_test` scripts honor the wait limit (both expect, via inherited config, and actions).
- The UI exposes a single "Wait limit" picker; no separate action/expect controls.
- `javascript`/`typescript` (raw) scripts honor `QACLAN_ACTION_TIMEOUT` for `waitFor`/`click`.
- No per-component UI is introduced.
- A 300 s subprocess kill still bounds every script regardless of timeout settings.

---

## Session notes

_Claude: append short dated notes here when finishing tasks._

- 2026-05-16: Plan written. Awaiting user approval before implementation.
- 2026-05-16: Corrected the `typescript_test` "gap" — there is none; it inherits the shared
  `_render_config`. Added Layer 4 (reactive fix-after-failure), dependent on
  `docs/error-reporting-plan.md`.
- 2026-05-16: Implementing Layers 1–3.
- 2026-05-16: Error-reporting plan steps 1–5 shipped — Layer 4 Tier A is now
  unblocked (structured `error` object + `error_detail` column exist). Tier B
  and Layer 3+ still wait on the phase-2 action manifest.
