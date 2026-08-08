# API negative testing — reference

Source of truth: `cli/negative_gen.py` (case generation), `cli/negative_check.py`
(severity classification + verdict), `cli/api_runner.py::run_api_request` (where
the mutated cases run), and `web/api/services/runner_service.py` (enablement
resolution, generate/regenerate, and the destructive-run safety gate).

**Maintenance rule:** any change to negative-testing behavior — generation in
[cli/negative_gen.py](../cli/negative_gen.py), classification/severity in
[cli/negative_check.py](../cli/negative_check.py), the runner wiring
(`_apply_mutation` / `_run_negative_case` / the negatives block) in
[cli/api_runner.py](../cli/api_runner.py), enablement resolution / `run_negatives`
/ `generate_negatives` / the safety gate in
[web/api/services/runner_service.py](../web/api/services/runner_service.py), the
`negative_cases` / `negative_check` / `field_constraints` / `negative_check_default`
/ `negative_result` columns in [cli/db.py](../cli/db.py) and their repositories
(`request_repo.py`, `collection_repo.py`, `collection_run_repo.py`,
`api_run_repo.py`), the OpenAPI constraint extraction in
`cli/api_discovery/openapi_parser.py`, the routes
(`web/api/routes/requests.py`, `collections.py`), the CLI
(`cli/commands/api_cmd.py`), sync (`cli/sync.py`, `cli/commands/pull.py`), the
HTML report (`cli/api_report.py`), or the UI (the shared renderer
`web/static/api/components/negative-view.js`, `response-panel.js`,
`web/static/api/views/request-editor-view.js`, `collection-detail-view.js`,
`collection-run-view.js`, and the Runs history modal in `web/static/app.js`) —
must be reflected in this doc in the same change. Grep for
`negative_cases\|negative_check\|negative_result\|field_constraints\|negative_gen\|negative_check`
if unsure whether a touched file is in scope.

## What it does

Negative testing verifies that an API **rejects** invalid, malformed, and
malicious input correctly — the right client-error status, no server crash, and
no acceptance of bad data. From a single happy-path request the tool
auto-generates a set of **negative cases**, each a declarative mutation of the
request plus an expected-rejection contract. Enabled cases run as mutated
re-sends of the request; each outcome is classified by severity. The headline
signal is a **false pass** — the API returned a success status to invalid input.

It is opt-in and, unlike an ordinary send, **does not fire on a normal "Send"**.
Negatives run only via the request editor's **Run negatives** action or when a
collection run is executed with negative testing enabled.

## Categories (v1)

v1 is **stateless single-request mutation** — each case is one derived send.

| Category | Subtypes | Default expected |
|---|---|---|
| `input-validation` | missing-required, wrong-type, null, empty, boundary-min/max, boundary-min/maxlength, enum, format, extra-field*, oversized* | 4xx (rep. 400) |
| `request-level` | no-auth, garbage-token, wrong-method, wrong-content-type, unknown-route, malformed-json | 4xx (rep. 401/405/415/404/400) |
| `injection` | sqli, xss, path-traversal, null-byte (per string field/param) | no 500, not reflected |

`*` extra-field and oversized are generated **disabled by default** (many APIs
legitimately ignore extra fields; oversized can stress a real backend).

**Deferred to v2 (the stateful/relational tier):** Authz/BOLA (multi-identity +
resource-ownership + ID-swap), state/conflict `409` (duplicate / operate-on-deleted
/ idempotency), rate-limit `429` (burst). Each needs sequences, identities, or
bursts on top of this foundation.

## Case shape

Stored as the JSON array `api_requests.negative_cases`:

```json
{
  "id": "body.age::wrong-type",
  "category": "input-validation",
  "subtype": "wrong-type",
  "target": "body.age",
  "label": "age wrong type",
  "enabled": true,
  "mutation": { "op": "set", "path": "body.age", "value": "not-a-number" },
  "expect": { "status_value": 400, "status_min": 400, "status_max": 499,
              "no_500": false, "no_reflect": false }
}
```

- **`mutation.op`** (closed set applied by `cli/api_runner.py::_apply_mutation`):
  `set` / `remove` (on `body.<dotted>` or `param.<key>`), `set_raw_body`
  (malformed JSON / oversized), `drop_auth`, `set_auth`, `set_method`,
  `set_header`, `remove_header`, `append_path`.
- **`expect`** is a **4xx family** check by default (`status_min`/`status_max`),
  with `status_value` as the representative code shown in the UI. Editing the
  cell's expected status to an exact code sets `status_min == status_max`
  (strict). Injection cases carry `no_500` + `no_reflect` (and a `reflect_value`)
  and ignore the status family.

## Generation

`cli/negative_gen.py::generate_cases(request_row, field_constraints=None)`:

- **Happy-path inference** (always): walks the raw JSON body, query params, and
  path params; infers each field's type from its value; emits the input-validation,
  request-level, and injection cases above. Works for any request — HAR import,
  OpenAPI import, or a manual send.
- **OpenAPI enrichment** (when present): a request imported from a spec carries
  `api_requests.field_constraints` — per-field `{type, required, enum, minimum,
  maximum, minLength, maxLength, format, pattern}` extracted by
  `cli/api_discovery/openapi_parser.py::_extract_constraints`. The generator uses
  them for **exact** boundary (`min-1` / `max+1`, length±1), true enum-violation,
  and format-violation cases, and limits `missing-required` to fields the spec
  marks required. Absent constraints, it falls back to type inference.
- **Regeneration** returns `diff_cases(old, new) → {added, removed}` so the UI
  merges new/removed cases without discarding user edits (enabled + expected).

## Enablement (inheritance)

Resolved per run by `_resolve_negative_check(req, col)` — mirrors schema-check.

| Field | Column | Values | Meaning |
|---|---|---|---|
| Request override | `api_requests.negative_check` | `inherit` \| `on` \| `off` | `on`/`off` win over the collection default |
| Collection default | `api_collections.negative_check_default` | `on` \| `off` | applied to requests whose override is `inherit` |

Default for new rows: request `inherit`, collection `off` → dormant until opted
in. **Master switch:** changing the collection default
(`CollectionRepo.reset_negative_check_overrides`, from the collection PATCH route)
resets every request's `negative_check` in that collection to `inherit`.

## Safety gate (destructive runs)

A case is *mutating* when its derived HTTP method is POST/PUT/PATCH/DELETE
(`negative_gen.case_method`). When an enabled set contains mutating cases:

- **Single request:** `run_negatives` returns `{needs_confirm: true, mutating_methods,
  environment}` and sends nothing until called again with `confirm_destructive: true`.
  The editor shows a confirm modal (environment named, verbs listed, focus on
  Cancel, Esc/backdrop dismiss).
- **Collection run:** the gate is applied **per case** by
  `runner_service._negatives_for_run` — an unconfirmed run keeps a request's
  read-only negatives and drops only its mutating-verb cases (so a wholly-mutating
  request such as a `POST` runs none until confirmed, while a mixed request still
  exercises its safe cases). The collection-run UI checks
  `GET /collections/<id>/negatives/plan` first (`plan_collection_negatives`) and,
  when it reports `needs_confirm`, shows the shared chooser
  (`window.qcCollectionRunConfirm`, wired from both run triggers —
  `collections-view.js` and `collection-detail-view.js`). The chooser presents a
  **warning** (not a red error): a short "state-changing payloads will affect
  `<env>` and may create/change/delete data" message plus a **collapsed,
  expandable** "Show N affected requests" list built from `plan.mutating_requests`
  (so it stays compact regardless of how many requests have negatives on). On
  confirm it sends `confirm_destructive: true` so the mutating cases run too.
- **CLI:** `--yes` supplies the confirmation headlessly.

## Collection-run negatives mode

When a collection has negative cases, the run chooser (`window.qcCollectionRunConfirm`)
offers three modes, sent to `POST /collections/<id>/run` as `negatives_mode` and
threaded through `start_collection_run → _execute_collection` (and the sync
`run_collection`), applied per request by `runner_service._negatives_for_run`:

- **`default`** — happy-path + negatives as configured (inheritance).
- **`off`** — happy-path only; negatives never run.
- **`only`** — negatives run **only for requests that are resolved on AND have
  enabled cases** (enablement is checked the same as `default` — a resolved-off
  request runs nothing even in only-mode). Qualifying requests are sent with the
  happy-path suppressed (`assertions: []`, schema check off) so the verdict
  reflects negatives alone; the base send is the mutation source. Requests that
  would run no negatives (resolved off, or no enabled cases) are **filtered out
  before the run starts** (`runner_service._requests_for_run`) — not sent, not
  recorded, and not counted. So the run's `total`, its per-request indices, and
  the live run view (`collection-run-view.js`) all contain exactly the qualifying
  requests, contiguously indexed. A completed row carries its own `request_name`;
  for a not-yet-run row of a subset run the view rebuilds the spine from the same
  qualifying set (resolved-on ∧ enabled cases, using the collection's
  `negative_check_default`) so the real request still shows instead of a wrong
  positional name. The `plan` endpoint's `has_negatives`
  (now the intersection resolved-on ∧ has-cases) decides whether the chooser is
  shown at all; when no request qualifies, the collection runs normally with no
  mode choice.

## Active-feature indicators

"Active" = effectively on (override, else collection default) **AND has at least
one enabled case**. A request that is on but has no cases runs nothing, so it is
**not** marked (mirrors the run and `has_negatives` behavior). The marker is
independent of row selection/hover — a long request name wraps instead of pushing
the marker column off the panel, so the selected row keeps its `⊘`:

- **Collection request list** (`collections-view.js::_featureBadges`): a `⊘`
  marker on a request row when negatives are active (on ∧ ≥1 enabled case), plus a
  `Δ` marker for the parallel response-schema-check feature. The name uses
  `.api-req-name` (flexible width, wraps on overflow); the two glyphs keep a
  fixed minimum-width column.
- **Request editor tab** (`request-editor-view.js`): the **Negative Testing** tab
  shows a `⊘` marker when active (on ∧ ≥1 enabled case), refreshed live as the
  tri-state control **or the case set** changes (and **Schema Check** a `Δ`).

## Severity (fixed mapping)

Computed in `cli/negative_check.py::classify_case`.

| Outcome | Severity | Detection |
|---|---|---|
| Success (2xx) where a client error was expected | **critical** (false-pass) | actual < 400 (non-injection) |
| Injection payload reflected, or 5xx on a fuzzed input | **critical** | `reflected`, or 5xx on injection |
| 5xx on an ordinary validation case, or wrong status family | **major** | 5xx (non-injection), or non-4xx non-2xx |
| Rejected but wrong specific 4xx code | **minor** | 4xx but outside the expected range |
| Matches the contract (incl. injection handled safely) | pass | — |
| Send errored / timed out | minor (inconclusive) | `actual_status` is null |

A run **fails** when `worst_severity` is `critical` or `major`. Minor-only or
all-pass keeps the run green. The negative failure is kept **separate** from
`assertion_results` (the signal lives in `negative_result`) and flips the request
status to `FAILED`.

## `negative_result` shape

Attached to the run result and persisted (JSON) on `api_request_results` and
`api_runs`.

```json
{
  "checked": true,
  "verdict": "pass | fail | skipped",
  "skipped_reason": "disabled | no-cases | null",
  "worst_severity": "critical | major | minor | none",
  "counts": { "total": 12, "passed": 11, "failed": 1, "false_pass": 1 },
  "by_category": { "input-validation": {"passed": 7, "total": 8} },
  "cases": [
    {"id": "body.age::wrong-type", "category": "input-validation",
     "label": "age wrong type", "method": "POST",
     "expected_status": 400, "actual_status": 200,
     "passed": false, "severity": "critical", "false_pass": true,
     "note": "accepted invalid input (200) — expected a 4xx rejection"}
  ]
}
```

Each case's `note` is the plain-words **"should vs happened"** line
(`server error (500) instead of a client-error rejection`, `payload reflected in
the response`, …) built in `cli/negative_check.py::classify_case`. It is the
single source the UI and report print verbatim — never re-compose it downstream.

## UI surfaces

The **settings** surface (the request editor tab) decides *which* tests run; the
**result** surfaces show *what happened*. They are kept strictly separate — the
settings grid never renders outcomes, and results never carry toggles.

### Settings — the "Negative Testing" editor tab

`web/static/api/views/request-editor-view.js`: the tri-state control, a category
filter, **Generate tests**, and a **config-only** grid — one **block per
category**:

- **Input validation** and **Injection / fuzz** are compact field × subtype
  grids; each cell is a real **checkbox** (on/off only — no outcomes). The
  expected contract is a per-block caption badge (`expects 4xx`, `no 500 · not
  reflected`), not a per-cell value. Each subtype **column header carries its own
  checkbox** that bulk-toggles the whole column and shows the column's tri-state
  status — checked (all on), empty (all off), or **indeterminate** (mixed);
  `indeterminate` is set as a DOM property post-render since HTML can't express
  it. The **Field** (target) column has no such checkbox. Clicking the header
  label still toggles the column too. Column headers carry a descriptive tooltip
  (the injection columns name their payload and the no-5xx / not-reflected
  contract).
- **Request-level** is a **list** (independent cases), each row a checkbox +
  friendly name + an **editable expected status code** (`401`/`405`/`404`…),
  since those genuinely differ per case.

**Run Negative Testing** shows the environment badge, opens the confirm modal for
mutating cases, and renders the outcome in the **response panel** (not in the
settings grid).

### Results — the shared renderer

Every result surface shares **one renderer**,
`web/static/api/components/negative-view.js` (a classic script loaded in
`index.html` before `app.js`): `window.qcNegativeCasesHtml(negative_result)` and
`window.qcNegativePill(negative_result)`. The HTML report reproduces the same
layout in `cli/api_report.py::_render_negative`.

`qcNegativeCasesHtml` renders, top to bottom:

1. a **headline** verdict banner (`N false passes — API accepted invalid input` /
   `All N invalid inputs correctly rejected`) with `rejected / total` on the right;
2. **count chips** — `REJECTED · FALSE PASS · SERVER ERROR · FAILED` (only nonzero,
   non-overlapping) — and a color legend;
3. a per-category **outcome heatmap** mirroring the settings grid — every case
   shown as its **actual status code, colored** (green rejected · red false-pass /
   reflected · amber server error · grey wrong code · `·` n/a), so the *full*
   result is visible compactly and failures light up by tint. The per-case `note`
   is the cell's tooltip (grids stay compact — no separate findings list, which
   became a repetitive wall when many cells shared one message).

Request-level renders as a colored **list** instead of a grid — each row a word
tag + the `note` message inline (it has room; grids don't). Outcome is always a
**word + color** (never a bare glyph); the heatmap adds the status code.

- **Response panel** (`response-panel.js`): a `Negative Testing (pass/total)`
  result tab when `negative_result` is present, colored by worst severity.
- **Collection detail → Negative tab** (`collection-detail-view.js`): the
  collection default toggle (master switch, confirm-gated).
- **Collection run rows** (`collection-run-view.js`) and **Runs history modal**
  (`web/static/app.js`): a compact pill per row (`N false-pass` when any, else
  `neg N/M`) and the shared renderer in the expanded detail.
- **HTML report** (`cli/api_report.py`): the same headline + chips + heatmap +
  findings per request, plus a **Negative** summary stat card counting requests
  with critical/major findings.

## CLI / CI

`qaclan api negatives <request|--collection C> [--env E] [--yes]` runs negatives
headless, prints a category/severity summary, and returns a **severity-gated exit
code** — non-zero when any Critical/Major finding is present, zero otherwise.
`--yes` confirms destructive (mutating-verb) runs.

## Cloud sync (agent → server)

Best-effort, alongside the existing schema columns:

- **Request**: `negative_cases`, `negative_check`, `field_constraints` in the
  request push (`cli/sync.py`) + pull upsert (`cli/commands/pull.py`).
- **Collection**: `negative_check_default` in the collection push + pull upsert.
- **Run results**: the `negative_result` verdict in both the collection-run push
  and the mixed-suite api-results payload. On the pull side it round-trips through
  **both** pull paths — the workspace pull *and* the standalone collection-run
  history pull (`pull_api_run_history`, `GET /api/pull/api-runs/<id>`), which
  persists `negative_result` (and `schema_drift`) onto each `api_request_results`
  row it merges. A pulled result with no verdict stores `NULL`.

## Known limitations

- **Stateless only**: no authz/BOLA, `409` conflict, or `429` rate-limit in v1
  (deferred — they need identities, multi-step setup, or bursts).
- **Body targeting is JSON-only**: input-validation and injection walk raw JSON
  bodies (and string query params); form/multipart/GraphQL bodies are not mutated
  field-by-field in v1.
- **Reflection is a heuristic**: `no_reflect` looks for the raw payload verbatim
  in the response body, so an API that legitimately echoes input can read as a
  reflection. It defaults to injection cases only and is per-case editable.
- **`missing-content-type`** is not generated because the runner auto-adds a JSON
  `Content-Type` for raw bodies; `wrong-content-type` covers the media-type case.
