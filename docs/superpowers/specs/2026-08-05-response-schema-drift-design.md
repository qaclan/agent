# Response Schema Drift Detection — Design

Date: 2026-08-05

Canonical planning artifacts live in the OpenSpec change
`openspec/changes/add-response-schema-drift-detection/` (proposal, spec, design,
tasks). Syntax/behavior source of truth: `docs/api-schema-check-reference.md`.
This file is the dated superpowers-format summary.

## Problem

1. Response contracts drift silently — a field is removed, a type flips, a value
   becomes null — and assertions only catch values a user thought to check, not
   the overall shape. Teams find out downstream.
2. The runner already infers a response type-tree on every send
   (`cli/schema_infer.py`, stored in `api_requests.response_schema`) and then
   throws the prior value away with an unconditional overwrite. The raw material
   for drift detection exists but is unused.

## Differentiated Position

Opt-in, per-request (with collection-default inheritance), severity-based
contract checking built on the existing home-grown type-tree — **zero new
dependencies** — with a first-class comparison view. Breaking changes fail the
run; additive changes only notify. This matches the industry contract-testing
model while staying local-first and non-disruptive by default.

## Decisions

| Question | Decision |
|---|---|
| Notify vs fail? | Severity-based: breaking → fail, additive → notify. |
| Diff engine? | Home-grown `cli/schema_diff.py` mirroring `merge_schemas`; no `jsonschema` dep. |
| Baseline storage? | Reuse the existing `response_schema` column, made frozen (no new column). |
| Capture? | Import-as-baseline, or capture first successful JSON response; frozen after; manual "Update response schema" to re-accept. |
| Enablement? | Tri-state request override + collection default, resolved at run time. The collection default is a master switch — changing it resets all request overrides to `inherit` (global overwrites all). |
| Where computed? | Inside `run_api_request` (shared by single/collection/suite runs); orchestration + capture in `runner_service`. |
| Comparison UI? | Inline "Schema Diff" tab in the response panel (Changes / Expected / Current). One shared renderer (`web/static/api/components/schema-diff-view.js`) drives every surface — editor tab, collection run, Runs modal, and the download report — in a plain-words grouped layout (Breaking/Added, one line per change, no `∅`/legend). |

## Data Model

New columns (all additive, idempotent `_migrate_api_schema_check` in `cli/db.py`):

- `api_requests.response_schema` (existing column) — reused as the frozen baseline type-tree; captured once, then never auto-overwritten.
- `api_requests.schema_check TEXT DEFAULT 'inherit'` — `inherit|on|off`.
- `api_collections.schema_check_default TEXT DEFAULT 'off'` — `on|off`.
- `api_request_results.schema_drift TEXT`, `api_runs.schema_drift TEXT` — persisted verdict (JSON).

`schema_drift` verdict shape and the fixed severity table are documented in
`docs/api-schema-check-reference.md`.

## Risks

- Depth-4 cap of `infer_schema` hides deeper drift (inherited limitation).
- Single-sample nullability reads intermittent nulls as breaking; reconciled via
  "Update response schema".
- Auto-capture guarded to JSON + `status_code < 400` so a first error response is
  not frozen as the contract.
