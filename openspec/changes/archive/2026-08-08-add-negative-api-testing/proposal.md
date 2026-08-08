## Why

QAClan tests only the **happy path**. A request carries `assertions[]`, pre/post scripts, and an opt-in response-schema drift check — all of which confirm the API works when given good input. Nothing verifies the API **rejects bad input correctly**: the right 4xx status, a consistent error shape, no `500`, no data leak, and no unintended write. That "unhappy path" is where real defects and security issues live (OWASP API Top 10 is dominated by it). Existing tools force a bad trade-off — Postman/REST Assured make you hand-author and maintain every negative case one by one, while schema fuzzers auto-generate but flood you with false positives and create junk state until teams stop trusting them. The runner already has everything needed to do better: a resolved-request pipeline (`cli/api_runner.py`), an assertion engine (`_evaluate_assertions`/`_compare`), an OpenAPI importer (`cli/api_discovery/openapi_parser.py`), and a proven "verdict object on the result row + one shared renderer" pattern from the schema-check slice.

## What Changes

- Add an opt-in **negative API testing** capability per request. From a single happy-path request the tool **auto-generates** negative cases across three categories and runs each as a mutated send that asserts a correct rejection.
  - **Input validation** — per field: missing-required, wrong-type, null, empty, boundary (min/max, length), enum-violation, format-violation; plus body-level malformed-JSON, oversized, and extra-unexpected-field.
  - **Request-level mutators** — no / garbage / expired auth token, wrong HTTP method, wrong or missing `Content-Type`, unknown route.
  - **Injection / security fuzz** — a curated SQLi / XSS / path-traversal / unicode / null-byte payload pack per string field, asserting **no `500`** and **not reflected**.
- **Auto-generation from what the user already has.** Cases are inferred from the resolved request body/params/path-params/auth (works for any request — HAR import, OpenAPI import, or a manual send) and **enriched by OpenAPI constraints** when the request came from a spec, for exact boundary and true enum-violation cases. Every generated case is a first-class, **editable** object, never a black box.
- **Expected-rejection contract per case.** Each case carries a smart-default expected status (401 no-auth, 415 bad content-type, 400/422 validation, 405 wrong method) evaluated through the existing assertion engine, with a per-endpoint override.
- **Severity-based verdict with false-pass as the headline signal.** The single most important outcome — the API returned `2xx` to invalid input (accepted bad data) — is classified **Critical** and surfaced prominently, not buried as a normal failure. Fixed severity mapping: Critical (false-pass / injection reflected / `500` on fuzz), Major (`5xx` crash on a validation case / wrong status family), Minor (wrong specific code / inconsistent error schema / missing `Allow`·`Retry-After`).
- **Inheritance model for enablement** (mirrors schema-check): a collection carries `negative_check_default` (on/off); each request carries a tri-state override (`inherit` / `on` / `off`); resolved at run time with no cascade writes.
- **Interactive matrix UI.** A new **Negative** tab in the request editor with a fields × mutation grid: Generate, toggle a cell, bulk-select a column, edit a cell's expected status, run, and see pass/fail heat inline.
- **Category + severity reporting on both surfaces.** Negatives fold into collection runs; the response panel, collection-run view, Runs history modal, and the downloadable HTML report all show a `neg N/M` pill and a category-grouped, severity-ranked detail with false-pass highlighted. A headless CLI/CI path returns a **severity-gated exit code** (non-zero on Critical/Major).
- **Safety gate.** A run that fires mutating verbs (POST/PUT/DELETE) requires an explicit confirm and surfaces the active environment — so injection payloads and bad writes cannot silently hit production.
- **Persistence, sync, docs.** A `negative_result` verdict is stored on per-run result rows and synced best-effort like `schema_drift`. A new `docs/api-negative-testing-reference.md` becomes the syntax source of truth under the same maintenance-rule convention as the assertions/script/schema-check docs.
- **Deferred to v2 (out of scope here):** the stateful/relational tier — Authz/BOLA (multi-identity + resource-ownership + ID-swap), state/conflict `409` (duplicate / operate-on-deleted / idempotency), and rate-limit `429` (burst). Each needs sequences, identities, or bursts — a distinct infra lift on top of this stateless-mutation foundation.
- No new Python/JS dependencies; built on the existing httpx pipeline, assertion engine, and OpenAPI parser.

## Capabilities

### New Capabilities

- `api-negative-testing`: Opt-in, per-request (with collection-default inheritance) auto-generated negative API testing across input-validation, request-level, and injection/fuzz categories. Generates editable negative cases from a happy-path request (enriched by OpenAPI constraints when present), runs each mutated send against an expected-rejection contract, classifies a severity-based verdict with false-pass flagged Critical, surfaces results in a request-editor matrix UI plus collection-run/report/CLI-CI, guards mutating runs behind an environment-aware confirm, and persists/syncs the verdict in run history.

### Modified Capabilities

<!-- None. openspec/specs/ is empty (no committed main specs yet); this introduces a new, separate spec for negative-testing behavior and does not change the requirements of the existing api-response-schema-check capability. -->

## Impact

- **Data model** (`cli/db.py`, idempotent `_migrate_*` migrations): new `api_requests.negative_cases` (TEXT JSON), `api_requests.negative_check` (TEXT tri-state), `api_requests.field_constraints` (TEXT JSON, OpenAPI constraints captured at import); new `api_collections.negative_check_default` (TEXT); new `negative_result` (TEXT) on both `api_request_results` and `api_runs`.
- **New pure logic** (mirrors `schema_infer`/`schema_diff`): `cli/negative_gen.py` (`generate_cases`, `diff_cases`, curated injection payload pack) and `cli/negative_check.py` (`classify` → fixed-shape verdict + severity mapping).
- **Runner** (`cli/api_runner.py`, `web/api/services/runner_service.py`): thread `negative_enabled` + resolved cases through `run_api_request`; loop enabled cases as mutated sends evaluated via the existing assertion engine; attach `negative_result`; force-fail on Critical/Major; add `_resolve_negative_check` and enforce the safety gate.
- **Generation enrichment** (`cli/api_discovery/openapi_parser.py`): keep raw per-field constraints (`required`/`enum`/`minimum`·`maximum`/`format`/`pattern`) alongside the example and persist them to `field_constraints`.
- **Repositories** (`web/api/repositories/request_repo.py`, `collection_repo.py`, `collection_run_repo.py`, `api_run_repo.py`): serialize/deserialize the new columns; accept them in create/update whitelists; add `reset_negative_check_overrides` mirroring the schema-check reset.
- **Routes** (`web/api/routes/requests.py`, `collections.py`): a run-negatives path and the confirm parameter.
- **UI** (`web/static/api/views/request-editor-view.js`, `collection-detail-view.js`, `collection-run-view.js`; `web/static/api/components/response-panel.js`; new shared renderer `web/static/api/components/negative-view.js`; `web/static/app.js`; `web/static/index.html`): Negative tab + matrix grid + tri-state control + safety-confirm modal, a Negative result tab, per-row `neg N/M` pills and grouped detail everywhere the schema-drift pill appears.
- **HTML report** (`cli/api_report.py`): per-request `neg N/M` pill, grouped severity detail with false-pass highlighted, and a Negative summary stat card.
- **CLI** (`cli/commands/api_cmd.py`): headless negatives run with a severity-gated exit code and a `--yes`/`--confirm-destructive` flag.
- **Sync** (`cli/sync.py`, `cli/commands/pull.py`): carry `negative_cases`/`negative_check` (request), `negative_check_default` (collection), and `negative_result` (run results) best-effort.
- **Docs**: new `docs/api-negative-testing-reference.md` + a maintenance-rule bullet in `CLAUDE.md`.
- No new dependencies. Fully local-first; negative data syncs best-effort like existing schema columns.
