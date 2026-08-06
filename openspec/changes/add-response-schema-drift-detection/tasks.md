## 1. Pure schema-diff logic (no DB, testable first)

- [x] 1.1 Create `cli/schema_diff.py` with `diff_schemas(expected, current)` mirroring `cli/api_discovery/schema_merger.py` recursion; return a flat list of `{path, kind, severity, expected_type, actual_type}` where `kind ∈ {removed, added, type-changed, became-nullable, element-type-changed}`.
- [x] 1.2 Implement the fixed severity mapping from design Decision 4: removed / type-changed / became-nullable / element-type-changed → `breaking`; added → `additive`; treat `"?"`, `"..."`, and `["?"]` as wildcards that never emit a difference.
- [x] 1.3 Add `classify_drift(differences)` (or inline in `diff_schemas`) building the `schema_drift` verdict object: `checked`, `verdict`, `skipped_reason`, `breaking_count`, `additive_count`, `worst_severity`, `differences` (shape per design Decision 6).
- [x] 1.4 Handle dotted/bracketed path building for nested objects and array elements (e.g. `data.items[].id`); respect the depth-4 cap already inherent in the type-tree without erroring.
- [x] 1.5 Sanity-check with representative fixtures (removed field, type change, new field, null flip, array element change, empty-array wildcard, identical shapes) — inline or a scratch script; there is no test harness in this repo.

## 2. Data model (migrations + repositories)

- [x] 2.1 Add `_migrate_api_schema_check(conn)` to `cli/db.py` adding `api_requests.expected_schema TEXT DEFAULT NULL` and `api_requests.schema_check TEXT DEFAULT 'inherit'` (idempotent try/except ALTER, matching `_migrate_api_schemas`).
- [x] 2.2 In the same or a sibling migration, add `api_collections.schema_check_default TEXT DEFAULT 'off'`.
- [x] 2.3 Add `schema_drift TEXT DEFAULT NULL` to `api_request_results` and `api_runs` via idempotent ALTERs.
- [x] 2.4 Register the new `_migrate_*` call(s) in the migration list at the end of `init_db()` (`cli/db.py:157`).
- [x] 2.5 Update `web/api/repositories/request_repo.py`: add `expected_schema` and `schema_check` to `_DEFAULTS`, `_serialize`/`_deserialize` (JSON-encode `expected_schema`; `schema_check` is a plain string), the `create` INSERT column list, and the `update` whitelist `fields`.
- [x] 2.6 Update the collection repository to read/write `schema_check_default` (defaults, serialize, create, update).
- [x] 2.7 Update `web/api/repositories/collection_run_repo.py` and `web/api/repositories/api_run_repo.py` to persist and deserialize `schema_drift` (JSON) on per-request result rows.

## 3. Runner: compute drift in the shared execution path

- [x] 3.1 Extend `cli/api_runner.py::run_api_request(...)` with `expected_schema=None` and `schema_check_enabled=False` params.
- [x] 3.2 When `schema_check_enabled` and the response body is JSON, infer the current schema via `cli/schema_infer.py::infer_schema`, call `diff_schemas(expected_schema, current)`, and attach the `schema_drift` verdict to the result dict.
- [x] 3.3 When enabled but the body is non-JSON, set `schema_drift = {checked: False, verdict: 'skipped', skipped_reason: 'non-json'}` and do not alter the verdict.
- [x] 3.4 Factor a breaking verdict into status: if `schema_drift.breaking_count > 0`, force `status = "FAILED"`, keeping the schema failure **separate** from `assertion_results` (per spec: distinguishable). Additive-only or skipped SHALL NOT change status.
- [x] 3.5 Ensure the error-path result variants (`cli/api_runner.py:732`, `:750`) carry a consistent `schema_drift` absence (omit or `checked: False`) so consumers never KeyError.

## 4. Service orchestration (inheritance, capture, persist)

- [x] 4.1 In `web/api/services/runner_service.py`, add effective-enablement resolution: `override in ('on','off') ? override=='on' : collection_default=='on'` (load the request's `schema_check` and its collection's `schema_check_default`).
- [x] 4.2 In `run_request` (single send), load `expected_schema`, pass it plus resolved `schema_check_enabled` into `run_api_request`.
- [x] 4.3 Auto-capture: when the check is enabled, no `expected_schema` exists, and the response is JSON with `status_code < 400`, store the freshly inferred schema into `api_requests.expected_schema` and mark the run `schema_drift = {checked: True, verdict: 'skipped', skipped_reason: 'first-capture'}` (no drift on first capture).
- [x] 4.4 Preserve the existing live `response_schema` overwrite at `runner_service.py:78-84` unchanged (extractor UI depends on it); only `expected_schema` is gated.
- [x] 4.5 Wire the same resolution + `schema_drift` persistence into collection runs (`_execute_collection` → `CollectionRunRepo.create_request_result`) so per-request results carry drift.
- [x] 4.6 Add an endpoint/handler for "Update expected" that re-infers from a supplied/last response and overwrites `api_requests.expected_schema` (route under `web/api/routes/requests.py`).

## 5. Sync

- [x] 5.1 Add `expected_schema` and `schema_check` to the request sync payload (`cli/sync.py:323-358`) and to the pull upsert (`cli/commands/pull.py:248-273`).
- [x] 5.2 Add `schema_check_default` to the collection sync payload and pull upsert.

## 6. UI — controls

- [x] 6.1 Request editor (`web/static/api/views/request-editor-view.js`): add a tri-state schema-check control near the Assertions section (`sectionMap` `:1674-1682`) showing effective state + source (`On (inherited)` / `On (overridden)` / `Off (overridden)`) with a reset-to-inherit affordance; include it in `_buildPayload()` as `schema_check`.
- [x] 6.2 Request editor: add an "Update expected" button that calls the task-4.6 endpoint and refreshes the stored expected.
- [x] 6.3 Collection detail (`web/static/api/views/collection-detail-view.js`): add a single "Schema check default" on/off toggle writing `schema_check_default`.

## 7. UI — comparison view & notifications

- [x] 7.1 Response panel (`web/static/api/components/response-panel.js`): add a `'schema-diff'` tab in the tab list (`:290-295`) and a branch in `_renderContent` (`:174`), shown only when `schema_drift.differences` is non-empty.
- [x] 7.2 Render expected-vs-current reusing `_renderSchemaTree` / `_mkPillGroup`, marking each field unchanged / added / removed / type-changed and color-splitting breaking vs additive; show an empty-state when there is nothing to compare (first capture / no expected).
- [x] 7.3 Request editor send handler (`:1709-1723`): surface a drift banner summarizing count + worst severity after a send.
- [x] 7.4 Collection run view (`web/static/api/views/collection-run-view.js:191-207`, `:282-287`): add a per-row drift marker driven by the persisted `schema_drift.worst_severity`.

## 8. Docs (maintenance rule)

- [x] 8.1 Create `docs/api-schema-check-reference.md` in the style of `docs/api-assertions-reference.md`: source-of-truth line, the severity table, the `schema_drift` shape, and `file:line` anchors; document the depth-4 and single-sample-nullability limitations.
- [x] 8.2 Add a CLAUDE.md maintenance rule tying schema-check behavior (`cli/schema_diff.py`, the new columns, the runner/service wiring, the UI controls) to `docs/api-schema-check-reference.md` so they cannot drift.
- [x] 8.3 Add a dated design spec under `docs/superpowers/specs/` and a dated plan under `docs/superpowers/plans/` following the existing skeletons.

## 9. Verification

- [x] 9.1 Manual end-to-end: enable per-request, send once (auto-capture, no drift), mutate the endpoint/mock to remove a field (breaking → FAILED + banner + Schema Diff tab), add a field (additive → still PASSED + notice).
- [x] 9.2 Verify inheritance + master switch: collection default on → an `inherit` request runs the check; a request `off` override stays off between toggles; changing the collection default resets all request overrides to `inherit`.
- [x] 9.3 Verify "Update expected" re-accepts the current shape and clears drift on the next send.
- [x] 9.4 Verify collection-run rows show drift markers and a past run retains its stored `schema_drift`.
- [x] 9.5 Run `npx openspec validate add-response-schema-drift-detection --strict` and fix any reported issues.

## 10. Follow-ups (global master switch + reports)

- [x] 10.1 Collection default is a master switch: `CollectionRepo.reset_schema_check_overrides` resets all request overrides to `inherit`; called from the collection PATCH route (with sync re-enqueue for changed requests) and confirmed in the collection Schema Check UI.
- [x] 10.2 HTML report (`cli/api_report.py`): select + deserialize `schema_drift`, render a per-request drift pill, a "Schema Drift" detail block, and a "Schema Drift" summary stat card. Reflected in `docs/api-schema-check-reference.md` and CLAUDE.md maintenance rule.

## 11. Baseline redesign (reuse frozen response_schema, drop expected_schema)

- [x] 11.1 Remove the `expected_schema` column and all wiring; the drift baseline reuses the existing `response_schema` column, kept frozen.
- [x] 11.2 Stop the unconditional every-send `response_schema` overwrite in `runner_service`; capture once when empty (`_maybe_capture_baseline`, import-as-baseline honored), frozen thereafter. Runner echoes each run's inferred shape into the result for display only.
- [x] 11.3 Rename `run_api_request` param `expected_schema` → `baseline_schema`; always infer current shape from a JSON body.
- [x] 11.4 Endpoint `/expected-schema` → `/response-schema`; service `set_expected_schema` → `set_response_schema` (writes `response_schema`).
- [x] 11.5 Remove `expected_schema` from sync/pull; `schema_check` still carried, `response_schema` already synced.
- [x] 11.6 UI: "Update expected" → "Update response schema"; badge reads `response_schema`; first-send capture mirrors locally.
- [x] 11.7 Update all artifacts + docs (proposal/spec/design/tasks, superpowers, reference doc, CLAUDE.md) to the frozen-`response_schema` model.
- [x] 11.8 Sync `schema_drift` on run results agent→server: add it to `sync_api_collection_run_to_cloud` (collection-run request_results) and `_gather_api_run_results` (suite api_results) payloads in `cli/sync.py`.

## 12. Diff UI redesign (Option A — plain-words, grouped, dense; one shared renderer)

- [x] 12.1 Add shared renderer `web/static/api/components/schema-diff-view.js` (classic script, `window.qcSchemaDiffHtml` + `window.qcSchemaDriftPill`); include it in `index.html` before `app.js`. Layout: `Schema changed — N breaking, M added` summary, **Breaking**(red)/**Added**(amber) groups, one-line rows `sign path type` (`−`/`~`/`+`), no `∅`/legend.
- [x] 12.2 `response-panel.js`: Changes sub-view uses the shared renderer; drop the old legend + per-row list + dead `_SEV_COLOR`/`_KIND_LABEL`; de-shout the tab label (no `⚠`).
- [x] 12.3 `collection-run-view.js`: row pill + detail block via the shared renderer.
- [x] 12.4 `app.js` Runs history modal: add the pill per request row and the shared diff block in the expanded detail (previously absent).
- [x] 12.5 `cli/api_report.py`: rewrite `_render_schema_drift` to the same grouped layout; drop dead `_KIND_LABELS`; de-triangle the row pill. No update-schema affordance (report is read-only).
- [x] 12.6 `request-editor-view.js`: shrink the drift banner to one quiet line; drop the `⚠` and the stale "Update expected" call-to-action.
- [x] 12.7 Reflect in `docs/api-schema-check-reference.md` (UI surfaces + file list), CLAUDE.md maintenance rule, design.md Decision 7, and the superpowers spec.
