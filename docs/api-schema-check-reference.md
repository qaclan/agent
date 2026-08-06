# API response schema check — reference

Source of truth: `cli/schema_diff.py` (the diff + severity + verdict logic),
`cli/api_runner.py::run_api_request` (where the check runs), and
`web/api/services/runner_service.py` (enablement resolution + baseline capture).

**Maintenance rule:** any change to schema-check behavior — the diff/severity
logic in [cli/schema_diff.py](../cli/schema_diff.py), the runner wiring in
[cli/api_runner.py](../cli/api_runner.py), the resolution / capture / `Update
response schema` flow in [web/api/services/runner_service.py](../web/api/services/runner_service.py),
the `schema_check` / `schema_check_default` / `schema_drift` columns and the
baseline reuse of `response_schema` in [cli/db.py](../cli/db.py), their storage
in the repositories (`request_repo.py`, `collection_repo.py`,
`collection_run_repo.py`, `api_run_repo.py`), the sync mapping (`cli/sync.py`,
`cli/commands/pull.py`), or the UI (the shared renderer
`web/static/api/components/schema-diff-view.js`,
`web/static/api/components/response-panel.js`,
`web/static/api/views/request-editor-view.js`, `collection-detail-view.js`,
`collection-run-view.js`, the Runs history modal in `web/static/app.js`, and the
downloadable report in `cli/api_report.py`) — must be reflected in this doc in
the same change.
Grep for `schema_check\|response_schema\|schema_drift\|diff_schemas` if unsure
whether a touched file is in scope.

## What it does

The runner infers a **type-tree** from a JSON response
(`cli/schema_infer.py::infer_schema` — primitives become `"string"` /
`"number"` / `"boolean"` / `"null"`, objects become `{key: schema}`, arrays
become `[item_schema]`, with `"?"` for empty arrays and `"..."` past depth 4).

When a request's schema check is enabled, the runner compares this run's
inferred shape against the request's stored **`response_schema`** baseline and
reports the structural differences. It is a shape check, not a value check — use
assertions ([api-assertions-reference.md](api-assertions-reference.md)) for
values.

**The baseline is `response_schema` itself, kept frozen.** There is no separate
"expected" column. `response_schema` is captured once (first successful JSON
response, or seeded by HAR/discovery import) and then never auto-overwritten —
only the explicit "Update response schema" action changes it. This is
deliberate: a baseline that silently tracked the latest response could never
reveal drift (it would always equal what just came back). The runner still
echoes each run's freshly inferred shape into the result as `response_schema`
for the Schema tab / extractor picker, but that display value is not persisted.

## Enablement (inheritance)

Resolved per run by `_resolve_schema_check(req, col)` — nothing is copied to
request rows when a collection default flips.

| Field | Column | Values | Meaning |
|---|---|---|---|
| Request override | `api_requests.schema_check` | `inherit` \| `on` \| `off` | `on`/`off` win over the collection default; `inherit` follows it |
| Collection default | `api_collections.schema_check_default` | `on` \| `off` | applied to requests whose override is `inherit` |

Effective enabled = `override == 'on'` when the override is `on`/`off`, else
`collection_default == 'on'`. Default for new rows: request `inherit`,
collection `off` → the feature is dormant until opted in.

**Master switch:** changing the collection default (`CollectionRepo.reset_schema_check_overrides`,
invoked from the collection PATCH route) resets every request's `schema_check`
in that collection to `inherit`, so all requests follow the new default —
"global on ⇒ everything is checked". A user can re-override an individual
request afterward. The UI confirms before applying. Between default changes, an
explicit override still wins at run time.

## Baseline capture (`response_schema`)

- **Import as baseline**: a request created from HAR/discovery already carries a
  `response_schema` inferred from captured traffic — that is its baseline
  immediately, no send required.
- **First-send capture**: when `response_schema` is empty, the first successful
  (`status_code < 400`) JSON response is stored as the baseline
  (`_maybe_capture_baseline` in `runner_service.py`). This runs regardless of
  whether the check is enabled, so the extractor picker gets populated too. When
  the check is enabled, that first run reports `skipped_reason: "first-capture"`
  and never fails.
- **Frozen after capture**: subsequent sends never overwrite `response_schema`.
  Only the explicit action changes it.
- **Update response schema**: `POST /api/api-requests/<id>/response-schema`
  (body: `{schema}` — the last send's inferred shape — or `{response_body}`)
  overwrites `response_schema`. UI: the **Update response schema** button in the
  request editor's **Schema Check** tab.
- A non-JSON response never captures or overwrites the baseline.

## Severity (fixed mapping)

Computed in `cli/schema_diff.py::diff_schemas`.

| Difference | `kind` | Severity | Effect |
|---|---|---|---|
| Field in baseline, absent in current | `removed` | breaking | fails the run |
| Primitive type changed | `type-changed` | breaking | fails the run |
| Value became `null` | `became-nullable` | breaking | fails the run |
| Array element type changed | `element-type-changed` | breaking | fails the run |
| Field in current, absent in baseline | `added` | additive | notify only, run stays green |
| Either side is `"?"`, `"..."`, or `["?"]` | — | none | wildcard — never reported |

A run **fails** when `breaking_count > 0`. Additive-only, first-capture,
non-JSON, and error-status runs never change the verdict. A schema-check failure
is kept **separate** from `assertion_results` so it is distinguishable — the
signal lives in `schema_drift`, and the run status flips to `FAILED`.

**Error responses are skipped.** The drift check only runs on a **successful**
response (`status_code < 400`) — the same guard used for baseline capture. A
non-2xx/3xx response carries a different shape (an error envelope, not the
success payload), so diffing it against the success baseline would be pure noise;
those runs report `skipped_reason: "error-status"` and show no drift. The request
still fails on its own merits (HTTP status / assertions), just not for schema.

## `schema_drift` shape

Attached to the run result and persisted (JSON) on `api_request_results` and
`api_runs`.

```json
{
  "checked": true,
  "verdict": "pass | fail | skipped",
  "skipped_reason": "disabled | non-json | first-capture | error-status | null",
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
  ],
  "expected": { "...": "baseline type-tree, present only for the compared case" },
  "current":  { "...": "this run's type-tree, present only for the compared case" }
}
```

The `expected` / `current` keys hold the baseline (`response_schema`) and the
current run's inferred shape, for the comparison view. `path` uses dotted object
keys and `[]` for array elements (e.g. `data.items[].id`). `expected_type` /
`actual_type` are compact labels (`object`, `array`, or a primitive name);
`null` means the field is absent on that side.

## UI surfaces

Every live surface shares **one renderer**,
`web/static/api/components/schema-diff-view.js` (a classic script loaded in
`index.html` before `app.js`), exposing `window.qcSchemaDiffHtml(drift)` (the
grouped changes block) and `window.qcSchemaDriftPill(drift)` (the compact
`schema Δ N` row pill). The downloadable report reproduces the identical layout
in `cli/api_report.py::_render_schema_drift`.

**Layout — plain-words, grouped, dense (one line per change):** a
`Schema changed — N breaking, M added` summary line, then a **Breaking** group
(red) and an **Added** group (amber). Each row is `sign  path  type` where the
sign is `−` removed / `~` type-changed (covers type-changed, became-nullable,
element-type-changed) / `+` added, and the type note is the lost type (removed),
the new type (added), or `old → new` (a type change). No `∅` / arrow-to-nothing
glyphs and no legend — the group headers and sign colors carry the severity.

- **Schema Diff tab** (`response-panel.js`): shown when `differences` is
  non-empty. Sub-views: *Changes* (the shared grouped block), *Expected* tree,
  *Current* tree.
- **Drift banner** (`request-editor-view.js`): one quiet line after a drifted
  send — `Schema drift — run failed. N breaking, M added. See the Schema Diff
  tab.` (breaking) or the run-still-passed variant (additive only). It does not
  offer to change the baseline.
- **Schema Check tab** (`request-editor-view.js`): the tri-state override (with
  the resolved effective state and its source) and the **Update response
  schema** button + a Captured / Not captured badge. This tab is the only place
  the baseline is changed.
- **Collection detail → Schema Check tab** (`collection-detail-view.js`): the
  collection default toggle.
- **Collection run rows** (`collection-run-view.js`): a `schema Δ N` pill per
  row and the shared grouped block in the expanded detail.
- **Runs history modal** (`web/static/app.js`): the same `schema Δ N` pill per
  request row and the shared grouped block in the expanded detail.
- **HTML report** (`cli/api_report.py`, `GET /api/api-collection-runs/<id>/report`):
  a per-request `schema Δ N` pill, the same grouped block in the expanded
  detail, and a "Schema Drift" summary stat card counting requests with breaking
  drift. Read-only — no "update response schema" affordance in any report or run
  view.

## Cloud sync (agent → server)

Best-effort, alongside the existing schema columns:

- **Request**: `schema_check` (and the reused `response_schema` baseline) in the
  request push (`cli/sync.py::sync_api_request_to_cloud`) + pull upsert.
- **Collection**: `schema_check_default` in the collection push + pull upsert.
- **Run results**: the `schema_drift` verdict in both the collection-run push
  (`sync_api_collection_run_to_cloud`) and the mixed-suite api-results payload
  (`_gather_api_run_results`).

The API client forwards payload dicts wholesale, so these ride along with no
client change; the server must persist them (out of scope here).

## Known limitations

- **Depth-4 cap**: `infer_schema` returns `"..."` beyond four levels, so drift
  deeper than that is invisible on both sides (an inherited limitation shared by
  every consumer of the type-tree).
- **Single-sample nullability**: a field that is legitimately null only
  sometimes will read as a breaking `became-nullable` change on a run where it
  came back `null`. Reconcile with **Update response schema**.
