## Context

See proposal.md — Why. Relevant current state:

- One per-request execution path, `resolve_and_run_api_item` (`web/api/services/runner_service.py`), is shared by single send, collection run, and suite run. It reads `req.get("response_schema")` as the frozen drift baseline and passes it straight to `run_api_request`, which hands it to `evaluate_drift` (`cli/api_runner.py:931`).
- Collection runs load requests through `RequestRepo.list()/get()`, which `_deserialize()`s every JSON column (`response_schema`, `pre_extractor`, `post_extractor`, `assertions`, …) from TEXT into Python objects. So the baseline reaching the comparator is a type-tree.
- The suite runner (`web/routes/runs.py`, API-item branch ~line 446) instead loads the request with a raw `SELECT * FROM api_requests` and manually `json.loads`es only `headers`, `params`, `assertions`, `auth_config`. `response_schema` stays a raw JSON string. `run_api_request` internally tolerates string `post_extractor`/`auth_config` (it `json.loads`es them), but it does **not** parse `baseline_schema` — so the suite path diffs a string against a dict tree and every field reads as changed → breaking → FAILED. This is the false schema-drift bug.
- The API section's own collection-run history modal (`web/static/app.js`, `_renderRows` ~line 4864) already renders API results in the desired rich format: a table with method pill / name (+ `qcSchemaDriftPill`) / status / code / duration / assertions columns, and an expandable detail row that shows error/reason, assertions, the schema-drift tree (`window.qcSchemaDiffHtml`, breaking/added with per-field types), and response body. This is the format the user wants for suite API items.
- The suite run-results / Execution History block (`web/static/app.js` ~line 4408) instead draws API items with a divergent, cramped `.script-result-row`/`.script-result-header` shell that misaligns and omits most of that detail — the screenshot problem.
- Variable persistence across items already works through two mechanisms in the working tree: the runner round-trips `state_updates` through the run's shared `state.json` (`runs.py`), and the web-script harnesses (`cli/script_strategies/*_strategy.py`) now merge rather than overwrite `qaclan_vars` when they snapshot storage state. This change ratifies that behavior as a requirement and verifies it.

## Goals / Non-Goals

**Goals:**
- Make a suite API item resolve/deserialize identically to a collection run so the schema-drift verdict matches (no false breaking drift).
- Render suite-run API items in the same rich row+detail format the API section's collection-run view uses (method/name/status/code/duration/assertions + expand → error, assertions, schema-drift tree with types, response body).
- Lock cross-item variable persistence (API→API, API→script) as covered behavior.

**Non-Goals:**
- No change to the shared `resolve_and_run_api_item` contract, or to collection/standalone-send behavior.
- Not restyling script items — scripts keep their `.script-result-card` layout; only the API-item rendering changes.
- No negative testing in suites (unchanged — suites always pass `include_negatives=False`), so the suite API detail shows no negative section even though the API-run renderer can.
- No DB schema change; no new endpoint.

## Decisions

**1. Fix the drift bug by loading the request the same way a collection run does, not by patching the comparator.**
In the suite API-item branch, replace the raw `SELECT *` + partial manual `json.loads` with the repository loader used by collection runs (`RequestRepo().get(api_request_id, project_id)`), which fully `_deserialize()`s the row. This makes `response_schema` a type-tree at the source, so the existing `resolve_and_run_api_item`/`evaluate_drift` path produces the same verdict as a collection run — and it also removes the ad-hoc per-field parsing that is the root cause.
- Alternative rejected: also deserializing `response_schema` inline in `runs.py`. It fixes this one symptom but leaves two divergent load paths that will drift again on the next added JSON column. Loading through the same repository is the parity guarantee the spec asks for.
- Alternative rejected: making `run_api_request` defensively `json.loads` a string `baseline_schema`. That hides the real defect (two load paths) and spreads string-tolerance further into the comparator.
- The parent collection is already loaded raw for auth/schema-check resolution; keep loading it the same way collection runs do (`CollectionRepo().get`) for consistency, since `run_api_request` tolerates a string `auth_config`.

**2. Render suite API items with the API-run row+detail format, ideally via a shared renderer.**
Replace the suite view's `.script-result-row`/`.script-result-header` API branch with the same output `_renderRows` produces in the API-run modal: method pill + name (+ `qcSchemaDriftPill`) + status + status code + duration + assertions count, expanding to a detail panel with error/reason, assertion lines, the schema-drift tree (`window.qcSchemaDiffHtml`, breaking/added with per-field types), and response body. Scripts are untouched and keep their card; the mixed list interleaves script cards and API rows in suite order.
- Prefer extracting the API-run item's row+detail builder into a shared helper (e.g. `window.qcApiResultRow(item)`) that both the API-run modal and the suite run-results view call, so the format cannot drift between the two views. If a full extraction is too invasive in one pass, at minimum reuse `qcSchemaDiffHtml`/`qcSchemaDriftPill`, the method-color pill, and the code/duration span styling so the suite API item is visually identical to the API-run row.
- Suppress the negative-testing section in the suite context (suites never produce one — matches the existing "no negative section" requirement), even though the API-run renderer can show it.
- Data is already available: `get_run` (`web/routes/runs.py`) merges `api_runs` rows carrying `status`, `status_code`, `duration_ms`, `assertion_results`, `schema_drift`, `response_body`, `response_headers` into the run's item list, so the renderer has every field the API-run modal uses.

**3. Fix variable persistence: seed collection vars in the suite API path (not just ratify the merge).**
The state.json round-trip plus the harness `qaclan_vars` merge are necessary but not sufficient. `resolve_vars` resolves `{{name}}` in the order state.qaclan_vars → env_vars → empty. If an intervening web-script storage-state snapshot drops `qaclan_vars` (old overwrite behavior, or any future snapshot that doesn't merge), a later API item's `{{access_token}}` falls through to a **stale/empty environment variable of the same name** and the request fails (observed on suite `suite_39202264`: `/summary` → 401 "Token has expired", while the fresh login token was still valid). A collection run never hits this because it seeds `CollectionVarsRepo.as_seed_dict(collection_id)` into state before running. So the suite path must do the same: seed the request's collection vars as a base, then overlay `state.json` `qaclan_vars` on top so this-run extractions still win. An earlier login item persists its fresh token to `collection_vars` every run, so the seed is fresh. This is the concrete parity fix, alongside confirming the harness merge is present in every strategy (python, javascript, javascript_test, typescript_test).

## Risks / Trade-offs

- [Loading via `RequestRepo.get` needs `project_id`] → `runs.py` already has `project_id` in scope for the run; pass it through. Low risk.
- [A request row with a genuinely malformed stored `response_schema`] → `_deserialize` catches parse errors and yields `None`, which the comparator treats as first-capture (skipped), not breaking — strictly better than today's false breaking verdict.
- [Restyling the API card could regress the expand toggle] → the toggle target (`detailId`) and `.api-result-detail.collapsed` behavior are preserved; only the outer wrapper changes from `.script-result-row` to `.script-result-card`.
- [Harness merge only helps runs after this change] → historical runs are unaffected; this is forward-only behavior, acceptable for a bugfix.

## Migration Plan

Pure code change, no data migration. Rollback is reverting the `runs.py` load change and the `app.js`/`style.css` render change; existing runs and DB rows are untouched.
