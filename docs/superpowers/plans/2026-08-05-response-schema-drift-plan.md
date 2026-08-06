# Response Schema Drift Detection — Implementation Plan

Date: 2026-08-05

Companion design: `docs/superpowers/specs/2026-08-05-response-schema-drift-design.md`.
Canonical task list: `openspec/changes/add-response-schema-drift-detection/tasks.md`.

**Goal:** Opt-in per-request response-schema drift detection with severity-based
pass/fail, a frozen `response_schema` baseline (import-as-baseline / first-send capture), inheritance-based enablement, and
an inline comparison view.

**Architecture:** Pure diff in `cli/schema_diff.py` → verdict computed inside
`cli/api_runner.py::run_api_request` → orchestration/capture in
`web/api/services/runner_service.py` → persisted on run-result rows → surfaced in
the response panel, request editor, collection detail, and collection-run views.

**Tech stack:** stdlib `json` + existing `cli/schema_infer.py` type-tree; no new
Python or JS dependencies.

## Global Constraints

- Feature dormant by default (`schema_check='inherit'`, `schema_check_default='off'`).
- Live `response_schema` overwrite in `runner_service` stays unchanged.
- A schema-check failure must be distinguishable from an assertion failure.
- Any behavior change must update `docs/api-schema-check-reference.md` (maintenance rule).

## Task 1: Diff logic

- Files (Create): `cli/schema_diff.py`.
- [x] `diff_schemas`, `classify_drift`, `evaluate_drift`, `skipped` with the fixed severity mapping and wildcard handling.

## Task 2: Data model

- Files (Modify): `cli/db.py`, `web/api/repositories/{request_repo,collection_repo,collection_run_repo,api_run_repo}.py`.
- [x] `_migrate_api_schema_check` (new columns) + repository serialize/deserialize/create/update wiring.

## Task 3: Runner

- Files (Modify): `cli/api_runner.py`.
- [x] `baseline_schema`/`schema_check_enabled` params; always infer current shape (display); diff→attach `schema_drift`; breaking → `FAILED`; error paths carry `schema_drift: None`.

## Task 4: Service orchestration

- Files (Modify): `web/api/services/runner_service.py`, `web/api/routes/requests.py`, `web/api/routes/collections.py`.
- [x] Inheritance resolution, frozen-baseline capture (no every-send overwrite), "Update response schema" endpoint, collection default toggle + reset-overrides endpoint.

## Task 5: Sync

- Files (Modify): `cli/sync.py`, `cli/commands/pull.py`.
- [x] Carry `schema_check`/`schema_check_default` through sync + pull (`response_schema` already synced).

## Task 6/7: UI

- Files (Modify): `web/static/api/components/response-panel.js`, `web/static/api/views/{request-editor-view,collection-detail-view,collection-run-view}.js`.
- [x] Schema Diff tab, Schema Check tab (tri-state + Update response schema), drift banner, collection default toggle, per-row drift markers.

## Task 8: Docs

- Files (Create): `docs/api-schema-check-reference.md`; this plan + design.
- Files (Modify): `CLAUDE.md` (maintenance rule).
- [x] Reference doc + maintenance rule.

## Task 9: Verification

- [ ] Manual end-to-end (first-send capture, frozen baseline, breaking fail, additive notify, inheritance/master-switch, Update response schema, collection-run markers, history persistence).
- [x] Pure-logic and runner functional checks against a local JSON server.
