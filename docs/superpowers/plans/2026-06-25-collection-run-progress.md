# Collection Run Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live request-by-request progress for collection runs — background thread execution, stop support, same-collection guard, per-collection running indicator in sidebar, collection detail panel, full run detail page.

**Architecture:** `start_collection_run()` checks for duplicate RUNNING run, creates DB row, spawns daemon thread, returns `run_id` immediately. Thread sets `current_request_index` before each request and checks `stop_requested` to halt early. Frontend has three views: run detail page (1s poll), collection detail panel (2s poll), sidebar running dots (3s poll).

**Tech Stack:** Python threading (stdlib), Flask, SQLite, vanilla JS ES modules, existing `window.api()` helper

## Global Constraints
- No automated test framework — verify via `python qaclan.py serve --port 7823` + browser + curl
- Never modify existing `web/routes/*.py` beyond specified changes
- Never refactor `web/static/app.js` existing code — additive only
- All new Python files: `from __future__ import annotations` first import
- SQLite only — parse JSON with `json.loads()`, serialize with `json.dumps()`
- All IDs: `generate_id(prefix)` from `cli/db.py`
- Logger every new Python module: `logger = logging.getLogger("qaclan.<module_name>")`
- JS: ES modules only, no build step, match style of existing views in `web/static/api/views/`

---

### Task 1: DB Migration

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: `current_request_index INTEGER DEFAULT -1` and `stop_requested INTEGER DEFAULT 0` on `api_collection_runs`

- [ ] **Step 1: Add migration function**

Add after the existing `_migrate_collection_run_progress` function if it exists, otherwise after `_migrate_pre_extractor`:

```python
def _migrate_collection_run_progress(conn):
    """Add current_request_index and stop_requested to api_collection_runs."""
    try:
        conn.execute(
            "ALTER TABLE api_collection_runs ADD COLUMN current_request_index INTEGER DEFAULT -1"
        )
    except Exception:
        pass  # already exists
    try:
        conn.execute(
            "ALTER TABLE api_collection_runs ADD COLUMN stop_requested INTEGER DEFAULT 0"
        )
    except Exception:
        pass  # already exists
    conn.commit()
```

- [ ] **Step 2: Register in `init_db()`**

At the end of `init_db()` in `cli/db.py`, after `_migrate_pre_extractor(conn)`:

```python
    _migrate_pre_extractor(conn)
    _migrate_collection_run_progress(conn)
```

If `_migrate_collection_run_progress` is already called there from a prior partial implementation, replace it (function body above is the canonical version — idempotent `try/except` for both columns).

- [ ] **Step 3: Verify**

```bash
python qaclan.py --help
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_collection_runs);"
```

Expected output includes rows with `name = current_request_index` and `name = stop_requested`.

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat: add current_request_index and stop_requested to api_collection_runs"
```

---

### Task 2: CollectionRunRepo — new methods

**Files:**
- Modify: `web/api/repositories/collection_run_repo.py`

**Interfaces:**
- Consumes: Task 1 (new columns)
- Produces:
  - `CollectionRunRepo.create_run(..., total: int = 0)` — writes `total` at creation
  - `CollectionRunRepo.update_current_index(run_id, idx)` — UPDATE before each request
  - `CollectionRunRepo.request_stop(run_id)` — sets `stop_requested = 1`
  - `CollectionRunRepo.is_stop_requested(run_id) -> bool`
  - `CollectionRunRepo.get_running_for_collection(collection_id) -> str | None` — returns `run_id` or `None`
  - `CollectionRunRepo.list_runs(project_id, status_filter=None)` — optional status WHERE clause
  - `CollectionRunRepo.get_run(run_id, project_id)` — SELECT includes `current_request_index`, `stop_requested`

- [ ] **Step 1: Update `create_run()` to accept and store `total` at creation**

Replace the full `create_run` method:

```python
def create_run(self, collection_id: str, project_id: str, collection_name: str,
               env_name: str | None, started_at: str, total: int = 0) -> str:
    conn = get_conn()
    run_id = generate_id("arun")
    conn.execute(
        "INSERT INTO api_collection_runs "
        "(id, project_id, collection_id, collection_name, env_name, status, "
        "total, passed, failed, error_count, started_at, current_request_index, stop_requested) "
        "VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, 0, 0, 0, ?, -1, 0)",
        (run_id, project_id, collection_id, collection_name, env_name, total, started_at),
    )
    conn.commit()
    logger.info("CollectionRunRepo.create_run: %s (total=%d)", run_id, total)
    return run_id
```

- [ ] **Step 2: Add `update_current_index()`**

```python
def update_current_index(self, run_id: str, idx: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE api_collection_runs SET current_request_index = ? WHERE id = ?",
        (idx, run_id),
    )
    conn.commit()
```

- [ ] **Step 3: Add `request_stop()`**

```python
def request_stop(self, run_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE api_collection_runs SET stop_requested = 1 WHERE id = ?",
        (run_id,),
    )
    conn.commit()
    logger.info("CollectionRunRepo.request_stop: %s", run_id)
```

- [ ] **Step 4: Add `is_stop_requested()`**

```python
def is_stop_requested(self, run_id: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT stop_requested FROM api_collection_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return bool(row and row["stop_requested"])
```

- [ ] **Step 5: Add `get_running_for_collection()`**

```python
def get_running_for_collection(self, collection_id: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM api_collection_runs WHERE collection_id = ? AND status = 'RUNNING' LIMIT 1",
        (collection_id,),
    ).fetchone()
    return row["id"] if row else None
```

- [ ] **Step 6: Update `list_runs()` to support optional status filter**

Replace the existing `list_runs` method:

```python
def list_runs(self, project_id: str, status_filter: str | None = None) -> list[dict]:
    conn = get_conn()
    if status_filter:
        rows = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE project_id = ? AND status = ? "
            "ORDER BY started_at DESC",
            (project_id, status_filter),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE project_id = ? "
            "ORDER BY started_at DESC",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 7: Update `get_run()` SELECT to include new columns**

In the existing `get_run()` method, find the SELECT:

```python
row = conn.execute(
    "SELECT id, collection_id, collection_name, env_name, status, "
    "total, passed, failed, error_count, started_at, finished_at "
    "FROM api_collection_runs WHERE id = ? AND project_id = ?",
    (run_id, project_id),
).fetchone()
```

Change to:

```python
row = conn.execute(
    "SELECT id, collection_id, collection_name, env_name, status, "
    "total, passed, failed, error_count, started_at, finished_at, "
    "current_request_index, stop_requested "
    "FROM api_collection_runs WHERE id = ? AND project_id = ?",
    (run_id, project_id),
).fetchone()
```

- [ ] **Step 8: Commit**

```bash
git add web/api/repositories/collection_run_repo.py
git commit -m "feat: add update_current_index, request_stop, is_stop_requested, get_running_for_collection to CollectionRunRepo"
```

---

### Task 3: RunnerService — guard + stop

**Files:**
- Modify: `web/api/services/runner_service.py`

**Interfaces:**
- Consumes: Task 2 (all new repo methods)
- Produces:
  - `RunnerService.start_collection_run(collection_id, project_id, env_name, seed_vars) -> str` — returns existing `run_id` if already RUNNING, else creates new run and spawns thread
  - `RunnerService._execute_collection(run_id, collection_id, project_id, env_name, seed_vars)` — thread target with stop check + `update_current_index` before each request
  - Existing `run_collection()` unchanged

- [ ] **Step 1: Add `start_collection_run()`**

Add to `RunnerService` class:

```python
def start_collection_run(self, collection_id: str, project_id: str,
                          env_name: str | None = None,
                          seed_vars: dict | None = None) -> tuple[str, bool]:
    """
    Returns (run_id, already_running).
    If a RUNNING run exists for this collection, returns it without spawning a new thread.
    """
    import threading
    from web.api.repositories.collection_repo import CollectionRepo
    from web.api.repositories.request_repo import RequestRepo
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from datetime import datetime, timezone

    run_repo = CollectionRunRepo()

    # Same-collection guard
    existing_run_id = run_repo.get_running_for_collection(collection_id)
    if existing_run_id:
        logger.info("start_collection_run: collection %s already running as %s", collection_id, existing_run_id)
        return existing_run_id, True

    col = CollectionRepo().get(collection_id, project_id)
    if col is None:
        raise LookupError(f"Collection {collection_id} not found")

    requests = RequestRepo().list(project_id, collection_id=collection_id)
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = run_repo.create_run(
        collection_id=collection_id,
        project_id=project_id,
        collection_name=col["name"],
        env_name=env_name,
        started_at=started_at,
        total=len(requests),
    )

    thread = threading.Thread(
        target=self._execute_collection,
        args=(run_id, collection_id, project_id, env_name, seed_vars),
        daemon=True,
    )
    thread.start()
    logger.info("start_collection_run: run_id=%s thread started", run_id)
    return run_id, False
```

- [ ] **Step 2: Add `_execute_collection()`**

Add to `RunnerService` class directly after `start_collection_run`:

```python
def _execute_collection(self, run_id: str, collection_id: str, project_id: str,
                         env_name: str | None, seed_vars: dict | None) -> None:
    """Thread target. Checks stop_requested before each request."""
    from web.api.repositories.collection_repo import CollectionRepo
    from web.api.repositories.request_repo import RequestRepo
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from cli.api_runner import run_api_request
    from datetime import datetime, timezone

    run_repo = CollectionRunRepo()
    results: list = []
    final_status = "ERROR"

    try:
        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            logger.error("_execute_collection: collection %s not found", collection_id)
            return  # finally handles finish_run with ERROR + empty results

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        env_vars = load_env_vars(project_id, env_name)
        state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

        for idx, req in enumerate(requests):
            if run_repo.is_stop_requested(run_id):
                logger.info("_execute_collection: stop requested at idx %d for run %s", idx, run_id)
                final_status = "STOPPED"
                break
            run_repo.update_current_index(run_id, idx)
            result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
            results.append(result)
            run_repo.create_request_result(run_id, req, result, idx)
        else:
            # for-else: loop completed without break (no stop)
            passed = sum(1 for r in results if r.get("status") == "PASSED")
            failed_c = sum(1 for r in results if r.get("status") == "FAILED")
            err_c = sum(1 for r in results if r.get("status") == "ERROR")
            final_status = "PASSED" if (failed_c + err_c) == 0 and results else "FAILED"

    except Exception:
        logger.exception("_execute_collection: unhandled error in run %s", run_id)
        # final_status stays "ERROR"

    finally:
        passed = sum(1 for r in results if r.get("status") == "PASSED")
        failed_c = sum(1 for r in results if r.get("status") == "FAILED")
        err_c = sum(1 for r in results if r.get("status") == "ERROR")
        run_repo.finish_run(
            run_id=run_id,
            status=final_status,
            total=len(results),
            passed=passed,
            failed=failed_c,
            error_count=err_c,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("_execute_collection: run %s → %s", run_id, final_status)
```

- [ ] **Step 3: Verify `run_collection()` still exists**

```bash
grep -n "def run_collection" web/api/services/runner_service.py
```

Expected: one result — the original sync method still present.

- [ ] **Step 4: Commit**

```bash
git add web/api/services/runner_service.py
git commit -m "feat: add start_collection_run with same-collection guard and _execute_collection with stop support"
```

---

### Task 4: Routes — non-blocking trigger + stop endpoint

**Files:**
- Modify: `web/api/routes/collections.py`
- Modify: `web/api/routes/api_collection_runs.py`

**Interfaces:**
- Consumes: Task 3 (`start_collection_run() -> tuple[str, bool]`), Task 2 (`request_stop`, `list_runs(status_filter)`)
- Produces:
  - `POST /api/collections/<col_id>/run` → `{"ok": true, "run_id": "...", "status": "RUNNING", "already_running": bool}`
  - `POST /api/api-collection-runs/<run_id>/stop` → `{"ok": true}`
  - `GET /api/api-collection-runs?status=RUNNING` → filtered list

- [ ] **Step 1: Update `run_collection` route in `collections.py`**

Find and replace the existing `run_collection` route body:

```python
@bp.route("/api/collections/<col_id>/run", methods=["POST"])
def run_collection(col_id):
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name") or None
        seed_vars = data.get("seed_vars") or None
        pid = _project_id()
        run_id, already_running = _runner_svc.start_collection_run(
            col_id, pid, env_name=env_name, seed_vars=seed_vars
        )
        return jsonify({"ok": True, "run_id": run_id, "status": "RUNNING",
                        "already_running": already_running})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("run_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Add stop route to `api_collection_runs.py`**

Add after the existing `get_api_collection_run` route:

```python
@bp.route("/api/api-collection-runs/<run_id>/stop", methods=["POST"])
def stop_api_collection_run(run_id):
    try:
        pid = _project_id()
        run = _repo.get_run(run_id, pid)
        if run is None:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404
        if run["status"] != "RUNNING":
            return jsonify({"ok": False, "error": "Run is not RUNNING"}), 400
        _repo.request_stop(run_id)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("stop_api_collection_run")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 3: Update `list_api_collection_runs` to support `?status=` filter**

Find the existing `list_api_collection_runs` route in `api_collection_runs.py`:

```python
@bp.route("/api/api-collection-runs", methods=["GET"])
def list_api_collection_runs():
    try:
        runs = _repo.list_runs(_project_id())
        return jsonify({"ok": True, "runs": runs})
```

Change to:

```python
@bp.route("/api/api-collection-runs", methods=["GET"])
def list_api_collection_runs():
    try:
        status_filter = request.args.get("status") or None
        runs = _repo.list_runs(_project_id(), status_filter=status_filter)
        return jsonify({"ok": True, "runs": runs})
```

- [ ] **Step 4: Verify routes**

```bash
# Start server
python qaclan.py serve --port 7823

# Trigger a run (use a real collection ID from your DB)
curl -s -X POST http://localhost:7823/api/collections/<col_id>/run \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
# Expected: {"ok": true, "run_id": "arun_...", "status": "RUNNING", "already_running": false}

# Trigger again immediately — should return already_running: true
curl -s -X POST http://localhost:7823/api/collections/<col_id>/run \
  -H 'Content-Type: application/json' -d '{}' | python3 -m json.tool
# Expected: {"ok": true, "run_id": "<same_id>", "status": "RUNNING", "already_running": true}

# List only running
curl -s "http://localhost:7823/api/api-collection-runs?status=RUNNING" | python3 -m json.tool
# Expected: runs array with only RUNNING entries

# Stop the run
curl -s -X POST http://localhost:7823/api/api-collection-runs/<run_id>/stop | python3 -m json.tool
# Expected: {"ok": true}

# Verify stopped
curl -s http://localhost:7823/api/api-collection-runs/<run_id> | python3 -m json.tool
# Expected: status = "STOPPED"
```

- [ ] **Step 5: Commit**

```bash
git add web/api/routes/collections.py web/api/routes/api_collection_runs.py
git commit -m "feat: non-blocking run trigger, stop endpoint, status filter on collection runs list"
```

---

### Task 5: `collection-run-view.js` — full run detail page with Stop

**Files:**
- Create: `web/static/api/views/collection-run-view.js`

**Interfaces:**
- Consumes:
  - `GET /api/api-collection-runs/<runId>` → `{ok, run: {id, collection_id, collection_name, status, total, passed, failed, error_count, started_at, current_request_index, request_results: [{request_name, method, url, order_index, status, status_code, duration_ms, assertion_results, error_message, response_body}]}}`
  - `GET /api/collections/<collectionId>` → `{ok, collection: {requests: [{id, name, method, url, created_at}]}}`
  - `POST /api/api-collection-runs/<runId>/stop`
- Produces: `export function renderCollectionRunView(container, runId, collectionId, collectionName, onBack)`
  - `onBack()` — called when user clicks ← Back
  - Sets `container.__destroyRunView` for external teardown

- [ ] **Step 1: Create the file**

```js
/**
 * renderCollectionRunView(container, runId, collectionId, collectionName, onBack)
 * Full run detail page. Polls GET /api/api-collection-runs/<runId> every 1s while RUNNING.
 * Sets container.__destroyRunView for teardown by parent.
 */
export function renderCollectionRunView(container, runId, collectionId, collectionName, onBack) {
  let _pollTimer = null;
  let _elapsedTimer = null;
  let _startedAt = null;
  let _allRequests = [];
  let _destroyed = false;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer)   { clearInterval(_pollTimer);   _pollTimer = null; }
    if (_elapsedTimer){ clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }
  container.__destroyRunView = _destroy;

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _startElapsed() {
    if (_elapsedTimer) return;
    _elapsedTimer = setInterval(() => {
      const el = document.getElementById('crv-elapsed');
      if (!el || !_startedAt) return;
      const s = Math.floor((Date.now() - new Date(_startedAt).getTime()) / 1000);
      el.textContent = `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
    }, 1000);
  }

  function _statusBadge(status) {
    const map = { RUNNING:'var(--warning,#f59e0b)', PASSED:'var(--success,#22c55e)', FAILED:'var(--danger,#ef4444)', STOPPED:'var(--text-muted,#888)', ERROR:'var(--danger,#ef4444)' };
    const color = map[status] || 'var(--text-muted,#888)';
    const pulse = status === 'RUNNING'
      ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warning,#f59e0b);margin-right:5px;animation:crv-pulse 1s infinite"></span>'
      : '';
    return `<span style="font-weight:600;font-size:13px;color:${color}">${pulse}${_esc(status)}</span>`;
  }

  function _renderShell() {
    container.innerHTML = `
      <style>
        @keyframes crv-pulse{0%,100%{opacity:1}50%{opacity:.35}}
        @keyframes crv-spin{to{transform:rotate(360deg)}}
        .crv-row{display:flex;align-items:center;gap:8px;padding:9px 16px;border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:12px;cursor:pointer;}
        .crv-row:hover{background:var(--bg-hover,rgba(255,255,255,.04));}
        .crv-detail{padding:12px 18px;background:var(--bg-inset,rgba(0,0,0,.2));border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:11px;display:none;}
        .crv-detail.open{display:block;}
        .crv-spin{display:inline-block;width:11px;height:11px;border:2px solid var(--border,#444);border-top-color:var(--text-muted,#999);border-radius:50%;animation:crv-spin .7s linear infinite;}
        .crv-bar{height:4px;background:var(--border-subtle,rgba(255,255,255,.1));border-radius:2px;overflow:hidden;margin:10px 0 2px;}
        .crv-fill{height:100%;background:var(--primary,#6366f1);border-radius:2px;transition:width .4s;}
        .crv-method{font-family:monospace;font-size:11px;font-weight:700;min-width:52px;}
        .crv-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .crv-code{font-size:11px;color:var(--text-muted);min-width:36px;text-align:right;}
        .crv-dur{font-size:11px;color:var(--text-muted);min-width:56px;text-align:right;}
        .crv-chevron{font-size:10px;color:var(--text-muted);min-width:14px;text-align:right;}
        .pass{color:var(--success,#22c55e);font-weight:600;}
        .fail{color:var(--danger,#ef4444);font-weight:600;}
        .err{color:var(--warning,#f59e0b);font-weight:600;}
        .pend{color:var(--text-muted,#888);opacity:.5;}
        pre.crv-body{margin:6px 0 0;padding:8px;background:var(--bg-code,rgba(0,0,0,.25));border-radius:4px;font-size:10px;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;}
      </style>
      <div style="padding:14px 18px;border-bottom:1px solid var(--border,rgba(255,255,255,.1));flex-shrink:0;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <button class="btn btn-xs btn-ghost" id="crv-back">← Back</button>
            <span style="font-size:13px;font-weight:600;" id="crv-title">${_esc(collectionName)}</span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <button class="btn btn-xs btn-danger" id="crv-stop" style="display:none">■ Stop</button>
            <button class="btn btn-xs btn-ghost" id="crv-report" style="display:none">⬇ Report</button>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
          <span id="crv-badge"></span>
          <span style="font-size:12px;color:var(--text-muted)" id="crv-counts"></span>
          <span style="font-size:12px;color:var(--text-muted)">⏱ <span id="crv-elapsed">00:00</span></span>
        </div>
        <div class="crv-bar"><div class="crv-fill" id="crv-fill" style="width:0%"></div></div>
      </div>
      <div style="overflow-y:auto;flex:1;" id="crv-rows"></div>`;

    document.getElementById('crv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    document.getElementById('crv-stop').onclick = async () => {
      const btn = document.getElementById('crv-stop');
      if (btn) { btn.disabled = true; btn.textContent = 'Stopping…'; }
      await window.api('POST', `/api-collection-runs/${runId}/stop`);
    };

    document.getElementById('crv-report').onclick = () => {
      window.open(`/api/api-collection-runs/${runId}/report?view=1`, '_blank');
    };
  }

  function _updateHeader(run) {
    const badge   = document.getElementById('crv-badge');
    const counts  = document.getElementById('crv-counts');
    const fill    = document.getElementById('crv-fill');
    const stopBtn = document.getElementById('crv-stop');
    const repBtn  = document.getElementById('crv-report');
    if (!badge) return;

    badge.innerHTML = _statusBadge(run.status);
    const done = (run.request_results || []).length;
    const total = run.total || 0;
    counts.textContent = `${done}/${total}  ·  ${run.passed} passed · ${run.failed} failed · ${run.error_count} errors`;
    fill.style.width = total > 0 ? `${Math.round(done / total * 100)}%` : '0%';

    if (stopBtn) stopBtn.style.display = run.status === 'RUNNING' ? '' : 'none';
    if (repBtn)  repBtn.style.display  = run.status !== 'RUNNING' ? '' : 'none';
  }

  function _renderRows(run) {
    const rowsEl = document.getElementById('crv-rows');
    if (!rowsEl) return;

    const byIdx = {};
    (run.request_results || []).forEach(r => { byIdx[r.order_index] = r; });
    const curIdx = run.current_request_index ?? -1;
    const total = run.total || _allRequests.length;

    let html = '';
    for (let i = 0; i < total; i++) {
      const spine = _allRequests[i] || {};
      const result = byIdx[i];
      const name   = result ? result.request_name : (spine.name || `Request ${i+1}`);
      const method = result ? result.method : (spine.method || '');

      let badge, code = '', dur = '', chevron = '';
      if (result) {
        if (result.status === 'PASSED')  badge = '<span class="pass">✓</span>';
        else if (result.status === 'FAILED') badge = '<span class="fail">✗</span>';
        else badge = '<span class="err">!</span>';
        code    = result.status_code != null ? String(result.status_code) : '';
        dur     = result.duration_ms  != null ? `${result.duration_ms}ms` : '';
        chevron = '<span class="crv-chevron">▼</span>';
      } else if (i === curIdx) {
        badge = '<span class="crv-spin"></span>';
      } else {
        badge = '<span class="pend">·</span>';
      }

      html += `<div class="crv-row" data-i="${i}">
        ${badge}
        <span class="crv-method">${_esc(method)}</span>
        <span class="crv-name">${_esc(name)}</span>
        <span class="crv-code">${_esc(code)}</span>
        <span class="crv-dur">${_esc(dur)}</span>
        ${chevron}
      </div>`;

      if (result) {
        const asserts = Array.isArray(result.assertion_results) ? result.assertion_results : [];
        const assertHtml = asserts.length
          ? asserts.map(a => `<div style="color:${a.passed?'var(--success,#22c55e)':'var(--danger,#ef4444)'}">
              ${a.passed?'✓':'✗'} ${_esc(a.type)}${a.path?' '+_esc(a.path):''}
              ${a.op?' '+_esc(a.op):''}${a.value!=null?' '+_esc(String(a.value)):''}
              ${!a.passed&&a.actual!=null?' → actual: '+_esc(String(a.actual)):''}
            </div>`).join('')
          : '<div style="color:var(--text-muted)">No assertions</div>';
        const body = result.response_body || '';
        const preview = body.length > 500 ? body.slice(0, 500) + '\n… (truncated)' : body;
        const errHtml = result.error_message
          ? `<div style="color:var(--danger,#ef4444);margin-bottom:6px">Error: ${_esc(result.error_message)}</div>` : '';
        html += `<div class="crv-detail" id="crv-det-${i}">
          ${errHtml}
          <div style="font-weight:600;color:var(--text-secondary);margin-bottom:4px">Assertions</div>
          ${assertHtml}
          ${body ? `<div style="font-weight:600;color:var(--text-secondary);margin-top:8px;margin-bottom:4px">Response body</div>
          <pre class="crv-body">${_esc(preview)}</pre>` : ''}
        </div>`;
      }
    }

    rowsEl.innerHTML = html;

    // Wire expand click — only completed rows have a detail div
    rowsEl.querySelectorAll('.crv-row[data-i]').forEach(row => {
      const i = parseInt(row.dataset.i, 10);
      const det = document.getElementById(`crv-det-${i}`);
      if (det) row.onclick = () => det.classList.toggle('open');
    });
  }

  async function _poll() {
    if (_destroyed) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (!res.ok || !res.run) return;
      const run = res.run;
      if (!_startedAt) { _startedAt = run.started_at; _startElapsed(); }
      _updateHeader(run);
      _renderRows(run);
      if (run.status !== 'RUNNING') {
        if (_pollTimer)   { clearInterval(_pollTimer);   _pollTimer = null; }
        if (_elapsedTimer){ clearInterval(_elapsedTimer); _elapsedTimer = null; }
      }
    } catch (e) { console.error('crv poll:', e); }
  }

  async function _init() {
    _renderShell();
    // Fetch collection request spine for pending row names
    try {
      const colRes = await window.api('GET', `/collections/${collectionId}`);
      if (colRes.ok && colRes.collection?.requests) {
        _allRequests = colRes.collection.requests.slice()
          .sort((a, b) => (a.created_at||'').localeCompare(b.created_at||''));
      }
    } catch (_) {}
    await _poll();
    _pollTimer = setInterval(_poll, 1000);
  }

  _init();
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/api/views/collection-run-view.js
git commit -m "feat: add CollectionRunView with live polling, stop button, expand detail rows"
```

---

### Task 6: `collection-detail-view.js` — summary card + running indicator

**Files:**
- Create: `web/static/api/views/collection-detail-view.js`

**Interfaces:**
- Consumes:
  - `GET /api/api-collection-runs/<runId>` (polls every 2s while RUNNING)
  - `POST /api/api-collection-runs/<runId>/stop`
- Produces: `export function renderCollectionDetailView(container, col, runId, onViewRun, onBack)`
  - `col`: `{id, name, env_name, request_count}`
  - `runId`: active run ID or `null`
  - `onViewRun(runId)`: called when user clicks "View Full Progress"
  - `onBack()`: called on ← Back
  - Sets `container.__destroyRunView` for teardown

- [ ] **Step 1: Create the file**

```js
/**
 * renderCollectionDetailView(container, col, runId, onViewRun, onBack)
 * Shows collection info and, if runId provided, a live summary card with Stop button.
 */
export function renderCollectionDetailView(container, col, runId, onViewRun, onBack) {
  let _pollTimer = null;
  let _destroyed = false;

  function _destroy() {
    _destroyed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }
  container.__destroyRunView = _destroy;

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _renderCard(run) {
    const el = document.getElementById('cdv-card');
    if (!el) return;
    if (!run) { el.style.display = 'none'; return; }

    const isRunning = run.status === 'RUNNING';
    const done = (run.request_results || []).length;
    const total = run.total || 0;
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    const statusColor = isRunning ? 'var(--warning,#f59e0b)'
      : run.status === 'PASSED' ? 'var(--success,#22c55e)'
      : 'var(--danger,#ef4444)';

    el.style.display = '';
    el.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
        <span style="font-size:12px;font-weight:600;color:${statusColor}">
          ${isRunning ? '<span style="animation:cdv-pulse 1s infinite;display:inline-block;margin-right:4px">⟳</span>' : ''}
          ${_esc(run.status)}  ·  ${done}/${total}  ·  ${run.passed} passed · ${run.failed} failed
        </span>
        <div style="display:flex;gap:6px;">
          ${isRunning ? `<button class="btn btn-xs btn-danger" id="cdv-stop">■ Stop</button>` : ''}
          <button class="btn btn-xs btn-primary" id="cdv-view">View Progress →</button>
        </div>
      </div>
      <div style="height:3px;background:var(--border-subtle,rgba(255,255,255,.1));border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:${statusColor};border-radius:2px;transition:width .4s;"></div>
      </div>`;

    const viewBtn = document.getElementById('cdv-view');
    if (viewBtn) viewBtn.onclick = () => { _destroy(); if (onViewRun) onViewRun(run.id); };

    const stopBtn = document.getElementById('cdv-stop');
    if (stopBtn) stopBtn.onclick = async () => {
      stopBtn.disabled = true; stopBtn.textContent = 'Stopping…';
      await window.api('POST', `/api-collection-runs/${run.id}/stop`);
    };

    if (!isRunning) {
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }
  }

  async function _poll() {
    if (_destroyed || !runId) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (res.ok && res.run) _renderCard(res.run);
    } catch (_) {}
  }

  async function _init() {
    container.innerHTML = `
      <style>@keyframes cdv-pulse{0%,100%{opacity:1}50%{opacity:.35}}</style>
      <div style="padding:16px 18px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
          <button class="btn btn-xs btn-ghost" id="cdv-back">← Back</button>
          <span style="font-size:14px;font-weight:700;">${_esc(col.name)}</span>
          <span style="font-size:11px;color:var(--text-muted)">${col.request_count || 0} requests</span>
        </div>
        <div id="cdv-card" style="display:none;background:var(--bg-panel,rgba(255,255,255,.04));
          border:1px solid var(--border-default,rgba(255,255,255,.12));border-radius:8px;
          padding:12px 14px;margin-bottom:16px;"></div>
        <div style="font-size:12px;color:var(--text-muted);">
          Select a request from the left panel to view or edit it.
        </div>
      </div>`;

    document.getElementById('cdv-back').onclick = () => { _destroy(); if (onBack) onBack(); };

    if (runId) {
      await _poll();
      _pollTimer = setInterval(_poll, 2000);
    }
  }

  _init();
}
```

- [ ] **Step 2: Commit**

```bash
git add web/static/api/views/collection-detail-view.js
git commit -m "feat: add CollectionDetailView with running summary card and stop support"
```

---

### Task 7: `collections-view.js` — pulsing dot + collection name click

**Files:**
- Modify: `web/static/api/views/collections-view.js`

**Interfaces:**
- Consumes: `GET /api/api-collection-runs?status=RUNNING` (polls every 3s)
- Produces:
  - `renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection)` — adds two new callbacks
  - `onRunStarted(runId, colId, colName)` — called after run trigger (navigate to run detail)
  - `onSelectCollection(col, runId|null)` — called when collection name clicked (show detail panel)

- [ ] **Step 1: Add `onSelectCollection` parameter to function signature**

Change the function declaration from:

```js
export function renderCollectionsView(container, onSelectRequest) {
```

To:

```js
export function renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection) {
```

- [ ] **Step 2: Add running-status polling state and helpers**

Add these variables near the top of `renderCollectionsView`, after the existing `let _envNames = [];`:

```js
  let _runningByColId = {}; // { [collection_id]: run_id }
  let _runningPollTimer = null;

  async function _refreshRunningStatus() {
    try {
      const res = await window.api('GET', '/api-collection-runs?status=RUNNING');
      const runs = res.runs || [];
      const fresh = {};
      runs.forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
      // Only re-render dots if something changed
      const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
      _runningByColId = fresh;
      if (changed) _updateRunningDots();
    } catch (_) {}
  }

  function _updateRunningDots() {
    // Update dot visibility without full reload
    document.querySelectorAll('[data-col-dot]').forEach(dot => {
      const colId = dot.dataset.colDot;
      dot.style.display = _runningByColId[colId] ? '' : 'none';
    });
  }
```

- [ ] **Step 3: Start the polling loop inside `reload()`**

At the end of the existing `reload()` function (after all collections are rendered), add:

```js
    // Start/restart running-status poll
    if (_runningPollTimer) clearInterval(_runningPollTimer);
    await _refreshRunningStatus(); // immediate first check
    _runningPollTimer = setInterval(_refreshRunningStatus, 3000);
```

- [ ] **Step 4: Add pulsing dot and name-click handler to collection header render**

Find the section inside `collections.forEach(col => {` where `leftSide` is constructed:

```js
const leftSide = document.createElement('span');
leftSide.innerHTML = `<strong>${_esc(col.name)}</strong> <span class="text-muted text-sm">(${col.request_count})</span>`;
header.appendChild(leftSide);
```

Replace with:

```js
const leftSide = document.createElement('span');
leftSide.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1;min-width:0;';
leftSide.innerHTML = `
  <span data-col-dot="${col.id}" style="display:none;width:7px;height:7px;border-radius:50%;
    background:var(--warning,#f59e0b);flex-shrink:0;animation:cdot-pulse 1s infinite"></span>
  <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(col.name)}</strong>
  <span class="text-muted text-sm" style="flex-shrink:0;">(${col.request_count})</span>`;
leftSide.onclick = (e) => {
  e.stopPropagation();
  if (onSelectCollection) {
    const runId = _runningByColId[col.id] || null;
    onSelectCollection(col, runId);
  }
};
header.appendChild(leftSide);
```

Also add the pulse keyframe style once at the top of `reload()` (before the forEach):

```js
if (!document.getElementById('cdot-style')) {
  const st = document.createElement('style');
  st.id = 'cdot-style';
  st.textContent = '@keyframes cdot-pulse{0%,100%{opacity:1}50%{opacity:.3}}';
  document.head.appendChild(st);
}
```

- [ ] **Step 5: Update `header.onclick` to only toggle expand (not trigger on leftSide click)**

The existing handler:

```js
header.onclick = (e) => {
  if (e.target === expandBtn || e.target === menuBtn || e.target === envSel) return;
  _toggleExpand();
};
```

Change to:

```js
header.onclick = (e) => {
  if (e.target === expandBtn || e.target === menuBtn || e.target === envSel) return;
  if (leftSide.contains(e.target)) return; // name click handled by leftSide.onclick
  _toggleExpand();
};
```

- [ ] **Step 6: Update `_runCollection()` to use `onRunStarted` callback**

Find the existing `_runCollection` function and replace it:

```js
async function _runCollection(colId, colName, envName) {
  const confirmed = await window._confirmDialog(
    `Run '${colName}'?`,
    'All requests in this collection will be executed in order.',
    'Run'
  );
  if (!confirmed) return;
  const res = await window.api('POST', `/collections/${colId}/run`, { env_name: envName || null });
  if (res.ok === false) {
    await window._alertDialog('Run failed: ' + res.error);
    return;
  }
  if (onRunStarted && res.run_id) {
    onRunStarted(res.run_id, colId, colName);
  }
}
```

- [ ] **Step 7: Verify in browser**

Start server: `python qaclan.py serve --port 7823`

1. Navigate to API section
2. Trigger a collection run (⋯ → Run Collection)
3. Verify: run detail page appears in main panel with live progress
4. Navigate away (click Scripts nav item), come back to API
5. Verify: pulsing dot appears next to the collection that's running
6. Click the collection name
7. Verify: main panel shows summary card with "View Progress →" and "■ Stop"
8. Click Stop — verify run stops (status = STOPPED, dot disappears within 3s)

- [ ] **Step 8: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "feat: pulsing dot for running collections, collection name click → detail panel"
```

---

### Task 8: `api-section.js` — wire all views and callbacks

**Files:**
- Modify: `web/static/api/api-section.js`

**Interfaces:**
- Consumes: Tasks 5, 6, 7 (all new view exports + updated `renderCollectionsView` signature)
- Produces: fully wired API section with run detail, collection detail, running dots

- [ ] **Step 1: Add new imports to `_loadViews()`**

Find the existing `_loadViews` function:

```js
async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
    { renderDocsView },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
    import('./views/docs-view.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal, renderDocsView };
}
```

Replace with:

```js
async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
    { renderDocsView },
    { renderCollectionRunView },
    { renderCollectionDetailView },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
    import('./views/docs-view.js'),
    import('./views/collection-run-view.js'),
    import('./views/collection-detail-view.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal, renderDocsView,
           renderCollectionRunView, renderCollectionDetailView };
}
```

- [ ] **Step 2: Wire all callbacks in `renderApiPage()`**

Find the `_getViews().then(...)` block inside `renderApiPage`. Replace it entirely:

```js
  _getViews().then(({
    renderCollectionsView, renderRequestEditor, showDiscoverModal,
    renderCollectionRunView, renderCollectionDetailView
  }) => {
    const mainEl = () => document.getElementById('api-main-content');

    function _teardown() {
      const el = mainEl();
      if (el && el.__destroyRunView) { el.__destroyRunView(); el.__destroyRunView = null; }
    }

    function _emptyMain() {
      _teardown();
      const el = mainEl();
      if (el) el.innerHTML = '<div class="empty-state"><p>Select a request or collection to get started.</p></div>';
    }

    function _showRunDetail(runId, colId, colName) {
      _teardown();
      renderCollectionRunView(mainEl(), runId, colId, colName, _emptyMain);
    }

    function _showCollectionDetail(col, runId) {
      _teardown();
      renderCollectionDetailView(
        mainEl(), col, runId,
        (rid) => _showRunDetail(rid, col.id, col.name),  // onViewRun
        _emptyMain                                        // onBack
      );
    }

    renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId, defaultCollectionId, collectionId, collectionEnvName) => {
        _teardown();
        renderRequestEditor(mainEl(), requestId, defaultCollectionId, collectionId, collectionEnvName);
      },
      (runId, colId, colName) => _showRunDetail(runId, colId, colName),       // onRunStarted
      (col, runId) => _showCollectionDetail(col, runId)                        // onSelectCollection
    );

    document.getElementById('api-discover-btn').onclick = () => showDiscoverModal();
  }).catch(err => {
    console.error('API section load error:', err);
    const m = document.getElementById('api-main-content');
    if (m) m.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Failed to load: ${err.message}</p></div>`;
  });
```

- [ ] **Step 3: End-to-end browser test**

Start server: `python qaclan.py serve --port 7823`

Run through the full flow:

1. **Run + live progress**: Click ⋯ → Run on a collection → navigates to run detail → requests appear as they complete → progress bar fills → Stop button visible
2. **Stop mid-run**: While RUNNING, click ■ Stop → run halts, status shows STOPPED, pending rows stay pending
3. **Navigate away and back**: While a collection runs, click Scripts in nav → click API → pulsing dot appears next to the running collection
4. **Collection detail**: Click the collection **name** (not ▾) → main panel shows summary card with "View Progress →" and "■ Stop"
5. **View progress from detail**: Click "View Progress →" → navigates to full run detail page
6. **Duplicate run guard**: With one collection running, click ⋯ → Run on the same collection → no new run created, navigates to the existing running run
7. **Refresh during run**: While RUNNING, refresh the page → navigate back to API section → pulsing dot still there → click name → summary card shows partial progress
8. **Report**: After run completes, Report button appears → click opens HTML report

- [ ] **Step 4: Commit**

```bash
git add web/static/api/api-section.js
git commit -m "feat: wire CollectionRunView, CollectionDetailView, pulsing dots into API section"
```
