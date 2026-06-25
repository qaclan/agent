# Collection Run Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show live request-by-request progress when a collection runs — navigate immediately to a dedicated run page that polls for updates, renders each request as it completes, and persists state in the DB so refresh never loses progress.

**Architecture:** Background thread executes the collection run while the route returns `run_id` immediately. Frontend polls `GET /api/api-collection-runs/<run_id>` every 1s while `status === 'RUNNING'`. A new `collection-run-view.js` renders the progress page inside the existing `api-main-content` panel. DB already persists each result incrementally via `create_request_result()` — one new column (`current_request_index`) signals which request is currently executing.

**Tech Stack:** Python threading (stdlib), Flask, SQLite, vanilla JS ES modules (no build step), existing `window.api()` helper

## Global Constraints
- No automated test framework — verify via `python qaclan.py serve --port 7823` + browser
- Never modify existing `web/routes/*.py` logic beyond specified changes
- Never refactor `web/static/app.js` existing code — additive changes only
- All new Python files: `from __future__ import annotations` as first import
- SQLite only — no JSONB, parse with `json.loads()` before use
- All IDs: `generate_id(prefix)` from `cli/db.py`
- Logger in every new Python module: `logger = logging.getLogger("qaclan.<module_name>")`
- JS files: ES modules only (`export`/`import`), no build step, consistent with existing views in `web/static/api/views/`

---

### Task 1: DB Migration — add `current_request_index`

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Consumes: existing `api_collection_runs` table (has `id`, `status`, `total`, `passed`, `failed`, `error_count`, `started_at`, `finished_at`)
- Produces: `current_request_index INTEGER DEFAULT -1` column on `api_collection_runs`, callable via `_migrate_collection_run_progress(conn)`

- [ ] **Step 1: Add migration function**

Add this function to `cli/db.py` after the existing `_migrate_pre_extractor` function:

```python
def _migrate_collection_run_progress(conn):
    """Add current_request_index to api_collection_runs for live progress tracking."""
    try:
        conn.execute(
            "ALTER TABLE api_collection_runs ADD COLUMN current_request_index INTEGER DEFAULT -1"
        )
    except Exception:
        pass  # Column already exists
    conn.commit()
```

- [ ] **Step 2: Register migration in `init_db()`**

In `cli/db.py`, the last line of `init_db()` currently ends with:
```python
    _migrate_pre_extractor(conn)
```

Add the new migration call directly after it:
```python
    _migrate_pre_extractor(conn)
    _migrate_collection_run_progress(conn)
```

- [ ] **Step 3: Verify**

```bash
python qaclan.py --help
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_collection_runs);"
```

Expected: output includes a row with `name = current_request_index`.

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat: add current_request_index to api_collection_runs for progress tracking"
```

---

### Task 2: CollectionRunRepo — update_current_index + total at creation

**Files:**
- Modify: `web/api/repositories/collection_run_repo.py`

**Interfaces:**
- Consumes: Task 1 (`current_request_index` column)
- Produces:
  - `CollectionRunRepo.create_run(collection_id, project_id, collection_name, env_name, started_at, total)` — accepts `total: int` param, writes it at creation time
  - `CollectionRunRepo.update_current_index(run_id, idx)` — new method
  - `CollectionRunRepo.get_run(run_id, project_id)` — now includes `current_request_index` in returned dict

- [ ] **Step 1: Update `create_run()` to accept and store `total` at creation**

Current signature: `create_run(self, collection_id, project_id, collection_name, env_name, started_at)`

Current INSERT: sets `total=0` (default).

Replace the full `create_run` method in `web/api/repositories/collection_run_repo.py`:

```python
def create_run(self, collection_id: str, project_id: str, collection_name: str,
               env_name: str | None, started_at: str, total: int = 0) -> str:
    conn = get_conn()
    run_id = generate_id("arun")
    conn.execute(
        "INSERT INTO api_collection_runs "
        "(id, project_id, collection_id, collection_name, env_name, status, "
        "total, passed, failed, error_count, started_at, current_request_index) "
        "VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, 0, 0, 0, ?, -1)",
        (run_id, project_id, collection_id, collection_name, env_name, total, started_at),
    )
    conn.commit()
    logger.info("CollectionRunRepo.create_run: %s (total=%d)", run_id, total)
    return run_id
```

- [ ] **Step 2: Add `update_current_index()` method**

Add this method to `CollectionRunRepo` class in `web/api/repositories/collection_run_repo.py`:

```python
def update_current_index(self, run_id: str, idx: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE api_collection_runs SET current_request_index = ? WHERE id = ?",
        (idx, run_id),
    )
    conn.commit()
```

- [ ] **Step 3: Update `get_run()` to include `current_request_index`**

In the existing `get_run()` method, the SELECT currently reads:

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
    "total, passed, failed, error_count, started_at, finished_at, current_request_index "
    "FROM api_collection_runs WHERE id = ? AND project_id = ?",
    (run_id, project_id),
).fetchone()
```

- [ ] **Step 4: Verify via curl**

Start server: `python qaclan.py serve --port 7823`

Trigger a collection run (use an existing collection ID from your project):
```bash
curl -s -X POST http://localhost:7823/api/collections/<col_id>/run \
  -H 'Content-Type: application/json' -d '{}'
```

Then fetch the run:
```bash
curl -s http://localhost:7823/api/api-collection-runs/<run_id> | python3 -m json.tool
```

Expected: response includes `"current_request_index": -1` (or final index if run is fast).

- [ ] **Step 5: Commit**

```bash
git add web/api/repositories/collection_run_repo.py
git commit -m "feat: add update_current_index to CollectionRunRepo; store total at run creation"
```

---

### Task 3: RunnerService — background thread execution

**Files:**
- Modify: `web/api/services/runner_service.py`

**Interfaces:**
- Consumes: Task 2 (`CollectionRunRepo.update_current_index`, `create_run` with `total` param)
- Produces:
  - `RunnerService.start_collection_run(collection_id, project_id, env_name, seed_vars) -> str` — creates DB row, spawns thread, returns `run_id` immediately
  - `RunnerService._execute_collection(run_id, collection_id, project_id, env_name, seed_vars)` — thread target, contains existing loop logic + `update_current_index` call before each request
  - Existing `run_collection()` method kept unchanged for CLI use

- [ ] **Step 1: Add `start_collection_run()` method**

Add this method to `RunnerService` class in `web/api/services/runner_service.py`:

```python
def start_collection_run(self, collection_id: str, project_id: str,
                          env_name: str | None = None,
                          seed_vars: dict | None = None) -> str:
    """Create DB run row, spawn background thread, return run_id immediately."""
    import threading
    from web.api.repositories.collection_repo import CollectionRepo
    from web.api.repositories.request_repo import RequestRepo
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from datetime import datetime, timezone

    col = CollectionRepo().get(collection_id, project_id)
    if col is None:
        raise LookupError(f"Collection {collection_id} not found")

    requests = RequestRepo().list(project_id, collection_id=collection_id)
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = CollectionRunRepo().create_run(
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
    return run_id
```

- [ ] **Step 2: Add `_execute_collection()` thread target**

Add this method to `RunnerService` class directly after `start_collection_run`:

```python
def _execute_collection(self, run_id: str, collection_id: str, project_id: str,
                         env_name: str | None, seed_vars: dict | None) -> None:
    """Thread target: runs all collection requests, updates DB after each one."""
    # All imports before try so they're available in finally
    from web.api.repositories.collection_repo import CollectionRepo
    from web.api.repositories.request_repo import RequestRepo
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from cli.api_runner import run_api_request
    from datetime import datetime, timezone

    run_repo = CollectionRunRepo()
    results = []  # initialized before try so finally always has it
    final_status = "ERROR"

    try:
        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            logger.error("_execute_collection: collection %s not found", collection_id)
            return  # finally will finish_run with ERROR + empty results

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        env_vars = load_env_vars(project_id, env_name)
        state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

        for idx, req in enumerate(requests):
            run_repo.update_current_index(run_id, idx)
            result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
            results.append(result)
            run_repo.create_request_result(run_id, req, result, idx)

        passed = sum(1 for r in results if r.get("status") == "PASSED")
        failed_count = sum(1 for r in results if r.get("status") == "FAILED")
        error_count = sum(1 for r in results if r.get("status") == "ERROR")
        final_status = "PASSED" if (failed_count + error_count) == 0 and results else "FAILED"

    except Exception:
        logger.exception("_execute_collection: unhandled error in run %s", run_id)
        # final_status stays "ERROR", results has whatever completed so far

    finally:
        passed = sum(1 for r in results if r.get("status") == "PASSED")
        failed_count = sum(1 for r in results if r.get("status") == "FAILED")
        error_count = sum(1 for r in results if r.get("status") == "ERROR")
        run_repo.finish_run(
            run_id=run_id,
            status=final_status,
            total=len(results),
            passed=passed,
            failed=failed_count,
            error_count=error_count,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("_execute_collection: run %s finished → %s", run_id, final_status)
```

- [ ] **Step 3: Verify existing `run_collection()` is untouched**

Check that `run_collection()` method still exists unchanged in `runner_service.py`. It must remain for CLI use (`qaclan api run --collection`).

```bash
grep -n "def run_collection" web/api/services/runner_service.py
```

Expected: one hit showing the existing method still present.

- [ ] **Step 4: Commit**

```bash
git add web/api/services/runner_service.py
git commit -m "feat: add start_collection_run and _execute_collection for background thread execution"
```

---

### Task 4: Route — return run_id immediately

**Files:**
- Modify: `web/api/routes/collections.py`

**Interfaces:**
- Consumes: Task 3 (`RunnerService.start_collection_run(collection_id, project_id, env_name, seed_vars) -> str`)
- Produces: `POST /api/collections/<col_id>/run` returns `{"ok": true, "run_id": "<id>", "status": "RUNNING"}` immediately

- [ ] **Step 1: Update `run_collection` route**

In `web/api/routes/collections.py`, find the existing `run_collection` route. It currently calls `_runner_svc.run_collection(...)` and returns the full result. Replace the body with:

```python
@bp.route("/api/collections/<col_id>/run", methods=["POST"])
def run_collection(col_id):
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name") or None
        seed_vars = data.get("seed_vars") or None
        pid = _project_id()
        run_id = _runner_svc.start_collection_run(
            col_id, pid, env_name=env_name, seed_vars=seed_vars
        )
        return jsonify({"ok": True, "run_id": run_id, "status": "RUNNING"})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("run_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Verify the route returns immediately**

Start server and trigger a run. The response must come back within ~200ms, not after all requests complete:

```bash
time curl -s -X POST http://localhost:7823/api/collections/<col_id>/run \
  -H 'Content-Type: application/json' -d '{}'
```

Expected: response `{"ok": true, "run_id": "arun_...", "status": "RUNNING"}` in under 1 second (regardless of how many requests are in the collection).

- [ ] **Step 3: Verify run completes in background**

```bash
# Replace <run_id> with the ID from step 2
sleep 5 && curl -s http://localhost:7823/api/api-collection-runs/<run_id> | python3 -m json.tool
```

Expected: `"status"` is `"PASSED"` or `"FAILED"` (not `"RUNNING"`) after the collection finishes. `"request_results"` is populated. `"current_request_index"` is at the last index.

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/collections.py
git commit -m "feat: make collection run non-blocking — return run_id immediately"
```

---

### Task 5: Frontend — CollectionRunView

**Files:**
- Create: `web/static/api/views/collection-run-view.js`

**Interfaces:**
- Consumes:
  - `GET /api/api-collection-runs/<run_id>` → `{ ok, run: { id, collection_id, collection_name, status, total, passed, failed, error_count, started_at, finished_at, current_request_index, request_results: [{request_name, method, url, order_index, status, status_code, duration_ms, assertion_results, error_message, response_body}] } }`
  - `GET /api/collections/<collection_id>` → `{ ok, collection: { requests: [{id, name, method, url, order_index}] } }`
- Produces: `export function renderCollectionRunView(container, runId, collectionId, collectionName)` — renders live progress page into `container`, handles its own polling lifecycle

- [ ] **Step 1: Create `web/static/api/views/collection-run-view.js`**

```js
/**
 * renderCollectionRunView(container, runId, collectionId, collectionName)
 * Renders live collection run progress. Polls GET /api/api-collection-runs/<runId>
 * every 1s while status === 'RUNNING'. Stops polling on PASSED/FAILED/ERROR.
 */
export function renderCollectionRunView(container, runId, collectionId, collectionName) {
  let _pollTimer = null;
  let _startedAt = null;
  let _elapsedTimer = null;
  let _allRequests = []; // full ordered request list from collection
  let _destroyed = false;

  // ── Teardown ──────────────────────────────────────────────────────────────
  function _destroy() {
    _destroyed = true;
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }

  // Store teardown on container so api-section.js can call it before re-render
  container.__destroyRunView = _destroy;

  // ── Elapsed timer ─────────────────────────────────────────────────────────
  function _startElapsedTimer() {
    if (_elapsedTimer) return;
    _elapsedTimer = setInterval(() => {
      const el = document.getElementById('crv-elapsed');
      if (!el || !_startedAt) return;
      const secs = Math.floor((Date.now() - new Date(_startedAt).getTime()) / 1000);
      const mm = String(Math.floor(secs / 60)).padStart(2, '0');
      const ss = String(secs % 60).padStart(2, '0');
      el.textContent = `${mm}:${ss}`;
    }, 1000);
  }

  // ── Status badge ──────────────────────────────────────────────────────────
  function _statusBadge(status) {
    const colors = {
      RUNNING: 'color:var(--warning,#f59e0b)',
      PASSED:  'color:var(--success,#22c55e)',
      FAILED:  'color:var(--danger,#ef4444)',
      ERROR:   'color:var(--danger,#ef4444)',
    };
    const style = colors[status] || '';
    const dot = status === 'RUNNING'
      ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warning,#f59e0b);margin-right:5px;animation:crv-pulse 1s infinite"></span>'
      : '';
    return `<span style="font-weight:600;font-size:13px;${style}">${dot}${status}</span>`;
  }

  // ── Render shell (called once) ────────────────────────────────────────────
  function _renderShell() {
    container.innerHTML = `
      <style>
        @keyframes crv-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes crv-spin  { to{transform:rotate(360deg)} }
        .crv-row { display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:12px;cursor:pointer;transition:background .12s; }
        .crv-row:hover { background:var(--bg-hover,rgba(255,255,255,.04)); }
        .crv-row-detail { padding:12px 16px;background:var(--bg-inset,rgba(0,0,0,.18));border-bottom:1px solid var(--border-subtle,rgba(255,255,255,.07));font-size:11px;display:none; }
        .crv-row-detail.open { display:block; }
        .crv-badge-pass { color:var(--success,#22c55e);font-weight:600; }
        .crv-badge-fail { color:var(--danger,#ef4444);font-weight:600; }
        .crv-badge-err  { color:var(--warning,#f59e0b);font-weight:600; }
        .crv-badge-run  { color:var(--text-muted,#888); }
        .crv-badge-pend { color:var(--text-muted,#888);opacity:.5; }
        .crv-spinner { display:inline-block;width:11px;height:11px;border:2px solid var(--border-default,#444);border-top-color:var(--text-secondary,#aaa);border-radius:50%;animation:crv-spin .7s linear infinite;vertical-align:middle; }
        .crv-progress-bar { height:4px;background:var(--border-subtle,rgba(255,255,255,.1));border-radius:2px;overflow:hidden;margin:10px 0; }
        .crv-progress-fill { height:100%;background:var(--primary,#6366f1);border-radius:2px;transition:width .3s; }
        .crv-method { font-family:monospace;font-size:11px;font-weight:600;min-width:52px;display:inline-block; }
        .crv-name   { flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-primary); }
        .crv-dur    { font-size:11px;color:var(--text-muted,#888);min-width:60px;text-align:right; }
        .crv-code   { font-size:11px;color:var(--text-muted,#888);min-width:36px;text-align:right; }
        .crv-expand-btn { font-size:10px;color:var(--text-muted,#888);min-width:16px;text-align:right; }
        .crv-assert-pass { color:var(--success,#22c55e); }
        .crv-assert-fail { color:var(--danger,#ef4444); }
        pre.crv-body { margin:6px 0 0;padding:8px;background:var(--bg-code,rgba(0,0,0,.25));border-radius:4px;font-size:10px;white-space:pre-wrap;word-break:break-all;max-height:180px;overflow-y:auto;color:var(--text-secondary); }
      </style>
      <div style="padding:16px 20px;border-bottom:1px solid var(--border,rgba(255,255,255,.1));">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <button class="btn btn-xs btn-ghost" id="crv-back">← Back</button>
            <span style="font-size:14px;font-weight:600;color:var(--text-primary)" id="crv-title">${_esc(collectionName)} — Run</span>
          </div>
          <button class="btn btn-xs btn-ghost" id="crv-report-btn" style="display:none">⬇ Report</button>
        </div>
        <div style="display:flex;align-items:center;gap:14px;margin-top:8px;flex-wrap:wrap;">
          <span id="crv-status-badge"></span>
          <span style="font-size:12px;color:var(--text-muted,#888)" id="crv-counts"></span>
          <span style="font-size:12px;color:var(--text-muted,#888)">⏱ <span id="crv-elapsed">00:00</span></span>
        </div>
        <div class="crv-progress-bar"><div class="crv-progress-fill" id="crv-progress-fill" style="width:0%"></div></div>
      </div>
      <div style="overflow-y:auto;flex:1;" id="crv-rows"></div>`;

    document.getElementById('crv-back').onclick = () => {
      _destroy();
      // Re-render the API section into main content (same panel)
      if (window.__qaclanApi) {
        window.__qaclanApi.render(container.closest('#page-content') || container);
      }
    };

    document.getElementById('crv-report-btn').onclick = () => {
      window.open(`/api/api-collection-runs/${runId}/report?view=1`, '_blank');
    };
  }

  // ── Render rows ───────────────────────────────────────────────────────────
  function _renderRows(run) {
    const rowsEl = document.getElementById('crv-rows');
    if (!rowsEl) return;

    const results = run.request_results || [];
    const resultsByIndex = {};
    results.forEach(r => { resultsByIndex[r.order_index] = r; });

    const currentIdx = run.current_request_index ?? -1;
    const spine = _allRequests.length > 0 ? _allRequests : results;
    const total = run.total || spine.length || 0;

    let html = '';
    for (let i = 0; i < total; i++) {
      const req = _allRequests[i] || {};
      const result = resultsByIndex[i];
      const reqName = result ? result.request_name : (req.name || `Request ${i + 1}`);
      const method  = result ? result.method : (req.method || '');
      const rowId   = `crv-r-${i}`;
      const detId   = `crv-d-${i}`;

      let badge, statusText, codeText = '', durText = '', expandBtn = '';

      if (result) {
        if (result.status === 'PASSED') {
          badge = `<span class="crv-badge-pass">✓</span>`;
        } else if (result.status === 'FAILED') {
          badge = `<span class="crv-badge-fail">✗</span>`;
        } else {
          badge = `<span class="crv-badge-err">!</span>`;
        }
        codeText = result.status_code != null ? String(result.status_code) : '';
        durText  = result.duration_ms != null ? `${result.duration_ms}ms` : '';
        expandBtn = `<span class="crv-expand-btn">▼</span>`;
      } else if (i === currentIdx) {
        badge = `<span class="crv-spinner"></span>`;
      } else {
        badge = `<span class="crv-badge-pend">·</span>`;
      }

      html += `
        <div class="crv-row" id="${rowId}" data-idx="${i}">
          ${badge}
          <span class="crv-method">${_esc(method)}</span>
          <span class="crv-name">${_esc(reqName)}</span>
          <span class="crv-code">${_esc(codeText)}</span>
          <span class="crv-dur">${_esc(durText)}</span>
          ${expandBtn}
        </div>`;

      if (result) {
        const assertions = Array.isArray(result.assertion_results) ? result.assertion_results : [];
        const assertHtml = assertions.length ? assertions.map(a =>
          `<div class="${a.passed ? 'crv-assert-pass' : 'crv-assert-fail'}">
            ${a.passed ? '✓' : '✗'} ${_esc(a.type)}
            ${a.path ? ` ${_esc(a.path)}` : ''}
            ${a.op ? ` ${_esc(a.op)}` : ''}
            ${a.value != null ? ` ${_esc(String(a.value))}` : ''}
            ${!a.passed && a.actual != null ? ` → actual: ${_esc(String(a.actual))}` : ''}
          </div>`
        ).join('') : '<div style="color:var(--text-muted,#888)">No assertions</div>';

        const body = result.response_body || '';
        const bodyPreview = body.length > 500 ? body.slice(0, 500) + '\n… (truncated)' : body;
        const errHtml = result.error_message
          ? `<div style="color:var(--danger,#ef4444);margin-bottom:6px">Error: ${_esc(result.error_message)}</div>` : '';

        html += `
          <div class="crv-row-detail" id="${detId}">
            ${errHtml}
            <div style="margin-bottom:6px;font-weight:600;color:var(--text-secondary)">Assertions</div>
            ${assertHtml}
            ${body ? `<div style="margin-top:8px;font-weight:600;color:var(--text-secondary)">Response body</div>
            <pre class="crv-body">${_esc(bodyPreview)}</pre>` : ''}
          </div>`;
      }
    }

    rowsEl.innerHTML = html;

    // Wire expand toggles — only on completed rows
    results.forEach((_, i) => {
      const rowEl = document.getElementById(`crv-r-${i}`);
      const detEl = document.getElementById(`crv-d-${i}`);
      if (rowEl && detEl) {
        rowEl.onclick = () => detEl.classList.toggle('open');
      }
    });
  }

  // ── Update header ─────────────────────────────────────────────────────────
  function _updateHeader(run) {
    const statusEl = document.getElementById('crv-status-badge');
    const countsEl = document.getElementById('crv-counts');
    const fillEl   = document.getElementById('crv-progress-fill');
    const reportBtn = document.getElementById('crv-report-btn');
    if (!statusEl) return;

    statusEl.innerHTML = _statusBadge(run.status);
    const done = (run.request_results || []).length;
    const total = run.total || 0;
    countsEl.textContent = `${done} / ${total}  ·  ${run.passed} passed · ${run.failed} failed · ${run.error_count} errors`;
    fillEl.style.width = total > 0 ? `${Math.round((done / total) * 100)}%` : '0%';
    if (run.status !== 'RUNNING' && reportBtn) reportBtn.style.display = '';
  }

  // ── Poll ──────────────────────────────────────────────────────────────────
  async function _poll() {
    if (_destroyed) return;
    try {
      const res = await window.api('GET', `/api-collection-runs/${runId}`);
      if (!res.ok || !res.run) return;
      const run = res.run;
      if (_startedAt === null) {
        _startedAt = run.started_at;
        _startElapsedTimer();
      }
      _updateHeader(run);
      _renderRows(run);
      if (run.status !== 'RUNNING') {
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
        if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
      }
    } catch (e) {
      console.error('crv poll error:', e);
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  async function _init() {
    _renderShell();

    // Fetch collection's full request list for the spine (pending row names)
    try {
      const colRes = await window.api('GET', `/collections/${collectionId}`);
      if (colRes.ok && colRes.collection && Array.isArray(colRes.collection.requests)) {
        // Sort by created_at (same order as runner) — repo returns in created_at order
        _allRequests = colRes.collection.requests.slice().sort((a, b) =>
          (a.created_at || '').localeCompare(b.created_at || '')
        );
      }
    } catch (e) { /* spine will fall back to request_results only */ }

    await _poll(); // immediate first render
    _pollTimer = setInterval(_poll, 1000);
  }

  _init();
}

function _esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```

- [ ] **Step 2: Verify file exists**

```bash
ls web/static/api/views/collection-run-view.js
```

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/collection-run-view.js
git commit -m "feat: add CollectionRunView with live polling progress"
```

---

### Task 6: Wire frontend — collections-view + api-section

**Files:**
- Modify: `web/static/api/views/collections-view.js`
- Modify: `web/static/api/api-section.js`

**Interfaces:**
- Consumes: Task 5 (`renderCollectionRunView(container, runId, collectionId, collectionName)`)
- Produces:
  - `renderCollectionsView(container, onSelectRequest, onRunStarted)` — adds `onRunStarted` param
  - `api-section.js` imports `renderCollectionRunView`, passes callback to `renderCollectionsView`, tears down previous run view before re-render

- [ ] **Step 1: Update `renderCollectionsView` signature in `collections-view.js`**

In `web/static/api/views/collections-view.js`, the function declaration is:

```js
export function renderCollectionsView(container, onSelectRequest) {
```

Change to:

```js
export function renderCollectionsView(container, onSelectRequest, onRunStarted) {
```

- [ ] **Step 2: Update `_runCollection` in `collections-view.js`**

Find the existing `_runCollection` function (around line 447):

```js
async function _runCollection(colId, colName, envName) {
  const confirmed = await window._confirmDialog(`Run '${colName}'?`, 'All requests in this collection will be executed in order.', 'Run');
  if (!confirmed) return;
  const res = await window.api('POST', `/collections/${colId}/run`, { env_name: envName || null });
  if (res.ok === false) {
    await window._alertDialog('Run failed: ' + res.error);
  } else {
    window._toast(`Run complete: ${res.passed}/${res.total} passed`);
  }
}
```

Replace with:

```js
async function _runCollection(colId, colName, envName) {
  const confirmed = await window._confirmDialog(`Run '${colName}'?`, 'All requests in this collection will be executed in order.', 'Run');
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

- [ ] **Step 3: Update `api-section.js` to import and wire the run view**

In `web/static/api/api-section.js`, find the `_loadViews` function:

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

Change to:

```js
async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
    { renderDocsView },
    { renderCollectionRunView },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
    import('./views/docs-view.js'),
    import('./views/collection-run-view.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal, renderDocsView, renderCollectionRunView };
}
```

- [ ] **Step 4: Pass `onRunStarted` callback in `renderApiPage`**

In `web/static/api/api-section.js`, find the `_getViews().then(...)` block inside `renderApiPage`:

```js
_getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal }) => {
  renderCollectionsView(
    document.getElementById('api-collections-panel'),
    (requestId, defaultCollectionId, collectionId, collectionEnvName) => {
      renderRequestEditor(
        document.getElementById('api-main-content'),
        requestId,
        defaultCollectionId,
        collectionId,
        collectionEnvName,
      );
    }
  );
```

Change to:

```js
_getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal, renderCollectionRunView }) => {
  renderCollectionsView(
    document.getElementById('api-collections-panel'),
    (requestId, defaultCollectionId, collectionId, collectionEnvName) => {
      const mainEl = document.getElementById('api-main-content');
      if (mainEl && mainEl.__destroyRunView) { mainEl.__destroyRunView(); mainEl.__destroyRunView = null; }
      renderRequestEditor(mainEl, requestId, defaultCollectionId, collectionId, collectionEnvName);
    },
    (runId, colId, colName) => {
      const mainEl = document.getElementById('api-main-content');
      if (mainEl && mainEl.__destroyRunView) { mainEl.__destroyRunView(); mainEl.__destroyRunView = null; }
      renderCollectionRunView(mainEl, runId, colId, colName);
    }
  );
```

- [ ] **Step 5: End-to-end browser test**

Start the server:
```bash
python qaclan.py serve --port 7823
```

1. Open `http://localhost:7823` in a browser
2. Navigate to API section
3. Open a collection with 2+ requests
4. Click `⋯` menu → **Run Collection** → confirm
5. Verify: immediately navigates to a run progress page
6. Verify: requests show `⟳ running...` as they execute, then ✓/✗ as they complete
7. Verify: progress bar fills, counts update
8. Verify: after completion, status shows PASSED/FAILED, Report button appears
9. Verify: click ▼ on a completed row — response body and assertions expand
10. Verify: refresh the page while RUNNING (or after completion) — state is preserved
11. Verify: click ← Back returns to API section

- [ ] **Step 6: Commit**

```bash
git add web/static/api/views/collections-view.js web/static/api/api-section.js
git commit -m "feat: wire CollectionRunView into API section — navigate on run, live progress"
```
