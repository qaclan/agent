## 1. Fix schema-drift parity (bug 2a)

- [x] 1.1 In `web/routes/runs.py`, replace the API-item branch's raw `SELECT * FROM api_requests` + manual per-field `json.loads` with `RequestRepo().get(api_request_id, project_id)` so the request is fully deserialized (`response_schema` becomes a type-tree, not a raw string).
- [x] 1.2 Load the parent collection via `CollectionRepo().get(collection_id, project_id)` (same as collection runs) instead of the raw `SELECT * FROM api_collections`.
- [x] 1.3 Confirm the branch still passes `include_negatives=False` and still round-trips `state_updates` into `state.json` after the loader change; remove the now-dead manual deserialization block.
- [x] 1.4 Verify: a request whose live response matches its frozen baseline produces the same schema-drift verdict as a collection run — no false breaking drift, item PASSES (reproduce with the login request that fails today as a suite item but passes in `apicol_9fcc2cfb`).

## 2. Render suite API items in the API-run result format (UI #1)

- [x] 2.1 Extract the API-run item's row + expandable-detail builder from `_renderRows` (`web/static/app.js` ~line 4864) into a shared helper (e.g. `window.qcApiResultRow(item, {showNegative})`) that returns the method-pill/name/status/code/duration/assertions row and the detail panel (error/reason, assertions, `qcSchemaDiffHtml` drift tree, response body). Have the API-run modal call the helper so its output is unchanged.
- [x] 2.2 In the suite run-results / Execution History renderer (`web/static/app.js` ~line 4408), replace the `.script-result-row`/`.script-result-header` API branch with the shared helper, passing `showNegative:false` (suites never produce a negative verdict).
- [x] 2.3 Ensure the suite API item exposes the fields the helper needs (`method`, `request_name`/`name`, `status`, `status_code`, `duration_ms`, `assertion_results`, `schema_drift`, `response_body`) — `get_run` already merges these from `api_runs`; map any key-name differences.
- [x] 2.4 Keep script items rendering as `.script-result-card`; confirm the mixed list interleaves script cards and API rows in suite order without layout breakage.
- [x] 2.5 In `web/static/style.css`, remove suite-only API styles made dead by the switch (`.script-result-row` API usage, `.api-result-header`) and keep the shared schema-drift / `.api-result-*` styles the helper relies on.
- [x] 2.6 Verify in the browser against the reference screenshot: a suite API item shows method pill, name + schema-drift pill, status, code, duration, assertions count, and expands to assertions + schema-drift (breaking/added with types) + response body — matching the `API Run` modal; no negative section.

## 3. Ratify cross-item variable persistence (bug 2b)

- [x] 3.1 Confirm each web-script strategy (`python_strategy.py`, `javascript_strategy.py`, `javascript_test_strategy.py`, `typescript_test_strategy.py`) merges (not overwrites) `qaclan_vars` when snapshotting `state.json`.
- [x] 3.2 Confirm `runs.py` writes an API item's `state_updates` back into `state.json` `qaclan_vars` and injects `QACLAN_STATE_<KEY>` for subsequent script items.
- [x] 3.3 Verify: a suite of [login API → summary API] where login extracts `access_token` — the summary item authenticates with the token (no "no access token" failure).
- [x] 3.4 Verify: an API item's extracted variable survives an intervening web-script snapshot and is still readable by a later item.
- [x] 3.5 Seed each suite API item's state from its collection's persisted vars (`CollectionVarsRepo.as_seed_dict`) in `runs.py`, overlaying `state.json` `qaclan_vars` on top (this-run extractions win). Without it, an intervening web-script snapshot that drops `qaclan_vars` lets `resolve_vars` fall through to a stale/empty environment variable of the same name (observed: suite `suite_39202264` `/summary` → 401 "Token has expired"). Verified: with seeding a wiped `state.json` still yields the fresh token → summary PASSES; without it the control FAILS 401.
- [x] 3.6 Seed isolation: apply the seed to a SEPARATE in-memory `run_state` copy, never to the shared `state_dict`. Persist only genuinely-extracted `state_updates` (plus `_last_response`) back to `state.json`, so the collection seed never leaks into later script items as `QACLAN_STATE_*` env vars and cookies/origins stay untouched. Verified: after a seeded summary run, `state.json` qaclan_vars is unchanged (seed absent), cookies intact, and the token still resolved (200).

## 4. Regression checks

- [x] 4.1 Standalone single-send and collection runs still produce identical schema-drift and variable results (shared `resolve_and_run_api_item` untouched).
- [x] 4.2 Downloaded HTML report and reopened run history still list every API item alongside script items in suite order (report path unchanged).
- [x] 4.3 Suites still never run negative cases; the expanded API card shows no negative-testing section.
- [x] 4.4 Run `npx openspec validate fix-suite-api-report-and-parity --strict` and resolve any reported issues.
