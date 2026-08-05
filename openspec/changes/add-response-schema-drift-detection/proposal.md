## Why

When an API's response shape silently changes — a field is removed, a type flips, a value becomes nullable — existing assertions rarely catch it, because assertions test values a user thought to check, not the overall contract. Teams find out in production. The runner already infers a response type-tree on every send (`cli/schema_infer.py`, stored in `api_requests.response_schema`), so the raw material for contract-drift detection already exists and is currently thrown away by an unconditional overwrite. This change turns that latent data into an explicit, opt-in contract check with a clear comparison view.

## What Changes

- Add an opt-in **response schema check** per request. When enabled, each run compares the fresh inferred response shape against the request's stored **`response_schema` baseline** and reports drift.
- **Severity-based verdict** (industry-standard contract-testing model): breaking changes (field removed, type changed, nullable-introduced, array element type changed) **fail** the request; additive changes (new field) **notify only** and keep the run green.
- **Frozen baseline in `response_schema`** (no new column): the baseline is the existing `response_schema` — seeded by HAR/discovery import, or captured from the first successful JSON response, then kept frozen (the old every-send auto-overwrite is removed). A manual **"Update response schema"** action re-accepts the current shape.
- **Inheritance model** for enablement: a collection carries a `schema_check_default` (on/off); each request carries a tri-state override (`inherit` / `on` / `off`). Effective state is resolved at run time — no cascade writes, per-request choices survive a global flip.
- **Comparison view**: a new "Schema Diff" tab in the response panel renders expected-vs-current with added / removed / type-changed markers. A drift banner appears in the request editor after a send; per-request drift markers appear in the collection-run view.
- **Persistence & history**: drift verdicts are stored on per-run result rows (`api_request_results`, `api_runs`) so run history and reports can show schema drift.
- New `diff_schemas()` function (mirrors the existing `merge_schemas()` recursion) — no new third-party dependency; built on the existing `infer_schema` type-tree.
- New reference doc `docs/api-schema-check-reference.md` under the same maintenance-rule convention as the assertions/script reference docs.

## Capabilities

### New Capabilities

- `api-response-schema-check`: Opt-in per-request (with collection-default inheritance) detection of response-schema drift against the request's frozen `response_schema` baseline, with severity-based pass/fail, first-send capture and manual re-accept, a schema-diff comparison view, and persisted drift verdicts in run history.

### Modified Capabilities

<!-- None. openspec/specs/ is empty (no committed main specs yet); this introduces the first spec for this behavior. -->

## Impact

- **Data model** (`cli/db.py`): reuse the existing `api_requests.response_schema` column as the frozen baseline (no new column); new `api_requests.schema_check` (TEXT tri-state override) column; new `api_collections.schema_check_default` column; new `schema_drift` (TEXT) column on `api_request_results` and `api_runs`. Added via `_migrate_*`-style idempotent migrations.
- **Runner** (`cli/api_runner.py`, `web/api/services/runner_service.py`): remove the unconditional every-send `response_schema` overwrite (capture once, then freeze); compute drift against the frozen baseline; attach a `schema_drift` object to the result and factor it into the pass/fail decision.
- **New logic**: `cli/schema_diff.py` (`diff_schemas`) + a severity classifier.
- **Repositories** (`web/api/repositories/request_repo.py`, `collection_run_repo.py`, `api_run_repo.py`): serialize/deserialize the new columns; accept them in create/update whitelists.
- **Sync** (`cli/sync.py`, `cli/commands/pull.py`): carry the new request/collection columns through cloud sync.
- **UI** (`web/static/api/components/response-panel.js`, `assertion-builder.js` area, `web/static/api/views/request-editor-view.js`, `collection-detail-view.js`, `collection-run-view.js`): schema-check tri-state toggle + baseline (Update response schema) controls, Schema Diff tab, drift banner, per-row drift markers.
- **HTML report** (`cli/api_report.py`): per-request drift pill, Schema Drift detail block, and a Schema Drift summary stat card.
- **Docs**: new `docs/api-schema-check-reference.md`; new dated spec + plan under `docs/superpowers/`.
- No new Python/JS dependencies. Fully local-first; drift data syncs best-effort like existing schema columns.
