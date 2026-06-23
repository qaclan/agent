# 10 - Retry Policy

Deep-dive on feature #10 from [feature-ideas.md](../feature-ideas.md). Covers the "passed on retry" distinction, the single-script run question, and where retry config should live.

---

## The problem

A test fails. Is it a real bug or a timing fluke? Right now QAClan records one outcome per script run. There is no retry. If it fails on step 3 due to a slow network response, the user has to re-run the whole suite manually to confirm.

Retries reduce noise. But naïve retries hide real flakiness — a "passed on retry" result should be tracked separately from a clean pass.

## Example

```
Script: "checkout-flow"
Retry config: max_retries=2, retry_delay=3s

Run attempt 1:
  step 1  PASS  goto /cart
  step 2  PASS  fill quantity
  step 3  FAIL  locator "#pay-btn" timeout (backend slow)

Retry 1 (after 3s):
  step 1  PASS
  step 2  PASS
  step 3  PASS  ← backend responded this time

Result stored as: PASSED_ON_RETRY (not PASSED, not FAILED)
UI: green icon with a retry badge, not a clean green.
```

## Impact

| Dimension | Effect |
|---|---|
| Noise reduction | One-off flakes (slow backends, cold starts) stop causing false failures. Team trust in the suite increases. |
| Flake signal | "Passed on retry" rate per script surfaces unstable tests. Feeds naturally into feature #6 Flaky Test Detection. |
| Manual re-run elimination | Current behavior: failure → user clicks re-run manually → waits → confirms. Retries automate this loop. |
| Suite completion rate | Fewer abandoned suite runs due to one flaky script blocking the rest. |

Overall: **medium-high impact**. Low implementation cost relative to benefit.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Playwright Test** | `--retries 2` flag or `test.describe.configure({retries: 2})` in code. | Per-file config embedded in code. No UI. No "passed on retry" badge. All retries are transparent — final outcome only. |
| **Cypress** | `retries: { runMode: 2, openMode: 0 }` in `cypress.config.js`. | Global or per-test config in code. No UI toggle per test. |
| **Mocha** | `this.retries(2)` inside test. | Code-level only. |
| **Jest** | No native retry. Requires `jest-circus` config. | Community plugin, not first-class. |

**Our diff:** Per-script retry config via UI. No code changes needed. "Passed on retry" is a first-class outcome — not silently promoted to PASSED. This makes retry policy transparent rather than a hidden fallback.

## Single-script run question

**Current state:** In QAClan, a script can only be run as part of a suite. There is no "run this one script now" option from the script detail page. To test a single script you must create a suite with just that script in it.

**Should we add single-script runs?**

Yes. Adding retry policy makes this more urgent. Retry is most useful when iterating on a single script. Creating a suite just to test one script is unnecessary friction.

Proposed change:
- "Run" button on the script detail page.
- Creates an ephemeral `suite_run` with a single `script_run` entry under it.
- Uses the same `execute_run` path — no new execution logic.
- Appears in run history as "Single run" (no suite name), distinguishable from suite runs.

This is a small change that unblocks retry iteration and other features (step-by-step replay, trace viewer) that are most naturally triggered from a single-script context.

## Where retry config lives

### Option A — on the `scripts` table

- `retry_count INTEGER DEFAULT 0` — max retries (0 = no retry)
- `retry_delay_ms INTEGER DEFAULT 0` — wait between attempts

Each script has its own retry setting. Override suite-level default.

### Option B — on the `suites` or `suite_items` table

- Suite-level default. Per-item override optional.

### Decision

**Option A (per-script) for v1.** Retry behavior is a property of the test, not the suite. A login test that touches a flaky backend should always retry regardless of which suite it is in. Suite-level default is a comfort feature, not a necessity.

## Outcome states

Current: `PASSED`, `FAILED`, `SKIPPED`, `RUNNING`.

Add: `PASSED_ON_RETRY` — test ultimately passed but not on the first attempt.

This feeds:
- Feature #6 Flaky Test Detection: flake score = pass rate where first-attempt PASSED / (PASSED + PASSED_ON_RETRY + FAILED).
- Run history badge: retry icon next to any PASSED_ON_RETRY entry.

## Schema changes

```sql
-- Migration: add retry columns to scripts
ALTER TABLE scripts ADD COLUMN retry_count INTEGER DEFAULT 0;
ALTER TABLE scripts ADD COLUMN retry_delay_ms INTEGER DEFAULT 0;

-- Migration: add attempt tracking to script_runs
ALTER TABLE script_runs ADD COLUMN attempt_number INTEGER DEFAULT 1;
ALTER TABLE script_runs ADD COLUMN final_status TEXT;
-- final_status: PASSED | PASSED_ON_RETRY | FAILED
-- status column keeps per-attempt status for each row
-- Each retry = a new script_runs row with attempt_number incremented
```

Storing each attempt as a separate `script_runs` row is preferred over a single row + JSON blob. It reuses existing schema, preserves per-attempt timings, errors, and screenshots.

## Implementation path

### Phase 1 — single-script run

- "Run" button on script detail page in [web/static/app.js](../../web/static/app.js).
- Backend: `POST /api/scripts/:id/run` — creates ephemeral suite_run, delegates to `execute_run`.
- UI: result appears in run history tab on the script page.

### Phase 2 — retry config UI

- Add `retry_count` and `retry_delay_ms` to scripts table migration.
- UI: retry settings on script detail page (number input 0–10 for count, delay selector).
- Runner in [web/routes/runs.py](../../web/routes/runs.py): on script failure, check retry_count, loop with delay, record each attempt as separate script_run row.

### Phase 3 — PASSED_ON_RETRY status + badge

- Add `final_status` column, compute after all attempts.
- Run detail UI: show retry badge (e.g. circular arrow icon) for PASSED_ON_RETRY rows.
- Suite run summary: count PASSED_ON_RETRY separately in the passed/failed/retry breakdown.

## Open questions

- **Which steps retry?** On retry, does the whole script restart from step 1 (clean state) or from the failed step? Must restart from step 1 — scripts are stateful E2E flows, not isolated unit tests. Partial retry would leave the page in unknown state.
- **State carryover.** If a script in a suite shares state (via `state.json`) and retries, the retry starts with potentially dirty shared state. Options: wipe state.json before retry (breaks intended sharing), copy state.json to a retry-specific backup, or retry never carries over state (safest). Start with "retry always starts fresh state for this script only".
- **Retry limit safety.** Max retries cap at 10 in UI to prevent accidental infinite loops. Document clearly.

## Next concrete step

Add "Run" button on script detail page (single-script run, Phase 1). Then add `retry_count` / `retry_delay_ms` migration. Update runner loop in [web/routes/runs.py](../../web/routes/runs.py) to respect retry config. Ship retry before PASSED_ON_RETRY status — the status distinction is a reporting enhancement, not required for basic retry to work.
