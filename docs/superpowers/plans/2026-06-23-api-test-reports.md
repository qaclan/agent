# API Test Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every API collection run to SQLite, expose it in a new "API Runs" tab on the Runs page, and make each run downloadable as a self-contained HTML report.

**Architecture:** Two new DB tables (`api_collection_runs`, `api_request_results`) mirror the `suite_runs` / `script_runs` pattern. `RunnerService.run_collection` writes a result row after each request. A new Flask blueprint adds list/detail/report endpoints. The Runs page gets a tab switcher using the existing `.req-tab` / `.req-tab-bar` CSS classes.

**Tech Stack:** Python 3.10+, Flask, SQLite (WAL, thread-local via `get_conn()`), vanilla JS, self-contained HTML report (no external deps).

## Global Constraints

- No automated test runner — verify manually via `python qaclan.py serve --port 7823`
- All DB migrations: idempotent `CREATE TABLE IF NOT EXISTS` inside a dedicated `_migrate_*` function, called from `_run_migrations()` in `cli/db.py`
- All IDs: `generate_id(prefix)` from `cli/db.py`
- Blueprint pattern: `bp = Blueprint("name", __name__)` registered in `web/server.py` via `app.register_blueprint(bp)`
- HTML report: fully self-contained (inline CSS + JS), no external URLs
- Single-request sends (`/api/api-requests/<id>/send`) remain ephemeral — no changes to `run_request`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `cli/db.py` | Modify | Add `_migrate_api_collection_runs()` + call in `_run_migrations()` |
| `web/api/repositories/collection_run_repo.py` | Create | CRUD for `api_collection_runs` + `api_request_results` |
| `cli/api_runner.py` | Modify | Add resolved `url` to every result dict |
| `web/api/services/runner_service.py` | Modify | Persist run + per-request rows in `run_collection` |
| `web/api/routes/api_collection_runs.py` | Create | 3 routes: list, detail, report download |
| `web/server.py` | Modify | Register new blueprint |
| `cli/api_report.py` | Create | `generate_api_html_report(run_id, project_id) -> str` |
| `web/static/app.js` | Modify | Runs page tab switcher + API Runs tab rendering |

---

## Task 1: DB Migration

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: tables `api_collection_runs` and `api_request_results` available after app start

- [ ] **Step 1: Add migration function to `cli/db.py`**

Find the end of the existing migration functions (after `_migrate_collection_auth`). Add:

```python
def _migrate_api_collection_runs(conn):
    """Create api_collection_runs and api_request_results tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_collection_runs (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL,
            collection_id   TEXT NOT NULL REFERENCES api_collections(id) ON DELETE CASCADE,
            collection_name TEXT NOT NULL,
            env_name        TEXT,
            status          TEXT NOT NULL,
            total           INTEGER NOT NULL DEFAULT 0,
            passed          INTEGER NOT NULL DEFAULT 0,
            failed          INTEGER NOT NULL DEFAULT 0,
            error_count     INTEGER NOT NULL DEFAULT 0,
            started_at      TEXT NOT NULL,
            finished_at     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_request_results (
            id                TEXT PRIMARY KEY,
            collection_run_id TEXT NOT NULL REFERENCES api_collection_runs(id) ON DELETE CASCADE,
            api_request_id    TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
            request_name      TEXT NOT NULL,
            method            TEXT,
            url               TEXT,
            order_index       INTEGER NOT NULL DEFAULT 0,
            status            TEXT,
            status_code       INTEGER,
            response_body     TEXT,
            response_headers  TEXT,
            duration_ms       INTEGER,
            assertion_results TEXT,
            error_message     TEXT,
            started_at        TEXT,
            finished_at       TEXT
        )
    """)
    conn.commit()
```

- [ ] **Step 2: Register the migration in `_run_migrations()`**

In `cli/db.py`, find the `_run_migrations` function (around line 134). Add the call at the end of the sequence:

```python
    _migrate_collection_auth(conn)
    _migrate_api_collection_runs(conn)   # ← add this line
```

- [ ] **Step 3: Verify migration runs**

```bash
python qaclan.py --help
# Should print help without error

python -c "
from cli.db import get_conn, init_db
init_db()
conn = get_conn()
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('api_collection_runs' in tables, 'api_request_results' in tables)
"
# Expected: True True
```

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat: add api_collection_runs and api_request_results DB tables"
```

---

## Task 2: CollectionRunRepo

**Files:**
- Create: `web/api/repositories/collection_run_repo.py`

**Interfaces:**
- Consumes: `get_conn()`, `generate_id()` from `cli/db.py`
- Produces:
  - `CollectionRunRepo().create_run(collection_id: str, project_id: str, collection_name: str, env_name: str | None, started_at: str) -> str` — returns run_id
  - `CollectionRunRepo().finish_run(run_id: str, status: str, total: int, passed: int, failed: int, error_count: int, finished_at: str) -> None`
  - `CollectionRunRepo().create_request_result(collection_run_id: str, req: dict, result: dict, order_index: int) -> None`
  - `CollectionRunRepo().list_runs(project_id: str) -> list[dict]`
  - `CollectionRunRepo().get_run(run_id: str, project_id: str) -> dict | None` — includes `request_results` list

- [ ] **Step 1: Create the file**

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.collection_run_repo")


def _deser_result(row: dict) -> dict:
    out = dict(row)
    for key in ("response_headers", "assertion_results"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = None
    return out


class CollectionRunRepo:

    def create_run(self, collection_id: str, project_id: str, collection_name: str,
                   env_name: str | None, started_at: str) -> str:
        conn = get_conn()
        run_id = generate_id("arun")
        conn.execute(
            "INSERT INTO api_collection_runs "
            "(id, project_id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at) "
            "VALUES (?, ?, ?, ?, ?, 'RUNNING', 0, 0, 0, 0, ?)",
            (run_id, project_id, collection_id, collection_name, env_name, started_at),
        )
        conn.commit()
        logger.info("CollectionRunRepo.create_run: %s", run_id)
        return run_id

    def finish_run(self, run_id: str, status: str, total: int, passed: int,
                   failed: int, error_count: int, finished_at: str) -> None:
        conn = get_conn()
        conn.execute(
            "UPDATE api_collection_runs "
            "SET status=?, total=?, passed=?, failed=?, error_count=?, finished_at=? "
            "WHERE id=?",
            (status, total, passed, failed, error_count, finished_at, run_id),
        )
        conn.commit()
        logger.info("CollectionRunRepo.finish_run: %s → %s", run_id, status)

    def create_request_result(self, collection_run_id: str, req: dict,
                               result: dict, order_index: int) -> None:
        conn = get_conn()
        rid = generate_id("arreq")
        resp_headers = result.get("response_headers")
        assert_results = result.get("assertion_results")
        conn.execute(
            "INSERT INTO api_request_results "
            "(id, collection_run_id, api_request_id, request_name, method, url, order_index, "
            "status, status_code, response_body, response_headers, duration_ms, "
            "assertion_results, error_message, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid, collection_run_id, req["id"], req.get("name", ""), req.get("method"),
                result.get("url") or req.get("url", ""),
                order_index,
                result.get("status"), result.get("status_code"),
                result.get("response_body"),
                json.dumps(resp_headers) if resp_headers is not None else None,
                result.get("duration_ms"),
                json.dumps(assert_results) if assert_results is not None else None,
                result.get("error_message"),
                result.get("started_at"),
                result.get("finished_at"),
            ),
        )
        conn.commit()

    def list_runs(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE project_id = ? "
            "ORDER BY started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, collection_id, collection_name, env_name, status, "
            "total, passed, failed, error_count, started_at, finished_at "
            "FROM api_collection_runs WHERE id = ? AND project_id = ?",
            (run_id, project_id),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        result_rows = conn.execute(
            "SELECT id, api_request_id, request_name, method, url, order_index, "
            "status, status_code, response_body, response_headers, duration_ms, "
            "assertion_results, error_message, started_at, finished_at "
            "FROM api_request_results WHERE collection_run_id = ? ORDER BY order_index",
            (run_id,),
        ).fetchall()
        run["request_results"] = [_deser_result(dict(r)) for r in result_rows]
        return run
```

- [ ] **Step 2: Smoke-test the import**

```bash
python -c "from web.api.repositories.collection_run_repo import CollectionRunRepo; print('ok')"
# Expected: ok
```

- [ ] **Step 3: Commit**

```bash
git add web/api/repositories/collection_run_repo.py
git commit -m "feat: add CollectionRunRepo for api_collection_runs persistence"
```

---

## Task 3: Add `url` to runner result + persist runs in `run_collection`

**Files:**
- Modify: `cli/api_runner.py`
- Modify: `web/api/services/runner_service.py`

**Interfaces:**
- Consumes: `CollectionRunRepo` from Task 2
- Produces:
  - `run_api_request()` result dict now always includes `"url": str` (resolved URL, empty string on pre-request error)
  - `RunnerService.run_collection()` returns dict that now includes `"run_id": str`

- [ ] **Step 1: Initialize `url` before the try block in `run_api_request`**

In `cli/api_runner.py`, find `def run_api_request` (line 357). The function currently sets `started_at` and `start_time` then opens a `try:` block where `url = resolve_vars(...)` is the first line.

Change the top of the function to initialize `url` before the try block:

```python
def run_api_request(req: dict, env_vars: dict, state: dict, state_path: str | None = None) -> dict:
    import httpx

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()
    url = req.get("url", "")          # ← add this line before try

    try:
        # 1. Resolve variables in URL, headers, params
        url = resolve_vars(req.get("url", ""), env_vars, state)
        # ... rest of try block unchanged
```

- [ ] **Step 2: Add `"url": url` to the success return dict**

Still in `run_api_request`, find the `return` at the end of the `try` block (around line 523). Add `"url": url`:

```python
        return {
            "status": status,
            "status_code": status_code,
            "url": url,                    # ← add this
            "response_body": response_body,
            "response_headers": response_headers,
            "duration_ms": duration_ms,
            "assertion_results": assertion_results,
            "error_message": None,
            "state_updates": state_updates,
            "started_at": started_at,
            "finished_at": finished_at,
        }
```

- [ ] **Step 3: Add `"url": url` to both error return dicts**

In the `except httpx.TimeoutException` block and the `except Exception` block, add `"url": url` the same way. `url` is now defined before the try block, so it's always in scope even if the exception fires before resolution.

```python
    except httpx.TimeoutException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Request timed out after {timeout_ms}ms"
        logger.error("run_api_request: timeout — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "url": url,                    # ← add this
            "response_body": None,
            ...
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = str(e)
        logger.error("run_api_request: error — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "url": url,                    # ← add this
            "response_body": None,
            ...
        }
```

- [ ] **Step 4: Modify `RunnerService.run_collection` to persist runs**

Replace the entire `run_collection` method in `web/api/services/runner_service.py`:

```python
def run_collection(self, collection_id: str, project_id: str,
                   env_name: str | None = None,
                   seed_vars: dict | None = None) -> dict:
    """Run all requests in a collection sequentially. Results persisted to api_collection_runs."""
    from web.api.repositories.collection_repo import CollectionRepo
    from web.api.repositories.request_repo import RequestRepo
    from web.api.repositories.collection_run_repo import CollectionRunRepo
    from cli.api_runner import run_api_request
    from datetime import datetime, timezone

    col = CollectionRepo().get(collection_id, project_id)
    if col is None:
        raise LookupError(f"Collection {collection_id} not found")

    requests = RequestRepo().list(project_id, collection_id=collection_id)
    env_vars = load_env_vars(project_id, env_name)

    state: dict = {"qaclan_vars": dict(seed_vars)} if seed_vars else {}

    started_at = datetime.now(timezone.utc).isoformat()
    run_repo = CollectionRunRepo()
    run_id = run_repo.create_run(
        collection_id=collection_id,
        project_id=project_id,
        collection_name=col["name"],
        env_name=env_name,
        started_at=started_at,
    )

    results = []
    for idx, req in enumerate(requests):
        result = run_api_request(_resolve_auth(req, col), env_vars, state, state_path=None)
        results.append({
            "request_id": req["id"],
            "name": req["name"],
            "method": req["method"],
            "url": result.get("url") or req.get("url", ""),
            **result,
        })
        run_repo.create_request_result(run_id, req, result, idx)

    passed = sum(1 for r in results if r["status"] == "PASSED")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    error_count = sum(1 for r in results if r["status"] == "ERROR")
    final_status = "PASSED" if (failed + error_count) == 0 else "FAILED"
    finished_at = datetime.now(timezone.utc).isoformat()

    run_repo.finish_run(
        run_id=run_id,
        status=final_status,
        total=len(requests),
        passed=passed,
        failed=failed,
        error_count=error_count,
        finished_at=finished_at,
    )

    return {
        "run_id": run_id,
        "collection_id": collection_id,
        "collection_name": col["name"],
        "status": final_status,
        "total": len(requests),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
```

- [ ] **Step 5: Verify end-to-end with a test run**

Start the server and run a collection via the UI or curl. Then check the DB:

```bash
python qaclan.py serve --port 7823 &
# Run a collection via UI or:
# curl -s -X POST http://localhost:7823/api/collections/<col_id>/run -H 'Content-Type: application/json' -d '{}'

python -c "
from cli.db import get_conn, init_db
init_db()
conn = get_conn()
runs = conn.execute('SELECT id, status, total, passed FROM api_collection_runs LIMIT 3').fetchall()
for r in runs: print(dict(r))
results = conn.execute('SELECT id, request_name, status, status_code FROM api_request_results LIMIT 5').fetchall()
for r in results: print(dict(r))
"
# Expected: rows appear in both tables
```

- [ ] **Step 6: Commit**

```bash
git add cli/api_runner.py web/api/services/runner_service.py
git commit -m "feat: persist API collection runs to DB, add url to runner result"
```

---

## Task 4: API Routes + Blueprint Registration

**Files:**
- Create: `web/api/routes/api_collection_runs.py`
- Modify: `web/server.py`

**Interfaces:**
- Consumes: `CollectionRunRepo.list_runs`, `CollectionRunRepo.get_run` (Task 2); `generate_api_html_report` (Task 5 — import is deferred inside the route, so this file can be created before Task 5)
- Produces:
  - `GET /api/api-collection-runs` → `{"ok": true, "runs": [...]}`
  - `GET /api/api-collection-runs/<run_id>` → `{"ok": true, "run": {..., "request_results": [...]}}`
  - `GET /api/api-collection-runs/<run_id>/report` → HTML file (`?view=1` = inline, default = attachment)

- [ ] **Step 1: Create `web/api/routes/api_collection_runs.py`**

```python
from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request, Response
from cli.config import get_active_project_id
from web.api.repositories.collection_run_repo import CollectionRunRepo

logger = logging.getLogger("qaclan.routes.api_collection_runs")
bp = Blueprint("api_collection_runs_bp", __name__)
_repo = CollectionRunRepo()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/api-collection-runs", methods=["GET"])
def list_api_collection_runs():
    try:
        runs = _repo.list_runs(_project_id())
        return jsonify({"ok": True, "runs": runs})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_api_collection_runs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-collection-runs/<run_id>", methods=["GET"])
def get_api_collection_run(run_id):
    try:
        pid = _project_id()
        run = _repo.get_run(run_id, pid)
        if run is None:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404
        return jsonify({"ok": True, "run": run})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_api_collection_run")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-collection-runs/<run_id>/report", methods=["GET"])
def download_api_report(run_id):
    try:
        from cli.api_report import generate_api_html_report
        pid = _project_id()
        html_str = generate_api_html_report(run_id, pid)
        view = request.args.get("view") == "1"
        disposition = "inline" if view else "attachment"
        return Response(
            html_str,
            mimetype="text/html",
            headers={
                "Content-Disposition": (
                    f'{disposition}; filename="qaclan-api-report-{run_id}.html"'
                )
            },
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("download_api_report")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Register blueprint in `web/server.py`**

At the top of `web/server.py`, add the import after the existing API route imports:

```python
from .api.routes.api_collection_runs import bp as api_collection_runs_bp
```

Then in the `create_app()` function, add `api_collection_runs_bp` to the `register_blueprint` loop:

```python
    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp, sync_bp,
               api_collections_bp, api_requests_bp, api_discovery_bp, api_runs_bp, api_docs_bp,
               api_collection_runs_bp]:   # ← add here
        app.register_blueprint(bp)
```

- [ ] **Step 3: Verify routes are registered**

```bash
python -c "
from web.server import create_app
app = create_app()
rules = [str(r) for r in app.url_map.iter_rules() if 'api-collection-runs' in str(r)]
print(rules)
"
# Expected:
# ['/api/api-collection-runs', '/api/api-collection-runs/<run_id>', '/api/api-collection-runs/<run_id>/report']
```

- [ ] **Step 4: Test list endpoint (requires running server + at least one completed run from Task 3)**

```bash
curl -s http://localhost:7823/api/api-collection-runs | python -m json.tool
# Expected: {"ok": true, "runs": [...]}
```

- [ ] **Step 5: Commit**

```bash
git add web/api/routes/api_collection_runs.py web/server.py
git commit -m "feat: add API collection runs routes and register blueprint"
```

---

## Task 5: HTML Report Generator

**Files:**
- Create: `cli/api_report.py`

**Interfaces:**
- Consumes: `get_conn()` from `cli/db.py`; `_AGENT_VERSION` from `cli/_version.py` (with fallback)
- Produces: `generate_api_html_report(run_id: str, project_id: str) -> str` — raises `ValueError` if run not found

- [ ] **Step 1: Create `cli/api_report.py`**

```python
"""Self-contained HTML report generator for API collection runs.

Mirrors cli/report.py — produces a single HTML file with no external deps.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from cli.db import get_conn

try:
    from cli._version import __version__ as _AGENT_VERSION
except Exception:
    _AGENT_VERSION = ""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value)


def _duration(started, finished) -> str:
    if not started or not finished:
        return "—"
    try:
        d = (
            datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        ).total_seconds()
        if d < 1:
            return f"{int(d * 1000)}ms"
        return f"{d:.1f}s"
    except (ValueError, TypeError):
        return "—"


def _render_body(body: str | None) -> str:
    if not body:
        return "<pre><em>(empty)</em></pre>"
    try:
        parsed = json.loads(body)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return f"<pre>{_esc(formatted)}</pre>"
    except (ValueError, TypeError):
        return f"<pre>{_esc(body[:8000])}</pre>"


_OP_LABELS = {
    "eq": "equals", "ne": "does not equal", "lt": "is less than",
    "gt": "is greater than", "contains": "contains",
    "exists": "exists", "not_exists": "does not exist", "matches": "matches pattern",
}

_METHOD_COLORS = {
    "GET": "#0969da", "POST": "#1a7f37", "PUT": "#e16f24",
    "PATCH": "#9a6700", "DELETE": "#cf222e", "HEAD": "#6e40c9", "OPTIONS": "#57606a",
}


def _assertion_label(a: dict) -> str:
    atype = a.get("type", "")
    op = _OP_LABELS.get(a.get("op", "eq"), a.get("op", ""))
    val = _esc(str(a.get("value", "")))
    if atype == "status":
        return f"Status code {op} <strong>{val}</strong>"
    if atype == "json_path":
        path = _esc(a.get("path", "$"))
        return f"JSON path <code>{path}</code> {op} <strong>{val}</strong>"
    if atype == "header":
        key = _esc(a.get("key", ""))
        return f"Header <code>{key}</code> {op} <strong>{val}</strong>"
    if atype == "response_time":
        return f"Response time {op} <strong>{val}ms</strong>"
    if atype == "body_text":
        return f"Response body {op} <strong>{val}</strong>"
    return f"{_esc(atype)} {op} <strong>{val}</strong>"


def _render_assertions(assertions: list) -> str:
    if not assertions:
        return '<p style="color:#57606a;font-size:12px;margin:4px 0">No assertions defined</p>'
    rows = []
    for a in assertions:
        passed = a.get("passed", False)
        icon = "✓" if passed else "✗"
        color = "#1a7f37" if passed else "#cf222e"
        actual = _esc(str(a.get("actual"))) if a.get("actual") is not None else "—"
        expected = _esc(str(a.get("value"))) if a.get("value") is not None else "—"
        detail = (
            f'<span style="color:#57606a;font-family:monospace;font-size:11px">'
            f'expected: {expected} · got: {actual}</span>'
            if not passed else
            f'<span style="color:#57606a;font-family:monospace;font-size:11px">'
            f'got: {actual}</span>'
        )
        rows.append(
            f'<div style="display:flex;align-items:flex-start;gap:8px;'
            f'padding:5px 0;border-bottom:1px solid #f0f0f0">'
            f'<span style="color:{color};font-size:14px;width:18px;flex-shrink:0">{icon}</span>'
            f'<div><div style="font-size:12px">{_assertion_label(a)}</div>'
            f'<div>{detail}</div></div>'
            f'</div>'
        )
    return "".join(rows)


def _render_headers_table(headers) -> str:
    if not headers or not isinstance(headers, dict):
        return '<p style="color:#57606a;font-size:12px;margin:4px 0">No headers</p>'
    rows = "".join(
        f'<tr><td style="padding:3px 8px;font-weight:600;color:#57606a;width:220px;'
        f'font-size:12px;border-bottom:1px solid #eee">{_esc(k)}</td>'
        f'<td style="padding:3px 8px;font-size:12px;border-bottom:1px solid #eee;'
        f'font-family:monospace;word-break:break-all">{_esc(str(v))}</td></tr>'
        for k, v in headers.items()
    )
    return f'<table style="width:100%;border-collapse:collapse"><tbody>{rows}</tbody></table>'


def _render_request_rows(request_results: list) -> str:
    rows = []
    for i, rr in enumerate(request_results):
        rid = _esc(rr.get("id", str(i)))
        method = (rr.get("method") or "GET").upper()
        method_color = _METHOD_COLORS.get(method, "#57606a")
        name = _esc(rr.get("request_name") or "")
        url = _esc(rr.get("url") or "")
        status = rr.get("status") or "ERROR"
        code = rr.get("status_code")
        duration_ms = rr.get("duration_ms")
        assertions = rr.get("assertion_results") or []
        error_msg = rr.get("error_message")

        passed_count = sum(1 for a in assertions if a.get("passed"))
        total_count = len(assertions)
        status_color = {"PASSED": "#1a7f37", "FAILED": "#cf222e", "ERROR": "#9a6700"}.get(
            status, "#9a6700"
        )

        error_html = (
            f'<div style="background:#fff8f0;border:1px solid #f5c2a0;border-radius:6px;'
            f'padding:10px 14px;font-size:12px;color:#8a3a00;margin-bottom:10px">'
            f'<strong>Error:</strong> {_esc(error_msg)}</div>'
            if error_msg else ""
        )

        detail_html = (
            f'<tr class="det-{rid}" style="display:none">'
            f'<td colspan="8" style="padding:0;background:#f6f8fa;border-bottom:2px solid #d0d7de">'
            f'<div style="padding:14px 16px">'
            f'{error_html}'
            f'<div style="margin-bottom:14px">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Assertions</div>'
            f'{_render_assertions(assertions)}'
            f'</div>'
            f'<div style="margin-bottom:14px">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Response Headers</div>'
            f'{_render_headers_table(rr.get("response_headers"))}'
            f'</div>'
            f'<div>'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Response Body</div>'
            f'{_render_body(rr.get("response_body"))}'
            f'</div>'
            f'</div></td></tr>'
        )

        row_html = (
            f'<tr onclick="tog(\'{rid}\')" style="cursor:pointer;border-bottom:1px solid #eee" '
            f'onmouseover="this.style.background=\'#f6f8fa\'" '
            f'onmouseout="this.style.background=\'\'">'
            f'<td style="padding:10px 12px;font-size:12px;color:#57606a">{i + 1}</td>'
            f'<td style="padding:10px 12px">'
            f'<span style="display:inline-block;background:{method_color};color:#fff;'
            f'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            f'min-width:50px;text-align:center">{_esc(method)}</span></td>'
            f'<td style="padding:10px 12px;font-size:13px;font-weight:500">{name}</td>'
            f'<td style="padding:10px 12px;font-size:11px;font-family:monospace;'
            f'color:#57606a;max-width:260px;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap" title="{url}">{url}</td>'
            f'<td style="padding:10px 12px">'
            f'<span style="background:{status_color};color:#fff;font-size:11px;'
            f'font-weight:700;padding:2px 8px;border-radius:6px">{_esc(status)}</span></td>'
            f'<td style="padding:10px 12px;font-size:13px">'
            f'{_esc(str(code)) if code is not None else "—"}</td>'
            f'<td style="padding:10px 12px;font-size:13px">'
            f'{_esc(str(duration_ms)) + "ms" if duration_ms is not None else "—"}</td>'
            f'<td style="padding:10px 12px;font-size:12px;color:#57606a">'
            f'{passed_count}/{total_count} passed</td>'
            f'</tr>'
        )

        rows.append(row_html + detail_html)

    return "".join(rows)


_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QAClan API Report — {title}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1c2128}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:700;margin:0 0 4px}}
pre{{background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:8px 10px;
  font-size:11px;font-family:ui-monospace,Menlo,monospace;overflow-x:auto;
  white-space:pre-wrap;word-break:break-word;margin:0;max-height:320px;overflow-y:auto}}
footer{{color:#8c959f;font-size:11px;margin-top:24px;text-align:center}}
</style>
<script>
function tog(id){{
  var r=document.querySelector('.det-'+id);
  if(r)r.style.display=r.style.display==='table-row'?'none':'table-row';
}}
</script>
</head>
<body>
<div class="wrap">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;flex-wrap:wrap">
    <h1>{title}</h1>
    <span style="background:{status_bg};color:#fff;font-size:13px;font-weight:700;
      padding:4px 14px;border-radius:20px">{status}</span>
  </div>
  <div style="color:#57606a;font-size:13px;margin-bottom:16px">{meta}</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">{stats}</div>
  <div style="height:8px;border-radius:4px;background:#eee;overflow:hidden;margin-bottom:20px">
    <div style="height:100%;width:{passrate}%;background:#1a7f37"></div>
  </div>
  <div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;overflow:hidden">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f6f8fa;border-bottom:1px solid #d0d7de">
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">#</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Method</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Name</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">URL</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Status</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Code</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Duration</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Assertions</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
  <footer>QAClan Agent {version} &middot; generated {generated}</footer>
</div>
</body>
</html>
"""


def _stat_card(n, label, color="#1c2128") -> str:
    return (
        f'<div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;'
        f'padding:10px 18px;text-align:center;min-width:90px">'
        f'<div style="font-size:24px;font-weight:700;color:{color}">{_esc(str(n))}</div>'
        f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;'
        f'color:#57606a">{label}</div>'
        f'</div>'
    )


def generate_api_html_report(run_id: str, project_id: str) -> str:
    """Build self-contained HTML report for one API collection run.
    Raises ValueError if run not found."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, collection_name, env_name, status, total, passed, failed, "
        "error_count, started_at, finished_at "
        "FROM api_collection_runs WHERE id = ? AND project_id = ?",
        (run_id, project_id),
    ).fetchone()
    if not row:
        raise ValueError(f"API collection run {run_id} not found")
    run = dict(row)

    result_rows = conn.execute(
        "SELECT id, request_name, method, url, status, status_code, "
        "response_body, response_headers, duration_ms, assertion_results, "
        "error_message, started_at, finished_at "
        "FROM api_request_results WHERE collection_run_id = ? ORDER BY order_index",
        (run_id,),
    ).fetchall()

    request_results = []
    for r in result_rows:
        rr = dict(r)
        for key in ("response_headers", "assertion_results"):
            if isinstance(rr.get(key), str):
                try:
                    rr[key] = json.loads(rr[key])
                except (ValueError, TypeError):
                    rr[key] = None
        request_results.append(rr)

    total = run.get("total") or 0
    passed = run.get("passed") or 0
    failed = run.get("failed") or 0
    error_count = run.get("error_count") or 0
    passrate = int((passed / total) * 100) if total else 0

    status = run.get("status", "ERROR")
    status_bg = "#1a7f37" if status == "PASSED" else "#cf222e"

    title = _esc(run.get("collection_name") or "API Run")
    env = _esc(run.get("env_name") or "No environment")
    duration = _duration(run.get("started_at"), run.get("finished_at"))
    meta = (
        f"Environment: {env} · "
        f"Started: {_fmt_dt(run.get('started_at'))} · "
        f"Duration: {duration}"
    )

    stats = (
        _stat_card(total, "Total")
        + _stat_card(passed, "Passed", "#1a7f37")
        + _stat_card(failed, "Failed", "#cf222e")
        + (_stat_card(error_count, "Errors", "#9a6700") if error_count else "")
        + _stat_card(f"{passrate}%", "Pass Rate")
        + _stat_card(duration, "Duration")
    )

    rows_html = _render_request_rows(request_results)
    if not rows_html:
        rows_html = (
            '<tr><td colspan="8" style="text-align:center;padding:24px;color:#57606a">'
            "No requests were run.</td></tr>"
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return _HTML.format(
        title=title,
        status=_esc(status),
        status_bg=status_bg,
        meta=meta,
        stats=stats,
        passrate=passrate,
        rows=rows_html,
        version=_esc(_AGENT_VERSION),
        generated=generated,
    )
```

- [ ] **Step 2: Smoke-test the generator**

Requires at least one completed run (from Task 3 verification):

```bash
python -c "
from cli.db import init_db, get_conn
init_db()
conn = get_conn()
run = conn.execute('SELECT id, project_id FROM api_collection_runs LIMIT 1').fetchone()
if not run:
    print('No runs yet — run a collection first')
else:
    from cli.api_report import generate_api_html_report
    html = generate_api_html_report(run['id'], run['project_id'])
    with open('/tmp/test-api-report.html', 'w') as f:
        f.write(html)
    print('Written to /tmp/test-api-report.html — open in browser')
"
```

Open `/tmp/test-api-report.html` in a browser. Verify:
- Header shows collection name + PASSED/FAILED badge
- Stat cards show correct totals
- Each request row shows method badge, name, URL, status, code, duration, assertion count
- Clicking a row expands the detail panel
- Assertions show ✓/✗ with expected vs actual
- Response body is formatted JSON (if JSON) or raw text

- [ ] **Step 3: Test the report route**

```bash
# With server running:
curl -s -I "http://localhost:7823/api/api-collection-runs/<run_id>/report"
# Expected: Content-Type: text/html, Content-Disposition: attachment

curl -s -I "http://localhost:7823/api/api-collection-runs/<run_id>/report?view=1"
# Expected: Content-Disposition: inline
```

- [ ] **Step 4: Commit**

```bash
git add cli/api_report.py
git commit -m "feat: add API collection run HTML report generator"
```

---

## Task 6: Frontend — Runs Page Tab Switcher + API Runs Tab

**Files:**
- Modify: `web/static/app.js`

**Interfaces:**
- Consumes: `GET /api/api-collection-runs` (Task 4), `GET /api/api-collection-runs/<id>` (Task 4), `GET /api/api-collection-runs/<id>/report` (Task 5)
- Consumes (existing): `showModal(title, bodyHTML, buttons, subtitle, size)` at line ~545, `.req-tab-bar` + `.req-tab` CSS classes from `style.css`
- Produces: working two-tab Runs page

- [ ] **Step 1: Add `_runsTab` state variable**

Find the block of global state variables near the top of `app.js` (around where `state` is defined). Add:

```javascript
let _runsTab = 'regression'  // 'regression' | 'api'
```

- [ ] **Step 2: Replace `renderRunsPage` with tab-aware version**

Find `async function renderRunsPage()` (around line 4240). Replace the entire function:

```javascript
async function renderRunsPage() {
  const page = document.getElementById('page-content')
  if (!state.activeProject) { renderNoProject(page); return }

  page.innerHTML = `
    <div class="page-header">
      <div class="page-header-text">
        <h2>Runs</h2>
        <p>View execution history</p>
      </div>
    </div>
    <div class="req-tab-bar">
      <button class="req-tab ${_runsTab === 'regression' ? 'active' : ''}" onclick="switchRunsTab('regression')">Regression Runs</button>
      <button class="req-tab ${_runsTab === 'api' ? 'active' : ''}" onclick="switchRunsTab('api')">API Runs</button>
    </div>
    <div id="runs-tab-content" style="padding-top:16px"></div>`

  await renderActiveRunsTab()
}
```

- [ ] **Step 3: Add `switchRunsTab` and `renderActiveRunsTab` functions**

Add immediately after the new `renderRunsPage`:

```javascript
function switchRunsTab(tab) {
  _runsTab = tab
  document.querySelectorAll('.req-tab-bar .req-tab').forEach((b, i) => {
    b.classList.toggle('active', (i === 0 && tab === 'regression') || (i === 1 && tab === 'api'))
  })
  renderActiveRunsTab()
}

async function renderActiveRunsTab() {
  if (_runsTab === 'regression') {
    await _renderRegressionRunsTab()
  } else {
    await _renderApiRunsTab()
  }
}
```

- [ ] **Step 4: Extract existing Regression Runs table into `_renderRegressionRunsTab`**

The existing body of `renderRunsPage` (the `api('GET', '/runs')` call and table HTML) becomes `_renderRegressionRunsTab`. Add:

```javascript
async function _renderRegressionRunsTab() {
  const container = document.getElementById('runs-tab-content')
  const res = await api('GET', '/runs')
  const runs = res.runs || []
  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Run ID</th><th>Suite</th><th>Status</th><th>Results</th><th>Started</th><th></th>
        </tr></thead>
        <tbody>
          ${runs.length === 0
            ? `<tr><td colspan="6"><div class="empty-state"><div class="empty-state-icon">&#9654;</div><p>No runs yet.<br>Run a suite to see results here.</p></div></td></tr>`
            : runs.map(r => `
              <tr>
                <td class="mono">${escHtml(r.id)}</td>
                <td>${escHtml(r.suite_name)}</td>
                <td><span class="badge ${r.status === 'PASSED' ? 'badge-success' : 'badge-danger'}"><span class="badge-dot"></span>${r.status}</span></td>
                <td class="text-sm">${r.passed}/${r.total} passed${r.failed ? ', ' + r.failed + ' failed' : ''}</td>
                <td class="text-muted text-sm">${fmtDate(r.started_at)}</td>
                <td><div class="table-actions">
                  <button class="btn btn-xs btn-ghost" onclick="viewRunModal('${r.id}','${escHtml(r.suite_name)}')">View</button>
                  <button class="btn btn-xs btn-ghost" onclick="downloadReport('${r.id}')">Report</button>
                </div></td>
              </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}
```

- [ ] **Step 5: Add `_renderApiRunsTab` function**

```javascript
async function _renderApiRunsTab() {
  const container = document.getElementById('runs-tab-content')
  container.innerHTML = `<div class="text-muted text-sm" style="padding:8px">Loading...</div>`
  const res = await api('GET', '/api/api-collection-runs')
  const runs = res.runs || []
  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Run ID</th><th>Collection</th><th>Status</th><th>Results</th><th>Started</th><th></th>
        </tr></thead>
        <tbody>
          ${runs.length === 0
            ? `<tr><td colspan="6"><div class="empty-state"><div class="empty-state-icon">&#9654;</div><p>No API runs yet.<br>Run a collection to see results here.</p></div></td></tr>`
            : runs.map(r => `
              <tr>
                <td class="mono">${escHtml(r.id)}</td>
                <td>${escHtml(r.collection_name)}</td>
                <td><span class="badge ${r.status === 'PASSED' ? 'badge-success' : 'badge-danger'}"><span class="badge-dot"></span>${r.status}</span></td>
                <td class="text-sm">${r.passed}/${r.total} passed${r.failed ? ', ' + r.failed + ' failed' : ''}</td>
                <td class="text-muted text-sm">${fmtDate(r.started_at)}</td>
                <td><div class="table-actions">
                  <button class="btn btn-xs btn-ghost" onclick="viewApiRunModal('${r.id}')">View</button>
                  <button class="btn btn-xs btn-ghost" onclick="downloadApiReport('${r.id}')">Report</button>
                </div></td>
              </tr>`).join('')}
        </tbody>
      </table>
    </div>`
}
```

- [ ] **Step 6: Add `viewApiRunModal` function**

```javascript
async function viewApiRunModal(runId) {
  const res = await api('GET', '/api/api-collection-runs/' + runId)
  if (!res.ok) { toast(res.error || 'Failed to load run', 'error'); return }
  const run = res.run
  const statusCls = run.status === 'PASSED' ? 'badge-success' : 'badge-danger'
  const methodColors = {GET:'#0969da',POST:'#1a7f37',PUT:'#e16f24',PATCH:'#9a6700',DELETE:'#cf222e',HEAD:'#6e40c9'}

  const rows = (run.request_results || []).map((rr, i) => {
    const assertions = rr.assertion_results || []
    const passedA = assertions.filter(a => a.passed).length
    const sc = rr.status === 'PASSED' ? 'badge-success' : 'badge-danger'
    const mc = methodColors[(rr.method || 'GET').toUpperCase()] || '#57606a'
    return `<tr>
      <td class="text-sm text-muted">${i + 1}</td>
      <td><span style="display:inline-block;background:${mc};color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;min-width:46px;text-align:center">${escHtml(rr.method || '')}</span></td>
      <td style="font-size:13px">${escHtml(rr.request_name || '')}</td>
      <td><span class="badge ${sc}" style="font-size:11px">${rr.status || 'ERROR'}</span></td>
      <td class="text-sm">${rr.status_code != null ? rr.status_code : '—'}</td>
      <td class="text-sm">${rr.duration_ms != null ? rr.duration_ms + 'ms' : '—'}</td>
      <td class="text-sm text-muted">${passedA}/${assertions.length}</td>
    </tr>`
  }).join('')

  const bodyHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
      <span class="badge ${statusCls}">${run.status}</span>
      <span class="text-muted text-sm">${run.passed}/${run.total} passed &middot; ${fmtDate(run.started_at)}</span>
    </div>
    <div class="table-wrap" style="max-height:380px;overflow-y:auto">
      <table>
        <thead><tr>
          <th>#</th><th>Method</th><th>Name</th><th>Status</th><th>Code</th><th>Duration</th><th>Assertions</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="text-muted text-sm">No requests</td></tr>'}</tbody>
      </table>
    </div>`

  showModal(
    escHtml(run.collection_name) + ' · API Run',
    bodyHTML,
    [
      { label: 'Download Report', cls: 'btn-ghost', action: () => downloadApiReport(run.id) },
      { label: 'Close', cls: 'btn-ghost', action: closeModal },
    ]
  )
}
```

- [ ] **Step 7: Add `downloadApiReport` function**

Add next to the existing `downloadReport` function:

```javascript
function downloadApiReport(runId) {
  const base = '/api/api-collection-runs/' + encodeURIComponent(runId) + '/report'
  window.open(base + '?view=1', '_blank')
  const a = document.createElement('a')
  a.href = base
  a.download = 'qaclan-api-report-' + runId + '.html'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
```

- [ ] **Step 8: Manual verification**

Start the server, navigate to Runs page. Verify:
1. Two tabs appear: "Regression Runs" and "API Runs"
2. Clicking "Regression Runs" shows existing suite run table (unchanged)
3. Clicking "API Runs" shows API collection run table
4. After running a collection (from API tab), refresh Runs → API Runs tab shows the new entry
5. "View" button opens modal with per-request table
6. "Report" button opens HTML in new tab and triggers download
7. Downloaded HTML opens offline, rows expand on click, assertions show ✓/✗

- [ ] **Step 9: Commit**

```bash
git add web/static/app.js
git commit -m "feat: add API Runs tab to Runs page with view modal and report download"
```

---

## Done

All 6 tasks complete. The feature is fully implemented:
- Every `/api/collections/<id>/run` call now persists to `api_collection_runs` + `api_request_results`
- `GET /api/api-collection-runs` lists all runs for the active project
- `GET /api/api-collection-runs/<id>` returns full detail with per-request results
- `GET /api/api-collection-runs/<id>/report` serves a self-contained HTML file
- Runs page shows both Regression and API runs in separate tabs
- Single-request sends remain ephemeral (no changes to `run_request`)
