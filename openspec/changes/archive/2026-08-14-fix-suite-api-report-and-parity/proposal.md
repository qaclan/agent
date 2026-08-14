## Why

Suites now hold a mix of web scripts and API requests, but a suite API item does not yet behave or render like its collection-run counterpart. Two concrete regressions: (1) in the suite run summary / Execution History view the API item is drawn with a different card shell than script items, so it visually misaligns; (2) the same login request that passes in a standalone collection run reports a false breaking **schema drift** and fails when run as a suite item, and a downstream request loses the access token the login extracted.

## What Changes

- Render each suite-run API item using the **same rich result format the API section's collection-run view uses** (the `voxcruit schema diff · API Run` modal): a columnar row — method pill, name + schema-drift pill, status, status code, duration, assertions count — that expands in place to show error/reason, assertions, the schema-drift breaking/added tree with per-field types, and the response body. Today the suite view instead draws a cramped, differently-styled row that misaligns and omits most of that detail.
- Fix the false schema-drift failure: the suite execution path loads an API request via a raw `SELECT *` and only deserializes a few JSON columns, leaving `response_schema` as a raw string. It is then handed to the drift comparator as the frozen baseline, so a string is diffed against an inferred type-tree and every field reads as changed → breaking → FAILED. Load the request the same way a collection run does (fully deserialized) so the baseline is a type-tree and the drift result matches the collection run exactly.
- Confirm and lock in cross-item **variable persistence** so a token extracted by an API item is readable by later items regardless of type. The web-script harnesses now merge (not overwrite) `qaclan_vars` when they snapshot `state.json`, and the runner round-trips extracted vars through `state.json`; this behavior becomes a covered requirement, not an accident.
- No behavior change to negative testing: suites still never run negative cases.

## Capabilities

### New Capabilities
<!-- none: all behavior lives in the existing suite-mixed-items capability -->

### Modified Capabilities
- `suite-mixed-items`: add a requirement that suite-run API items render with the same card structure/alignment as script items in both the results view and history modal; tighten the schema-check-parity and variable-persistence requirements so the suite path resolves an API request identically to a collection run (deserialized baseline; no false drift) and so an extracted variable survives across items of either type.

## Impact

- `web/routes/runs.py` — suite execution: load the API request fully deserialized (parity with collection run) so the schema-drift baseline is a type-tree, not a string.
- `web/static/app.js` — suite run-results / Execution History: render API items with the same row+expandable-detail renderer the API-run modal uses (`_renderRows` detail: method pill, columns, `qcSchemaDiffHtml` drift tree, response body). Prefer extracting that renderer into a shared helper so the two views can't drift.
- `web/static/style.css` — reuse existing API-run row / schema-drift / `.api-result-*` styles; no divergent suite-only card for API items.
- `cli/script_strategies/*_strategy.py` — already merge `qaclan_vars` into `state.json` on snapshot (variable-persistence support); covered by the tightened requirement.
- No DB schema change. No change to the shared `resolve_and_run_api_item` contract or to collection/standalone runs.
