## Why

Three problems in the negative-testing collection experience: the "Only negative tests" collection-run mode runs negatives for requests that have negative testing turned **off**, which is wrong and can fire cases the user disabled; the collection request-list rows are misaligned, the selected row loses its negative-testing marker, and long URIs are not laid out sensibly; and the run-collection confirmation dialog frames the state-changing warning as a red error that grows unbounded with the number of affected APIs.

## What Changes

- **BREAKING (behavior):** "Only negatives" collection-run mode SHALL run negative cases only for requests whose **effective negative-testing state is on** and that have generated cases — no longer for every request that merely has cases regardless of enablement. Requests with negatives off (by their own override or an off collection default) are skipped in this mode.
- The state-changing confirmation in the run-collection dialog SHALL only enumerate requests whose negatives will actually run under the chosen mode (effective-on, mutating verb, has cases), keeping it consistent with the corrected run behavior.
- The run-collection confirmation SHALL present the mutating-verb warning as a **warning** (not a red error), with a short explanatory message and a collapsed, expandable list of affected APIs instead of an always-expanded inline block that grows with request count.
- The collection request-list rows SHALL align consistently; the negative-testing marker SHALL remain visible on the **selected** row; the URI SHALL take the maximum available width and wrap when it overflows; the two feature-marker symbols SHALL occupy only their minimum width; and the request-list panel SHALL be widened.
- The negative-testing marker (list row and editor tab) SHALL require **effective-on AND at least one enabled case** — a request that is on but has no generated cases behaves as off (nothing runs) and is not marked, matching the run and mode-chooser behavior.

## Capabilities

### New Capabilities

<!-- None -->

### Modified Capabilities

- `api-negative-testing`: The only-negatives collection-run mode now filters by effective enablement (not just case existence); the destructive-run confirmation presentation moves from an always-expanded red block to a warning with an expandable affected-API list; and the request-list negative-testing marker is required to persist while a row is selected.

## Impact

- Backend run logic: `web/api/services/runner_service.py` (negatives-mode resolution / which requests run negatives), `cli/api_runner.py::run_api_request` (per-request negative execution gating), `web/api/routes/collections.py` (run route), `cli/negative_check.py` (verdict, unaffected but adjacent).
- Frontend: `web/static/api/api-section.js::qcCollectionRunConfirm` (run-collection dialog / mutating-verb enumeration + warning presentation), `web/static/api/views/collection-detail-view.js` and `web/static/api/views/collections-view.js` (request-list row layout, selected-row marker), the shared `web/static/api/components/negative-view.js`, and the request-list CSS.
- Docs: `docs/api-negative-testing-reference.md` must be updated in the same change per the repo maintenance rule.
