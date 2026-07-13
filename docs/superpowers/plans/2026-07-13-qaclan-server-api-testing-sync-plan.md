# qaclan-server: API Testing Sync Support — Migration + API Plan

> **Target repo:** `qaclan-server` (separate codebase from this one — the CLI/agent repo). This document is the implementation contract to hand to that repo. It is *not* a task-by-task TDD plan for subagent-driven-development in this repo, because the target repo, its ORM, and its test framework are not accessible from here. Each section below is a self-contained unit of work; implement and deploy in the order given (DB migration → push endpoints → pull/workspace changes → new pull-runs endpoints).

**Goal:** Extend qaclan-server's schema and sync API so the "API testing" feature (HTTP collections/folders/requests, collection-scoped variables, and collection run history) added to the CLI can be synced and shared across a team, without touching any existing table or endpoint behavior.

**Architecture:** Mirror the existing sync pattern exactly — one `cloud_<entity>` table per local entity, `cli_<entity>_id` + `cloud_id` upsert semantics, one `POST /api/sync/<entity>` + `DELETE /api/sync/<entity>/<cli_id>` pair per top-level entity, full-replace-list semantics for child collections (headers/vars/results), and additive fields on `GET /api/pull/workspace`. Team/user scoping stays implicit from the Bearer token — no `team_id`/`user_id` fields are ever read from client payloads.

**Tech Stack:** Whatever qaclan-server currently runs (Postgres-flavored SQL per the existing schema — `VARCHAR(36)` UUIDs, `TIMESTAMP`, `JSON` columns). DDL below uses that dialect. Adjust column type spelling only if the target ORM requires it — do not change names, nullability, or constraints.

## Global Constraints

- Every new table follows the existing `cloud_*` naming and column conventions: `id VARCHAR(36) PRIMARY KEY`, a `cli_<entity>_id VARCHAR(255) NOT NULL` client-supplied id, `user_id VARCHAR(36) NOT NULL REFERENCES users(id)`, `team_id VARCHAR(36) REFERENCES teams(id)` (nullable — same as `cloud_projects`/`cloud_features`/etc.), `synced_at TIMESTAMP NOT NULL`, and where the local table has an `updated_at`, an `updated_at TIMESTAMP` here too.
- Upsert identity for every entity that supports it: `UNIQUE (cli_<entity>_id, user_id)` — identical to `cloud_scripts`, `cloud_suites`, etc. Do not use `cloud_id` alone as the unique key (client sends `cloud_id = NULL` on first sync).
- `team_id` and `user_id` are **never** read from the request body — they are resolved server-side from the authenticated user's Bearer token / active team context, exactly like every existing `/api/sync/*` endpoint. Do not add a `team_id` or `user_id` field to any request JSON schema below.
- All parent-reference fields in push payloads (`project_id`, `feature_id`, `collection_id`, `folder_id`, `collection_run_id`, `run_id`) are **cloud ids**, not CLI-local ids — the client resolves local→cloud before sending, exactly as it already does for `sync_script`'s `suite_id`/`feature_id`/`project_id`.
- No existing table gets an `ALTER TABLE`. No existing endpoint's request/response shape loses a field or changes a type — only new optional fields are added (see the `/api/sync/run` and `/api/pull/runs/<run_id>` changes below).
- `api_doc_entries` is **not client-pushed**. It is a server-computed, team-wide cache derived from `cloud_api_requests` — see Section 1's `cloud_api_doc_entries` table and the regeneration trigger in Section 2.5. This avoids syncing a client-computed aggregate (which would conflict across teammates' differently-scoped local merges) while still giving the team one canonical shared view once `api_requests` sync (the real source of truth).
- One feature stays explicitly **out of scope** — do not build sync support for it:
  - "captured requests" (`docs/superpowers/plans/2026-07-11-api-script-run-capture-plan.md`'s `script_runs.captured_requests` column) — designed but not implemented in the local CLI schema yet (`git log` on `cli/db.py` confirms no such migration exists). Nothing to sync until that ships locally.
- Run-status notifications (`docs/superpowers/plans/2026-07-13-collection-run-status-notifications.md`) are pure client-side polling UI over existing/new run tables — no schema or endpoint impact beyond what's already listed here.

---

## Section 1 — Database Migration

New tables, in FK-safe creation order. Nothing here touches the 15 existing tables.

```sql
-- 1. Top-level HTTP collection container (peer of cloud_suites, scoped to a project)
CREATE TABLE cloud_api_collections (
    id VARCHAR(36) PRIMARY KEY,
    cli_collection_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    team_id VARCHAR(36) REFERENCES teams(id),
    project_id VARCHAR(36) NOT NULL REFERENCES cloud_projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    env_name VARCHAR(255),
    auth_type VARCHAR(32) NOT NULL DEFAULT 'none',
    auth_config JSON NOT NULL DEFAULT '{}',
    order_index INTEGER NOT NULL DEFAULT 0,
    synced_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    UNIQUE (cli_collection_id, user_id)
);

-- 2. Nested folder tree inside a collection (unlimited depth, self-referencing)
CREATE TABLE cloud_api_folders (
    id VARCHAR(36) PRIMARY KEY,
    cli_folder_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    team_id VARCHAR(36) REFERENCES teams(id),
    project_id VARCHAR(36) NOT NULL REFERENCES cloud_projects(id) ON DELETE CASCADE,
    collection_id VARCHAR(36) NOT NULL REFERENCES cloud_api_collections(id) ON DELETE CASCADE,
    parent_folder_id VARCHAR(36) REFERENCES cloud_api_folders(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    synced_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    UNIQUE (cli_folder_id, user_id)
);
CREATE INDEX idx_cloud_api_folders_collection ON cloud_api_folders(collection_id, parent_folder_id);

-- 3. The HTTP request definition itself (peer of cloud_scripts)
CREATE TABLE cloud_api_requests (
    id VARCHAR(36) PRIMARY KEY,
    cli_request_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    team_id VARCHAR(36) REFERENCES teams(id),
    project_id VARCHAR(36) NOT NULL REFERENCES cloud_projects(id) ON DELETE CASCADE,
    feature_id VARCHAR(36) REFERENCES cloud_features(id) ON DELETE SET NULL,
    collection_id VARCHAR(36) REFERENCES cloud_api_collections(id) ON DELETE SET NULL,
    folder_id VARCHAR(36) REFERENCES cloud_api_folders(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL DEFAULT 0,
    name VARCHAR(255) NOT NULL,
    method VARCHAR(16) NOT NULL DEFAULT 'GET',
    url TEXT NOT NULL,
    headers JSON NOT NULL DEFAULT '[]',
    params JSON NOT NULL DEFAULT '[]',
    path_params JSON NOT NULL DEFAULT '[]',
    body_type VARCHAR(32),
    body TEXT,
    auth_type VARCHAR(32) NOT NULL DEFAULT 'none',
    auth_config JSON NOT NULL DEFAULT '{}',
    pre_script TEXT,
    pre_lang VARCHAR(16) DEFAULT 'js',
    pre_extractor JSON,
    post_script TEXT,
    post_lang VARCHAR(16) DEFAULT 'js',
    post_extractor JSON,
    request_schema JSON,
    response_schema JSON,
    assertions JSON NOT NULL DEFAULT '[]',
    follow_redirects BOOLEAN DEFAULT TRUE,
    timeout_ms INTEGER DEFAULT 30000,
    include_in_docs BOOLEAN DEFAULT TRUE,
    synced_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    UNIQUE (cli_request_id, user_id)
);
CREATE INDEX idx_cloud_api_requests_project ON cloud_api_requests(project_id);
CREATE INDEX idx_cloud_api_requests_collection ON cloud_api_requests(collection_id, folder_id);

-- 4. Server-computed API docs cache — NEVER written directly from a client push. Regenerated as a
--    side effect of POST /api/sync/api-request (see Section 2.5) by re-running the merge over every
--    cloud_api_requests row that shares (project_id, method, path_pattern). One row = one team-wide
--    canonical doc entry for that endpoint, aggregating everyone's synced requests, not just one
--    client's local view.
CREATE TABLE cloud_api_doc_entries (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES cloud_projects(id) ON DELETE CASCADE,
    team_id VARCHAR(36) REFERENCES teams(id),
    method VARCHAR(16) NOT NULL,
    path_pattern TEXT NOT NULL,
    description TEXT,
    request_schema JSON,
    response_schema JSON,
    headers_schema JSON,
    params_schema JSON,
    source_request_ids JSON NOT NULL DEFAULT '[]',
    include_in_docs BOOLEAN DEFAULT TRUE,
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    UNIQUE (project_id, method, path_pattern)
);

-- 5. Collection-scoped variables (peer of cloud_env_vars, full-replace-list semantics)
CREATE TABLE cloud_collection_vars (
    id VARCHAR(36) PRIMARY KEY,
    collection_id VARCHAR(36) NOT NULL REFERENCES cloud_api_collections(id) ON DELETE CASCADE,
    key VARCHAR(255) NOT NULL,
    initial_value TEXT NOT NULL DEFAULT '',
    synced_at TIMESTAMP NOT NULL,
    UNIQUE (collection_id, key)
);

-- 6. Variant library examples (Phase 2 — optional, reference/docs data only, not used by runs)
CREATE TABLE cloud_api_request_examples (
    id VARCHAR(36) PRIMARY KEY,
    cli_example_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    team_id VARCHAR(36) REFERENCES teams(id),
    request_id VARCHAR(36) NOT NULL REFERENCES cloud_api_requests(id) ON DELETE CASCADE,
    label VARCHAR(255) NOT NULL,
    params JSON NOT NULL DEFAULT '[]',
    body TEXT,
    response_status INTEGER,
    response_headers JSON,
    response_body TEXT,
    synced_at TIMESTAMP NOT NULL,
    UNIQUE (cli_example_id, user_id)
);

-- 7. Standalone collection-run history (peer of cloud_runs, run header)
CREATE TABLE cloud_api_collection_runs (
    id VARCHAR(36) PRIMARY KEY,
    cli_collection_run_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    team_id VARCHAR(36) REFERENCES teams(id),
    collection_id VARCHAR(36) NOT NULL REFERENCES cloud_api_collections(id) ON DELETE CASCADE,
    collection_name VARCHAR(255) NOT NULL,
    env_name VARCHAR(255),
    status VARCHAR(50) NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    synced_at TIMESTAMP NOT NULL
);

-- 8. Per-request result row for a collection run (peer of cloud_script_results)
CREATE TABLE cloud_api_request_results (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES cloud_api_collection_runs(id) ON DELETE CASCADE,
    cli_request_id VARCHAR(255) NOT NULL,
    request_name VARCHAR(255) NOT NULL,
    method VARCHAR(16),
    url TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    status_code INTEGER,
    duration_ms INTEGER,
    response_body TEXT,
    response_headers JSON,
    assertion_results JSON,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
CREATE INDEX idx_cloud_api_request_results_run ON cloud_api_request_results(run_id);

-- 9. API results interleaved into a MIXED (E2E + API) suite run — sibling of cloud_script_results,
--    referencing the SAME cloud_runs row, not a new run header. Purely additive: cloud_runs and
--    cloud_script_results are untouched.
CREATE TABLE cloud_run_api_results (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES cloud_runs(id) ON DELETE CASCADE,
    cli_request_id VARCHAR(255) NOT NULL,
    request_name VARCHAR(255) NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    status_code INTEGER,
    duration_ms INTEGER,
    response_body TEXT,
    response_headers JSON,
    assertion_results JSON,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
CREATE INDEX idx_cloud_run_api_results_run ON cloud_run_api_results(run_id);
```

**Why a sibling table (`cloud_run_api_results`) instead of extending `cloud_script_results`:** a mixed suite orders scripts and API requests together via `order_index` (local `suite_items.item_type` discriminates). Adding ~15 nullable API-only columns to `cloud_script_results` would bloat an existing, working table for every non-API-testing user. A sibling table keyed by the same `run_id` reproduces the interleaving (both tables carry `order_index`; the consumer merge-sorts by it) with zero risk to the existing table.

**Rollout:** plain additive migration, no backfill needed (all-new tables, no data to migrate). Safe to run against a live DB with no downtime.

---

## Section 2 — Push API (new/changed `/api/sync/*` endpoints)

Same shape/pattern as the existing endpoints (`sync_project` → `POST /api/sync/project`, etc., defined in `cli/api.py` on the client side). Auth: `Authorization: Bearer <auth_key>` header only, same as every existing sync call — no `team_id`/`user_id` in any body below.

### 2.1 `POST /api/sync/api-collection`

Request:
```json
{
  "cli_collection_id": "apicol_abc123",
  "cloud_id": null,
  "name": "Billing API",
  "description": "Endpoints for the billing service",
  "env_name": "staging",
  "auth_type": "bearer",
  "auth_config": {"token": "{{authToken}}"},
  "order_index": 0,
  "project_id": "<cloud project uuid, required>"
}
```
Response: `{"id": "<cloud_id>"}`
Upsert key: `(cli_collection_id, user_id)`. `project_id` must already be a synced `cloud_projects.id` — if the client hasn't synced the parent project yet, reject with 400 (client is responsible for ensure-parent-first, exactly like `_ensure_project_synced` does today).

### 2.2 `DELETE /api/sync/api-collection/<cli_collection_id>`
No body. Cascades to folders/requests/collection_vars/collection_runs via FK `ON DELETE CASCADE` (matches how `delete_script`/`delete_suite` behave today).

### 2.3 `POST /api/sync/api-folder`

Request:
```json
{
  "cli_folder_id": "apifold_def456",
  "cloud_id": null,
  "name": "Invoices",
  "order_index": 1,
  "project_id": "<cloud project uuid, required>",
  "collection_id": "<cloud collection uuid, required>",
  "parent_folder_id": null
}
```
Response: `{"id": "<cloud_id>"}`
Upsert key: `(cli_folder_id, user_id)`. `parent_folder_id`, when non-null, must resolve to a `cloud_api_folders.id` already owned by the same `collection_id`.

### 2.4 `DELETE /api/sync/api-folder/<cli_folder_id>`
Cascades to sub-folders and requests.

### 2.5 `POST /api/sync/api-request`

Request:
```json
{
  "cli_request_id": "apireq_ghi789",
  "cloud_id": null,
  "name": "Create invoice",
  "method": "POST",
  "url": "{{baseUrl}}/invoices",
  "headers": [{"key": "Content-Type", "value": "application/json", "enabled": true}],
  "params": [],
  "path_params": [],
  "body_type": "raw",
  "body": "{\"amount\": 100}",
  "auth_type": "inherit",
  "auth_config": {},
  "pre_script": null,
  "pre_lang": "js",
  "pre_extractor": null,
  "post_script": "qc.test('status is 201', () => qc.expect(qc.response.status).toBe(201));",
  "post_lang": "js",
  "post_extractor": [{"name": "invoiceId", "path": "$.id", "prefix": ""}],
  "request_schema": null,
  "response_schema": null,
  "assertions": [{"type": "status", "op": "eq", "value": 201}],
  "follow_redirects": true,
  "timeout_ms": 30000,
  "include_in_docs": true,
  "order_index": 0,
  "project_id": "<cloud project uuid, required>",
  "feature_id": null,
  "collection_id": "<cloud collection uuid, optional>",
  "folder_id": "<cloud folder uuid, optional>"
}
```
Response: `{"id": "<cloud_id>"}`
Upsert key: `(cli_request_id, user_id)`. Same as `sync_script`: `feature_id`/`collection_id`/`folder_id` are only attached by the client if those parents already have a `cloud_id` — treat all three as optional/nullable server-side.

**Side effect — docs regeneration:** after the upsert commits, if `include_in_docs` is true, recompute `path_pattern` for this request's `url` (using its `path_params`, the same normalization the CLI's own doc-generation code applies — port that exact function from the CLI's docs feature rather than re-deriving it, to keep patterns comparable) and re-run the schema merge over every `cloud_api_requests` row sharing `(project_id, method, path_pattern)` and `include_in_docs = true`. Upsert the result into `cloud_api_doc_entries` keyed by `(project_id, method, path_pattern)`: set `request_schema`/`response_schema`/`headers_schema`/`params_schema` from the merge, `source_request_ids` to the contributing request ids, `last_seen_at` to now, `first_seen_at` only on first insert. Do this synchronously in the same transaction (dataset is per-endpoint, not team-wide, so cost is bounded) or fire-and-forget async — either is acceptable since `cloud_api_doc_entries` is a read cache, not a source of truth.

### 2.6 `DELETE /api/sync/api-request/<cli_request_id>`
Cascades to `cloud_api_request_examples`. **Side effect:** re-run the same docs regeneration for the deleted request's `(project_id, method, path_pattern)` — if no `cloud_api_requests` rows remain matching that key, delete the `cloud_api_doc_entries` row; otherwise re-merge over what's left.

### 2.7 `POST /api/sync/collection-vars`
Full-replace-list, same pattern as `sync_env_vars`.

Request:
```json
{
  "cli_collection_id": "apicol_abc123",
  "cloud_collection_id": "<cloud collection uuid>",
  "vars": [{"key": "baseUrl", "initial_value": "https://staging.example.com"}]
}
```
Response: `{"ok": true}`
Server behavior: delete all `cloud_collection_vars` rows for `collection_id` not present in `vars`, upsert the rest by `(collection_id, key)` — identical semantics to how `sync_env_vars` fully replaces `env_vars` for one environment.

### 2.8 `POST /api/sync/api-request-example` (Phase 2 — optional)

Request:
```json
{
  "cli_example_id": "apiex_jkl012",
  "cloud_id": null,
  "request_id": "<cloud request uuid, required>",
  "label": "sort=date",
  "params": [{"key": "sort", "value": "date", "enabled": true}],
  "body": null,
  "response_status": 200,
  "response_headers": {"content-type": "application/json"},
  "response_body": "{\"items\": []}"
}
```
Response: `{"id": "<cloud_id>"}`
Upsert key: `(cli_example_id, user_id)`.

### 2.9 `DELETE /api/sync/api-request-example/<cli_example_id>` (Phase 2 — optional)

### 2.10 `POST /api/sync/api-collection-run`
Append-only history write, same pattern as `sync_run` — no delete endpoint (matches: runs are never deleted individually today).

Request:
```json
{
  "cli_collection_run_id": "apirun_mno345",
  "collection_id": "<cloud collection uuid, required>",
  "collection_name": "Billing API",
  "env_name": "staging",
  "status": "passed",
  "total": 5,
  "passed": 5,
  "failed": 0,
  "error_count": 0,
  "started_at": "2026-07-13T10:00:00Z",
  "completed_at": "2026-07-13T10:00:04Z",
  "duration_ms": 4210,
  "request_results": [
    {
      "cli_request_id": "apireq_ghi789",
      "request_name": "Create invoice",
      "method": "POST",
      "url": "https://staging.example.com/invoices",
      "order_index": 0,
      "status": "passed",
      "status_code": 201,
      "duration_ms": 812,
      "response_body": "{\"id\": \"inv_1\"}",
      "response_headers": {"content-type": "application/json"},
      "assertion_results": [{"type": "status", "op": "eq", "value": 201, "passed": true, "actual": 201}],
      "error_message": null,
      "started_at": "2026-07-13T10:00:00Z",
      "finished_at": "2026-07-13T10:00:00.812Z"
    }
  ]
}
```
Response: `{"id": "<cloud_id>"}`
Server: like `sync_run`, ensure the parent collection is resolvable (reject 400 if `collection_id` doesn't map to an existing `cloud_api_collections` row), insert one `cloud_api_collection_runs` row plus N `cloud_api_request_results` rows in the same transaction.

### 2.11 `POST /api/sync/run` — additive change only

Add one **optional** field to the existing request schema, `api_results`, alongside the existing `script_results`. Do not rename or remove `script_results`.

```json
{
  "run_id": "...",
  "suite_id": "...",
  "status": "passed",
  "started_at": "...",
  "completed_at": "...",
  "duration_ms": 1234,
  "script_results": [ /* unchanged */ ],
  "api_results": [
    {
      "cli_request_id": "apireq_ghi789",
      "request_name": "Create invoice",
      "order_index": 2,
      "status": "passed",
      "status_code": 201,
      "duration_ms": 812,
      "response_body": "...",
      "response_headers": {"content-type": "application/json"},
      "assertion_results": [ /* ... */ ],
      "error_message": null,
      "started_at": "...",
      "finished_at": "..."
    }
  ],
  "browser": "chromium",
  "resolution": "1280x720",
  "headless": true
}
```
Server: when `api_results` is present (and non-empty), insert matching rows into `cloud_run_api_results` with the same `run_id` as the `cloud_runs` row created/updated in this same call. When absent, behave exactly as today — this keeps every existing non-API-testing client working unmodified.

---

## Section 3 — Pull API (`GET /api/pull/workspace`) changes

Add four new keys to the existing response object. Every existing key (`projects`, `features`, `scripts`, `environments`, `env_vars`, `suites`, `suite_items`) is untouched — this is a pure addition.

```json
{
  "projects": [ /* unchanged */ ],
  "features": [ /* unchanged */ ],
  "scripts": [ /* unchanged */ ],
  "environments": [ /* unchanged */ ],
  "env_vars": [ /* unchanged */ ],
  "suites": [ /* unchanged */ ],
  "suite_items": [ /* unchanged */ ],

  "api_collections": [
    {
      "id": "<cloud collection uuid>",
      "name": "Billing API",
      "description": "Endpoints for the billing service",
      "env_name": "staging",
      "auth_type": "bearer",
      "auth_config": {"token": "{{authToken}}"},
      "order_index": 0,
      "project_id": "<cloud project uuid>",
      "updated_at": "2026-07-13T09:00:00Z"
    }
  ],
  "api_folders": [
    {
      "id": "<cloud folder uuid>",
      "name": "Invoices",
      "order_index": 1,
      "collection_id": "<cloud collection uuid>",
      "parent_folder_id": null,
      "updated_at": "2026-07-13T09:00:00Z"
    }
  ],
  "api_requests": [
    {
      "id": "<cloud request uuid>",
      "name": "Create invoice",
      "method": "POST",
      "url": "{{baseUrl}}/invoices",
      "headers": [ /* ... */ ],
      "params": [],
      "path_params": [],
      "body_type": "raw",
      "body": "{\"amount\": 100}",
      "auth_type": "inherit",
      "auth_config": {},
      "pre_script": null,
      "pre_lang": "js",
      "pre_extractor": null,
      "post_script": "...",
      "post_lang": "js",
      "post_extractor": [ /* ... */ ],
      "request_schema": null,
      "response_schema": null,
      "assertions": [ /* ... */ ],
      "follow_redirects": true,
      "timeout_ms": 30000,
      "include_in_docs": true,
      "order_index": 0,
      "project_id": "<cloud project uuid>",
      "feature_id": null,
      "collection_id": "<cloud collection uuid>",
      "folder_id": "<cloud folder uuid or null>",
      "updated_at": "2026-07-13T09:00:00Z"
    }
  ],
  "collection_vars": [
    {"collection_id": "<cloud collection uuid>", "key": "baseUrl", "initial_value": "https://staging.example.com"}
  ]
}
```

Field-resolution rule for the client (mirrors how `project_id` on `features`/`scripts`/`suites` already works): every parent-reference field here (`project_id`, `feature_id`, `collection_id`, `folder_id`, `parent_folder_id`) is a **cloud id** — the pulling client resolves it to a local id via the same kind of `*_map` dict it already builds for `project_map`/`feature_map`/`script_map`/etc.

**Client-side merge order** (for the companion CLI change, informational — see Section 5): insert `api_collections` right after `features` (only needs `project_id` resolved), then `api_folders` (needs `collection_id` resolved, self-referential so parent folders must be inserted before child folders — sort by depth or retry-on-FK-miss), then `api_requests` (needs `project_id`/`feature_id`/`collection_id`/`folder_id`), then `collection_vars` (needs `collection_id`). This slots between the existing `scripts` and `environments` steps, or after `suite_items` — either position works since none of the new entities are referenced by the existing ones.

### 3.1 `GET /api/pull/runs` and `GET /api/pull/runs/<run_id>` — additive change

`GET /api/pull/runs` (paginated list) is unchanged.

`GET /api/pull/runs/<run_id>` (single mixed-suite-run detail) gains one new optional array, `api_results`, alongside the existing per-script results — same shape as the `api_results` sent in `POST /api/sync/run` (Section 2.11). Omit the key (or send `[]`) for runs that have no API items, so existing non-API-testing consumers see no change.

### 3.2 New: `GET /api/pull/api-runs` and `GET /api/pull/api-runs/<run_id>`

Standalone collection-run history, parallel to `pull_runs`/`pull_run_detail`.

`GET /api/pull/api-runs?page=1&per_page=50` — response:
```json
{
  "runs": [
    {
      "id": "<cloud run uuid>",
      "collection_id": "<cloud collection uuid>",
      "collection_name": "Billing API",
      "env_name": "staging",
      "status": "passed",
      "total": 5, "passed": 5, "failed": 0, "error_count": 0,
      "started_at": "...", "completed_at": "...", "duration_ms": 4210
    }
  ],
  "page": 1, "per_page": 50, "total": 12
}
```

`GET /api/pull/api-runs/<run_id>` — response: the run header fields above plus `"request_results": [ /* same shape as POST /api/sync/api-collection-run's request_results */ ]`.

### 3.3 New: `GET /api/pull/api-docs?project_id=<cloud_project_id>`

Read-only access to the server-computed doc cache (Section 1, table 4). Deliberately **not** folded into `GET /api/pull/workspace` — doc entries carry full schema-tree JSON blobs per endpoint and are viewed per-project (a "Docs" tab), not needed on every general workspace sync, so keeping it a separate on-demand call keeps the workspace payload light for teams with large APIs.

Response:
```json
{
  "doc_entries": [
    {
      "id": "<cloud doc entry uuid>",
      "method": "POST",
      "path_pattern": "/invoices",
      "description": null,
      "request_schema": { /* merged type tree */ },
      "response_schema": { /* merged type tree */ },
      "headers_schema": null,
      "params_schema": null,
      "source_request_ids": ["<cloud request uuid>", "..."],
      "include_in_docs": true,
      "first_seen_at": "2026-07-01T12:00:00Z",
      "last_seen_at": "2026-07-13T09:00:00Z"
    }
  ]
}
```
`source_request_ids` are cloud ids — the client maps them back to local `api_requests` via its `script_map`-style cloud→local table for that entity, same as every other pulled list. This endpoint is purely additive; nothing consumes it until the companion CLI change (Section 5) adds a client for it.

---

## Section 4 — Compatibility Checklist

- [ ] No existing table gets `ALTER TABLE` — verify by diffing the migration against the 15 tables in the current schema dump.
- [ ] No existing endpoint's request schema drops or renames a field — `POST /api/sync/run` and `GET /api/pull/runs/<run_id>` only gain new **optional** fields (`api_results`); every other endpoint listed in Section 2/3 is entirely new.
- [ ] `GET /api/pull/workspace` for a team with zero API-testing data returns the four new keys as empty arrays (`[]`), not omitted — so existing non-API-testing clients that don't read those keys are unaffected, and future clients don't need an `undefined` check.
- [ ] Every new table's `team_id`/`user_id` is set server-side from the auth context, never trusted from the client body.
- [ ] Cascade deletes verified: deleting a `cloud_api_collections` row removes its folders, requests, collection_vars, and collection_runs (and each request's examples) — confirm with a manual `DELETE` + row-count check after seeding one of each.
- [ ] `cloud_api_doc_entries` never appears as a writable field in any `POST` request body in this plan — confirm no endpoint accepts client-supplied `request_schema`/`response_schema`/etc. for a doc entry directly; it is written exclusively by the regeneration side effect in 2.5/2.6.

---

## Section 5 — Out of scope: companion CLI-side work (this repo, not qaclan-server)

Not part of this plan's deliverable (server-side only, per the request), but noted so the two sides land in a compatible order:

- `cli/db.py`: add `cloud_id TEXT` to `api_collections`, `api_folders`, `api_requests` (via a new `_migrate_*` function, following the existing `try/except: pass` idempotent `ALTER TABLE` pattern). `collection_vars`/`api_collection_runs`/`api_request_results` don't need `cloud_id` (full-replace / append-only, matching how `env_vars` has none today).
- `cli/api.py`: add client functions for every endpoint in Section 2/3 (`sync_api_collection`, `sync_api_folder`, `sync_api_request`, `sync_collection_vars`, `sync_api_collection_run`, `delete_api_collection`, `delete_api_folder`, `delete_api_request`, `pull_api_runs`, `pull_api_run_detail`), matching the existing function signatures in style.
- `cli/sync.py`: add `sync_api_collection_to_cloud`, `sync_api_folder_to_cloud`, `sync_api_request_to_cloud`, `sync_collection_vars_to_cloud`, `sync_api_collection_run_to_cloud`, each doing lazy-parent-ensure the same way `sync_feature_to_cloud`/`sync_script_to_cloud` do today.
- `cli/sync_queue.py`: extend `ENTITY_ORDER` to insert `api_collection`, `api_folder`, `api_request`, `collection_vars` after `script` and before `environment` (collections/folders/requests only depend on project+feature, same dependency depth as scripts).
- `cli/commands/pull.py`: extend `pull_workspace()` with the merge steps described in Section 3's "Client-side merge order" note, building `collection_map`/`folder_map` alongside the existing `project_map`/`feature_map`/`script_map`.
- Existing `sync_run_to_cloud`'s suite-run payload needs to also gather `api_runs` rows (joined with `api_requests` for names) into the new `api_results` array when the suite mixes item types.
- Optional: a `pull_api_docs(project_id)` client call against `GET /api/pull/api-docs` (Section 3.3) that merges the team-wide computed entries into the local `api_doc_entries` table — this lets a user see doc coverage contributed by teammates' synced requests, not just their own. Since local `api_doc_entries` already regenerates itself locally from local requests, treat pulled entries as informational overlay (e.g. merge by `(method, path_pattern)`, keep the richer/more-recent `last_seen_at` schema) rather than clobbering the user's own live-regenerated local view.

This should be a separate plan/PR in this repo, implemented only after the qaclan-server endpoints in Sections 2–3 are live (client changes are backward-compatible to add at any time since they only start firing new HTTP calls, but must target endpoints that exist).
