## 1. Phase 0: Solo run fix

- [x] 1.1 Fix `run_script_solo` in `web/routes/scripts.py` to unpack all 4 values from `_read_artifacts` at both call sites; run a script solo and confirm no unpack error

## 2. Phase 1: Budget module and runner wiring (no schema change)

- [x] 2.1 Re-run the read-only calibration query over `script_runs` and confirm `BASE` 30s / `PER_ACTION` 5s still hold; note results in the plan doc
- [x] 2.2 Create `cli/timeout_budget.py` with named constants `BASE`, `PER_ACTION`, built-in defaults (wait 15000, max script time 280000, kill margin 20s)
- [x] 2.3 Implement `resolve_wait_timeout` and `resolve_max_script_time` returning value plus winning level, accepting absent suite/project/run pick
- [x] 2.4 Implement `count_steps(source, strategy)` for each strategy's syntax (goto, click, fill, selectOption, check/uncheck, press, hover, dblclick; settles via the strategy settle marker)
- [x] 2.5 Implement `compute_test_timeout` (auto formula, floor, cap clamp, fixed override) and `subprocess_timeout(cap)`
- [x] 2.6 Implement `estimate` returning typical and worst case (settles at 15s soft cap) and `over_cap`
- [x] 2.7 Make `_render_config` in `javascript_test_strategy.py` read `QACLAN_TEST_TIMEOUT` with fallback to the old flat formula; confirm TypeScript inherits it
- [x] 2.8 Wire `web/routes/runs.py` loop to resolve per script via the module and export `QACLAN_EXPECT_TIMEOUT`, `QACLAN_ACTION_TIMEOUT`, `QACLAN_TEST_TIMEOUT`
- [x] 2.9 Replace the four `PER_SCRIPT_TIMEOUT_SEC` uses (`runs.py` subprocess timeout and message, `scripts.py` subprocess timeout, `cli/error_classifier.py` text) with the resolved value
- [x] 2.10 Make `run_script_solo` use the same resolver (script, project, built-in) instead of hardcoded 15000
- [x] 2.11 Grep for readers of `ScriptStrategy.expect_timeout`; remove or align it
- [ ] 2.12 Manual check: long `javascript_test` script shows scaled timeout in the generated config, short script keeps the 75s floor, a slow script past budget reports a test timeout (not the kill), a `python` script is unchanged except the derived kill time

## 3. Phase 2: Schema, settings, API, UI

- [x] 3.1 Add migrations in `cli/db.py`: nullable `wait_timeout`, `test_timeout`, `max_script_time` on `projects` and `suites`, following the `_migrate_script_wait_timeout` pattern
- [x] 3.2 Add validation helpers (wait set, test timeout range up to resolved cap, max script time 60000 to 1800000) and share them across routes
- [x] 3.3 Extend the budget resolvers to read suite and project values and apply the run-time clamp
- [x] 3.4 Add `GET` / `PUT /api/projects/<id>/settings` in `web/routes/projects.py` with validation and null-clears
- [x] 3.5 Extend `PUT /api/suites/<id>` in `web/routes/suites.py` to accept the three fields alongside rename without changing them when absent
- [x] 3.6 Enqueue a cloud sync (`enqueue("project" | "suite", id, "upsert")`) after both settings saves
- [x] 3.7 Build the "Project settings" page with a Timeouts section, reached from the project dropdown in `web/static/app.js`
- [x] 3.8 Add the three inputs to the suite settings UI with descriptions, examples, "Inherit project default (value)" and the four-budget explanation
- [x] 3.9 Add "Use suite default (Ns)" as the first run dialog wait-limit option, sending no value; confirm numeric picks remain one-off overrides
- [x] 3.10 Manual checks: suite wait 30s with dialog on default gives 30s; dialog 10s gives 10s; script override wins; lowering suite cap below a project fixed test timeout clamps at run time

## 4. Phase 3: Cloud sync

- [ ] 4.1 Agree the cloud contract (field names, null handling, unknown-field behavior) with the qaclan.com owner and confirm the cloud change ships first
- [x] 4.2 Extend `sync_project_to_cloud` in `cli/sync.py` to take and send the three fields only when non-NULL; update the queue handler in `cli/sync_queue.py`, `_ensure_project_synced` and `sync_all`
- [x] 4.3 Extend `sync_suite_to_cloud` likewise; update its queue handler and `sync_all`
- [x] 4.4 In `cli/commands/pull.py`, set the three fields on project and suite pulls when the key is present (null clears) and leave local values when absent
- [x] 4.5 Fix script pull: include `wait_timeout` in the script INSERT and UPDATE in `pull.py`
- [ ] 4.6 Manual checks: set values, push, wipe local DB, pull, confirm project, suite and script `wait_timeout` return; pull a response with the keys absent and confirm local values survive; confirm a failed sync does not block the local save

## 5. Phase 4: Snapshots and failure reporting

- [x] 5.1 Add migrations: `suite_runs.timeout_config` (TEXT JSON), `script_runs.effective_wait_timeout`, `script_runs.effective_test_timeout` (nullable)
- [x] 5.2 Write the snapshot (run pick, resolved wait, test timeout mode, max script time, winning levels) when inserting `suite_runs`, and effective values when inserting `script_runs` (NULL test timeout for strategies without one)
- [x] 5.3 Show the recorded configuration in run detail as plain words; handle NULL for old runs
- [x] 5.4 Update `cli/error_classifier.py` to separate per-test timeout, expect/action timeout and max-script-time kill, each with a matching `next_step`, and report the actual kill limit
- [x] 5.5 Manual check: open an old run with no snapshot and confirm the UI renders; trigger each of the three failures and confirm classification

## 6. Phase 5: Preview

- [x] 6.1 Add `GET /api/suites/<id>/timeout-preview` accepting `wait_timeout`, `test_timeout`, `max_script_time` query params, returning per-script rows and a summary via the budget module
- [x] 6.2 Build the suite settings panel: per-script table with budget bar, last-run marker where history exists, summary (suite total, longest script) and warnings (worst case over cap, last run over 80%, clamp warning)
- [x] 6.3 Show "limited only by max script time" for strategies with no per-test timeout
- [x] 6.4 Add the compact summary line to the run dialog, linking to the panel
- [x] 6.5 Manual check: change inputs, confirm the preview matches what the runner then logs

## 7. Phase 6: Docs

- [x] 7.1 Update `docs/test-timeout-budget-plan.md` status and correct the 90s floor note (runner floor is 75s; 90s only when env vars are unset)
- [x] 7.2 Update `docs/expect-timeout-strategy-plan.md` for the new resolution chain, `QACLAN_TEST_TIMEOUT`, formula and synced fields
