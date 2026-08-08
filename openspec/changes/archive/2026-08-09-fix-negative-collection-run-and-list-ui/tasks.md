## 1. Backend — only-negatives enablement fix

- [x] 1.1 In `web/api/services/runner_service.py::_negatives_for_run` (~line 109), drop the `mode != "only"` exemption so only-mode also requires `_resolve_negative_check(req, col)` to be true; a resolved-off request returns `(False, [])`.
- [x] 1.2 Rewrite the `_negatives_for_run` docstring (~lines 93-98): only-mode runs negatives for requests that are **resolved-on AND have cases**, not "regardless of enablement".
- [x] 1.3 In `_execute_collection` (~lines 421-444), in only-mode `continue` (skip the send and `create_request_result`) when `not neg_enabled`, so only qualifying requests execute and are recorded.
- [x] 1.4 Apply the identical only-mode skip in the synchronous `run_collection` loop (~lines 508-529).
- [x] 1.5 In `plan_collection_negatives` (~lines 322-323), set `has_negatives` from the intersection `_resolve_negative_check(req, col) and _enabled_negative_cases(req)` so the mode chooser appears only when negatives will actually run.

## 2. Backend — verification

- [x] 2.1 Manually verify: collection default off, 3 requests overridden on with cases → only-negatives run executes and records exactly those 3; requests with negatives off do not appear. (Verified by direct `_negatives_for_run` trace: override-on+cases → enabled; inherit-off+cases → skipped; on+no-cases → skipped.)
- [x] 2.2 Verify default and off modes are unchanged (happy-path still runs for all requests); confirm `run_api_request`'s negative gate (`cli/api_runner.py:943-952`) needs no change. (api_runner.py untouched; default-mode trace unchanged.)
- [x] 2.3 Verify `mutating_requests` in the plan still lists only resolved-on state-changing requests (unchanged), and drives the dialog's affected list. (The `_resolve_negative_check` continue-gate before appending is preserved.)

## 3. Frontend — request-list row layout

- [x] 3.1 In `web/static/style.css`, widen `.api-sidebar` from `280px` to `320px` (raise `min-width` to match).
- [x] 3.2 Add a class (e.g. `api-req-name`) to the request-name span in `web/static/api/views/collections-view.js::_renderRequestNode` (~line 346).
- [x] 3.3 In `style.css`, style `.api-req-name` with `flex:1; min-width:0` and wrapping (`overflow-wrap:anywhere; word-break:break-word`) — wrap on overflow, not ellipsis.
- [x] 3.4 Set `.api-request-item` `align-items:flex-start` so the method badge and marker column align to the top when the name wraps.
- [x] 3.5 Keep the `_featureBadges` group at minimum width (`flex:none`) and right-aligned; resolve the double `margin-left:auto` (badge group vs `.remove-from-col-btn`) so revealing the hover remove-button does not shift the marker column (reposition the remove button, e.g. absolute or without its own auto-margin). (Remove button now uses a reserved `visibility` slot instead of `margin-left:auto` + `display`.)
- [x] 3.6 Confirm the `⊘` negative marker stays visible on the selected (`.api-request-item.active`) row and is no longer pushed out of the panel by a long name. (Name wraps in-flow; markers keep a fixed reserved column; inline marker colors already beat `.active`'s color.)
- [x] 3.7 In `collections-view.js`, make the negative marker require **effective-on AND ≥1 enabled case** (not enablement alone) in `_featureBadges` (~line 324): a request on-but-no-cases shows no `⊘`. Verify the list `req` carries `negative_cases` (or add an active-negatives boolean to the list payload); apply the same on-AND-has-cases rule to the editor negative-tab marker. (Confirmed `tree → RequestRepo.list` deserializes `negative_cases`; editor tab updated + refreshed on grid changes.)
- [x] 3.8 Verify: enable negatives on a request but generate no cases → no `⊘` in the list and no tab marker; generate a case → marker appears. (`_hasEnabledNegatives`/tab condition require an enabled case; tab refresh wired into `renderGrid`.)

## 4. Frontend — run-confirmation dialog

- [x] 4.1 In `web/static/api/api-section.js::qcCollectionRunConfirm` (~lines 135-140), replace the `var(--danger)` block with a warning-themed block (`var(--warning)` border/text, subtle warning background).
- [x] 4.2 Write concise warning copy: state-changing negative payloads (POST/PUT/PATCH/DELETE) will be sent against `<env>` and may alter data — no inline dump of every request.
- [x] 4.3 Add a "Show N affected requests" toggle that expands a collapsed compact list built from `plan.mutating_requests` (name + methods); wire it with a click handler on the injected node, consistent with the existing `button[data-mode]` wiring.
- [x] 4.4 Keep the three run-mode buttons and the `{ run, mode, confirm_destructive }` return contract unchanged.

## 5. Docs & validation

- [x] 5.1 Update `docs/api-negative-testing-reference.md` for the corrected only-mode semantics (resolved-on AND has-cases; non-qualifying requests skipped) and the new warning-style confirmation with expandable affected list.
- [x] 5.2 Run `npx openspec validate fix-negative-collection-run-and-list-ui --strict` and fix any errors. (Valid.)
- [ ] 5.3 Smoke-test the full flow in the web UI: request-list alignment/wrapping/markers, and the run-collection dialog warning + expandable list, against the negative-only run behavior. (Requires a live browser — left for user visual confirmation. Python compile, JS `node --check`, spec validate, and a `_negatives_for_run` logic trace all pass.)

## 6. Only-negatives run set (report/live-view fix)

- [x] 6.1 Add `runner_service._requests_for_run` that, in only-mode, filters the collection to just the qualifying requests (resolved-on ∧ enabled cases); other modes return all requests.
- [x] 6.2 Pre-filter in `start_collection_run` so `create_run` `total` = qualifying count (fixes the running view showing all 35).
- [x] 6.3 Pre-filter in `_execute_collection` and the sync `run_collection` so results get **contiguous** order indices (fixes the finished view mapping results to wrong placeholder rows / missing summaries); drop the now-redundant in-loop `continue`.
- [x] 6.4 In `collection-run-view.js::_renderRows`, detect a subset run (`total < _allRequests.length`) and rebuild the spine from the qualifying set (`_crvNegActive`, using the collection's `negative_check_default`) so not-yet-run rows show the **real** request URI, not a wrong positional name or a bare `Pending…`; completed rows already use `result.request_name`.
- [x] 6.5 Verified with a `_requests_for_run` trace (only → exactly qualifying, contiguous; default → all) and updated `docs/api-negative-testing-reference.md` + the spec scenario "Only-negatives run reports exactly the qualifying requests".
