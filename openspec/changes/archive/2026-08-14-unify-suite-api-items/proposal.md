## Why

Suites already store scripts and API requests in one `suite_items` table and already run them in one ordered pass (`web/routes/runs.py`), but the edit UI shows two redundant, inconsistently-capable sections for the same data, and API items run through a stripped-down execution path that skips collection-level auth resolution, schema-check, and negative-check — so a request configured with `auth_type='inherit'` (the standard "auth lives on the collection" setup) silently gets no auth when run inside a suite, even though the identical request runs fine from the API section. A second bug independently breaks token hand-off whenever a script runs between two API items: Playwright's `storage_state()` teardown overwrites the whole shared `state.json` instead of merging, wiping out any `qaclan_vars` an API item wrote earlier in the suite.

## What Changes

- Remove the legacy "Scripts" section from the suite edit modal; the "Items" section becomes the single, drag-reorderable list for both script and API-request items.
- Add a generic mixed-item reorder endpoint/contract so drag-reorder persists `order_index` across both item types instead of only renumbering scripts (**BREAKING**: replaces the script-only `PUT /suites/<id>/order` contract with one that accepts ordered item ids of either type).
- Replace the single-select "Add API Request" dropdown with a full-height picker: requests grouped by collection, checkboxes, search, multi-select across collections in one add.
- Extract the per-request execution logic already living in the collection-run path (`web/api/services/runner_service.py`: auth/schema-check resolution, send, extractor/script output persisted into `collection_vars`) into one shared function, and have suite runs call that same function for API items instead of calling `run_api_request` raw. This keeps suite API items in lockstep with collection-run behavior by construction, not by hand-mirrored logic that can drift.
- **Negative testing is explicitly excluded from suite runs.** A suite API item never resolves or fires `negative_check`, regardless of what's configured on the request/collection — negative testing stays a collection-section-only concern (ad hoc "Run negatives" or a full collection run). Fits its purpose (fuzz/security probing) poorly against a suite's purpose (fast flow validation), and multiplies request count per item.
- Suite API items persist extracted variables (`qc.set`, extractors) into `collection_vars`, matching how collection runs already behave, and additionally mirror the same values into the run's own `state.json` so a script item later in the same suite run can read them via the existing `QACLAN_STATE_<KEY>` env var bridge.
- Fix the shared `state.json` write path so a script's `storage_state()` teardown merges into the existing `qaclan_vars`/API state instead of overwriting the file, so variable hand-off survives regardless of item order.
- Define API-item failure for suite stop-on-fail purposes as: assertion failure, request execution error, or a breaking schema-drift verdict. (Negative testing never runs in a suite, so it never factors in.)
- Enrich the suite run-results panel for API items with an expand-in-place response detail view (status, headers, body, assertions, schema-drift verdict) reusing the same rendering the collection-run view already uses, backed by the suite run's own persisted per-item result — not the request editor, and no negative-testing pill (since negatives never run there).
- Suite item rows: right-align each row's View/Remove controls (script and API rows alike), require an explicit confirm dialog before Remove deletes anything, and give API rows a View button that opens the real API section request editor for that request (same editor a collection uses), not a read-only preview.
- API request picker: fix the modal-height-jumps-while-searching bug by giving the list its own fixed-height scroll region independent of result count; make each collection group collapsible and show a live "N selected" count per group, computed on the fly from the picker's own in-memory selection — nothing persisted.

## Capabilities

### New Capabilities
- `suite-mixed-items`: unified suite item list (scripts + API requests) covering ordering, bulk API-request selection, and API-item execution parity with the standalone API runner (auth/schema-check/negative-check resolution, cross-item variable state).

### Modified Capabilities
(none — no existing spec capability covers suites today; this is net-new spec coverage)

## Impact

- `web/static/app.js`: suite edit modal (`editSuiteModal`, `~3954-4089`), `addApiRequestToSuite` (`~4114-4138`), drag-reorder handlers, `showRunResults` API-item rendering (`~4318-4343`).
- `web/routes/suites.py`: `PUT /suites/<id>/order` (replace script-only contract), item add/remove endpoints (unchanged shape, reused).
- `web/routes/runs.py`: `execute_run` API-item branch (`~422-511`) calls the new shared execution function instead of `run_api_request` directly; `state.json` write/merge fix touches the script-teardown call sites in each strategy; new failure-condition check feeds existing stop-on-fail skip logic.
- `cli/script_strategies/python_strategy.py`, `javascript_strategy.py`, `javascript_test_strategy.py`, `typescript_test_strategy.py`: `storage_state()` write becomes a merge instead of overwrite.
- `web/api/services/runner_service.py`: per-request resolve+execute+persist logic extracted out of `_execute_collection`/`run_collection` into one shared function both they and the suite path call; `CollectionVarsRepo` persistence now also invoked from the suite path via that shared function.
- No DB schema changes — `suite_items.item_type`/`api_request_id` columns already exist, and `collection_vars`/`api_runs` already have everything this design needs.
