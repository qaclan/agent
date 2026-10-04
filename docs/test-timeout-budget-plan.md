# Test Timeout Budget Plan

Extends [expect-timeout-strategy-plan.md](./expect-timeout-strategy-plan.md). That plan made the
**wait limit** (expect + action timeout) configurable per run and per script. This plan covers
what it left out: the **test timeout**, a configurable **max script time**, configuration at
**project / suite** level (synced to the cloud), a **record of what each run used**, and a
**preview UI** that shows the budget before running.

Status: implemented locally (OpenSpec change `test-timeout-budget`), phases 0 to 5. Cloud sync (phase 3)
is coded but unverified against qaclan.com: the cloud contract below is still open.

---

## Problem

1. The test timeout is a flat `max(expect, action) + 60s`
   ([javascript_test_strategy.py:425](../cli/script_strategies/javascript_test_strategy.py#L425)).
   The runner sets expect and action to the same wait limit, so a real run gets 75s with the 15s
   default (90s only appears when the env vars are unset and the config's 30000 action fallback
   applies). It does not grow with script length. A long recorded flow can pass every
   individual wait and still fail on the total.
2. Only `javascript_test` / `typescript_test` have a per-test timeout at all. `python`,
   `javascript` and `typescript` (raw playwright) have none; the only limit is the 300s subprocess
   kill (`PER_SCRIPT_TIMEOUT_SEC`, [runs.py:28](../web/routes/runs.py#L28)). That 300s is a
   hard-coded constant used in four places (see "Max script time").
3. Wait limit can be set per run and per script, but the script editor offers "Inherit suite
   default" ([app.js:2405](../web/static/app.js#L2405)) and **no suite default exists**. There
   is also no project settings screen and no project update route
   ([projects.py](../web/routes/projects.py) has list/create/active/delete only).
4. Runs record nothing about the timeouts they used, so a timeout failure cannot be explained
   after settings change.
5. There is no way to see, before running, how much time a suite is allowed to take.

### Related defects found while reading the code

- `run_script_solo` ([scripts.py:1153](../web/routes/scripts.py#L1153), `:1187`) unpacks 3 values
  from `_read_artifacts`, which returns 4 ([runs.py:35](../web/routes/runs.py#L35)). Fix first.
- `run_script_solo` hardcodes `QACLAN_EXPECT_TIMEOUT` / `QACLAN_ACTION_TIMEOUT` to 15000
  ([scripts.py:1135](../web/routes/scripts.py#L1135)) and ignores the script's `wait_timeout`.
- Script `wait_timeout` is pushed to the cloud (`sync_script_to_cloud`,
  [sync.py:189](../cli/sync.py#L189)) but never pulled: the script INSERT/UPDATE in
  [pull.py:132](../cli/commands/pull.py#L132) and `:155` omit it. A pull on a fresh machine loses
  every script override.
- `ScriptStrategy.expect_timeout = 7000` ([base.py:25](../cli/script_strategies/base.py#L25))
  looks stale next to the 15000 defaults. Check whether anything reads it.

---

## Decisions

| Question | Decision |
|---|---|
| Config scope | Project default + suite override. No global layer. |
| Knobs | Wait limit (existing; one value for expect + action), Test timeout (`auto` or fixed), Max script time. |
| Test timeout default | `auto`: scaled from the script's action count. |
| Max script time | Configurable at project and suite level. Default 280s. The subprocess kill is derived from it (`max script time + 20s`), so the in-process test timeout always fires first. |
| Project settings | New minimal "Project settings" page. Timeouts are its only section for now. |
| Cloud sync | Project and suite settings sync to the cloud. |
| Record per run | Yes: JSON snapshot on `suite_runs`, effective values on `script_runs`. |
| Preview | Full panel in suite settings, compact summary in the run dialog. |

### Wait limit resolution (highest wins)

1. Script `wait_timeout` (existing)
2. Run dialog pick (existing; see "Run dialog" below)
3. Suite `wait_timeout` (new)
4. Project `wait_timeout` (new)
5. Built-in default, 15000

### Max script time resolution

Suite `max_script_time`, then project `max_script_time`, then built-in 280000. Allowed range
60s to 1800s. A solo script run has no suite, so it resolves script, project, built-in.

### Test timeout

```
formula = BASE + PER_ACTION * n_actions
test_timeout = min(CAP, max(FLOOR, formula))
BASE       = 30s
PER_ACTION = 5s
FLOOR      = max(expect, action) + 60s     # today's value, so budgets never get shorter
CAP        = resolved max script time
```

- No separate settle term. Each settle follows an action that already gets `PER_ACTION`.
- Override order: fixed value (suite, then project) > `QACLAN_TEST_TIMEOUT` > auto.
- A fixed test timeout must be <= the resolved max script time. Validate on save, and clamp at
  run time if a lower level later reduces the cap (the preview shows a warning).
- `n_actions` counts `goto`, `click`, `fill`, `selectOption`, `check`/`uncheck`, `press`,
  `hover`, `dblclick` statements in the action block, in the strategy's own syntax.
- `BASE` and `PER_ACTION` are named constants in one place, so recalibration is a one-line change.

### Calibration (from the local run history)

Read-only query over `script_runs` joined to script source, 62 runs, one dev machine. Treat as a
sanity check, not proof: few distinct scripts, small sample.

| Strategy | Passing runs | Seconds per action (median / p90 / max) | Longest passing run |
|---|---|---|---|
| `javascript_test` | 8 | 2.1 / 2.7 / 3.4 | 42s, 20 actions, 14 settles |
| `typescript_test` | 8 | 0.9 / 2.0 / 2.1 | 21s, 10 actions, 8 settles |
| `python` | 6 | 0.3 / 0.4 / 0.8 | 9s, 22 actions, 6 settles |

Failed runs reach 77s on a 26-action script (each failing expect burns the 15s wait limit), so
the 75s floor is already exceeded for scripts only a little longer. A 40-action, settle-heavy passing script
would likely need 85-135s and hit the flat limit, which confirms the problem.

Conclusions for the constants:

- 5s per action is about 1.5x the worst passing rate seen (3.4s), which leaves headroom for slower
  apps without wasting time.
- Base 30s covers browser start (a 3-action script took 10s) and trailing state capture. The
  floor dominates up to 12 actions, so short scripts are unchanged.
- Results: 20 actions gives 130s, 40 actions gives 230s, 50 or more is held by the cap.
- Re-run before phase 1 (65 runs, same machine): `javascript_test` 8 passing, median 2.1 / max 3.4 s per
  action, longest 42s; `typescript_test` 10 passing, median 1.4 / max 2.5, longest 60s; `python` 6
  passing, median 0.3 / max 0.8. Constants hold (5s is still above 1.5x the worst rate).
- Re-run this query before phase 1 ships and again after the first week of real use. The run
  snapshots (phase 4) make this routine.

---

## Design

### 1. Shared budget module: `cli/timeout_budget.py` (new)

Single source of truth. Runner, solo run and preview endpoint all call it.

- `resolve_wait_timeout(script, run_pick, suite, project)` returns ms plus the winning level.
- `resolve_max_script_time(suite, project)` returns ms plus the winning level.
- `count_steps(source, strategy)` returns `{actions, settles}`. Settles use the strategy's settle
  marker ([base.py:109](../cli/script_strategies/base.py#L109)).
- `compute_test_timeout(n_actions, wait_timeout, cap, fixed=None)` returns ms.
- `estimate(...)` returns `{test_timeout, typical_ms, worst_ms, over_cap}`. Worst case assumes
  every settle runs to its own 15s soft cap (`_waitForNetworkSettle` never throws on the cap).
- `subprocess_timeout(cap)` returns `cap + 20s`.

Keeping this in one Python module is what stops the preview from drifting from the real run.

### 2. Schema (migrations in `cli/db.py`, same pattern as `_migrate_script_wait_timeout`)

- `projects`: `wait_timeout INTEGER`, `test_timeout INTEGER`, `max_script_time INTEGER`
  (all nullable, milliseconds; NULL `test_timeout` means auto)
- `suites`: the same three columns
- `suite_runs`: `timeout_config TEXT` (JSON snapshot: run pick, resolved wait limit, test timeout
  mode, max script time, and which level each came from)
- `script_runs`: `effective_wait_timeout INTEGER`, `effective_test_timeout INTEGER`
  (NULL for strategies with no per-test timeout)

Validation: wait limit uses the existing set `{5000, 10000, 15000, 30000, 45000, 60000}`; fixed
test timeout is an integer from 30000 up to the resolved max script time; max script time is an
integer from 60000 to 1800000.

### 3. Runner wiring

- Replace the four uses of the `PER_SCRIPT_TIMEOUT_SEC` constant with the resolved value:
  `subprocess.run(timeout=...)` in [runs.py:690](../web/routes/runs.py#L690) and
  [scripts.py:1150](../web/routes/scripts.py#L1150), the "timed out after Ns" message at
  [runs.py:80](../web/routes/runs.py#L80), and the classifier text at
  [error_classifier.py:536](../cli/error_classifier.py#L536).
- `runs.py` loop: resolve per script via the budget module, set `QACLAN_EXPECT_TIMEOUT`,
  `QACLAN_ACTION_TIMEOUT`, and new `QACLAN_TEST_TIMEOUT`.
- `_render_config` in `javascript_test_strategy.py`: read `QACLAN_TEST_TIMEOUT`, fall back to the
  current flat formula when unset. TypeScript inherits it.
- `run_script_solo`: use the same resolver instead of hardcoded values.
- Write the snapshot and effective values when inserting `suite_runs` / `script_runs` rows.

### 4. Run dialog

The wait-limit select ([app.js:4500](../web/static/app.js#L4500)) always sends a number, so it
would always beat a suite or project default. Add a first option "Use suite default (Ns)" that
sends nothing. Selecting a number is a one-off override.

### 5. API

- New `GET` / `PUT /api/projects/<id>/settings` for the three project fields. Project routes
  have no update today.
- `PUT /api/suites/<id>` accepts the three suite fields besides the rename
  ([suites.py:111](../web/routes/suites.py#L111)).
- Both settings routes enqueue a cloud sync (`enqueue("project" | "suite", id, "upsert")`), the
  way project creation already does.
- `GET /api/suites/<id>/timeout-preview?wait_timeout=&test_timeout=&max_script_time=` returns
  per-script rows (name, strategy, actions, settles, wait limit and source, test timeout,
  typical, worst) plus a summary. Query params let the UI preview unsaved edits.

### 6. Cloud sync

Push (follow the `sync_script_to_cloud` pattern: add a field to the payload only when it is not
NULL, so untouched projects and suites send exactly what they send today):

- `sync_project_to_cloud` ([sync.py:90](../cli/sync.py#L90)) takes and sends the three fields.
  It currently receives only `name`, so callers change too: the queue handler
  ([sync_queue.py:262](../cli/sync_queue.py#L262)), `_ensure_project_synced`, and `sync_all`.
- `sync_suite_to_cloud` ([sync.py:164](../cli/sync.py#L164)) likewise; update the queue handler
  at [sync_queue.py:273](../cli/sync_queue.py#L273) and `sync_all` ([sync.py:788](../cli/sync.py#L788)).

Pull ([pull.py](../cli/commands/pull.py)):

- Projects ([pull.py:68](../cli/commands/pull.py#L68)) and suites
  ([pull.py:388](../cli/commands/pull.py#L388)): set the three fields when the key is present in
  the payload (null clears it); leave the local value alone when the key is absent, so an older
  cloud response cannot wipe local settings.
- Fix the existing script gap: pull `wait_timeout` in the script INSERT and UPDATE.

Cloud-side dependency: the qaclan.com API must accept and return `wait_timeout`, `test_timeout`
and `max_script_time` on projects and suites. That is outside this repo. Ship the cloud change
first. Sync is best-effort and failures are swallowed, so an agent ahead of the cloud degrades to
local-only settings; but confirm the cloud ignores or accepts unknown fields rather than rejecting
the whole project or suite payload, since that would stop name sync as well.

Run snapshots (`suite_runs.timeout_config`) stay local in this plan. Adding them to the run
payload is a follow-up that also needs the cloud change.

### 7. UI

Project settings page (new): reached from the project dropdown ([app.js:638](../web/static/app.js#L638)).
One "Timeouts" section with Wait limit, Test timeout, Max script time, saved through the new
settings route. Built for more sections later, but nothing else goes in now.

Suite settings panel:

- Same three inputs, each with a one-line description and a short example, and a "Inherit
  project default (value)" choice. Explain the four budgets: test, action, expect, navigation.
- Table, one row per script, with a bar showing test timeout against the max script time. Show
  last real run duration as a marker where history exists.
- Summary: suite total (sum of test timeouts), longest script, and warnings for scripts whose
  worst case exceeds the cap or whose last run used over 80% of budget.
- Strategies without a per-test timeout show "limited only by max script time".

Run dialog: one summary line (suite total and longest script), linking to the panel.

### 8. Failure reporting

`@playwright/test` reports `Test timeout of Nms exceeded`. Make sure the classifier
(`cli/error_classifier.py`) separates this from an expect timeout and from the max-script-time
kill, and that `next_step` points at the matching setting. The run detail shows the snapshot
("wait limit 15s from suite, test timeout 130s auto, max script time 280s from project").

---

## Phases

Each phase can be tested alone.

| Phase | Scope |
|---|---|
| 0 | Fix the solo-run unpack bug. |
| 1 | `timeout_budget.py`, `QACLAN_TEST_TIMEOUT`, runner and solo wiring, derived subprocess timeout with built-in defaults. No schema change; auto mode is live. Re-run the calibration query first. |
| 2 | Schema, resolution chain, project and suite API, project settings page, run dialog "Use suite default". |
| 3 | Cloud sync: cloud API change, push, pull, queue handlers, plus the script `wait_timeout` pull gap. |
| 4 | Snapshots, run detail display, classifier messages. |
| 5 | Preview endpoint and UI. |
| 6 | Docs. |

Phase 3 can start in parallel with phase 2 once the cloud contract is agreed, but it cannot
finish before the cloud change ships.

---

## Verification

There are no automated tests in this repo, so check by hand:

1. Phase 1: run a long `javascript_test` script, confirm the generated config shows the scaled
   value, and that short scripts keep the old 75s floor (wait limit 15s + 60s).
2. Force a slow script past its budget. Confirm the test timeout message appears, not the
   subprocess kill.
3. Run a `python` script and confirm nothing changes except the derived kill time.
4. Phase 2: set suite wait 30s, leave the run dialog on default, confirm the child gets 30s. Then
   pick 10s in the dialog, confirm 10s. Then set a script override, confirm it wins.
5. Lower max script time on a suite below a project-level fixed test timeout, confirm the runtime
   clamp and the preview warning.
6. Phase 3: set values on a project and suite, push, wipe local DB, pull, confirm values and the
   script `wait_timeout` come back. Pull from a cloud response with the keys absent and confirm
   local values survive.
7. Phase 4: open an old run (no snapshot) and confirm the UI handles NULL.
8. Phase 5: change inputs and confirm the preview matches what the runner then logs.

---

## Open items

- Cloud contract for the new project and suite fields (names, null handling, unknown-field
  behaviour). Needs agreement with whoever owns qaclan.com.
- Run snapshots are local only for now. Decide later whether to sync them.
- Wait-scan gap: the Review & Improve wizard does not know `selectOption`
  (`_parseActionCalls`, [app.js:2743](../web/static/app.js#L2743)). Tracked separately; it
  changes settle counts but not this design.

---

## Implementation notes (deviations from the plan above)

- Cloud push reads the three project/suite fields from the row inside `sync_project_to_cloud` /
  `sync_suite_to_cloud` (`_timeout_settings_payload`), so the queue handler, `_ensure_project_synced`
  and `sync_all` send them without signature changes. Only non-NULL values are sent, so clearing a
  setting locally does not reach a cloud that already holds a value (see design.md risks).
- Failure reporting keeps the `TIMEOUT` category and adds a `timeout_kind` field (`test`,
  `script_kill`, `wait`) instead of new categories, so cloud and UI category handling is untouched.
  A `Test timeout of Nms exceeded` message is matched before the element and assertion rules,
  because Playwright often prints it as the tail of a locator call.
- A suite's `test_timeout` of NULL means "inherit the project value, else auto"; there is no way to
  force auto at suite level when the project sets a fixed value.
- `qaclan web run` (`cli/commands/web/run.py`) is a separate in-process runner and is not covered
  by this budget.

---

## Maintenance

Any change to the resolution chains, `QACLAN_TEST_TIMEOUT`, the budget formula, or the synced
project/suite fields must be reflected here and in `expect-timeout-strategy-plan.md` in the same
change.
