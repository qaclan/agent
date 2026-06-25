# Collection Run Progress — Design Spec
Date: 2026-06-25 (revised)

## Problem

Collection runs are synchronous and blocking — the HTTP call holds open until all requests complete. The UI has no visibility during execution, no way to stop a run, and no indication of run state when navigating away and back.

## Goal

- Live request-by-request progress on a dedicated run page
- Stop a run mid-execution
- Prevent the same collection running twice simultaneously
- Show running status per collection in the sidebar when navigating away and back
- Persist all state in DB — refresh never loses progress

## Decisions

| Question | Decision |
|---|---|
| Live updates mechanism | Background thread + DB polling (1s on detail page, 3s on sidebar) |
| Async vs threading | Threading — Flask dev server already threaded; httpx I/O-bound; async = ASGI refactor, overkill |
| Navigation on run trigger | Navigate immediately to dedicated run detail page in `api-main-content` |
| Same collection concurrently | Prevented — `start_collection_run()` checks for existing RUNNING run, returns existing `run_id` |
| Multiple different collections | Allowed — no cross-contamination (separate state dicts, separate DB rows) |
| Stop mechanism | `stop_requested` column polled by thread at start of each iteration; status becomes `STOPPED` |
| Failed request rows | Stay collapsed — user clicks to expand |
| Elapsed timer | Client-side `setInterval`, not server-derived |
| Report button visibility | Shown only after run completes (PASSED/FAILED/STOPPED) |
| Sidebar running indicator | Pulsing dot (●) next to collection name — no extra text, no space cost |
| Collection name click | Clicking name (not ▾) shows collection detail in main panel; ▾ still toggles expand |
| Collection detail panel | Shows running summary card (if active run) + request list; replaces current empty-state when no request selected |
| Summary card stop button | In both: collection detail panel + run detail page header |

---

## Section 1: Data Layer

### New columns on `api_collection_runs`

```sql
ALTER TABLE api_collection_runs ADD COLUMN current_request_index INTEGER DEFAULT -1;
ALTER TABLE api_collection_runs ADD COLUMN stop_requested INTEGER DEFAULT 0;
```

- `current_request_index`: `-1` = not started; `0..n` = index of currently executing request (set BEFORE request fires)
- `stop_requested`: `0` = normal; `1` = stop requested by user; thread checks at start of each iteration

### `create_run()` fix

`total` must be written at creation time (not only at `finish_run()`). `start_collection_run()` passes `len(requests)` so the progress bar denominator is correct from the first poll.

### New / updated `CollectionRunRepo` methods

- **`update_current_index(run_id, idx)`** — single UPDATE before each request
- **`request_stop(run_id)`** — sets `stop_requested = 1`
- **`is_stop_requested(run_id)`** — returns `bool`
- **`get_running_for_collection(collection_id)`** — returns `run_id` if any RUNNING run exists for this collection, else `None`
- **`list_runs(project_id, status_filter=None)`** — accepts optional status filter so frontend can fetch only RUNNING runs cheaply
- **`get_run()`** — updated SELECT to include `current_request_index`, `stop_requested`

---

## Section 2: Runner

### `start_collection_run()` — new method (non-blocking)

1. Check `get_running_for_collection(collection_id)` — if found, return existing `run_id` immediately (no new thread)
2. Load collection + requests to get `total` count
3. Create DB row with `status='RUNNING'`, `total=len(requests)`, `current_request_index=-1`
4. Spawn `daemon=True` thread targeting `_execute_collection()`
5. Return `run_id` immediately

### `_execute_collection()` — thread target

```
results = []   # initialized BEFORE try so finally always has it
final_status = "ERROR"

try:
    for idx, req in enumerate(requests):
        if run_repo.is_stop_requested(run_id):   ← check BEFORE updating index
            final_status = "STOPPED"
            break
        run_repo.update_current_index(run_id, idx)
        result = run_api_request(...)
        results.append(result)
        run_repo.create_request_result(...)
    else:
        # loop completed without break
        final_status = "PASSED" if no failures else "FAILED"
except Exception:
    final_status = "ERROR"
finally:
    run_repo.finish_run(run_id, final_status, ...)
```

Thread safety: `get_conn()` uses `threading.local()` — each thread gets own SQLite connection.

### Existing `run_collection()` kept for CLI

`qaclan api run --collection` continues to block synchronously.

---

## Section 3: Routes

### `POST /api/collections/<col_id>/run`
Returns `{"ok": true, "run_id": "...", "status": "RUNNING", "already_running": false}` immediately.
If collection already running: same shape, `"already_running": true`, with existing `run_id`.

### `POST /api/api-collection-runs/<run_id>/stop`
New route. Sets `stop_requested=1`. Returns `{"ok": true}`. 400 if run not RUNNING.

### `GET /api/api-collection-runs`
Add `?status=RUNNING` filter support so sidebar can poll only active runs cheaply.

### `GET /api/api-collection-runs/<run_id>`
No route change — just `get_run()` SELECT now includes `current_request_index` and `stop_requested`.

---

## Section 4: Frontend

### Sidebar — pulsing dot

`renderCollectionsView` polls `GET /api/api-collection-runs?status=RUNNING` every 3s. For each collection with an active run, a small pulsing dot appears before the name:

```
● Auth Flows  (4)  [staging ▾]  [⋯]  [▾]
  POST /login
  GET  /me
```

Clicking the collection **name** (`leftSide` element) now calls `onSelectCollection(col, runId|null)` — navigates to collection detail in main panel. Clicking **▾** still just expands/collapses the sidebar list.

### Collection Detail Panel (`collection-detail-view.js`)

Rendered in `api-main-content` when collection name is clicked. Two states:

**State A — no active run:**
```
Auth Flows
──────────────────────────────────
No requests selected.
[Select a request from the left to edit it]
```

**State B — active run:**
```
Auth Flows
──────────────────────────────────────────────────
⟳ Run in progress  ·  3 / 7  ·  2 passed · 1 failed
[View Full Progress →]                    [■ Stop]
──────────────────────────────────────────────────
POST  /login    ✓   GET  /me    ✓   POST /refresh ✗ ...
```

Summary card polls `GET /api/api-collection-runs/<run_id>` every 2s while RUNNING.
"View Full Progress" → navigates to `CollectionRunView` (same `api-main-content`).
"Stop" → `POST /api/api-collection-runs/<run_id>/stop`.
When run finishes (poll detects non-RUNNING status): card shows final result, Stop button disappears.

### Run Detail Page (`collection-run-view.js`)

Full-page progress view rendered in `api-main-content`. Polls every 1s while RUNNING.

```
Collection Run: Auth Flows           [← Back]  [■ Stop]  [⬇ Report]
──────────────────────────────────────────────────────────────────────
● RUNNING   3/7   2 passed · 1 failed · 0 errors   00:14
[████████████░░░░░░░░░░░░░░░░░░] 43%

METHOD  NAME               STATUS    CODE  DURATION
POST    /auth/login        ✓ PASSED  201   142ms    [▼]
GET     /auth/me           ✓ PASSED  200    89ms    [▼]
POST    /auth/refresh      ✗ FAILED  401   203ms    [▼]
POST    /auth/logout       ⟳ running...
GET     /users             · pending
DELETE  /users/{{id}}      · pending
```

- Stop button: visible only while RUNNING; calls `POST /api/api-collection-runs/<run_id>/stop`
- Report button: visible only when status is PASSED/FAILED/STOPPED
- Rows collapsed by default — click to expand response body + assertion results
- On refresh: poll returns current DB state, rendering resumes from where it was

### Teardown

Before rendering any new view into `api-main-content`, check `container.__destroyRunView` and call it if present. This clears poll timers from any previously-rendered run/detail view.

---

## Out of Scope

- Parallel request execution within a collection
- SSE streaming
- Cancel mid-request (stop waits for current request to finish, then halts before next)
