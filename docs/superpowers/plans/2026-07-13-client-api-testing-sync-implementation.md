# Client-Side API Testing Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built local API-testing feature (collections/folders/requests/vars/variant-library/run-history) into this repo's cloud sync (`cli/sync.py`, `cli/api.py`, `cli/sync_queue.py`, `cli/commands/pull.py`), against the endpoint contracts defined in `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md`.

**Architecture:** Extend the existing generic push/pull machinery entity-by-entity, exactly matching the pattern already used for `projects`/`features`/`suites`/`scripts`/`environments`. No new queue, no new worker, no new UI trigger — the existing Push/Pull buttons (`web/static/app.js:452-486`) pick up every new entity once it's registered.

**Tech Stack:** Python (Flask backend, `cli/` package), SQLite (`cli/db.py`), `requests` for HTTP. No test framework in this repo — every task's verification step is manual (CLI/curl/sqlite3 inspection against a throwaway mock server), per repo convention and the approved design doc.

**Companion docs:**
- `docs/superpowers/specs/2026-07-13-client-api-testing-sync-design.md` — the approved design this plan implements.
- `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` — the server-side contract every payload shape below must match exactly.

## Global Constraints

- Every new `sync_*_to_cloud()` function follows the exact shape of the existing ones in `cli/sync.py`: read auth key, return `None` if absent, read fresh state from SQLite, lazy-ensure parent entities, build a payload dict, call `_try_sync(label, lambda: api.<fn>(key, payload))`, save the returned cloud id if the entity supports one.
- JSON columns in SQLite are TEXT — always `json.loads()` before putting a value in an outgoing payload, and `json.dumps()`/store-as-given when writing pulled JSON back to a TEXT column (matching `web/api/repositories/request_repo.py`'s `_serialize`/`_deserialize` pattern).
- No task modifies the *behavior* of an existing endpoint's request/response shape for current users — `sync_run_to_cloud` and `_dispatch_run` gain a new **optional** `api_results` parameter/field only; every other change adds new functions/branches, it does not touch existing ones.
- No task changes `docs/api-script-reference.md` or `docs/api-assertions-reference.md` — this plan only adds sync plumbing around the `pre_script`/`post_script`/`assertions` columns, it does not change their semantics, so the CLAUDE.md maintenance rule for those docs does not apply here.
- Commit after each task, using the entity name in the message (e.g. `feat(sync): push/pull api_collections`).

---

### Task 1: Local schema — add `cloud_id` to the four upsertable API-testing tables

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: a `cloud_id TEXT` column on `api_collections`, `api_folders`, `api_requests`, `api_request_examples` — consumed by every `sync_*_to_cloud`/`_get_cloud_id`/`_save_cloud_id` call added in Tasks 4-8.

- [ ] **Step 1: Add the migration function**

Add this function to `cli/db.py`, near `_migrate_cloud_id` (around line 526):

```python
def _migrate_api_cloud_id(conn):
    """Add cloud_id column to the API-testing tables that get individually
    upserted to the cloud (collections/folders/requests/variant-library
    examples). collection_vars/api_collection_runs/api_request_results don't
    need it — full-replace-list or append-only, same as env_vars/suite_runs."""
    for table in ("api_collections", "api_folders", "api_requests", "api_request_examples"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN cloud_id TEXT")
        except Exception:
            pass  # already exists
    conn.commit()
```

- [ ] **Step 2: Register it in `init_db()`**

In `cli/db.py`, change:

```python
    _migrate_api_request_examples(conn)
    _migrate_nested_folders(conn)
```

to:

```python
    _migrate_api_request_examples(conn)
    _migrate_nested_folders(conn)
    _migrate_api_cloud_id(conn)
```

- [ ] **Step 3: Verify manually**

```bash
rm -f ~/.qaclan/qaclan.db   # only if you have no data you care about; otherwise skip deletion — ALTER is additive/idempotent
python qaclan.py status     # any command triggers init_db()
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_collections)" | grep cloud_id
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_folders)" | grep cloud_id
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_requests)" | grep cloud_id
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(api_request_examples)" | grep cloud_id
```
Expected: each command prints a row containing `cloud_id`. Run `python qaclan.py status` a second time — no error (proves the `try/except: pass` idempotency).

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat(db): add cloud_id to api_collections/folders/requests/request_examples"
```

---

### Task 2: Throwaway mock qaclan-server for manual verification

**Files:**
- Create (NOT committed — save outside the repo, e.g. `/tmp/mock_qaclan_server.py`): a small Flask app implementing just enough of the server-plan contract to exercise every task below.

**Interfaces:**
- Produces: an HTTP server on `127.0.0.1:8765` that every later task's manual verification step points `QACLAN_SERVER_URL` at.

- [ ] **Step 1: Write the mock server**

Save this to `/tmp/mock_qaclan_server.py` (or any path outside the repo — it's a dev aid, not part of the codebase):

```python
"""Throwaway mock of the qaclan-server endpoints this plan targets.
Not a real server — just enough to see what the client sends and to
return canned pull data. Run: python /tmp/mock_qaclan_server.py"""
import hashlib
from flask import Flask, request, jsonify

app = Flask(__name__)
RECEIVED = []  # every push payload, for manual inspection


def fake_cloud_id(prefix, cli_id):
    return f"cloud_{prefix}_{hashlib.sha1(cli_id.encode()).hexdigest()[:8]}"


@app.route("/api/sync/status", methods=["GET"])
def status():
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    return jsonify({"id": "u1", "email": "test@example.com"})


def _generic_sync(prefix, id_field):
    body = request.get_json(force=True)
    RECEIVED.append((request.path, body))
    print(f"\n=== POST {request.path} ===\n{body}\n")
    return jsonify({"id": fake_cloud_id(prefix, body[id_field])})


@app.route("/api/sync/api-collection", methods=["POST"])
def sync_api_collection():
    return _generic_sync("col", "cli_collection_id")


@app.route("/api/sync/api-folder", methods=["POST"])
def sync_api_folder():
    return _generic_sync("fold", "cli_folder_id")


@app.route("/api/sync/api-request", methods=["POST"])
def sync_api_request():
    return _generic_sync("req", "cli_request_id")


@app.route("/api/sync/api-request-example", methods=["POST"])
def sync_api_request_example():
    return _generic_sync("ex", "cli_example_id")


@app.route("/api/sync/collection-vars", methods=["POST"])
def sync_collection_vars():
    body = request.get_json(force=True)
    RECEIVED.append((request.path, body))
    print(f"\n=== POST {request.path} ===\n{body}\n")
    return jsonify({"ok": True})


@app.route("/api/sync/api-collection-run", methods=["POST"])
def sync_api_collection_run():
    body = request.get_json(force=True)
    RECEIVED.append((request.path, body))
    print(f"\n=== POST {request.path} ===\n{body}\n")
    return jsonify({"id": fake_cloud_id("run", body["cli_collection_run_id"])})


@app.route("/api/sync/run", methods=["POST"])
def sync_run():
    body = request.get_json(force=True)
    RECEIVED.append((request.path, body))
    print(f"\n=== POST {request.path} (api_results={len(body.get('api_results', []))}) ===\n")
    return jsonify({"id": fake_cloud_id("run", body["run_id"])})


@app.route("/api/sync/api-collection/<cli_id>", methods=["DELETE"])
@app.route("/api/sync/api-folder/<cli_id>", methods=["DELETE"])
@app.route("/api/sync/api-request/<cli_id>", methods=["DELETE"])
@app.route("/api/sync/api-request-example/<cli_id>", methods=["DELETE"])
def delete_generic(cli_id):
    print(f"\n=== DELETE {request.path} ===\n")
    return jsonify({"ok": True})


@app.route("/api/pull/workspace", methods=["GET"])
def pull_workspace():
    return jsonify({
        "projects": [], "features": [], "scripts": [], "environments": [], "env_vars": [],
        "suites": [], "suite_items": [],
        "api_collections": [], "api_folders": [], "api_requests": [], "collection_vars": [],
    })


@app.route("/api/pull/api-runs", methods=["GET"])
def pull_api_runs():
    return jsonify({"runs": [], "page": 1, "per_page": 50, "total": 0})


@app.route("/api/pull/api-docs", methods=["GET"])
def pull_api_docs():
    return jsonify({"doc_entries": []})


if __name__ == "__main__":
    app.run(port=8765, debug=False)
```

- [ ] **Step 2: Verify it runs**

```bash
python /tmp/mock_qaclan_server.py &
sleep 1
curl -s http://127.0.0.1:8765/api/sync/status
```
Expected: `{"ok":true}`. Keep this server running in a background terminal for every subsequent task's manual verification. Point the CLI at it:
```bash
export QACLAN_SERVER_URL=http://127.0.0.1:8765
```
(set this in every shell you run `qaclan`/the web server from, for the rest of this plan)

No commit — this file lives outside the repo.

---

### Task 3: `cli/api.py` — HTTP client functions for every new endpoint

**Files:**
- Modify: `cli/api.py`

**Interfaces:**
- Produces: `sync_api_collection`, `sync_api_folder`, `sync_api_request`, `sync_collection_vars`, `sync_api_request_example`, `sync_api_collection_run`, `delete_api_collection`, `delete_api_folder`, `delete_api_request`, `delete_api_request_example`, `pull_api_runs`, `pull_api_run_detail`, `pull_api_docs` — consumed by every `cli/sync.py` function added in Tasks 4-9 and by Task 18's on-demand pull.

- [ ] **Step 1: Add the functions**

Append to `cli/api.py` (after `sync_env_vars`, before end of file):

```python
def sync_api_collection(auth_key, payload):
    """POST /api/sync/api-collection — push API collection metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/api-collection", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def delete_api_collection(auth_key, cli_collection_id):
    """DELETE /api/sync/api-collection/<id> — delete API collection from cloud."""
    r = requests.delete(f"{get_server_url()}/api/sync/api-collection/{cli_collection_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_api_folder(auth_key, payload):
    """POST /api/sync/api-folder — push API folder metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/api-folder", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def delete_api_folder(auth_key, cli_folder_id):
    """DELETE /api/sync/api-folder/<id> — delete API folder from cloud."""
    r = requests.delete(f"{get_server_url()}/api/sync/api-folder/{cli_folder_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_api_request(auth_key, payload):
    """POST /api/sync/api-request — push API request metadata."""
    r = requests.post(f"{get_server_url()}/api/sync/api-request", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def delete_api_request(auth_key, cli_request_id):
    """DELETE /api/sync/api-request/<id> — delete API request from cloud."""
    r = requests.delete(f"{get_server_url()}/api/sync/api-request/{cli_request_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_collection_vars(auth_key, payload):
    """POST /api/sync/collection-vars — push collection-scoped variables (full replace)."""
    r = requests.post(f"{get_server_url()}/api/sync/collection-vars", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_api_request_example(auth_key, payload):
    """POST /api/sync/api-request-example — push a variant-library example."""
    r = requests.post(f"{get_server_url()}/api/sync/api-request-example", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def delete_api_request_example(auth_key, cli_example_id):
    """DELETE /api/sync/api-request-example/<id> — delete example from cloud."""
    r = requests.delete(f"{get_server_url()}/api/sync/api-request-example/{cli_example_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def sync_api_collection_run(auth_key, payload):
    """POST /api/sync/api-collection-run — push standalone collection run history."""
    r = requests.post(f"{get_server_url()}/api/sync/api-collection-run", json=payload, headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def pull_api_runs(auth_key, page=1, per_page=50):
    """GET /api/pull/api-runs — fetch standalone collection-run history."""
    r = requests.get(
        f"{get_server_url()}/api/pull/api-runs",
        params={"page": page, "per_page": per_page},
        headers=_headers(auth_key),
    )
    _raise_with_body(r)
    return r.json()


def pull_api_run_detail(auth_key, run_id):
    """GET /api/pull/api-runs/<run_id> — fetch single collection run with request results."""
    r = requests.get(f"{get_server_url()}/api/pull/api-runs/{run_id}", headers=_headers(auth_key))
    _raise_with_body(r)
    return r.json()


def pull_api_docs(auth_key, project_id):
    """GET /api/pull/api-docs?project_id=<id> — fetch server-computed docs cache for a project."""
    r = requests.get(
        f"{get_server_url()}/api/pull/api-docs",
        params={"project_id": project_id},
        headers=_headers(auth_key),
    )
    _raise_with_body(r)
    return r.json()
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli import api
print(api.sync_api_collection('testkey', {'cli_collection_id': 'apicol_test', 'cloud_id': None, 'name': 'Test', 'project_id': 'cloud_proj_1'}))
print(api.pull_api_docs('testkey', 'cloud_proj_1'))
"
```
(with the mock server from Task 2 running and `QACLAN_SERVER_URL` exported)
Expected: first line prints `{'id': 'cloud_col_xxxxxxxx'}`, second prints `{'doc_entries': []}`. The mock server's terminal should log the received payload.

- [ ] **Step 3: Commit**

```bash
git add cli/api.py
git commit -m "feat(api): add client functions for api-testing sync endpoints"
```

---

### Task 4: `cli/sync.py` — sync `api_collections`

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_api_collection`, `api.delete_api_collection` (Task 3); `_ensure_project_synced`, `_get_cloud_id`, `_save_cloud_id`, `_try_sync` (existing).
- Produces: `sync_api_collection_to_cloud(collection_id)`, `_ensure_api_collection_synced(collection_id)`, `delete_api_collection_from_cloud(collection_id)` — consumed by Task 5 (folders), Task 6 (requests' collection FK), Task 9 (collection runs), Task 11 (`sync_queue`), Task 12 (route wiring).

- [ ] **Step 1: Add `import json` at the top of `cli/sync.py`**

Change:
```python
import base64
import contextlib
import os
import threading
```
to:
```python
import base64
import contextlib
import json
import os
import threading
```

- [ ] **Step 2: Add the functions**

Add after `sync_script_to_cloud` (before the `# --- Delete operations ---` comment):

```python
def sync_api_collection_to_cloud(collection_id):
    """Sync an API collection. Requires cloud_project_id."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    row = get_conn().execute(
        "SELECT project_id, name, description, env_name, auth_type, auth_config, order_index "
        "FROM api_collections WHERE id = ?", (collection_id,)
    ).fetchone()
    if not row:
        return None
    cloud_project_id = _ensure_project_synced(row["project_id"])
    if not cloud_project_id:
        return None
    cloud_id = _get_cloud_id("api_collections", collection_id)
    result = _try_sync("api collection", lambda: api.sync_api_collection(key, {
        "cli_collection_id": collection_id,
        "cloud_id": cloud_id,
        "name": row["name"],
        "description": row["description"],
        "env_name": row["env_name"],
        "auth_type": row["auth_type"],
        "auth_config": json.loads(row["auth_config"] or "{}"),
        "order_index": row["order_index"],
        "project_id": cloud_project_id,
    }))
    if result and result.get("id"):
        _save_cloud_id("api_collections", collection_id, result["id"])
    return result


def _ensure_api_collection_synced(collection_id):
    """Ensure the API collection has a cloud_id. If not, sync it now."""
    cloud_id = _get_cloud_id("api_collections", collection_id)
    if cloud_id:
        return cloud_id
    result = sync_api_collection_to_cloud(collection_id)
    if result:
        return result.get("id") or _get_cloud_id("api_collections", collection_id)
    return None
```

Add after `delete_environment_from_cloud` (in the `# --- Delete operations ---` section):

```python
def delete_api_collection_from_cloud(collection_id):
    """Delete an API collection from cloud by CLI collection ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete api collection", lambda: api.delete_api_collection(key, collection_id))
```

- [ ] **Step 3: Verify manually**

With the Task 2 mock server running and a logged-in local config (`qaclan login` against any placeholder key works since the mock doesn't check it — set one via `python -c "from cli.config import set_auth_key; set_auth_key('testkey')"` if you haven't logged in):

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
pid = generate_id('proj')
conn.execute(\"INSERT INTO projects (id, name, created_at) VALUES (?, 'Test Project', ?)\", (pid, datetime.now(timezone.utc).isoformat()))
cid = generate_id('apicol')
conn.execute(\"INSERT INTO api_collections (id, project_id, name, description, created_at) VALUES (?, ?, 'Billing API', 'desc', ?)\", (cid, pid, datetime.now(timezone.utc).isoformat()))
conn.commit()
from cli import sync
print(sync.sync_api_collection_to_cloud(cid))
print('cloud_id in DB:', conn.execute('SELECT cloud_id FROM api_collections WHERE id=?', (cid,)).fetchone()['cloud_id'])
"
```
Expected: prints `{'id': 'cloud_col_xxxxxxxx'}` twice (once from the direct call, once confirming it was saved). Mock server terminal shows the POST body with `project_id` set to a `cloud_proj_...` id (proving the lazy project-ensure ran first).

- [ ] **Step 4: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push api_collections to cloud"
```

---

### Task 5: `cli/sync.py` — sync `api_folders`

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_api_folder`, `api.delete_api_folder` (Task 3); `_ensure_project_synced`, `_ensure_api_collection_synced` (Task 4).
- Produces: `sync_api_folder_to_cloud(folder_id)`, `_ensure_api_folder_synced(folder_id)` (recursive — handles arbitrary nesting depth), `delete_api_folder_from_cloud(folder_id)` — consumed by Task 6 (requests' folder FK), Task 11, Task 13.

- [ ] **Step 1: Add the functions**

Add directly after the Task 4 functions:

```python
def sync_api_folder_to_cloud(folder_id):
    """Sync an API folder. Requires cloud_project_id and cloud_collection_id;
    recursively ensures its parent folder is synced first (if any)."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    row = get_conn().execute(
        "SELECT project_id, collection_id, parent_folder_id, name, order_index "
        "FROM api_folders WHERE id = ?", (folder_id,)
    ).fetchone()
    if not row:
        return None
    cloud_project_id = _ensure_project_synced(row["project_id"])
    cloud_collection_id = _ensure_api_collection_synced(row["collection_id"])
    if not cloud_project_id or not cloud_collection_id:
        return None
    cloud_parent_id = None
    if row["parent_folder_id"]:
        cloud_parent_id = _ensure_api_folder_synced(row["parent_folder_id"])
    cloud_id = _get_cloud_id("api_folders", folder_id)
    result = _try_sync("api folder", lambda: api.sync_api_folder(key, {
        "cli_folder_id": folder_id,
        "cloud_id": cloud_id,
        "name": row["name"],
        "order_index": row["order_index"],
        "project_id": cloud_project_id,
        "collection_id": cloud_collection_id,
        "parent_folder_id": cloud_parent_id,
    }))
    if result and result.get("id"):
        _save_cloud_id("api_folders", folder_id, result["id"])
    return result


def _ensure_api_folder_synced(folder_id):
    """Ensure the API folder has a cloud_id. If not, sync it now
    (which recursively ensures its parent folder first)."""
    cloud_id = _get_cloud_id("api_folders", folder_id)
    if cloud_id:
        return cloud_id
    result = sync_api_folder_to_cloud(folder_id)
    if result:
        return result.get("id") or _get_cloud_id("api_folders", folder_id)
    return None
```

Add after `delete_api_collection_from_cloud`:

```python
def delete_api_folder_from_cloud(folder_id):
    """Delete an API folder from cloud by CLI folder ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete api folder", lambda: api.delete_api_folder(key, folder_id))
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
now = datetime.now(timezone.utc).isoformat()
row = conn.execute('SELECT id, project_id FROM api_collections LIMIT 1').fetchone()
cid, pid = row['id'], row['project_id']
parent_id = generate_id('apifold')
conn.execute('INSERT INTO api_folders (id, project_id, collection_id, name, created_at) VALUES (?,?,?,?,?)', (parent_id, pid, cid, 'Parent', now))
child_id = generate_id('apifold')
conn.execute('INSERT INTO api_folders (id, project_id, collection_id, parent_folder_id, name, created_at) VALUES (?,?,?,?,?,?)', (child_id, pid, cid, parent_id, 'Child', now))
conn.commit()
from cli import sync
print('child sync result:', sync.sync_api_folder_to_cloud(child_id))
print('parent got cloud_id too:', conn.execute('SELECT cloud_id FROM api_folders WHERE id=?', (parent_id,)).fetchone()['cloud_id'])
"
```
Expected: mock server logs TWO `POST /api/sync/api-folder` calls (parent first via the recursive ensure, then child), and the parent's `cloud_id` in the DB is populated even though you only called sync on the child.

- [ ] **Step 3: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push api_folders to cloud (recursive parent ensure)"
```

---

### Task 6: `cli/sync.py` — sync `api_requests`

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_api_request`, `api.delete_api_request` (Task 3); `_ensure_project_synced`, `_get_cloud_id` for `features`/`api_collections`/`api_folders` (existing + Task 4/5).
- Produces: `sync_api_request_to_cloud(request_id)`, `delete_api_request_from_cloud(request_id)` — consumed by Task 8 (examples' parent-ensure), Task 11, Task 14, Task 15.

- [ ] **Step 1: Add the functions**

Add directly after the Task 5 functions:

```python
def sync_api_request_to_cloud(request_id):
    """Sync an API request. project_id is required (lazy-ensured); feature_id/
    collection_id/folder_id are attached only if those parents already have a
    cloud_id (same rule sync_script_to_cloud uses for suite_id/feature_id)."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    row = get_conn().execute(
        "SELECT project_id, feature_id, collection_id, folder_id, name, method, url, headers, "
        "params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, "
        "pre_extractor, post_script, post_lang, post_extractor, request_schema, response_schema, "
        "assertions, follow_redirects, timeout_ms, include_in_docs, order_index "
        "FROM api_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not row:
        return None
    cloud_project_id = _ensure_project_synced(row["project_id"])
    if not cloud_project_id:
        return None
    cloud_id = _get_cloud_id("api_requests", request_id)
    payload = {
        "cli_request_id": request_id,
        "cloud_id": cloud_id,
        "name": row["name"],
        "method": row["method"],
        "url": row["url"],
        "headers": json.loads(row["headers"] or "[]"),
        "params": json.loads(row["params"] or "[]"),
        "path_params": json.loads(row["path_params"] or "[]"),
        "body_type": row["body_type"],
        "body": row["body"],
        "auth_type": row["auth_type"],
        "auth_config": json.loads(row["auth_config"] or "{}"),
        "pre_script": row["pre_script"],
        "pre_lang": row["pre_lang"],
        "pre_extractor": json.loads(row["pre_extractor"]) if row["pre_extractor"] else None,
        "post_script": row["post_script"],
        "post_lang": row["post_lang"],
        "post_extractor": json.loads(row["post_extractor"]) if row["post_extractor"] else None,
        "request_schema": json.loads(row["request_schema"]) if row["request_schema"] else None,
        "response_schema": json.loads(row["response_schema"]) if row["response_schema"] else None,
        "assertions": json.loads(row["assertions"] or "[]"),
        "follow_redirects": bool(row["follow_redirects"]),
        "timeout_ms": row["timeout_ms"],
        "include_in_docs": bool(row["include_in_docs"]),
        "order_index": row["order_index"],
        "project_id": cloud_project_id,
    }
    if row["feature_id"]:
        cloud_feature_id = _get_cloud_id("features", row["feature_id"])
        if cloud_feature_id:
            payload["feature_id"] = cloud_feature_id
    if row["collection_id"]:
        cloud_collection_id = _get_cloud_id("api_collections", row["collection_id"])
        if cloud_collection_id:
            payload["collection_id"] = cloud_collection_id
    if row["folder_id"]:
        cloud_folder_id = _get_cloud_id("api_folders", row["folder_id"])
        if cloud_folder_id:
            payload["folder_id"] = cloud_folder_id
    result = _try_sync("api request", lambda: api.sync_api_request(key, payload))
    if result and result.get("id"):
        _save_cloud_id("api_requests", request_id, result["id"])
    return result
```

Add after `delete_api_folder_from_cloud`:

```python
def delete_api_request_from_cloud(request_id):
    """Delete an API request from cloud by CLI request ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete api request", lambda: api.delete_api_request(key, request_id))
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
now = datetime.now(timezone.utc).isoformat()
row = conn.execute('SELECT id, project_id FROM api_collections LIMIT 1').fetchone()
cid, pid = row['id'], row['project_id']
rid = generate_id('apireq')
conn.execute(
    'INSERT INTO api_requests (id, project_id, collection_id, name, method, url, created_at) VALUES (?,?,?,?,?,?,?)',
    (rid, pid, cid, 'Create invoice', 'POST', '{{baseUrl}}/invoices', now)
)
conn.commit()
from cli import sync
print(sync.sync_api_request_to_cloud(rid))
"
```
Expected: mock server logs the POST with `headers`/`params`/`assertions` as real JSON arrays (not string-encoded) and `collection_id` present as a `cloud_col_...` value.

- [ ] **Step 3: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push api_requests to cloud"
```

---

### Task 7: `cli/sync.py` — sync `collection_vars`

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_collection_vars` (Task 3).
- Produces: `sync_collection_vars_to_cloud(collection_id)` — consumed by Task 11, Task 12.

- [ ] **Step 1: Add the function**

Add directly after the Task 6 functions:

```python
def sync_collection_vars_to_cloud(collection_id):
    """Read collection vars from local DB and push full list to cloud
    (full-replace, same semantics as sync_env_vars_to_cloud)."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    rows = get_conn().execute(
        "SELECT key, initial_value FROM collection_vars WHERE collection_id = ? ORDER BY key",
        (collection_id,)
    ).fetchall()
    cloud_collection_id = _get_cloud_id("api_collections", collection_id)
    return _try_sync("collection vars", lambda: api.sync_collection_vars(key, {
        "cli_collection_id": str(collection_id),
        "cloud_collection_id": cloud_collection_id,
        "vars": [{"key": r["key"], "initial_value": r["initial_value"]} for r in rows],
    }))
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
row = conn.execute('SELECT id FROM api_collections LIMIT 1').fetchone()
cid = row['id']
vid = generate_id('cv')
conn.execute('INSERT INTO collection_vars (id, collection_id, key, initial_value, created_at) VALUES (?,?,?,?,?)',
             (vid, cid, 'baseUrl', 'https://staging.example.com', datetime.now(timezone.utc).isoformat()))
conn.commit()
from cli import sync
print(sync.sync_collection_vars_to_cloud(cid))
"
```
Expected: mock server logs `POST /api/sync/collection-vars` with `vars: [{'key': 'baseUrl', 'initial_value': 'https://staging.example.com'}]`.

- [ ] **Step 3: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push collection_vars to cloud"
```

---

### Task 8: `cli/sync.py` — sync `api_request_examples` (variant library)

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_api_request_example`, `api.delete_api_request_example` (Task 3); `sync_api_request_to_cloud` (Task 6, as a fallback parent-ensure).
- Produces: `sync_api_request_example_to_cloud(example_id)`, `delete_api_request_example_from_cloud(example_id)` — consumed by Task 11, Task 15.

- [ ] **Step 1: Add the functions**

Add directly after the Task 7 function:

```python
def sync_api_request_example_to_cloud(example_id):
    """Sync a variant-library example. Requires the parent request's cloud_id
    (ensured here since every example always has exactly one parent request)."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    row = get_conn().execute(
        "SELECT api_request_id, label, params, body, response_status, response_headers, response_body "
        "FROM api_request_examples WHERE id = ?", (example_id,)
    ).fetchone()
    if not row:
        return None
    cloud_request_id = _get_cloud_id("api_requests", row["api_request_id"])
    if not cloud_request_id:
        parent_result = sync_api_request_to_cloud(row["api_request_id"])
        cloud_request_id = parent_result.get("id") if parent_result else None
    if not cloud_request_id:
        return None
    cloud_id = _get_cloud_id("api_request_examples", example_id)
    result = _try_sync("api request example", lambda: api.sync_api_request_example(key, {
        "cli_example_id": example_id,
        "cloud_id": cloud_id,
        "request_id": cloud_request_id,
        "label": row["label"],
        "params": json.loads(row["params"] or "[]"),
        "body": row["body"],
        "response_status": row["response_status"],
        "response_headers": json.loads(row["response_headers"]) if row["response_headers"] else None,
        "response_body": row["response_body"],
    }))
    if result and result.get("id"):
        _save_cloud_id("api_request_examples", example_id, result["id"])
    return result
```

Add after `delete_api_request_from_cloud`:

```python
def delete_api_request_example_from_cloud(example_id):
    """Delete a variant-library example from cloud by CLI example ID."""
    key = get_auth_key()
    if not key:
        return None
    return _try_sync("delete api request example", lambda: api.delete_api_request_example(key, example_id))
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
row = conn.execute('SELECT id FROM api_requests LIMIT 1').fetchone()
rid = row['id']
eid = generate_id('apiex')
conn.execute(
    'INSERT INTO api_request_examples (id, api_request_id, label, created_at) VALUES (?,?,?,?)',
    (eid, rid, 'sort=date', datetime.now(timezone.utc).isoformat())
)
conn.commit()
from cli import sync
print(sync.sync_api_request_example_to_cloud(eid))
"
```
Expected: mock server logs `POST /api/sync/api-request-example` with `request_id` set to a `cloud_req_...` value (already synced from Task 6's test, or synced just-in-time by this call if not).

- [ ] **Step 3: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push api_request_examples (variant library) to cloud"
```

---

### Task 9: `cli/sync.py` — sync standalone `api_collection_runs`

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Consumes: `api.sync_api_collection_run` (Task 3); `_ensure_api_collection_synced` (Task 4).
- Produces: `sync_api_collection_run_to_cloud(run_id)` — consumed by Task 11, Task 16.

- [ ] **Step 1: Add the function**

Add directly after the Task 8 functions:

```python
def sync_api_collection_run_to_cloud(run_id):
    """Sync a finished standalone collection run with all its request results.
    Ensures the parent collection is synced first. Append-only — no cloud_id
    stored locally, same as suite runs."""
    key = get_auth_key()
    if not key:
        return None
    from cli.db import get_conn
    conn = get_conn()
    run = conn.execute(
        "SELECT collection_id, collection_name, env_name, status, total, passed, failed, "
        "error_count, started_at, finished_at FROM api_collection_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if not run:
        return None
    cloud_collection_id = _ensure_api_collection_synced(run["collection_id"])
    if not cloud_collection_id:
        return None
    results = conn.execute(
        "SELECT api_request_id, request_name, method, url, order_index, status, status_code, "
        "response_body, response_headers, duration_ms, assertion_results, error_message, "
        "started_at, finished_at FROM api_request_results "
        "WHERE collection_run_id = ? ORDER BY order_index", (run_id,)
    ).fetchall()
    payload = {
        "cli_collection_run_id": run_id,
        "collection_id": cloud_collection_id,
        "collection_name": run["collection_name"],
        "env_name": run["env_name"],
        "status": (run["status"] or "error").lower(),
        "total": run["total"],
        "passed": run["passed"],
        "failed": run["failed"],
        "error_count": run["error_count"],
        "started_at": run["started_at"],
        "completed_at": run["finished_at"],
        "duration_ms": 0,
        "request_results": [
            {
                "cli_request_id": r["api_request_id"],
                "request_name": r["request_name"],
                "method": r["method"],
                "url": r["url"],
                "order_index": r["order_index"],
                "status": (r["status"] or "error").lower(),
                "status_code": r["status_code"],
                "duration_ms": r["duration_ms"],
                "response_body": r["response_body"],
                "response_headers": json.loads(r["response_headers"]) if r["response_headers"] else None,
                "assertion_results": json.loads(r["assertion_results"]) if r["assertion_results"] else None,
                "error_message": r["error_message"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
            }
            for r in results
        ],
    }
    return _try_sync("api collection run", lambda: api.sync_api_collection_run(key, payload))
```

(`duration_ms: 0` matches the existing hardcoded placeholder in `sync_run_to_cloud`'s callers — `api_collection_runs` has no `duration_ms` column locally, same gap `suite_runs` has today.)

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
now = datetime.now(timezone.utc).isoformat()
row = conn.execute('SELECT id, project_id FROM api_collections LIMIT 1').fetchone()
cid, pid = row['id'], row['project_id']
run_id = generate_id('arun')
conn.execute(
    \"INSERT INTO api_collection_runs (id, project_id, collection_id, collection_name, status, total, passed, failed, error_count, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)\",
    (run_id, pid, cid, 'Billing API', 'PASSED', 1, 1, 0, 0, now, now)
)
req_row = conn.execute('SELECT id FROM api_requests LIMIT 1').fetchone()
conn.execute(
    \"INSERT INTO api_request_results (id, collection_run_id, api_request_id, request_name, order_index, status, status_code, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)\",
    (generate_id('arreq'), run_id, req_row['id'], 'Create invoice', 0, 'PASSED', 201, now, now)
)
conn.commit()
from cli import sync
print(sync.sync_api_collection_run_to_cloud(run_id))
"
```
Expected: mock server logs `POST /api/sync/api-collection-run` with one entry in `request_results`.

- [ ] **Step 3: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): push standalone api_collection_runs history to cloud"
```

---

### Task 10: `cli/sync.py` — fold mixed-suite `api_runs` into existing run sync

**Files:**
- Modify: `cli/sync.py`

**Interfaces:**
- Produces: `_gather_api_run_results(suite_run_id)` helper; `sync_run_to_cloud` gains an `api_results=None` parameter.
- Consumes internally: no new entity type, rides on the existing `run` sync path.

- [ ] **Step 1: Add the gather helper**

Add directly after the Task 9 function:

```python
def _gather_api_run_results(suite_run_id):
    """Build the api_results payload list for a mixed E2E+API suite run
    (rows from the api_runs table, interleaved with script_runs via order_index)."""
    from cli.db import get_conn
    rows = get_conn().execute(
        "SELECT ar.api_request_id, req.name AS request_name, ar.order_index, ar.status, "
        "ar.status_code, ar.duration_ms, ar.response_body, ar.response_headers, "
        "ar.assertion_results, ar.error_message, ar.started_at, ar.finished_at "
        "FROM api_runs ar JOIN api_requests req ON ar.api_request_id = req.id "
        "WHERE ar.suite_run_id = ? ORDER BY ar.order_index", (suite_run_id,)
    ).fetchall()
    return [
        {
            "cli_request_id": r["api_request_id"],
            "request_name": r["request_name"],
            "order_index": r["order_index"],
            "status": (r["status"] or "error").lower(),
            "status_code": r["status_code"],
            "duration_ms": r["duration_ms"],
            "response_body": r["response_body"],
            "response_headers": json.loads(r["response_headers"]) if r["response_headers"] else None,
            "assertion_results": json.loads(r["assertion_results"]) if r["assertion_results"] else None,
            "error_message": r["error_message"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
        }
        for r in rows
    ]
```

- [ ] **Step 2: Modify `sync_run_to_cloud`'s signature and payload**

Change:
```python
def sync_run_to_cloud(run_id, suite_id, status, started_at, completed_at, duration_ms, script_results,
                      project_id=None, browser=None, resolution=None, headless=None):
    """Sync a completed test run with all script results.
    Ensures the parent suite (and its project) are synced first."""
    key = get_auth_key()
    if not key:
        return None
    if project_id and suite_id:
        _ensure_suite_synced(suite_id, project_id)
    payload = {
        "run_id": run_id,
        "suite_id": suite_id,
        "status": status.lower(),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "script_results": script_results,
    }
    if browser:
```
to:
```python
def sync_run_to_cloud(run_id, suite_id, status, started_at, completed_at, duration_ms, script_results,
                      project_id=None, browser=None, resolution=None, headless=None, api_results=None):
    """Sync a completed test run with all script results (and, for mixed
    E2E+API suites, api_results). Ensures the parent suite (and its project)
    are synced first."""
    key = get_auth_key()
    if not key:
        return None
    if project_id and suite_id:
        _ensure_suite_synced(suite_id, project_id)
    payload = {
        "run_id": run_id,
        "suite_id": suite_id,
        "status": status.lower(),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "script_results": script_results,
    }
    if api_results:
        payload["api_results"] = api_results
    if browser:
```

- [ ] **Step 3: Wire it into `sync_all`'s run loop**

In `sync_all`, change the `sync_run_to_cloud(...)` call to add one line:
```python
            result = sync_run_to_cloud(
                run_id=run["id"],
                suite_id=run["suite_id"],
                status=run["status"],
                started_at=started,
                completed_at=finished,
                duration_ms=0,
                project_id=pid,
                browser=run["browser"],
                resolution=run["resolution"],
                headless=bool(run["headless"]) if run["headless"] is not None else None,
                api_results=_gather_api_run_results(run["id"]),
                script_results=[
```
(add the `api_results=_gather_api_run_results(run["id"]),` line right before `script_results=[`)

- [ ] **Step 4: Verify manually**

```bash
python -c "
from cli.db import get_conn, generate_id
from datetime import datetime, timezone
conn = get_conn()
now = datetime.now(timezone.utc).isoformat()
sr_row = conn.execute('SELECT id FROM suite_runs LIMIT 1').fetchone()
if sr_row:
    req_row = conn.execute('SELECT id FROM api_requests LIMIT 1').fetchone()
    conn.execute(
        \"INSERT INTO api_runs (id, suite_run_id, api_request_id, order_index, status, status_code, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)\",
        (generate_id('apirun'), sr_row['id'], req_row['id'], 0, 'PASSED', 200, now, now)
    )
    conn.commit()
    from cli import sync
    print(sync._gather_api_run_results(sr_row['id']))
else:
    print('no suite_runs rows to test with — run a suite once first, then re-run this check')
"
```
Expected: a list with one dict (or the fallback message if you have no `suite_runs` rows yet — run any suite through the web UI once to get one, then re-run).

- [ ] **Step 5: Commit**

```bash
git add cli/sync.py
git commit -m "feat(sync): fold mixed-suite api_runs into existing run push"
```

---

### Task 11: `cli/sync_queue.py` — register new entity types

**Files:**
- Modify: `cli/sync_queue.py`

**Interfaces:**
- Consumes: every `sync_*_to_cloud`/`delete_*_from_cloud` function from Tasks 4-10.
- Produces: the new entity types become drainable from the offline queue, and `enqueue_all()` (used by the Push button) picks them up automatically.

- [ ] **Step 1: Extend `ENTITY_ORDER`**

Change:
```python
ENTITY_ORDER = (
    "project",
    "feature",
    "suite",
    "script",
    "environment",
    "env_vars",
    "suite_items",
    "run",
)
```
to:
```python
ENTITY_ORDER = (
    "project",
    "feature",
    "suite",
    "script",
    "api_collection",
    "api_folder",
    "api_request",
    "collection_vars",
    "api_request_example",
    "environment",
    "env_vars",
    "suite_items",
    "api_collection_run",
    "run",
)
```

- [ ] **Step 2: Extend `_dispatch`'s delete-branch dict and add upsert branches**

Change:
```python
    with sync.strict_mode():
        if op == "delete":
            {
                "project": sync.delete_project_from_cloud,
                "feature": sync.delete_feature_from_cloud,
                "suite": sync.delete_suite_from_cloud,
                "script": sync.delete_script_from_cloud,
                "environment": sync.delete_environment_from_cloud,
            }[et](eid)
            return
```
to:
```python
    with sync.strict_mode():
        if op == "delete":
            {
                "project": sync.delete_project_from_cloud,
                "feature": sync.delete_feature_from_cloud,
                "suite": sync.delete_suite_from_cloud,
                "script": sync.delete_script_from_cloud,
                "environment": sync.delete_environment_from_cloud,
                "api_collection": sync.delete_api_collection_from_cloud,
                "api_folder": sync.delete_api_folder_from_cloud,
                "api_request": sync.delete_api_request_from_cloud,
                "api_request_example": sync.delete_api_request_example_from_cloud,
            }[et](eid)
            return
```

Then, in the same function, add these branches right after the existing `elif et == "script":` block and before `elif et == "environment":` (order in the `if/elif` chain doesn't matter functionally, but keep it near its `ENTITY_ORDER` position for readability):

```python
        elif et == "api_collection":
            sync.sync_api_collection_to_cloud(eid)
        elif et == "api_folder":
            sync.sync_api_folder_to_cloud(eid)
        elif et == "api_request":
            sync.sync_api_request_to_cloud(eid)
        elif et == "collection_vars":
            sync.sync_collection_vars_to_cloud(eid)
        elif et == "api_request_example":
            sync.sync_api_request_example_to_cloud(eid)
        elif et == "api_collection_run":
            sync.sync_api_collection_run_to_cloud(eid)
```

- [ ] **Step 3: Wire `api_results` into `_dispatch_run`**

Change the `sync.sync_run_to_cloud(...)` call inside `_dispatch_run` to add one argument:
```python
    sync.sync_run_to_cloud(
        run_id=run_id,
        suite_id=run["suite_id"],
        status=run["status"],
        started_at=run["started_at"] or "",
        completed_at=run["finished_at"] or run["started_at"] or "",
        duration_ms=0,
        project_id=run["project_id"],
        browser=run["browser"],
        resolution=run["resolution"],
        headless=bool(run["headless"]) if run["headless"] is not None else None,
        api_results=sync._gather_api_run_results(run_id),
        script_results=[
```
(add the `api_results=sync._gather_api_run_results(run_id),` line right before `script_results=[`)

- [ ] **Step 4: Extend `enqueue_all`**

Change:
```python
    for pid in project_ids:
        enqueue("project", pid, "upsert")
        for f in conn.execute("SELECT id FROM features WHERE project_id = ?", (pid,)).fetchall():
            enqueue("feature", f["id"], "upsert")
        for s in conn.execute("SELECT id FROM suites WHERE project_id = ?", (pid,)).fetchall():
            enqueue("suite", s["id"], "upsert")
            enqueue("suite_items", s["id"], "upsert")
        for sc in conn.execute("SELECT id FROM scripts WHERE project_id = ?", (pid,)).fetchall():
            enqueue("script", sc["id"], "upsert")
        for env in conn.execute("SELECT id FROM environments WHERE project_id = ?", (pid,)).fetchall():
            enqueue("environment", env["id"], "upsert")
            enqueue("env_vars", env["id"], "upsert")
        for run in conn.execute("SELECT id FROM suite_runs WHERE project_id = ?", (pid,)).fetchall():
            enqueue("run", run["id"], "upsert")
```
to:
```python
    for pid in project_ids:
        enqueue("project", pid, "upsert")
        for f in conn.execute("SELECT id FROM features WHERE project_id = ?", (pid,)).fetchall():
            enqueue("feature", f["id"], "upsert")
        for s in conn.execute("SELECT id FROM suites WHERE project_id = ?", (pid,)).fetchall():
            enqueue("suite", s["id"], "upsert")
            enqueue("suite_items", s["id"], "upsert")
        for sc in conn.execute("SELECT id FROM scripts WHERE project_id = ?", (pid,)).fetchall():
            enqueue("script", sc["id"], "upsert")
        for col in conn.execute("SELECT id FROM api_collections WHERE project_id = ?", (pid,)).fetchall():
            enqueue("api_collection", col["id"], "upsert")
            enqueue("collection_vars", col["id"], "upsert")
        for fold in conn.execute("SELECT id FROM api_folders WHERE project_id = ?", (pid,)).fetchall():
            enqueue("api_folder", fold["id"], "upsert")
        for req in conn.execute("SELECT id FROM api_requests WHERE project_id = ?", (pid,)).fetchall():
            enqueue("api_request", req["id"], "upsert")
            for ex in conn.execute(
                "SELECT id FROM api_request_examples WHERE api_request_id = ?", (req["id"],)
            ).fetchall():
                enqueue("api_request_example", ex["id"], "upsert")
        for env in conn.execute("SELECT id FROM environments WHERE project_id = ?", (pid,)).fetchall():
            enqueue("environment", env["id"], "upsert")
            enqueue("env_vars", env["id"], "upsert")
        for run in conn.execute("SELECT id FROM suite_runs WHERE project_id = ?", (pid,)).fetchall():
            enqueue("run", run["id"], "upsert")
        for arun in conn.execute("SELECT id FROM api_collection_runs WHERE project_id = ?", (pid,)).fetchall():
            enqueue("api_collection_run", arun["id"], "upsert")
```

- [ ] **Step 5: Verify manually**

```bash
python -c "
from cli.sync_queue import enqueue_all, drain_once, queue_depth
enqueued, depth = enqueue_all()
print('enqueued:', enqueued, 'depth:', depth)
synced, failed, offline = drain_once(max_items=100)
print('synced:', synced, 'failed:', failed, 'offline:', offline)
print('remaining depth:', queue_depth())
"
```
(with the mock server from Task 2 running, and the rows created in Tasks 4-9/10 still in the DB)
Expected: `enqueued` > 0, `synced` equals it (or close — some may already be queued from earlier manual tests), `failed: 0`, `offline: False`, `remaining depth: 0`. Watch the mock server's terminal scroll through every entity type's POST.

- [ ] **Step 6: Commit**

```bash
git add cli/sync_queue.py
git commit -m "feat(sync-queue): register api-testing entities in the drain queue"
```

---

### Task 12: Wire `enqueue()` into `web/api/routes/collections.py`

**Files:**
- Modify: `web/api/routes/collections.py`

**Interfaces:**
- Consumes: `cli.sync_queue.enqueue` (existing), the `api_collection`/`collection_vars` entity types (Task 11).

- [ ] **Step 1: Add the import**

Add near the top, with the other imports:
```python
from cli.sync_queue import enqueue
```

- [ ] **Step 2: Enqueue on every mutation**

In `create_collection`, after `col = _svc.create(...)`, before the `return`:
```python
        col = _svc.create(_project_id(), data.get("name", ""), data.get("description"))
        enqueue("api_collection", col["id"], "upsert")
        return jsonify({"ok": True, "collection": col}), 201
```

In `update_collection`, same pattern:
```python
        col = _svc.update(col_id, _project_id(), data.get("name", ""), data.get("description"))
        enqueue("api_collection", col_id, "upsert")
        return jsonify({"ok": True, "collection": col})
```

In `delete_collection`:
```python
        _svc.delete(col_id, _project_id())
        enqueue("api_collection", col_id, "delete")
        return jsonify({"ok": True})
```

In `patch_collection`, after the `CollectionRepo().update(...)` call:
```python
        CollectionRepo().update(
            col_id,
            body.get("name", col["name"]),
            body.get("description", col.get("description")),
            body.get("env_name", col.get("env_name")),
            body.get("auth_type", col.get("auth_type", "none")),
            body.get("auth_config", col.get("auth_config", "{}")),
        )
        enqueue("api_collection", col_id, "upsert")
        return jsonify({"ok": True, "collection": CollectionRepo().get(col_id, pid)})
```

In `reorder_collections`, after `_svc.reorder(...)`:
```python
        _svc.reorder(_project_id(), ids)
        for cid in ids:
            enqueue("api_collection", cid, "upsert")
        return jsonify({"ok": True})
```

In `upsert_collection_var`, after `CollectionVarsRepo().upsert(...)`:
```python
        result = CollectionVarsRepo().upsert(col_id, key, body.get("initial_value", ""))
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True, "var": result})
```

In `delete_collection_var`, after `CollectionVarsRepo().delete(...)`:
```python
        CollectionVarsRepo().delete(col_id, key)
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True})
```
(note: `"upsert"`, not `"delete"` — `collection_vars` is a full-replace list, same as `env_vars`; a var deletion re-sends the whole remaining list)

- [ ] **Step 3: Verify manually**

Start the web server (`python qaclan.py serve --port 7823`) with `QACLAN_SERVER_URL` pointed at the Task 2 mock and an active project set. Then:
```bash
curl -s -X POST http://127.0.0.1:7823/api/collections -H "Content-Type: application/json" -d '{"name": "Test Collection"}'
```
Expected: mock server's terminal (from Task 2) logs a `POST /api/sync/api-collection` within a few seconds (background worker drains it) — or immediately if you also hit `POST /api/sync/push` on the local server. Confirm via:
```bash
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/collections.py
git commit -m "feat(collections): enqueue cloud sync on collection/vars mutations"
```

---

### Task 13: Wire `enqueue()` into `web/api/routes/folders.py`

**Files:**
- Modify: `web/api/routes/folders.py`

**Interfaces:**
- Consumes: `cli.sync_queue.enqueue`, `cli.db.get_conn` (existing), the `api_folder`/`api_request` entity types.

- [ ] **Step 1: Add imports**

```python
from cli.sync_queue import enqueue
```

- [ ] **Step 2: Enqueue on every mutation**

In `create_folder`:
```python
        folder = _svc.create(_project_id(), col_id, data.get("name", ""), data.get("parent_folder_id"))
        enqueue("api_folder", folder["id"], "upsert")
        return jsonify({"ok": True, "folder": folder}), 201
```

In `update_folder`:
```python
        folder = _svc.update(folder_id, _project_id(), data)
        enqueue("api_folder", folder_id, "upsert")
        return jsonify({"ok": True, "folder": folder})
```

In `delete_folder`:
```python
        _svc.delete(folder_id, _project_id())
        enqueue("api_folder", folder_id, "delete")
        return jsonify({"ok": True})
```

In `reorder_tree`, after `_svc.reorder(...)`. A reorder/reparent can move both folders and requests across parent scopes at once, and `FolderService.reorder`'s internals aren't touched by this task — the safe, simple move is to re-enqueue every folder and request in the whole collection (idempotent, a little extra network traffic on reorder, but guarantees nothing is under-synced):
```python
        _svc.reorder(col_id, _project_id(), data.get("parent_folder_id"), items)
        from cli.db import get_conn
        conn = get_conn()
        for row in conn.execute("SELECT id FROM api_folders WHERE collection_id = ?", (col_id,)).fetchall():
            enqueue("api_folder", row["id"], "upsert")
        for row in conn.execute("SELECT id FROM api_requests WHERE collection_id = ?", (col_id,)).fetchall():
            enqueue("api_request", row["id"], "upsert")
        return jsonify({"ok": True})
```

- [ ] **Step 3: Verify manually**

```bash
curl -s -X POST http://127.0.0.1:7823/api/collections/<col_id>/folders -H "Content-Type: application/json" -d '{"name": "Invoices"}'
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```
Expected: mock server logs `POST /api/sync/api-folder`.

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/folders.py
git commit -m "feat(folders): enqueue cloud sync on folder mutations"
```

---

### Task 14: Wire `enqueue()` into `web/api/routes/requests.py`

**Files:**
- Modify: `web/api/routes/requests.py`

**Interfaces:**
- Consumes: `cli.sync_queue.enqueue`, the `api_request` entity type.

- [ ] **Step 1: Add import**

```python
from cli.sync_queue import enqueue
```

- [ ] **Step 2: Enqueue on every mutation**

In `create_request`:
```python
        req = _svc.create(_project_id(), data)
        enqueue("api_request", req["id"], "upsert")
        return jsonify({"ok": True, "request": req}), 201
```

In `update_request`:
```python
        req = _svc.update(req_id, _project_id(), data)
        enqueue("api_request", req_id, "upsert")
        return jsonify({"ok": True, "request": req})
```

In `patch_request`:
```python
        req = _svc.update(req_id, pid, merged)
        enqueue("api_request", req_id, "upsert")
        return jsonify({"ok": True, "request": req})
```

In `delete_request`:
```python
        _svc.delete(req_id, _project_id())
        enqueue("api_request", req_id, "delete")
        return jsonify({"ok": True})
```

- [ ] **Step 3: Verify manually**

```bash
curl -s -X POST http://127.0.0.1:7823/api/api-requests -H "Content-Type: application/json" -d '{"name": "Get invoice", "method": "GET", "url": "{{baseUrl}}/invoices/1"}'
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```
Expected: mock server logs `POST /api/sync/api-request`.

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/requests.py
git commit -m "feat(requests): enqueue cloud sync on request mutations"
```

---

### Task 15: Wire `enqueue()` into `web/api/services/discovery_service.py`

**Files:**
- Modify: `web/api/services/discovery_service.py`

**Interfaces:**
- Consumes: `cli.sync_queue.enqueue`.
- Rationale: `_save_requests` (bulk import/review-and-save flow) and `save_library` (variant-library "Save as Library" flow) create `api_collections`/`api_requests`/`api_request_examples` rows directly through the repos, bypassing the routes wired in Tasks 12-14 — these need their own enqueue calls.

- [ ] **Step 1: Add import**

```python
from cli.sync_queue import enqueue
```

- [ ] **Step 2: Enqueue in `_save_requests`**

Change:
```python
        saved_req = _req_repo.create(project_id, data)

        # Sync to API docs if flagged (default: include)
```
to:
```python
        saved_req = _req_repo.create(project_id, data)
        enqueue("api_request", saved_req["id"], "upsert")

        # Sync to API docs if flagged (default: include)
```

- [ ] **Step 3: Enqueue in `save_library`**

Change:
```python
    col = _col_repo.create(project_id, collection_name)
    example_repo = RequestExampleRepo()
```
to:
```python
    col = _col_repo.create(project_id, collection_name)
    enqueue("api_collection", col["id"], "upsert")
    example_repo = RequestExampleRepo()
```

Change:
```python
            saved_req = _req_repo.create(project_id, merged_req)
            try:
                sync_doc_entry(project_id, {**merged_req, "id": saved_req["id"]})
            except Exception as e:
                logger.warning("sync_doc_entry failed for merged request %s: %s", saved_req["id"], e)

            included_requests = [v["request"] for v in included]
            diff_fields = compute_diff_fields(included_requests)
            for i, v in enumerate(included[1:], start=1):
                r = v["request"]
                example_repo.create(saved_req["id"], {
                    "label": suggest_label(r, diff_fields, i),
                    "params": r.get("params", []),
                    "body": r.get("body"),
                    "response_status": r.get("response_status"),
                    "response_headers": r.get("response_headers"),
                    "response_body": r.get("response_body"),
                })
            saved += 1
```
to:
```python
            saved_req = _req_repo.create(project_id, merged_req)
            enqueue("api_request", saved_req["id"], "upsert")
            try:
                sync_doc_entry(project_id, {**merged_req, "id": saved_req["id"]})
            except Exception as e:
                logger.warning("sync_doc_entry failed for merged request %s: %s", saved_req["id"], e)

            included_requests = [v["request"] for v in included]
            diff_fields = compute_diff_fields(included_requests)
            for i, v in enumerate(included[1:], start=1):
                r = v["request"]
                example = example_repo.create(saved_req["id"], {
                    "label": suggest_label(r, diff_fields, i),
                    "params": r.get("params", []),
                    "body": r.get("body"),
                    "response_status": r.get("response_status"),
                    "response_headers": r.get("response_headers"),
                    "response_body": r.get("response_body"),
                })
                enqueue("api_request_example", example["id"], "upsert")
            saved += 1
```

Note: the `else` branch of `save_library` (the "separate" action) calls `_save_requests(...)`, which already enqueues from Step 2 above — no separate change needed there.

- [ ] **Step 4: Verify manually**

Exercise the discovery/save-as-library flow via the web UI (record or import a session, use "Save as Library" on a group with 2+ variants), then:
```bash
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```
Expected: mock server logs `POST /api/sync/api-collection`, one or more `POST /api/sync/api-request`, and at least one `POST /api/sync/api-request-example`.

- [ ] **Step 5: Commit**

```bash
git add web/api/services/discovery_service.py
git commit -m "feat(discovery): enqueue cloud sync for bulk-saved requests/examples"
```

---

### Task 16: Wire `enqueue()` into `web/api/services/runner_service.py`

**Files:**
- Modify: `web/api/services/runner_service.py`

**Interfaces:**
- Consumes: `cli.sync_queue.enqueue`, the `api_collection_run` entity type.

- [ ] **Step 1: Enqueue after `_execute_collection` finishes**

In the `finally` block of `_execute_collection`, after `run_repo.finish_run(...)`:
```python
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed_c,
                error_count=err_c,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            from cli.sync_queue import enqueue
            enqueue("api_collection_run", run_id, "upsert")
            logger.info("_execute_collection: run %s → %s", run_id, final_status)
```

- [ ] **Step 2: Enqueue after `run_collection` finishes** (the synchronous variant — currently unreferenced by any route, kept in parity for whenever it is used)

In the `finally` block of `run_collection`, after `run_repo.finish_run(...)`:
```python
            run_repo.finish_run(
                run_id=run_id,
                status=final_status,
                total=len(results),
                passed=passed,
                failed=failed,
                error_count=error_count,
                finished_at=finished_at,
            )
            from cli.sync_queue import enqueue
            enqueue("api_collection_run", run_id, "upsert")
```

- [ ] **Step 3: Verify manually**

```bash
curl -s -X POST http://127.0.0.1:7823/api/collections/<col_id>/run -H "Content-Type: application/json" -d '{}'
sleep 2   # let the background collection-run thread finish
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```
Expected: mock server logs `POST /api/sync/api-collection-run` once the run reaches a terminal state.

- [ ] **Step 4: Commit**

```bash
git add web/api/services/runner_service.py
git commit -m "feat(runner): enqueue collection run history for cloud sync on completion"
```

---

### Task 17: `cli/commands/pull.py` — merge core entities from `pull_workspace()`

**Files:**
- Modify: `cli/commands/pull.py`

**Interfaces:**
- Consumes: `data.get("api_collections"|"api_folders"|"api_requests"|"collection_vars")` from `GET /api/pull/workspace` (server plan Section 3).
- Produces: `collection_map`, `folder_map` (local `pull_workspace()` maps, mirroring `project_map`/`feature_map`).

- [ ] **Step 1: Add new maps and counts**

Change:
```python
    # Track cloud_id -> local_id mappings for resolving foreign keys
    project_map = {}   # cloud project id -> local project id
    feature_map = {}   # cloud feature id -> local feature id
    suite_map = {}     # cloud suite id -> local suite id
    script_map = {}    # cloud script cli_script_id -> local script id
    env_map = {}       # cloud environment id -> local environment id

    counts = {"projects": 0, "features": 0, "scripts": 0, "suites": 0, "environments": 0, "env_vars": 0}
```
to:
```python
    # Track cloud_id -> local_id mappings for resolving foreign keys
    project_map = {}    # cloud project id -> local project id
    feature_map = {}    # cloud feature id -> local feature id
    suite_map = {}      # cloud suite id -> local suite id
    script_map = {}     # cloud script cli_script_id -> local script id
    env_map = {}        # cloud environment id -> local environment id
    collection_map = {} # cloud api_collection id -> local api_collection id
    folder_map = {}     # cloud api_folder id -> local api_folder id

    counts = {
        "projects": 0, "features": 0, "scripts": 0, "suites": 0, "environments": 0, "env_vars": 0,
        "api_collections": 0, "api_folders": 0, "api_requests": 0, "collection_vars": 0,
    }
```

- [ ] **Step 2: Insert the merge steps after the existing "3. Scripts" block, before "4. Environments"**

Insert this block between the scripts loop and the `# 4. Environments` comment:

```python
    # 3b. API collections
    for c in data.get("api_collections", []):
        cloud_id = c["id"]
        existing = conn.execute("SELECT id FROM api_collections WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE api_collections SET name = ?, description = ?, env_name = ?, auth_type = ?, "
                "auth_config = ?, order_index = ? WHERE id = ?",
                (c["name"], c.get("description"), c.get("env_name"), c.get("auth_type", "none"),
                 json.dumps(c.get("auth_config", {})), c.get("order_index", 0), existing["id"]),
            )
            collection_map[cloud_id] = existing["id"]
        else:
            local_project_id = project_map.get(c["project_id"])
            if not local_project_id:
                continue
            local_id = generate_id("apicol")
            conn.execute(
                "INSERT INTO api_collections (id, project_id, name, description, env_name, auth_type, "
                "auth_config, order_index, created_at, cloud_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_project_id, c["name"], c.get("description"), c.get("env_name"),
                 c.get("auth_type", "none"), json.dumps(c.get("auth_config", {})),
                 c.get("order_index", 0), now, cloud_id),
            )
            collection_map[cloud_id] = local_id
            counts["api_collections"] += 1
            console.print(f"  [green]✓[/green] API collection: {c['name']}")

    # 3c. API folders — self-referential tree, resolve parents before children.
    # Repeatedly sweep the pulled list, inserting any folder whose parent is
    # already resolved (or has none), until a full pass makes no progress.
    pending_folders = list(data.get("api_folders", []))
    while pending_folders:
        progressed = False
        still_pending = []
        for f in pending_folders:
            cloud_id = f["id"]
            parent_cloud_id = f.get("parent_folder_id")
            if parent_cloud_id and parent_cloud_id not in folder_map:
                existing_parent = conn.execute(
                    "SELECT id FROM api_folders WHERE cloud_id = ?", (parent_cloud_id,)
                ).fetchone()
                if existing_parent:
                    folder_map[parent_cloud_id] = existing_parent["id"]
                else:
                    still_pending.append(f)
                    continue
            local_parent_id = folder_map.get(parent_cloud_id) if parent_cloud_id else None
            existing = conn.execute("SELECT id FROM api_folders WHERE cloud_id = ?", (cloud_id,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE api_folders SET name = ?, order_index = ?, parent_folder_id = ? WHERE id = ?",
                    (f["name"], f.get("order_index", 0), local_parent_id, existing["id"]),
                )
                folder_map[cloud_id] = existing["id"]
            else:
                local_project_id = project_map.get(f.get("project_id"))
                local_collection_id = collection_map.get(f.get("collection_id"))
                if not local_project_id or not local_collection_id:
                    continue
                local_id = generate_id("apifold")
                conn.execute(
                    "INSERT INTO api_folders (id, project_id, collection_id, parent_folder_id, name, "
                    "order_index, created_at, cloud_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (local_id, local_project_id, local_collection_id, local_parent_id,
                     f["name"], f.get("order_index", 0), now, cloud_id),
                )
                folder_map[cloud_id] = local_id
                counts["api_folders"] += 1
                console.print(f"  [green]✓[/green] API folder: {f['name']}")
            progressed = True
        if not progressed:
            for f in still_pending:
                console.print(f"  [yellow]⚠[/yellow] API folder skipped (unresolved parent): {f.get('name')}")
            break
        pending_folders = still_pending

    # 3d. API requests
    for r in data.get("api_requests", []):
        cloud_id = r["id"]
        local_project_id = project_map.get(r.get("project_id"))
        local_feature_id = feature_map.get(r.get("feature_id")) if r.get("feature_id") else None
        local_collection_id = collection_map.get(r.get("collection_id")) if r.get("collection_id") else None
        local_folder_id = folder_map.get(r.get("folder_id")) if r.get("folder_id") else None
        row_values = (
            r["name"], r.get("method", "GET"), r.get("url", ""),
            json.dumps(r.get("headers", [])), json.dumps(r.get("params", [])),
            json.dumps(r.get("path_params", [])), r.get("body_type"), r.get("body"),
            r.get("auth_type", "none"), json.dumps(r.get("auth_config", {})),
            r.get("pre_script"), r.get("pre_lang", "js"),
            json.dumps(r["pre_extractor"]) if r.get("pre_extractor") else None,
            r.get("post_script"), r.get("post_lang", "js"),
            json.dumps(r["post_extractor"]) if r.get("post_extractor") else None,
            json.dumps(r["request_schema"]) if r.get("request_schema") else None,
            json.dumps(r["response_schema"]) if r.get("response_schema") else None,
            json.dumps(r.get("assertions", [])),
            1 if r.get("follow_redirects", True) else 0, r.get("timeout_ms", 30000),
            1 if r.get("include_in_docs", True) else 0, r.get("order_index", 0),
        )
        existing = conn.execute("SELECT id FROM api_requests WHERE cloud_id = ?", (cloud_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE api_requests SET name=?, method=?, url=?, headers=?, params=?, path_params=?, "
                "body_type=?, body=?, auth_type=?, auth_config=?, pre_script=?, pre_lang=?, pre_extractor=?, "
                "post_script=?, post_lang=?, post_extractor=?, request_schema=?, response_schema=?, "
                "assertions=?, follow_redirects=?, timeout_ms=?, include_in_docs=?, order_index=?, "
                "feature_id=?, collection_id=?, folder_id=? WHERE id=?",
                row_values + (local_feature_id, local_collection_id, local_folder_id, existing["id"]),
            )
        else:
            if not local_project_id:
                console.print(f"  [yellow]⚠[/yellow] API request skipped (missing project): {r.get('name')}")
                continue
            local_id = generate_id("apireq")
            conn.execute(
                "INSERT INTO api_requests (id, project_id, feature_id, collection_id, folder_id, name, "
                "method, url, headers, params, path_params, body_type, body, auth_type, auth_config, "
                "pre_script, pre_lang, pre_extractor, post_script, post_lang, post_extractor, "
                "request_schema, response_schema, assertions, follow_redirects, timeout_ms, "
                "include_in_docs, order_index, created_at, cloud_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_project_id, local_feature_id, local_collection_id, local_folder_id)
                + row_values + (now, cloud_id),
            )
            counts["api_requests"] += 1
            console.print(f"  [green]✓[/green] API request: {r.get('name')}")

    # 3e. Collection variables (full-replace-list semantics, like env_vars)
    for v in data.get("collection_vars", []):
        local_collection_id = collection_map.get(v["collection_id"])
        if not local_collection_id:
            continue
        existing = conn.execute(
            "SELECT id FROM collection_vars WHERE collection_id = ? AND key = ?",
            (local_collection_id, v["key"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ? WHERE id = ?",
                (v["initial_value"], existing["id"]),
            )
        else:
            local_id = generate_id("cv")
            conn.execute(
                "INSERT INTO collection_vars (id, collection_id, key, initial_value, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (local_id, local_collection_id, v["key"], v["initial_value"], now),
            )
            counts["collection_vars"] += 1

```

- [ ] **Step 3: Add the `json` import**

At the top of `cli/commands/pull.py`, `json` is already imported (line 1: `import json`) — no change needed here.

- [ ] **Step 4: Verify manually**

Point the mock server's `/api/pull/workspace` at canned data (edit the mock's `pull_workspace()` to return one collection/folder/request/var, matching Section 3's example payload in the server plan), then:
```bash
curl -s -X POST http://127.0.0.1:7823/api/sync/pull | python -m json.tool
sqlite3 ~/.qaclan/qaclan.db "SELECT name, cloud_id FROM api_collections"
sqlite3 ~/.qaclan/qaclan.db "SELECT name, cloud_id FROM api_requests"
```
Expected: the pulled collection/request appear locally with `cloud_id` populated. Run the pull a second time — row counts don't double (update path, not insert).

- [ ] **Step 5: Commit**

```bash
git add cli/commands/pull.py
git commit -m "feat(pull): merge api_collections/api_folders/api_requests/collection_vars"
```

---

### Task 18: On-demand pull — team run history and docs cache

**Files:**
- Modify: `cli/commands/pull.py` (new functions), `web/api/routes/api_collection_runs.py`, `web/api/routes/docs.py`

**Interfaces:**
- Consumes: `api.pull_api_runs`, `api.pull_api_run_detail`, `api.pull_api_docs` (Task 3).
- Produces: `pull_api_run_history(project_id)`, `pull_api_docs_overlay(project_id)` in `cli/commands/pull.py`; two new routes.

- [ ] **Step 1: Add `pull_api_run_history` to `cli/commands/pull.py`**

```python
def pull_api_run_history(project_id):
    """On-demand pull of standalone collection-run history for one project.
    Not part of pull_workspace() — called lazily when the API Runs view opens.
    Returns the number of new runs inserted."""
    key = get_auth_key()
    if not key:
        raise RuntimeError("Not logged in")
    conn = get_conn()
    inserted = 0
    page = 1
    while True:
        data = api.pull_api_runs(key, page=page, per_page=50)
        runs = data.get("runs", [])
        if not runs:
            break
        for run_summary in runs:
            # Match on cli_collection_run_id (the pushing client's own local id) first —
            # api_collection_runs has no cloud_id column, so if this row was originally
            # pushed FROM this machine, its local id already equals cli_collection_run_id
            # and this avoids inserting a second, duplicate copy under the server's id.
            # Falls back to the server's id only for runs this machine never pushed itself.
            local_run_id = run_summary.get("cli_collection_run_id") or run_summary["id"]
            existing = conn.execute(
                "SELECT id FROM api_collection_runs WHERE id = ?", (local_run_id,)
            ).fetchone()
            if existing:
                continue  # runs are immutable once finished — nothing to update
            local_collection_row = conn.execute(
                "SELECT id FROM api_collections WHERE cloud_id = ?", (run_summary["collection_id"],)
            ).fetchone()
            if not local_collection_row:
                continue  # collection not pulled locally yet — skip, will retry next pull
            detail = api.pull_api_run_detail(key, run_summary["id"])
            conn.execute(
                "INSERT INTO api_collection_runs (id, project_id, collection_id, collection_name, "
                "env_name, status, total, passed, failed, error_count, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_run_id, project_id, local_collection_row["id"], run_summary["collection_name"],
                 run_summary.get("env_name"), run_summary["status"].upper(), run_summary["total"],
                 run_summary["passed"], run_summary["failed"], run_summary["error_count"],
                 run_summary["started_at"], run_summary.get("completed_at")),
            )
            for r in detail.get("request_results", []):
                local_request_row = conn.execute(
                    "SELECT id FROM api_requests WHERE cloud_id = ?", (r["cli_request_id"],)
                ).fetchone()
                if not local_request_row:
                    # Parent request not pulled locally (yet, or ever — e.g. deleted since).
                    # api_request_results.api_request_id is NOT NULL + FK-enforced
                    # (PRAGMA foreign_keys = ON, cli/db.py:20) — inserting the raw cloud
                    # request id here would raise sqlite3.IntegrityError. Skip the row
                    # instead, same as every other orphan guard in pull_workspace().
                    continue
                conn.execute(
                    "INSERT INTO api_request_results (id, collection_run_id, api_request_id, "
                    "request_name, method, url, order_index, status, status_code, response_body, "
                    "response_headers, duration_ms, assertion_results, error_message, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (generate_id("arreq"), local_run_id, local_request_row["id"],
                     r["request_name"], r.get("method"), r.get("url"), r["order_index"],
                     r["status"].upper(), r.get("status_code"), r.get("response_body"),
                     json.dumps(r["response_headers"]) if r.get("response_headers") else None,
                     r.get("duration_ms"),
                     json.dumps(r["assertion_results"]) if r.get("assertion_results") else None,
                     r.get("error_message"), r.get("started_at"), r.get("finished_at")),
                )
            inserted += 1
        if len(runs) < 50:
            break
        page += 1
    conn.commit()
    return inserted
```

- [ ] **Step 2: Add `pull_api_docs_overlay` to `cli/commands/pull.py`**

```python
def pull_api_docs_overlay(project_id):
    """On-demand pull of the server-computed docs cache for one project. Overlay
    semantics: only overwrite a local doc entry if the pulled last_seen_at is
    newer, so a user's own live-regenerated local docs aren't clobbered by a
    stale team snapshot. Returns the number of entries updated or inserted."""
    key = get_auth_key()
    if not key:
        raise RuntimeError("Not logged in")
    conn = get_conn()
    data = api.pull_api_docs(key, project_id)
    changed = 0
    for entry in data.get("doc_entries", []):
        existing = conn.execute(
            "SELECT id, last_seen_at FROM api_doc_entries WHERE project_id = ? AND method = ? AND path_pattern = ?",
            (project_id, entry["method"], entry["path_pattern"]),
        ).fetchone()
        if existing and existing["last_seen_at"] >= entry["last_seen_at"]:
            continue  # local copy is newer or equal — don't clobber
        if existing:
            conn.execute(
                "UPDATE api_doc_entries SET request_schema=?, response_schema=?, headers_schema=?, "
                "params_schema=?, source_request_ids=?, last_seen_at=? WHERE id=?",
                (json.dumps(entry.get("request_schema")) if entry.get("request_schema") else None,
                 json.dumps(entry.get("response_schema")) if entry.get("response_schema") else None,
                 json.dumps(entry.get("headers_schema")) if entry.get("headers_schema") else None,
                 json.dumps(entry.get("params_schema")) if entry.get("params_schema") else None,
                 json.dumps(entry.get("source_request_ids", [])), entry["last_seen_at"], existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO api_doc_entries (id, project_id, method, path_pattern, description, "
                "request_schema, response_schema, headers_schema, params_schema, source_request_ids, "
                "include_in_docs, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (generate_id("apidoc"), project_id, entry["method"], entry["path_pattern"],
                 entry.get("description"),
                 json.dumps(entry.get("request_schema")) if entry.get("request_schema") else None,
                 json.dumps(entry.get("response_schema")) if entry.get("response_schema") else None,
                 json.dumps(entry.get("headers_schema")) if entry.get("headers_schema") else None,
                 json.dumps(entry.get("params_schema")) if entry.get("params_schema") else None,
                 json.dumps(entry.get("source_request_ids", [])),
                 1 if entry.get("include_in_docs", True) else 0,
                 entry.get("first_seen_at", entry["last_seen_at"]), entry["last_seen_at"]),
            )
        changed += 1
    conn.commit()
    return changed
```

- [ ] **Step 3: Add trigger routes**

In `web/api/routes/api_collection_runs.py`, add:
```python
@bp.route("/api/api-collection-runs/pull-team", methods=["POST"])
def pull_team_api_runs():
    try:
        from cli.commands.pull import pull_api_run_history
        pid = _project_id()
        inserted = pull_api_run_history(pid)
        return jsonify({"ok": True, "inserted": inserted})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("pull_team_api_runs")
        return jsonify({"ok": False, "error": str(e)}), 500
```

In `web/api/routes/docs.py`, add:
```python
@bp.route("/api/docs/pull-team", methods=["POST"])
def pull_team_docs():
    try:
        from cli.commands.pull import pull_api_docs_overlay
        pid = _project_id()
        changed = pull_api_docs_overlay(pid)
        return jsonify({"ok": True, "changed": changed})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("pull_team_docs")
        return jsonify({"ok": False, "error": str(e)}), 500
```

(Wiring a UI button/trigger for these two routes into the "API Runs" and "Docs" tab views is a small frontend follow-up, left out of this plan's scope — the routes are usable standalone via curl for now, same testing posture as the rest of this plan.)

- [ ] **Step 4: Verify manually**

Update the mock server's `/api/pull/api-runs` and `/api/pull/api-docs` handlers to return one canned run / doc entry each (matching the shapes in server plan Sections 3.2/3.3), restart it, then:
```bash
curl -s -X POST http://127.0.0.1:7823/api/api-collection-runs/pull-team
curl -s -X POST http://127.0.0.1:7823/api/docs/pull-team
sqlite3 ~/.qaclan/qaclan.db "SELECT id, status FROM api_collection_runs"
sqlite3 ~/.qaclan/qaclan.db "SELECT method, path_pattern FROM api_doc_entries"
```
Expected: both commands return `{"ok": true, ...}` and the canned rows appear locally.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/pull.py web/api/routes/api_collection_runs.py web/api/routes/docs.py
git commit -m "feat(pull): on-demand team run-history and docs-cache pull"
```

---

### Task 19: End-to-end manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Full push round-trip**

With the Task 2 mock server running and a fresh `~/.qaclan/qaclan.db` (or a throwaway `QACLAN_HOME` override if you want to keep your real data untouched):
1. Create a project, a collection, a nested folder inside it, a request inside that folder, a collection var, and (via "Save as Library" in the UI) a variant example.
2. Run the collection once (`POST /api/collections/<id>/run`) so an `api_collection_run` exists.
3. `curl -s -X POST http://127.0.0.1:7823/api/sync/push`
4. Confirm the mock server's terminal shows, in some order: `api-collection`, `api-folder`, `api-request`, `collection-vars`, `api-request-example`, `api-collection-run` — one call each, no duplicates, no errors.
5. `sqlite3 ~/.qaclan/qaclan.db "SELECT count(*) FROM sync_queue"` → expect `0`.

- [ ] **Step 2: Full pull round-trip into a second, empty local DB**

```bash
mv ~/.qaclan/qaclan.db ~/.qaclan/qaclan.db.bak   # simulate a second machine
python qaclan.py status   # recreates an empty DB via init_db()
curl -s -X POST http://127.0.0.1:7823/api/sync/pull | python -m json.tool
sqlite3 ~/.qaclan/qaclan.db "SELECT name FROM api_collections"
sqlite3 ~/.qaclan/qaclan.db "SELECT name FROM api_requests"
mv ~/.qaclan/qaclan.db.bak ~/.qaclan/qaclan.db   # restore
```
(Requires the mock's `/api/pull/workspace` to echo back what was pushed in Step 1 — for a from-scratch mock this means hand-editing its canned response to match, since the toy mock in Task 2 doesn't persist pushed data across endpoints. This is the known limitation of a throwaway mock — the real integration check happens once qaclan-server implements the companion plan.)

- [ ] **Step 3: Cascade-delete check**

```bash
curl -s -X DELETE http://127.0.0.1:7823/api/collections/<col_id>
curl -s -X POST http://127.0.0.1:7823/api/sync/push
```
Expected: mock server logs exactly one `DELETE /api/sync/api-collection/<id>` call — not one per descendant folder/request (cascade is the server's job per the server plan, not the client's).

- [ ] **Step 4: Offline resilience check**

```bash
kill %1   # stop the mock server (background job from Task 2)
curl -s -X POST http://127.0.0.1:7823/api/collections -H "Content-Type: application/json" -d '{"name": "Offline Test"}'
curl -s -X POST http://127.0.0.1:7823/api/sync/push
sqlite3 ~/.qaclan/qaclan.db "SELECT entity_type, op FROM sync_queue"
```
Expected: push response shows `remaining > 0`; the queue row for `api_collection` is still present (not lost, not marked failed — offline detection short-circuits before attempting the call). Restart the mock server and push again — it drains.

- [ ] **Step 5: No commit needed** (verification only) — if any step above surfaces a bug, fix it in the relevant task's file and amend that task's commit (or add a small follow-up commit if the task was already several commits back).

---

## Self-Review Notes

- Every entity from the design spec's scope has a task: collections (4,12), folders (5,13), requests (6,14), collection_vars (7,12), variant-library examples (8,15), standalone collection-run history (9,16), mixed-suite api_runs (10,11), pull-side merge for the four core entities (17) and on-demand run-history/docs (18).
- No placeholders — every step shows the actual diff/code, not a description of one. Field names and endpoint paths are copied verbatim from the approved server plan (Sections 1-3 of `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md`).
- Type/signature consistency checked: `sync_run_to_cloud`'s new `api_results` parameter (Task 10) is called with a matching keyword argument in both its callers (`sync_all` in Task 10, `_dispatch_run` in Task 11) — no positional-vs-keyword mismatch.
- Task 13's `reorder_tree` handling is a deliberate simplification (re-enqueue everything in the collection rather than diffing exactly what moved) — flagged inline as a conscious trade-off, not an oversight.
- **Post-review fix:** Task 18's `pull_api_run_history` originally used the server's cloud run `id` as the local primary key with no de-dup against a run this same machine had already pushed — since `api_collection_runs` has no `cloud_id` column, pulling after pushing would have inserted a second, duplicate local row for the same run. Fixed to match on `cli_collection_run_id` first (added to the server plan's `/api/pull/api-runs` response in the same fix), falling back to the cloud id only for runs this machine never pushed.
- **Post-review fix:** the same task's request-results loop originally fell back to storing the raw cloud `cli_request_id` as `api_request_id` when the parent request wasn't found locally — that column is `NOT NULL` + FK-enforced (`PRAGMA foreign_keys = ON`), so this would have raised `sqlite3.IntegrityError` and aborted the whole pull the first time a run referenced a request the local machine hadn't pulled yet. Fixed to skip that result row instead, matching every other orphan guard in `pull_workspace()`.
