# Client-Side API Testing Sync — Design

**Companion doc:** `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` (the qaclan-server-side DB migration + API contract this design implements against). Every endpoint/payload shape referenced below is defined there — this doc does not redefine them, it wires this repo (the CLI/agent) to call them.

## Purpose

The API-testing feature (HTTP collections, nested folders, requests, collection-scoped variables, variant library, and run history) is fully implemented locally but has never been wired into cloud sync — none of its tables have a `cloud_id` column, and none of `cli/sync.py`/`cli/api.py`/`cli/sync_queue.py`/`cli/commands/pull.py` know these tables exist. This design adds that wiring, entity by entity, following the exact pattern already used for `projects`/`features`/`suites`/`scripts`/`environments`.

## Scope

In scope (per user decision — "everything now"):
- Push + pull: `api_collections`, `api_folders`, `api_requests`, `collection_vars`
- Push + pull: `api_request_examples` (variant library)
- Push + on-demand pull: `api_collection_runs` + `api_request_results` (standalone collection-run history)
- Push only (folded into existing suite-run sync), on-demand pull: `api_runs` (mixed E2E+API suite results)
- On-demand pull only: server-computed `api_doc_entries` cache (never pushed — see server plan Section 2.5)

Out of scope (unchanged from the server plan): `script_runs.captured_requests` (not implemented locally at all yet).

## Architecture

Extend the existing generic sync machinery — no new queue, no new worker, no new UI trigger. The existing `#btn-push`/`#btn-pull` buttons (`web/static/app.js:452-486`) already call `POST /api/sync/push` and `POST /api/sync/pull`; once the new entity types are registered in `cli/sync_queue.py`'s `ENTITY_ORDER` and `cli/commands/pull.py`'s merge loop, those same buttons carry the new data with zero UI changes.

Data flow, per entity, matches every existing entity exactly:
1. A CRUD route in `web/api/routes/*.py` mutates the local SQLite row and calls `enqueue(entity_type, id, "upsert"|"delete")` (`cli/sync_queue.py`).
2. The background worker (or a foreground `flush_sync` during `/api/sync/push`) drains the queue, calling a `sync_<entity>_to_cloud()` function in `cli/sync.py`.
3. That function reads the current row fresh from SQLite, resolves parent cloud ids (lazy-ensuring parents first, same as `sync_script_to_cloud`), and calls the matching `cli/api.py` HTTP client function, which POSTs to the qaclan-server endpoint from the server plan.
4. On success, the returned cloud id is written back via `_save_cloud_id(table, local_id, cloud_id)` (entities that support it).
5. On pull, `cli/commands/pull.py`'s `pull_workspace()` reads `GET /api/pull/workspace`, and for each new key, upserts by `cloud_id` into the matching local table, building a `cloud_id → local_id` map for entities referenced by children (`collection_map`, `folder_map`).

Run-history and docs-cache pull is deliberately **not** part of `pull_workspace()` — see "On-demand pull" below.

## Entities and Field Mapping

Each subsection lists: local table (already exists, from `cli/db.py`), new `cloud_id` column (yes/no), the `cli/sync.py` function to add, and the `cli/api.py` → server endpoint it calls (endpoint contracts are fully specified in the server plan; not repeated here beyond the field names needed to build the payload).

### 1. `api_collections` → `cloud_api_collections`
- **Gets `cloud_id`:** yes.
- Local columns read: `id, project_id, name, description, env_name, auth_type, auth_config, order_index`.
- `sync_api_collection_to_cloud(collection_id)`: lazy-ensure `project_id` synced first (reuse `_ensure_project_synced`), build payload `{cli_collection_id, cloud_id, name, description, env_name, auth_type, auth_config, order_index, project_id: <cloud>}`, call `api.sync_api_collection`, save returned `id` as `cloud_id`.
- Delete: `delete_api_collection_from_cloud(collection_id)` → `api.delete_api_collection(key, collection_id)`.
- Enqueue hook points: `web/api/routes/collections.py` — `create_collection` (line 37), `update_collection` (63), `patch_collection` (92) → `enqueue("api_collection", col_id, "upsert")`; `delete_collection` (78) → `enqueue("api_collection", col_id, "delete")`. Also `reorder_collections` (210) must enqueue an upsert per reordered collection (order_index changed).

### 2. `api_folders` → `cloud_api_folders`
- **Gets `cloud_id`:** yes.
- Local columns read: `id, project_id, collection_id, parent_folder_id, name, order_index`.
- `sync_api_folder_to_cloud(folder_id)`: lazy-ensure `collection_id`'s collection synced first; if `parent_folder_id` set, lazy-ensure that folder synced first too (recursive — same shape as ensuring a project before a feature, just one level deeper). Payload: `{cli_folder_id, cloud_id, name, order_index, project_id: <cloud>, collection_id: <cloud>, parent_folder_id: <cloud or null>}`.
- Delete: cascades server-side; client just calls `api.delete_api_folder`.
- Enqueue hook points: `web/api/routes/folders.py` — `create_folder` (33), `update_folder` (48) → upsert; `delete_folder` (63) → delete; `reorder_tree` (77) → upsert per moved/reordered folder AND any request whose `folder_id`/`order_index` changed (reparenting a folder can also move its child requests' effective position — re-enqueue affected `api_request` rows too, not just the folder).

### 3. `api_requests` → `cloud_api_requests`
- **Gets `cloud_id`:** yes.
- Local columns read: full column list from `cli/db.py` (`name, method, url, headers, params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, pre_extractor, post_script, post_lang, post_extractor, request_schema, response_schema, assertions, follow_redirects, timeout_ms, include_in_docs, order_index, project_id, feature_id, collection_id, folder_id`).
- `sync_api_request_to_cloud(request_id)`: same "attach FK only if parent already has cloud_id" rule as `sync_script_to_cloud` — do not force-ensure `feature_id`/`collection_id`/`folder_id`, only `project_id` (required). JSON columns (`headers`, `params`, `path_params`, `auth_config`, `pre_extractor`, `post_extractor`, `request_schema`, `response_schema`, `assertions`) are stored as TEXT locally — `json.loads()` before sending so the server receives real JSON, not a JSON-encoded string.
- Delete: `delete_api_request_from_cloud`.
- Enqueue hook points: `web/api/routes/requests.py` — `create_request` (34), `update_request` (60), `patch_request` (75) → upsert; `delete_request` (91) → delete.

### 4. `collection_vars` → `cloud_collection_vars`
- **Gets `cloud_id`:** no — full-replace-list semantics, same as `env_vars`.
- `sync_collection_vars_to_cloud(collection_id)`: `SELECT key, initial_value FROM collection_vars WHERE collection_id = ? ORDER BY key`, send the whole list. Payload: `{cli_collection_id, cloud_collection_id, vars: [{key, initial_value}]}`.
- Enqueue hook points: `web/api/routes/collections.py` — `upsert_collection_var` (151), `delete_collection_var` (167) → both `enqueue("collection_vars", col_id, "upsert")` (whole-list re-send on any single var change, exactly like `env_vars` does today).

### 5. `api_request_examples` → `cloud_api_request_examples` (variant library)
- **Gets `cloud_id`:** yes.
- Local columns read: `id, api_request_id, label, params, body, response_status, response_headers, response_body`.
- `sync_api_request_example_to_cloud(example_id)`: lazy-ensure parent request synced first (required — server rejects if `request_id` unresolved). Payload: `{cli_example_id, cloud_id, request_id: <cloud>, label, params, body, response_status, response_headers, response_body}`.
- Enqueue hook points: wherever the variant-library "Save as Library" flow creates/deletes `api_request_examples` rows (`web/api/services/request_service.py` — confirm exact function name at implementation time; not yet located in this pass) → `enqueue("api_request_example", id, "upsert"|"delete")`.

### 6. `api_collection_runs` + `api_request_results` → `cloud_api_collection_runs` + `cloud_api_request_results`
- **Gets `cloud_id`:** no — append-only history, same as `suite_runs`/`script_runs` today.
- `sync_api_collection_run_to_cloud(run_id)`: lazy-ensure the collection synced first. Read the `api_collection_runs` row plus all its `api_request_results` (ordered by `order_index`), build the `request_results` array per the server plan's `POST /api/sync/api-collection-run` shape, send in one call (mirrors `sync_run_to_cloud`'s `script_results` batching — one HTTP call per run, not per result row).
- No delete — run history is never deleted individually (matches existing `run` entity: no `delete_run` anywhere).
- Enqueue hook point: `web/api/services/runner_service.py`, at the point a collection run reaches a terminal status (`PASSED`/`FAILED`/`ERROR`/`STOPPED`) → `enqueue("api_collection_run", run_id, "upsert")`.

### 7. `api_runs` (mixed suite) → `cloud_run_api_results`
- No new local table, no `cloud_id` — this is an addition to the *existing* `run` entity's push, not a new entity type.
- Modify `sync_run_to_cloud` (`cli/sync.py`): alongside the existing `script_results` query, add `SELECT ... FROM api_runs JOIN api_requests ON api_runs.api_request_id = api_requests.id WHERE suite_run_id = ? ORDER BY order_index`, build an `api_results` array (shape per server plan Section 2.11), pass as the new optional `api_results` key in the existing payload dict. No `ENTITY_ORDER` change needed — this rides on the existing `run` enqueue at `web/routes/runs.py:747`.

## Pull

### `pull_workspace()` merge order (extends `cli/commands/pull.py`)

Insert after the existing `scripts` step, before `environments` (collections/folders only need `project_id` resolved, same dependency depth as scripts):

```
projects → features → scripts → api_collections → api_folders → api_requests
  → environments → env_vars → collection_vars → suites → suite_items
```

- **`api_collections`:** same pattern as `environments` — match by `cloud_id`, upsert, populate `collection_map[cloud_id] = local_id`.
- **`api_folders`:** self-referential — a single top-to-bottom pass can hit a folder before its parent if the server doesn't happen to return them in tree order. Use a worklist: repeatedly scan the pulled list for folders whose `parent_folder_id` is `null` or already in `folder_map`, insert those, remove from the worklist, repeat until either the worklist is empty or a full pass makes no progress (log + skip remaining — malformed/cyclic data, shouldn't happen but don't infinite-loop on it).
- **`api_requests`:** resolve `project_id` (required, skip request if unresolved — same "orphan protection" as scripts), `feature_id`/`collection_id`/`folder_id` (optional, via their maps).
- **`collection_vars`:** match by `(collection_id, key)` after resolving `collection_id` via `collection_map` — same as how `env_vars` matches by `(environment_id, key)`.

### On-demand pull (new, not part of `pull_workspace()`)

Two new functions, called lazily rather than on every generic pull:

- `pull_api_run_history(project_id)` — calls `api.pull_api_runs` + iterates pages, upserts into local `api_collection_runs`/`api_request_results` (matching by... these have no `cloud_id`; use `cli_collection_run_id` returned by the server as authoritative — if a local row with that id doesn't exist, insert it; collection runs are immutable once finished, so no update-in-place case to handle). Triggered when the web UI's "API Runs" view for a project is opened (new: a small route, e.g. `web/api/routes/api_collection_runs.py`, gains a `?pull_remote=1` query flag or a dedicated `POST /api/collections/<id>/runs/pull` action button).
- `pull_api_docs(project_id)` — calls `api.pull_api_docs`, upserts into local `api_doc_entries` by `(project_id, method, path_pattern)`, treating it as an **overlay**: only overwrite a local row if the pulled `last_seen_at` is newer than the local row's, so a user's own live-regenerated local docs aren't clobbered by a stale team snapshot. Triggered when the "Docs" tab for a project is opened.

Both are additive, read-only-feeling actions from the user's point of view (no data loss risk — worst case is a local doc entry gets an extra `source_request_ids` entry from a teammate).

## Error Handling

No new error-handling primitives. Reuse exactly what exists:
- `_try_sync(label, fn)` wraps ad-hoc calls (prints + swallows outside `strict_mode()`).
- `sync.strict_mode()` context, entered by `sync_queue._dispatch()`, makes the same functions raise instead — so the queue's `attempts`/`last_error`/backoff bookkeeping works unchanged for the new entity types.
- Lazy-parent-ensure failures (e.g. project sync fails) propagate up naturally — a child entity sync will fail with the same parent-unresolved error `sync_script_to_cloud` already produces when a suite/feature isn't synced yet; no new error type needed.
- Server-side 400s for unresolved FK references (per server plan) surface as `HTTPError` via `_raise_with_body`, same as every existing endpoint.

## Testing (manual — no automated test suite, per repo convention)

Since `qaclan-server` doesn't exist yet in this environment, verification needs a stand-in. Plan (detailed further in the implementation plan doc):

1. Build a throwaway local mock server (a small Flask app, not committed, or committed under a `scratch/`-style dev-only path) implementing just the new endpoint contracts from the server plan — enough to accept a POST and echo back a fake `cloud_id`, and to serve a canned `GET /api/pull/workspace`/`/api/pull/api-runs`/`/api/pull/api-docs` response.
2. Point `QACLAN_SERVER_URL` at the mock server (existing env var override, already read by `cli/api.py`).
3. Per entity: create/edit/delete it via the web UI or a `curl` call to the local Flask routes, click Push, inspect the mock server's received request body against the contract, click Pull against a canned response, inspect the local SQLite row (`sqlite3 ~/.qaclan/qaclan.db "select * from api_collections"` etc.) for correct `cloud_id`/field values.
4. Cascade-delete check: delete a collection locally, push, confirm the mock server received exactly one `DELETE /api/sync/api-collection/<id>` call (not one per descendant — cascade is server-side).
5. Once the real `qaclan-server` plan ships, repeat the same manual pass against it as a final integration check.

## Self-Review Notes

- Spec covers every entity called out in scope; mixed-suite `api_runs` explicitly folded into the existing `run` entity rather than invented as a new one, matching the server plan's `cloud_run_api_results` design.
- No placeholders — every function name, file path, and enqueue hook point is either confirmed against the current codebase (line numbers cited) or explicitly flagged as "confirm exact location at implementation time" (only the variant-library save flow, since its route wasn't located in this research pass).
- Consistent with the server plan: field names, JSON shapes, and endpoint URLs referenced here match Sections 1-3 of `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` exactly — no renaming drift.
