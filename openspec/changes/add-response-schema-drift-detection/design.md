## Context

See `proposal.md` — Why. Relevant current state (from the code, not restated motivation):

- A canonical response **type-tree** already exists: `cli/schema_infer.py::infer_schema(value)` — recursive, primitives → `"null"|"boolean"|"number"|"string"`, list → `[infer_schema(first)]` or `["?"]` for empty, dict → `{k: infer_schema(v)}`, and `"..."` beyond depth 4. This same format is used across HAR import, docs, and discovery, and is stored in `api_requests.response_schema`.
- `web/api/services/runner_service.py:78-84` already **re-infers and unconditionally overwrites** `response_schema` on every successful JSON single-send, and echoes it into the result. This overwrite is what currently discards drift information.
- A schema **union** helper exists (`cli/api_discovery/schema_merger.py::merge_schemas`) — a diff can mirror its recursion. **No diff/compare function exists** (grep confirms zero hits).
- Requests run through one execution path: `cli/api_runner.py::run_api_request(...)` returns a result dict (`status`, `status_code`, `response_body`, `response_headers`, `assertion_results`, …). Both single-send (`runner_service.run_request`) and collection runs (`runner_service._execute_collection`) call it.
- Per-run responses already persist: `api_request_results` (collection runs) and `api_runs` (suite runs) store `response_body`, `response_headers`, `assertion_results`.
- No `jsonschema` dependency; the whole codebase uses the home-grown type-tree.

## Goals / Non-Goals

**Goals:**

- Detect structural drift against a stored baseline using the existing type-tree — zero new third-party dependencies.
- Reuse the existing `response_schema` column as the baseline, made frozen — no new column.
- Resolve enablement by inheritance (collection default + request tri-state) with **no cascade writes**.
- Put pure comparison logic in one testable module reachable by every run path (single, collection, suite).

**Non-Goals:**

- Value-level assertions (that is what the assertion builder is for) — this checks **shape**, not values.
- Formal JSON-Schema (Draft-07 etc.) validation or import of external OpenAPI contracts as the expected source (future).
- Per-request configurable severity policy — the severity mapping is fixed in this change (see Open Questions).
- Deep drift below the existing depth-4 cap of `infer_schema` (inherited limitation, documented).

## Decisions

### 1. Home-grown `diff_schemas` over adding a JSON-Schema library

Add `cli/schema_diff.py::diff_schemas(expected, current)` returning a flat list of `{path, kind, severity, expected_type, actual_type}`, plus a classifier producing the verdict object. It mirrors `merge_schemas` recursion but emits differences instead of a union.

- Why: every consumer already speaks the `infer_schema` type-tree; a `jsonschema` dep would need a second schema format and conversion, and would still not match the stored data. Zero-dep keeps the Nuitka binary lean and matches convention.
- Alternative rejected: `jsonschema` / `genson` — heavier, format mismatch, no gain for a shape-only diff.

### 2. Reuse `response_schema` as the frozen baseline (no separate column)

The baseline is the existing `api_requests.response_schema` column, made **frozen**: captured once (first successful JSON response, or seeded by HAR/discovery import) and never auto-overwritten thereafter — only the explicit "Update response schema" action changes it. No `expected_schema` column.

- Why: a baseline that keeps absorbing the latest response can never reveal drift — at compare time it would already equal what just came back. The baseline *must* stay put; that is exactly what "frozen `response_schema`" is. A second column would be the same frozen value under a different name.
- The one behavior change: `response_schema` previously auto-overwrote on **every** send (its old code even self-corrected to the latest shape — i.e. silently swallowed drift). That unconditional refresh is removed. For display continuity the runner still echoes each run's freshly inferred shape into the *result* (`response_schema` key) for the Schema tab / extractor picker, but the service persists it only on first capture.
- Extractor picker: reads the stored (frozen) shape; a newly added API field needs one "Update response schema" click before it appears — acceptable, and a dropped field that an extractor used fails loudly anyway (same signal drift already reports).
- Alternative rejected: a separate `expected_schema` column alongside a still-live `response_schema` — an extra column and a live-overwrite that hides drift, for no gain.

### 3. Inheritance data model, resolved at run time

- `api_collections.schema_check_default` TEXT `'on'|'off'` (default `'off'`).
- `api_requests.schema_check` TEXT `'inherit'|'on'|'off'` (default `'inherit'`).
- Effective enabled = `override in ('on','off') ? override=='on' : collection_default=='on'`, computed in the service layer per run.

The collection default is a **master switch**: changing it resets every request's override in that collection to `inherit` (`CollectionRepo.reset_schema_check_overrides`, called from the collection PATCH route), so all requests follow the new default. This is a deliberate product choice — the tri-state still lets a user re-override an individual request afterward, but the global toggle is authoritative and its meaning is unambiguous ("on = everything is checked"). The reset is a bounded bulk write over one collection's requests (not per-keystroke), and the UI confirms before applying it. Changed request ids are re-enqueued for cloud sync. Between default changes, an explicit override still wins at run time.

### 4. Fixed severity classifier

| Difference | Severity | Detection in the type-tree |
|---|---|---|
| Field in expected, absent in current | breaking (removed) | key in expected dict, missing in current dict |
| Primitive type changed | breaking (type-changed) | expected leaf ≠ current leaf, both concrete |
| Value became `null` | breaking (became-nullable) | expected concrete non-`null`, current `"null"` |
| Array element type changed | breaking (element-type-changed) | recurse into `[elem]` on both sides |
| Field in current, absent in expected | additive (added) | key in current dict, missing in expected dict |
| Either side is `"?"`, `"..."`, or `["?"]` | none (unknown) | wildcard — never claim drift |

- `null` handling: a single response can't reveal "sometimes null"; a field that came back `null` this run flips its leaf to `"null"` and reads as breaking. That is the correct default (a contract consumer would break); users reconcile intermittent nulls with "Update response schema".
- Unknown wildcards (`"?"`/`"..."`) never generate false positives.

### 5. Verdict computed inside `run_api_request`, orchestration in the service

- `run_api_request(...)` gains `baseline_schema` and `schema_check_enabled` params. It always infers the current shape from a JSON body (echoed as `response_schema` for display). When enabled, it calls `diff_schemas`, builds a `schema_drift` object, attaches it to the result, and — if any difference is breaking — sets `status = "FAILED"`. Assertions and schema-check both feed the verdict; the schema failure is kept **separate** from `assertion_results` so it's distinguishable (spec requirement).
- The **service layer** (`runner_service`) resolves inheritance, loads the baseline from `response_schema`, passes both params in, and afterward: if `response_schema` was empty and the response was a successful JSON body, stores the inferred shape as the frozen baseline (`_maybe_capture_baseline`); persists `schema_drift` onto the result row. It no longer overwrites `response_schema` on every send.

Why here: `run_api_request` is the single path all run types share, so the pure verdict logic runs everywhere; DB reads/writes stay in the service where they belong. Alternative rejected: compute drift only in `runner_service` single-send — collection/suite runs would silently skip the check.

### 6. `schema_drift` result/verdict shape

```json
{
  "checked": true,
  "verdict": "pass | fail | skipped",
  "skipped_reason": "disabled | non-json | first-capture | null",
  "breaking_count": 2,
  "additive_count": 1,
  "worst_severity": "breaking | additive | none",
  "differences": [
    {"path": "data.email", "kind": "removed", "severity": "breaking",
     "expected_type": "string", "actual_type": null},
    {"path": "data.age", "kind": "type-changed", "severity": "breaking",
     "expected_type": "number", "actual_type": "string"},
    {"path": "data.nickname", "kind": "added", "severity": "additive",
     "expected_type": null, "actual_type": "string"}
  ]
}
```

Persisted JSON-encoded in new `schema_drift` TEXT columns on `api_request_results` and `api_runs`.

### 7. UI: inline Schema Diff tab + drift banner + per-row markers

- Response panel (`web/static/api/components/response-panel.js:290-295`, `_renderContent` `:174`): add a `'schema-diff'` tab, shown when `schema_drift.differences` is non-empty, reusing `_renderSchemaTree` / `_mkPillGroup` to render expected-vs-current with added/removed/type-changed markers and a breaking/additive color split.
- Request editor (`web/static/api/views/request-editor-view.js`): a tri-state schema-check control near the Assertions section (`sectionMap` `:1674-1682`) labeling effective state and source (`On (inherited)` / `On (overridden)` / `Off (overridden)`), a reset-to-inherit affordance, and an "Update response schema" button; a drift banner in the send handler (`:1709-1723`).
- Collection detail (`web/static/api/views/collection-detail-view.js`): one "Schema check default" toggle writing `schema_check_default`.
- Collection run (`web/static/api/views/collection-run-view.js:191-207`, `:282-287`): a per-row drift marker driven by the persisted `schema_drift.worst_severity`.
- HTML report (`cli/api_report.py`): the report reads `api_request_results`, so it must select and deserialize the new `schema_drift` column and render a per-request drift pill, a "Schema Drift" detail block, and a summary stat card counting requests with breaking drift.

### 8. Sync

Agent → server (outbound push), best-effort, same as existing schema columns:

- Request payload (`sync_api_request_to_cloud`): add `schema_check`; `response_schema` already syncs. Pull upsert (`cli/commands/pull.py`) mirrors it.
- Collection payload (`sync_api_collection_to_cloud`): add `schema_check_default`. Pull upsert mirrors it.
- Run-result payloads: add `schema_drift` to each request result in `sync_api_collection_run_to_cloud` (collection runs) and `_gather_api_run_results` (mixed E2E+API suite runs). The API client (`cli/api.py`) forwards payload dicts wholesale, so no client-side field change is needed. The server side must persist these fields — out of scope for this repo.

### 9. Docs

New `docs/api-schema-check-reference.md` mirroring the maintenance-rule style of `docs/api-assertions-reference.md` (source-of-truth line, severity table, `file:line` anchors). Add a matching maintenance rule so the doc can't drift from `cli/schema_diff.py` / the columns / the UI. New dated spec + plan under `docs/superpowers/`.

## Risks / Trade-offs

- **Depth-4 cap of `infer_schema`** → drift deeper than 4 levels is invisible (both sides read `"..."`). Mitigation: accept as an existing, consistent limitation; document it in the reference doc. Raising the cap is out of scope and would affect every other consumer.
- **Single-sample nullability** → a legitimately intermittent-null field reads as a breaking `became-nullable` change. Mitigation: "Update response schema" reconciles it; documented. Treating null as a wildcard was rejected — it would hide real null regressions.
- **Auto-capturing a bad first response** (e.g. a 500 JSON error body) as the baseline. Mitigation: capture only when the response is JSON **and** `status_code < 400`; otherwise leave `response_schema` unset so the next good response captures.
- **Removing the unconditional `response_schema` overwrite** (was `runner_service.py:78-84`). Consequence: the Schema tab / extractor picker no longer silently track the latest response — `response_schema` is frozen after first capture and only the "Update response schema" action changes it. This is intended (a self-refreshing baseline can't detect drift) and applies to all requests; the runner still echoes the current shape into the result for display.
- **Collection runs gain schema inference** they didn't do before → small per-request CPU cost. Mitigation: guarded to enabled + JSON responses; negligible next to the HTTP round-trip.
- **Tri-state UI complexity** → the request toggle now shows source ("inherited"/"overridden"). Mitigation: explicit labels + reset affordance; accepted as the cost of avoiding cascade writes.

## Migration Plan

- All schema changes are **additive columns** via idempotent `_migrate_*` functions appended at `cli/db.py:157`; defaults (`schema_check='inherit'`, `schema_check_default='off'`) leave the feature **dormant** — no existing run changes behavior until a user opts in.
- Deploy order is irrelevant (columns default-null/off; readers tolerate absence via repo `_DEFAULTS`).
- Rollback: the feature is inert with the columns present; if reverted, the extra columns are simply unread. No data migration or destructive step.

## Open Questions

- Per-request **severity policy override** (e.g. "treat additive as failing too", or "ignore a specific path") — deferrable; the fixed mapping in Decision 4 covers the common contract case and adding a policy later needs only a new request column, not a change to the specs or task breakdown here.
- Sourcing the baseline from an **imported OpenAPI/example** instead of a captured response — future capability, independent of this data model.
