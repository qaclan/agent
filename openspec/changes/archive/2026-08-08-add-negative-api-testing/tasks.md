## 1. Pure generation + classification logic (no DB, testable first)

- [x] 1.1 Create `cli/negative_gen.py` with `generate_cases(request_row, field_constraints=None) -> list[case]` producing the declarative case shape from design Decision 2 (`id`, `category`, `subtype`, `target`, `label`, `enabled`, `mutation`, `expect`).
- [x] 1.2 Input-validation generation: walk the resolved JSON body, query params, and path params; per field emit missing-required, wrong-type, null, empty, boundary (min/max, length), enum-violation, format-violation; plus body-level malformed-JSON, oversized, and extra-unexpected-field. Constraint-aware when `field_constraints` present, type-inference fallback otherwise.
- [x] 1.3 Request-level generation: missing/garbage/expired auth, wrong HTTP method, wrong `Content-Type`, missing `Content-Type`, unknown route — as `@auth`/`@method`/`@header` pseudo-target cases.
- [x] 1.4 Injection generation: a curated payload pack constant (SQLi / XSS / path-traversal / unicode / null-byte) applied per string field, each case carrying `expect.no_500` and `expect.no_reflect`. Cap the per-field count (design Open Question 1).
- [x] 1.5 Smart-default expected status per category (401 no-auth, 415 bad/missing content-type, 400/422 invalid input, 405 wrong method, 404 unknown route) written into each case's `expect`.
- [x] 1.6 Add `diff_cases(old_cases, new_cases) -> {added, removed}` for regeneration (identify newly-suggested and no-longer-applicable cases by `id`, without discarding edited cases).
- [x] 1.7 Create `cli/negative_check.py` with `classify(case_results) -> verdict` implementing the fixed severity mapping (design Decision 5) and the `negative_result` verdict shape (design Decision 6): `checked`, `verdict`, `skipped_reason`, `worst_severity`, `counts` (incl. `false_pass`), `by_category`, `cases`.
- [x] 1.8 Sanity-check both modules with representative fixtures (JSON body with fields + param + bearer auth; a false-pass 2xx; a 5xx-on-fuzz; a wrong-specific-code Minor; regeneration add/remove) — inline or a scratch script; there is no test harness in this repo.

## 2. Data model (migrations + repositories)

- [x] 2.1 Add `_migrate_api_negative_testing(conn)` to `cli/db.py` with idempotent try/except ALTERs: `api_requests.negative_cases TEXT DEFAULT '[]'`, `api_requests.negative_check TEXT DEFAULT 'inherit'`, `api_requests.field_constraints TEXT DEFAULT NULL`.
- [x] 2.2 In the same migration add `api_collections.negative_check_default TEXT DEFAULT 'off'`, and `negative_result TEXT DEFAULT NULL` on both `api_request_results` and `api_runs`.
- [x] 2.3 Register the `_migrate_api_negative_testing` call in the migration list at the end of `init_db()` (after `_migrate_api_schema_check`).
- [x] 2.4 Update `web/api/repositories/request_repo.py`: add `negative_cases`, `negative_check`, `field_constraints` to `_DEFAULTS`, the `_serialize`/`_deserialize` lists (JSON-encode `negative_cases`/`field_constraints`; `negative_check` is a plain string), the `create` INSERT column list, and the `update` whitelist `fields`.
- [x] 2.5 Update `web/api/repositories/collection_repo.py` to read/write `negative_check_default` (defaults, serialize, create, update).
- [x] 2.6 Update `web/api/repositories/collection_run_repo.py` and `web/api/repositories/api_run_repo.py` to persist and deserialize `negative_result` (JSON) on per-request result rows, alongside `schema_drift`.

## 3. Runner: run cases in the shared execution path

- [x] 3.1 Refactor `cli/api_runner.py`: factor the resolved-request apply-and-send-once portion out of `run_api_request` into an internal `_execute_http(...)` helper (behavior-preserving for the normal path), plus a `_neg_sent` snapshot of the resolved send.
- [x] 3.2 Add `_apply_mutation(base, mutation)` implementing the closed op set (`set` / `remove` / `set_raw_body` / `drop_auth` / `set_auth` / `set_method` / `set_header` / `remove_header` / `append_path`) addressing `body.*` / `param.*` / `@auth` / `@method` / `@route`.
- [x] 3.3 Extend `run_api_request(...)` with `negative_enabled=False` and `negative_cases=None` params (parallel to `schema_check_enabled`/`baseline_schema`).
- [x] 3.4 When `negative_enabled`, after the primary send loop each enabled case: clone the resolved send, apply the mutation, re-send via `_execute_http`, evaluate `expect` (status family + injection no-500/no-reflect), and collect a per-case result.
- [x] 3.5 Call `negative_check.classify` on the case results, attach `negative_result` to the result dict, and force `status = "FAILED"` on any Critical/Major — kept **separate** from `assertion_results` (per spec: distinguishable). Skipped/Minor-only SHALL NOT change status.
- [x] 3.6 Ensure the error-path result variants carry a consistent `negative_result` absence (`None`) so consumers never KeyError.

## 4. Service orchestration (inheritance, safety gate, persist)

- [x] 4.1 In `web/api/services/runner_service.py`, add `_resolve_negative_check(req, col)` mirroring `_resolve_schema_check` (override `on`/`off` wins, else `negative_check_default`).
- [x] 4.2 In a dedicated `run_negatives` path and `_execute_collection`/`run_collection`, resolve enablement, load the request's `negative_cases` + `field_constraints`, and pass `negative_enabled` + cases into `run_api_request`; persist `negative_result` on the result rows. (Ordinary `/send` intentionally does NOT auto-fire negatives.)
- [x] 4.3 Add a "generate/regenerate cases" service path (`generate_negatives`) that calls `negative_gen.generate_cases` (with `field_constraints`) and, on regenerate, returns the `diff_cases` result so the UI can merge without clobbering edits.
- [x] 4.4 Safety gate: compute whether the enabled set contains mutating-method cases (POST/PUT/PATCH/DELETE) via `_mutating_negative_methods`; when it does, `run_negatives`/collection runs require a `confirm_destructive` flag and `plan_*_negatives` surface the active environment.

## 5. Generation enrichment (OpenAPI constraints)

- [x] 5.1 Extend `cli/api_discovery/openapi_parser.py` (`_extract_constraints`) to keep raw per-field constraints (`required[]`, `enum`, `minimum`/`maximum`, `minLength`/`maxLength`, `format`, `pattern`, `type`) alongside the existing example (example output unchanged).
- [x] 5.2 Persist the extracted constraints into `api_requests.field_constraints` at import time (flows through `_save_requests` → `create`); verified `generate_cases` consumes them for exact boundary + enum-violation cases and falls back cleanly when absent.

## 6. Routes + CLI/CI

- [x] 6.1 `web/api/routes/requests.py` (`/negatives/generate`, `/negatives/plan`, `/negatives/run`) + `collections.py` (`/negatives/plan`, `confirm_destructive` on run, `negative_check_default` master switch in PATCH): expose generate/regenerate + thread `confirm_destructive`; return the safety-gate block when confirmation is required.
- [x] 6.2 `cli/commands/api_cmd.py`: added `qaclan api negatives` — prints the category/severity summary and returns a **severity-gated exit code** (non-zero on Critical/Major); `--yes` satisfies the safety gate headlessly.

## 7. Sync

- [x] 7.1 Added `negative_cases` + `negative_check` + `field_constraints` to the request sync payload (`cli/sync.py`) and the pull upsert (`cli/commands/pull.py`); added `negative_check_default` to the collection payload + upsert.
- [x] 7.2 Added `negative_result` to the run-result payloads (`sync_api_collection_run_to_cloud` request_results, `_gather_api_run_results` suite api_results), mirroring `schema_drift`.

## 8. UI — shared renderer + result surfaces

- [x] 8.1 Added shared renderer `web/static/api/components/negative-view.js` (classic script) exposing `window.qcNegativeCasesHtml` + `window.qcNegativePill`; included in `index.html` before `app.js`. Reuses existing pass-green / fail-red / warn-amber tokens.
- [x] 8.2 `qcNegativeCasesHtml`: lifts any **Critical** outcome (false pass first) into a **Critical findings band at the top**, above the category-grouped, severity-ranked detail. Each row shows a severity glyph + label, case label, and **expected → actual status** in tabular/monospace figures, with a plain-words reason.
- [x] 8.3 Severity tokens: Critical = danger + `‼` (heavier than an ordinary fail `✗`), Major = amber `✗`, Minor = muted `!`, pass = green `✓`. Every chip and the pill pair a **glyph with color** (never color-only).
- [x] 8.4 `response-panel.js`: added a `Negative (pass/total)` result tab in `show()` when `negative_result` is present, colored + glyphed by worst severity, body from the shared renderer.
- [x] 8.5 `collection-run-view.js` + `app.js` Runs modal: per-row `neg N/M` pill + grouped detail block via the shared renderer, matching where the `schema Δ N` pill appears.

## 9. UI — request-editor matrix + controls

- [x] 9.1 `request-editor-view.js`: added `'Negative'` to `SECTIONS` + `sectionMap`; section has the tri-state `negative_check` control (effective state + source), a category **segmented filter** (All / Input / Request / Injection), and a **Generate** button.
- [x] 9.2 Built the **matrix grid** (targets × subtypes) as a semantic table: **sticky-left** target column, **sticky-top** subtype headers each a bulk enable/disable toggle, grid in its own `overflow-x:auto` container, status/counts in tabular/monospace figures.
- [x] 9.3 **Five-state cell model** — not-applicable / disabled / ready / pass / fail — each a **glyph + color, never color alone**; expected status editable via a small inline number input per enabled cell; cell click toggles; column header bulk-toggles.
- [x] 9.4 States: **empty** shows a "Generate negative tests from this request" CTA + source line (spec-enriched when `field_constraints` exist); **ready** shows expected status neutrally; run shows a Running button state (sequential run, server-side).
- [x] 9.5 **Run negatives** action carries an environment badge ("Run negatives · DEV") once known; per-case outcomes render inline in the grid after a run.
- [x] 9.6 Destructive-run confirm modal: names the **active environment prominently**, lists mutating verbs + case count, danger **Run anyway** separated from **Cancel**, focus defaults to **Cancel**, `Esc`/backdrop dismiss.
- [x] 9.7 Included `negative_cases` + `negative_check` in `_buildPayload()`; regenerate merges by id, preserving user enabled/expected edits.
- [x] 9.8 `collection-detail-view.js`: added a "Negative" tab with an on/off default toggle writing `negative_check_default`, confirm-gated (master switch).

## 10. Report

- [x] 10.1 `cli/api_report.py`: selects + deserializes `negative_result`; added `_render_negative` mirroring `_render_schema_drift` (Critical findings band + category-grouped, severity-ranked, **false-pass highlighted**), a per-request `neg N/M` pill, and a **Negative** summary stat card.

## 11. Docs (maintenance rule)

- [x] 11.1 Created `docs/api-negative-testing-reference.md` in the style of `docs/api-schema-check-reference.md`: source-of-truth line, category taxonomy, case shape, generation (happy-path + OpenAPI enrichment), the fixed severity table, the `negative_result` verdict shape, every UI surface, CLI, sync mapping, and known limitations.
- [x] 11.2 Added a CLAUDE.md maintenance-rule bullet + feature summary tying negative-testing behavior to `docs/api-negative-testing-reference.md`, with the grep hint.

## 12. Master switch (collection default reset)

- [x] 12.1 `CollectionRepo.reset_negative_check_overrides` resets all request `negative_check` overrides in a collection to `inherit`; called from the collection PATCH route (with sync re-enqueue for changed requests) and confirm-gated in the collection Negative tab.

## 13. Verification

- [x] 13.1 Modules: ran `negative_gen.generate_cases` on a sample request → cases present per category; fed synthetic case-results to `negative_check.classify` → correct verdict + severity, false-pass detected.
- [x] 13.2 End-to-end engine + UI wiring: verified via a live stub-server run through `run_api_request` (mutated re-sends, false-pass→Critical, force-fail) and `run_negatives` (gate + result). JS syntax (`node --check`) and the shared renderer output (Critical band, false-pass, category groups, pill) verified functionally. (No live browser available in this environment; the response-panel Negative tab + matrix are wired and syntax-clean.)
- [x] 13.3 Collection + report: ran a collection with negatives on → `negative_result` persisted on `api_request_results`; the generated HTML report contains the Negative stat card + `neg N/M` pill + grouped detail.
- [x] 13.4 CLI/CI: `qaclan api negatives CreateUser --yes` exits 1 on a false-pass; without `--yes` a mutating-verb run exits 2 (confirm required).
- [x] 13.5 Safety: `run_negatives`/`plan_*_negatives` return `needs_confirm` + `mutating_methods` + `environment` for POST/PUT/DELETE cases; the collection run skips mutating negatives unless `confirm_destructive`. The editor confirm modal is wired (env named, focus on Cancel, Esc/backdrop dismiss).
- [x] 13.6 Inheritance + master switch: collection default on → an `inherit` request runs negatives; an `off` override wins; changing the collection default resets all overrides to `inherit`.
- [x] 13.7 `npx openspec validate add-negative-api-testing --strict` → valid.
