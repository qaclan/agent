# Collection Run Progress — Design Spec
Date: 2026-06-25

## Problem

Collection runs (`POST /api/collections/<col_id>/run`) are synchronous and blocking — the HTTP call holds open until all requests complete, then returns the full result. The UI has no visibility into what is happening during execution. Users with collections of 5–30 requests see a blank loading state for seconds to minutes with no feedback.

## Goal

Show live request-by-request progress as a collection executes. Each request row appears as it completes. The currently-executing request shows a spinner. Results persist in the DB so a page refresh never loses progress.

## Decisions

| Question | Decision |
|---|---|
| Live updates mechanism | Background thread + DB polling (1s interval) |
| Async vs threading | Threading — Flask dev server is already threaded; httpx calls are I/O-bound; async requires ASGI refactor (overkill for local-first, single-user tool) |
| Navigation on run | Navigate immediately to dedicated run detail page |
| Failed request rows | Stay collapsed — user clicks to expand |
| Elapsed timer | Client-side `setInterval`, not server-derived |
| Report button visibility | Shown only after run completes |

---

## Section 1: Data Layer

### Migration

Add `current_request_index` to `api_collection_runs`:

```sql
ALTER TABLE api_collection_runs ADD COLUMN current_request_index INTEGER DEFAULT -1;
```

- `-1` = run created, not yet started
- `0, 1, 2...` = index of the request **currently executing** (set before the request fires)
- After run finishes, value is left at last index — irrelevant once status is PASSED/FAILED

### CollectionRunRepo changes

**`create_run()`** — accept `total` param and write it immediately (currently `total` is only written by `finish_run()` at the end, which means the progress bar denominator would be `0` during execution). `start_collection_run()` passes `len(requests)` at creation time.

**`update_current_index(run_id, idx)`** — new method:

```python
def update_current_index(self, run_id: str, idx: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE api_collection_runs SET current_request_index = ? WHERE id = ?",
        (idx, run_id),
    )
    conn.commit()
```

**`get_run()`** — add `current_request_index` to the SELECT. Already returns `request_results` rows from `api_request_results` — these accumulate incrementally as each request completes.

---

## Section 2: Runner

### RunnerService changes

#### New method: `start_collection_run()`

Replaces the direct `run_collection()` call from the route. Creates the DB row immediately, spawns a background thread, returns `run_id` to the caller without blocking.

```python
def start_collection_run(self, collection_id, project_id, env_name=None, seed_vars=None) -> str:
    import threading
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from web.api.repositories.collection_repo import CollectionRepo
    from datetime import datetime, timezone

    col = CollectionRepo().get(collection_id, project_id)
    if col is None:
        raise LookupError(f"Collection {collection_id} not found")

    started_at = datetime.now(timezone.utc).isoformat()
    run_id = CollectionRunRepo().create_run(
        collection_id=collection_id,
        project_id=project_id,
        collection_name=col["name"],
        env_name=env_name,
        started_at=started_at,
    )

    thread = threading.Thread(
        target=self._execute_collection,
        args=(run_id, collection_id, project_id, env_name, seed_vars),
        daemon=True,
    )
    thread.start()
    return run_id
```

#### New method: `_execute_collection()`

Contains the existing `run_collection()` loop logic, with one addition — `update_current_index` before each request:

```python
def _execute_collection(self, run_id, collection_id, project_id, env_name, seed_vars):
    # ... load col, requests, env_vars, state (same as existing run_collection) ...
    try:
        for idx, req in enumerate(requests):
            run_repo.update_current_index(run_id, idx)   # ← signals "this request is running"
            result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
            results.append({...})
            run_repo.create_request_result(run_id, req, result, idx)
    finally:
        # ... compute passed/failed/error_count, call finish_run() (same as existing) ...
```

Thread safety: `get_conn()` uses `threading.local()` — each thread gets its own SQLite connection. No shared mutable state beyond the DB.

#### Existing `run_collection()` method

Kept as-is for CLI usage (`qaclan api run --collection`). It continues to block synchronously, which is correct for terminal output.

---

## Section 3: Route

### `POST /api/collections/<col_id>/run` — change to non-blocking

```python
@bp.route("/api/collections/<col_id>/run", methods=["POST"])
def run_collection(col_id):
    data = request.get_json(force=True) or {}
    env_name = data.get("env_name") or None
    seed_vars = data.get("seed_vars") or None
    pid = _project_id()
    run_id = _runner_svc.start_collection_run(col_id, pid, env_name=env_name, seed_vars=seed_vars)
    return jsonify({"ok": True, "run_id": run_id, "status": "RUNNING"})
```

Returns immediately with `run_id`. Frontend navigates to the run page using this ID.

### `GET /api/api-collection-runs/<run_id>` — no change needed

Already returns full run dict including `request_results`. Adding `current_request_index` to `get_run()` SELECT is the only change. Frontend polls this endpoint.

---

## Section 4: Frontend

### Router

Add route: `#api-collection-runs/:runId` → renders `CollectionRunView`

Registered in `app.js` router alongside existing API routes.

### "Run" button flow (in collection view / collections sidebar)

```
1. User clicks [▶ Run]
2. POST /api/collections/<col_id>/run  →  { run_id }
3. Navigate to #api-collection-runs/<run_id>
4. CollectionRunView mounts, starts polling
```

### CollectionRunView (`web/static/api/views/collection-run-view.js`)

New ES module view. Polling lifecycle:

- On mount: fetch `GET /api/api-collection-runs/<run_id>` immediately
- While `status === 'RUNNING'`: poll every 1000ms via `setInterval`
- On `status !== 'RUNNING'`: clear interval, render final state

**Page layout:**

```
Collection Run: Auth Flows              [↩ Back to Collection]  [⬇ Report]
──────────────────────────────────────────────────────────────────────────
● RUNNING   3 / 7   2 passed · 1 failed · 0 errors   00:14 elapsed
[████████████░░░░░░░░░░░░░░░░] 43%

METHOD   NAME                STATUS      CODE   DURATION
POST     /auth/login         ✓ PASSED    201    142ms      [▼]
GET      /auth/me            ✓ PASSED    200     89ms      [▼]
POST     /auth/refresh       ✗ FAILED    401    203ms      [▼]
POST     /auth/logout        ⟳ running...
GET      /users              · pending
DELETE   /users/{{id}}       · pending
```

**Status determination per row** (derived client-side from `request_results` + `current_request_index`):

| Condition | Display |
|---|---|
| `request_results[idx]` exists | Completed — show status badge + code + duration |
| `idx === current_request_index` (no result yet) | ⟳ running... spinner |
| `idx > current_request_index` | · pending (dimmed) |

**Expand row `[▼]`** (collapsed by default, even on failure):
- Response body (truncated to 500 chars, "show more" link if longer)
- Response headers (key-value, collapsed by default)
- Assertion results: ✓/✗ per assertion with actual vs expected

**Header section:**
- Status badge: `RUNNING` (pulsing) / `PASSED` (green) / `FAILED` (red)
- `N / total` counter
- `X passed · Y failed · Z errors` counters
- Elapsed timer: client-side `setInterval(1s)`, starts from `run.started_at`, stops when status is final
- Progress bar: `(request_results.length / total) * 100%`

**Report button:** rendered only when `status !== 'RUNNING'`. Links to `GET /api/api-collection-runs/<run_id>/report?view=1`.

**Back link:** links to `#api-collections` (or `#api-collections/<collection_id>` if available from run data).

### On page refresh

No data loss — `GET /api/api-collection-runs/<run_id>` returns the full current state from DB:
- If still `RUNNING`: partial `request_results`, `current_request_index` — resumes polling
- If `PASSED`/`FAILED`: full results, no polling needed

---

## Out of Scope

- Stop/cancel a running collection mid-execution
- Parallel request execution within a collection
- SSE streaming (polling at 1s is sufficient for this use case)
- Run history page (already exists in API Runs tab on the Runs page)
