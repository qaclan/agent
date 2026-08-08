## Context

See `proposal.md` — Why. Relevant current state (from the code, not restated motivation):

- Every request runs through one execution path: `cli/api_runner.py::run_api_request(req, env_vars, state, state_path=None, baseline_schema=None, schema_check_enabled=False)` (`:492`). It resolves `{{vars}}`, substitutes path params, applies auth (`_apply_auth`, `:101`), builds the body (`:577-656`), sends **once** via `httpx` (`:658-694`), then runs extractors, scripts, assertions, and the schema-drift check, and returns a result dict (`status`, `status_code`, `response_body`, `response_headers`, `assertion_results`, `schema_drift`, …, `:775-790`). Both single-send (`runner_service.run_request`) and collection runs (`runner_service._execute_collection`) call it.
- A **no-code assertion engine** already exists and is generic: `_evaluate_assertions` (`:381`) + `_compare` (`:361`, ops `eq/ne/lt/gt/contains/exists/not_exists/matches`) evaluate `{type: status|json_path|header|response_time|body_text, op, value}` records. This is exactly the machinery a per-case "expected rejection" needs — no second evaluator required.
- The **schema-check slice** is the proven template for this whole change: pure logic in `cli/schema_diff.py` (`diff_schemas` → `classify_drift` → fixed verdict object), a `baseline_schema`/`schema_check_enabled` kwarg threaded through `run_api_request`, inheritance resolved in `runner_service._resolve_schema_check` (`:41-50`) with a `reset_schema_check_overrides` master switch, a `schema_drift` TEXT verdict persisted on `api_request_results` and `api_runs`, one shared UI renderer `web/static/api/components/schema-diff-view.js` (`window.qcSchemaDiffHtml` / `qcSchemaDriftPill`) mirrored by `cli/api_report.py::_render_schema_drift`, best-effort sync of the new columns, and `docs/api-schema-check-reference.md` under a maintenance rule. Copy this shape.
- The **OpenAPI importer** `cli/api_discovery/openapi_parser.py` already parses specs into request rows, but `_schema_to_example` (`:18`) collapses each field's schema to one sample value and **discards** the constraints (`enum`, `minimum`/`maximum`, `required`, `format`, `pattern`) that negative generation wants.
- Persistence: `request_repo` create/update/serialize enumerate an explicit column list at four touch points (`_DEFAULTS` `:9-35`, `_serialize`/`_deserialize` `:38-64`, `create` `:90-134`, `update` `:136-153`); `collection_run_repo.create_request_result` (`:83+`) `json.dumps` the per-run verdict columns (`schema_drift` at `:88-108`). DB migrations are idempotent `_migrate_*` functions appended to a list in `cli/db.py` (`:134-158`, latest `_migrate_api_schema_check` `:161-188`; `schema_drift` added to both result tables at `:183-185`).
- No `jsonschema`/fuzzing dependency exists; the codebase is plain `httpx` + home-grown helpers. A repo-wide search for "negative" returns nothing — this is greenfield within the established patterns.

## Goals / Non-Goals

**Goals:**

- Put case **generation** and case **classification** in two pure, testable modules reachable by every run path, mirroring `schema_infer` + `schema_diff`. Zero new third-party dependencies.
- Represent a negative case as **declarative data** (a mutation + an expected-rejection contract) so it is storable, editable, diffable, and importable — never generated code.
- Reuse the existing assertion engine for the "expected" side and the existing `httpx` build/send pipeline for the mutated sends — no parallel HTTP or evaluation stack.
- Resolve enablement by inheritance (collection default + request tri-state) with **no cascade writes**, identical to schema-check.
- Make **false-pass** (API accepted invalid input) the loudest signal, and gate destructive runs behind an environment-aware confirm.

**Non-Goals (design-level boundaries; v2):**

- The **stateful/relational tier** — Authz/BOLA (needs 2+ identities + a resource-ownership map + ID-swap), state/conflict `409` (needs multi-step create-then-conflict setup), rate-limit `429` (needs burst orchestration). v1 is strictly **stateless single-request mutation**; each case is one derived send with no dependency on another.
- A general fuzzing/property-testing engine (Hypothesis-style shrinking, stateful sequences). v1 uses a bounded, curated case set, not open-ended input search.
- Per-request configurable severity policy — the severity mapping is fixed in this change.
- Value-level positive assertions — that remains the assertion builder's job.

## Decisions

### 1. Two home-grown pure modules, mirroring `schema_infer` + `schema_diff`

- `cli/negative_gen.py::generate_cases(request_row, field_constraints=None) -> list[case]` — walks the resolved body (JSON), query params, path params, and auth and emits case dicts across the three categories. Constraint-aware when `field_constraints` is present, type-inference fallback otherwise. A curated injection payload pack lives here as a module constant. Also `diff_cases(old_cases, new_cases) -> {added, removed}` for regeneration.
- `cli/negative_check.py::classify(case_results) -> verdict` — pure severity classification into the fixed-shape verdict object (below), matching `classify_drift`.

Why two modules: generation and classification are independently testable and have no I/O; keeping them pure lets the run wiring stay thin and lets both the web and CLI paths share them. A dependency (Schemathesis/Hypothesis) is rejected — it brings a spec-format requirement, non-determinism, junk-state generation, and the false-positive noise the proposal exists to avoid, and would bloat the Nuitka binary.

### 2. A negative case is declarative data

```json
{
  "id": "body.age::wrong-type",
  "category": "input-validation",
  "subtype": "wrong-type",
  "target": "body.age",
  "label": "age as string",
  "enabled": true,
  "mutation": { "op": "set", "path": "body.age", "value": "not-a-number" },
  "expect": { "status_op": "eq", "status_value": 422, "no_500": true, "no_reflect": false }
}
```

Stored as the JSON array `api_requests.negative_cases`. `mutation.op` is a small closed set — `set` / `remove` / `set_raw_body` (malformed JSON, oversized) / `drop_auth` / `set_auth` (garbage/expired token) / `set_method` / `set_header` / `remove_header` (content-type) / `append_path` (unknown route). `target`/`path` address the resolved request (`body.<json-path>`, `param.<key>`, `path.<name>`, request-level pseudo-targets like `@auth`, `@method`).

Why declarative over codegen: cases must survive round-trips (edit, disable, regenerate-diff, sync, import), be rendered in a matrix, and be applied uniformly by one `_apply_mutation`. Generated Python/JS (the Postman/REST-Assured approach) can't be diffed or toggled as data and reintroduces the maintenance drag we are removing.

### 3. Reuse the assertion engine for the "expected" side

The `expect` block compiles to the existing assertion records: `{type: 'status', op: status_op, value: status_value}` plus, for injection, a `no_500` guard (status `lt 500`) and an optional `no_reflect` body check. `run_api_request` already evaluates such records via `_evaluate_assertions`/`_compare`, so per-case evaluation is a call into existing code, not a new comparator.

Why: one evaluation semantics across positive and negative testing; the type-aware `_values_equal`/`_contains` fixes already documented in `api-assertions-reference.md` apply for free.

### 4. Factor a reusable single-send helper; loop cases over it

Negative testing needs **N extra sends** per request (one per enabled case), unlike schema-check which reused the one response. To avoid duplicating the resolve→auth→build→httpx pipeline, extract the "apply resolved request and send once" portion of `run_api_request` into an internal helper (e.g. `_send_once(resolved, ...)`). The normal path calls it once; the negative loop calls it once per mutated case.

- Wiring: `run_api_request` gains `negative_enabled` + `negative_cases` kwargs (parallel to `schema_check_enabled`/`baseline_schema`). When enabled, after the primary send it builds each enabled case by cloning the resolved request and applying `_apply_mutation`, sends via `_send_once`, evaluates `expect`, collects per-case results, calls `negative_check.classify`, attaches `negative_result` to the result dict, and force-fails the request on Critical/Major — mirroring the breaking-drift force-fail at `:769-770`. The negative failure is kept **separate** from `assertion_results` so it is distinguishable (spec requirement).

Why in the shared path: every run type (single, collection, suite) then gets negatives; DB reads/writes stay in the service. Alternative rejected — a standalone `negative_runner` that re-implements request building — duplicates the fragile body/auth/header hygiene in `:577-656`.

### 5. Fixed severity classifier, false-pass first

| Outcome | Severity | Detection |
|---|---|---|
| Success (2xx) where a client error was expected | **Critical** (false-pass) | actual status < 400 while `expect.status` is 4xx |
| Injection payload reflected unescaped / server error on fuzz | **Critical** | `no_reflect` violated, or 5xx on an injection case |
| 5xx crash on an ordinary validation case, or wholly wrong status family | **Major** | 5xx (non-fuzz), or actual family ≠ expected family and not 2xx |
| Rejected but wrong specific code / inconsistent error schema / missing `Allow`·`Retry-After` | **Minor** | 4xx but ≠ expected code |
| Matches the expected contract | pass | — |

`classify` sets `worst_severity`, `verdict = fail` when any Critical/Major, and marks each false-pass explicitly. Why fixed: a per-request policy is deferrable and would complicate the matrix UI; the mapping above is the industry-standard reading and the false-pass emphasis is the product's core value.

### 6. `negative_result` verdict shape

```json
{
  "checked": true,
  "verdict": "pass | fail | skipped",
  "skipped_reason": "disabled | no-cases | null",
  "worst_severity": "critical | major | minor | none",
  "counts": { "total": 12, "passed": 11, "failed": 1, "false_pass": 1 },
  "by_category": {
    "input-validation": { "passed": 7, "total": 8 },
    "request-level":    { "passed": 4, "total": 4 },
    "injection":        { "passed": 0, "total": 0 }
  },
  "cases": [
    { "id": "body.age::wrong-type", "category": "input-validation", "label": "age as string",
      "method": "POST", "expected_status": 422, "actual_status": 200,
      "passed": false, "severity": "critical", "false_pass": true,
      "note": "accepted invalid input" }
  ]
}
```

Persisted JSON-encoded in new `negative_result` TEXT columns on `api_request_results` and `api_runs`, exactly like `schema_drift`.

### 7. Inheritance data model, resolved at run time

- `api_collections.negative_check_default` TEXT `'on'|'off'` (default `'off'`).
- `api_requests.negative_check` TEXT `'inherit'|'on'|'off'` (default `'inherit'`).
- `api_requests.negative_cases` TEXT (default `'[]'`), `api_requests.field_constraints` TEXT (default `NULL`).
- Effective enabled = `override in ('on','off') ? override=='on' : default=='on'`, computed in `runner_service._resolve_negative_check(req, col)` mirroring `_resolve_schema_check`. The collection default is a **master switch**: changing it resets every request's `negative_check` in that collection to `inherit` (`CollectionRepo.reset_negative_check_overrides`, called from the collection PATCH route), UI-confirmed, changed ids re-enqueued for sync.

### 8. OpenAPI constraint enrichment (extend, don't add)

Extend `openapi_parser.py` with a pass that keeps raw per-field constraints (`required[]`, `enum`, `minimum`/`maximum`, `minLength`/`maxLength`, `format`, `pattern`, `type`) alongside the existing example, and persist them to the new `field_constraints` column at import. `generate_cases` consumes them for exact boundary (min-1/min/max/max+1) and true enum-violation cases; absent (HAR / manual requests), it falls back to type inference from the request values. Why extend the existing parser: the project already owns spec parsing; this is a smaller, lower-risk add than a second parser, and non-spec requests still work.

### 9. Safety gate for destructive runs

A case is "mutating" when its derived HTTP method is POST/PUT/PATCH/DELETE. The service layer computes whether an enabled set contains mutating cases; if so, the run requires an explicit confirm (`confirm_destructive` param on the run route; `--yes`/`--confirm-destructive` on the CLI) and the surfaces show the active environment name. Read-only sets run without prompting. Why in the service/route/CLI boundary, not the pure modules: the guard is an I/O-time policy about *where* requests are sent, not about case content.

### 10. UI: matrix tab + one shared renderer, mirroring schema-diff

**Design-system stance (reviewed against the UI/UX pass).** This surface lives *inside* the existing API client, so the quality bar is **consistency with the host app**, not a bespoke visual identity: reuse the existing tabs, the schema-check tri-state segmented control, the pass-green / fail-red / warn-amber badge tokens, the existing modal shell, and the app's Inter + monospace faces. A templated look here would come from *inconsistency*, not from reusing tokens. The one "signature" moment is the matrix heat plus the false-pass emphasis; everything around it stays quiet.

- **Request editor** (`web/static/api/views/request-editor-view.js`): add `'Negative'` to `SECTIONS` (`:399`) and `sectionMap` (`:1785`). The section holds the tri-state `negative_check` control copied from `makeSchemaCheckSection` (`:1674`), a category **segmented filter** (All / Input / Request / Injection, each with a count), a **Generate** button, the **matrix grid**, and a **Run negatives** action. `_buildPayload` (`:1873`) gains `negative_cases` + `negative_check`.

**Matrix mechanics.** Rows = targets grouped and visually banded by category (input-validation fields, then request-level pseudo-targets, then per-field injection); columns = mutation types. Row-header column (target labels) is **sticky-left**, the column-header row (mutation types, each with a bulk enable/disable affordance) is **sticky-top**, and the grid scrolls inside its own `overflow-x:auto` container so the editor never scrolls sideways. Status codes and counts render in **tabular/monospace** figures to prevent reflow. Editing a cell's expected status happens in a small popover on the cell, not inline, to keep the grid scannable (progressive disclosure).

**Cell state model (five states, never color-only).** A cell carries one of: *not-applicable* (no case for this target×mutation — empty, muted), *disabled* (case exists, toggled off — outlined, low emphasis, `cursor` + reduced opacity), *ready* (enabled, not yet run — shows the expected status in neutral), *pass* (✓ glyph + green), *fail* (severity glyph + severity color). Because a green/red pair alone fails colorblind users (WCAG `color-not-only`, High), **every** state pairs a **glyph and/or text** with its color — the cell is never distinguished by hue alone, and the same rule governs the row/results chips.

**Empty, first-run, and loading states.** Before Generate: an empty state with a single primary CTA — *"Generate negative tests from this request"* — and one line naming the source (*inferred from the request body · enriched by the imported spec* when `field_constraints` exist). After Generate, before Run: cells show expected status in the neutral *ready* state, no fake heat. During a run (N sequential sends): a running counter (*"Running 4 / 12"*), per-cell in-flight shimmer, and a **Cancel** control — the run is interruptible and never freezes the UI.

**Results presentation & the false-pass band.** The shared renderer groups outcomes by category and ranks by severity, but any **Critical** outcome — a false pass above all — is lifted into a **findings band at the top**, ahead of the grouped detail, so "the API accepted invalid input" is the first thing seen, not something to scroll for. Each finding row shows a severity chip (glyph + label + color), the case label, method, and **expected vs actual status side by side** in tabular figures, with a plain-words reason.

**Severity tokens (within the app palette, contrast-checked both themes).** Critical = filled danger (solid red, warning glyph) — deliberately heavier than an ordinary fail; Major = solid amber/orange; Minor = muted neutral outline; pass = green check. These map onto the existing tokens rather than introducing new hues, and each pairs a glyph with the color.

**Keyboard & focus.** The grid is a real semantic table with header scope; cells and the column bulk-toggles are focusable and operable by keyboard with visible focus rings; the run/cancel and confirm controls are in the tab order.

- **Shared renderer** — new `web/static/api/components/negative-view.js` (classic script loaded before `app.js`), exposing `window.qcNegativeCasesHtml(negative_result)` (the false-pass band + category-grouped, severity-ranked detail, glyph-plus-color chips) and `window.qcNegativePill(negative_result)` (`N/M passed`, worst-severity color **and** glyph). `cli/api_report.py` mirrors the identical layout in a `_render_negative`.
- **Response panel** (`response-panel.js` `show()` `:302-352`): a `Negative (pass/total)` result tab when `negative_result` is present, colored + glyphed by worst severity.
- **Collection detail / collection-run / Runs modal** (`collection-detail-view.js`, `collection-run-view.js` `:288-294`, `web/static/app.js` `:4736+`/`:4775`): the default toggle, and the `neg N/M` pill + grouped block everywhere the `schema Δ N` pill already appears.

### 10a. Destructive-run confirm modal

The safety gate (Decision 9) renders as a confirm modal, not a silent block, because destructive confirmation is a High-severity UX requirement. The modal: names the **active environment prominently** (name + base URL) so a production target is unmissable; lists the mutating cases **grouped by HTTP method** with a count (*"6 state-changing requests: 2 POST, 1 PUT, 3 DELETE"*); a danger-colored **Run anyway** button visually separated from **Cancel**, with focus defaulting to **Cancel** (not the danger action) and `Esc`/backdrop dismiss as escape routes. The **Run negatives** button itself carries a persistent environment badge (*"Run negatives · DEV"*) so the target is visible before the click, too. Copy states the risk plainly and the action keeps its verb through the flow.

### 11. Report + CLI/CI

`cli/api_report.py` (`generate_api_html_report` `:401`): select/deserialize the new `negative_result` column, add a per-request `neg N/M` pill and grouped severity detail (false-pass highlighted), and a **Negative** summary stat card (`:458-466`). `cli/commands/api_cmd.py`: a headless negatives run that prints the category/severity summary and returns a **severity-gated exit code** (non-zero on Critical/Major), satisfying the CI requirement; `--yes` satisfies the safety gate headlessly.

### 12. Sync + docs

Sync mirrors the schema columns, best-effort (`cli/sync.py`, `cli/commands/pull.py`): `negative_cases` + `negative_check` on the request push/upsert, `negative_check_default` on the collection, `negative_result` on each run result. New `docs/api-negative-testing-reference.md` modeled on `api-schema-check-reference.md` (source-of-truth line, category taxonomy, case shape, severity table, verdict shape, UI surfaces, sync, limitations) + a matching maintenance-rule bullet in `CLAUDE.md`.

## Risks / Trade-offs

- **Send fan-out** — N enabled cases = N extra HTTP round-trips per request, multiplied across a collection run. → Mitigation: opt-in and per-request; bound the generated set (a capped injection pack, no combinatorial explosion); reuse the existing per-request timeout; `log()`-style surfacing of case counts so the cost is visible. Concurrency stays sequential in v1 (simpler, gentler on the target).
- **Destructive writes / persisted bad data** — mutating cases and false-passes can write junk (or injection payloads) into the target store. → Mitigation: the safety gate (Decision 9), environment surfacing, and read-only-set bypass; documented guidance to run against a disposable environment.
- **False positives** (the Schemathesis failure mode) — a wrong default expected status, or treating an optional field as required, produces noisy failures that erode trust. → Mitigation: every case is editable with a per-case expected-status override; regeneration **diffs** instead of clobbering edits (Decision 1); a case can be disabled; missing-required is generated conservatively.
- **Reflection heuristic** — `no_reflect` (payload appears verbatim in the body) can false-positive when an API legitimately echoes input. → Mitigation: `no_reflect` defaults off except for the injection pack, is per-case editable, and looks for the raw unescaped payload only; documented as a heuristic.
- **Oversized / deeply-nested payload cases** could self-inflict load on the target. → Mitigation: bounded sizes, behind the safety gate, off by default for production-like environments.
- **Matrix UI complexity** — a fields×mutations grid is more UI than the schema-check tab. → Mitigation: reuse existing badge/color tokens and the tri-state control; the grid is a presentation over the same case list the engine already runs.

## Migration Plan

- All schema changes are **additive columns** via idempotent `_migrate_*` functions appended at the `cli/db.py` migration list; defaults (`negative_check='inherit'`, `negative_check_default='off'`, `negative_cases='[]'`, `field_constraints=NULL`, `negative_result=NULL`) leave the feature **dormant** — no existing run changes behavior until a user opts in and generates cases.
- Deploy order is irrelevant (columns default-off/null; repos tolerate absence via `_DEFAULTS`).
- Rollback: the feature is inert with the columns present; if reverted, the extra columns are simply unread. No data migration or destructive step. The `run_api_request` single-send refactor (Decision 4) is behavior-preserving for the normal path.

## Open Questions

- **Injection payload pack contents and cap size** — the exact curated SQLi/XSS/traversal/unicode/null-byte set and its per-field limit. Deferrable: it is data in `negative_gen.py`, tunable without touching the specs, the run wiring, or the task breakdown.
- **Error-schema-consistency Minor check** — asserting a consistent error-envelope shape needs a known canonical error schema, which many local-first users won't have declared. v1 may ship this Minor check as opt-in (or defer it) without changing the verdict model or any other requirement.
