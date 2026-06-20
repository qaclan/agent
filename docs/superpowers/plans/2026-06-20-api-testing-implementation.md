# API Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full API testing (requests, collections, assertions, discovery, mixed suites) to QAClan using 3-layer architecture for new backend and modular ES modules for new UI, without refactoring existing code.

**Architecture:** New backend in `web/api/` (routes→services→repositories). New UI in `web/static/api/` as ES modules exposing `window.__qaclanApi`. Existing `web/routes/` and `app.js` receive targeted additive changes only (suite runner dispatch, suite items endpoint, nav item).

**Tech Stack:** Python/Flask, httpx (HTTP), jsonpath-ng (JSONPath assertions), SQLite TEXT/JSON, vanilla JS ES modules (no build), CodeMirror 6 (existing window.CM6)

## Global Constraints
- SQLite only — TEXT for JSON columns, no JSONB
- No automated test framework — verification via `python qaclan.py serve --port 7823` + curl + browser
- Never modify existing `web/routes/*.py` logic beyond the two targeted additions described per-task
- Never refactor `web/static/app.js` existing code — additive changes only (two additions described above)
- All IDs: `generate_id(prefix)` from `cli/db.py` → `"prefix_xxxxxxxx"`
- Add to `requirements.txt`: `httpx>=0.27.0`, `jsonpath-ng>=1.6.0`
- All new Python modules: `logger = logging.getLogger("qaclan.<module_name>")`
- JSON columns stored as TEXT; parse with `json.loads()` before use, serialize with `json.dumps()` before save
- All new Python files include `from __future__ import annotations` as first import to support `X | Y` type unions on Python < 3.10. Files: `cli/api_runner.py`, `cli/env_loader.py`, `cli/api_discovery/har_parser.py`, `cli/api_discovery/openapi_parser.py`, `cli/api_discovery/postman_parser.py`, `cli/api_discovery/bruno_parser.py`, `web/api/repositories/collection_repo.py`, `web/api/repositories/request_repo.py`, `web/api/repositories/api_run_repo.py`, `web/api/services/collection_service.py`, `web/api/services/request_service.py`, `web/api/services/runner_service.py`, `web/api/services/discovery_service.py`, `web/api/routes/collections.py`, `web/api/routes/requests.py`, `web/api/routes/discovery.py`, `web/api/routes/api_runs.py`, `cli/commands/api_cmd.py`

---

### Task 1: DB Schema & Migrations

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Consumes: nothing
- Produces: `api_collections`, `api_requests`, `api_runs` tables; extended `suite_items` with `item_type`/`api_request_id`; `description` on `suites`

- [ ] Step 1: Add `_migrate_api_tables(conn)` function to `cli/db.py` after the existing `_migrate_error_detail` function:

```python
def _migrate_api_tables(conn):
    """Create api_collections, api_requests, api_runs tables and extend suite_items."""
    # 1. api_collections
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_collections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 2. api_requests
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_requests (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            feature_id TEXT REFERENCES features(id) ON DELETE SET NULL,
            collection_id TEXT REFERENCES api_collections(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'GET',
            url TEXT NOT NULL,
            headers TEXT NOT NULL DEFAULT '[]',
            params TEXT NOT NULL DEFAULT '[]',
            body_type TEXT DEFAULT NULL,
            body TEXT DEFAULT NULL,
            auth_type TEXT NOT NULL DEFAULT 'none',
            auth_config TEXT NOT NULL DEFAULT '{}',
            pre_script TEXT DEFAULT NULL,
            pre_lang TEXT DEFAULT 'js',
            post_script TEXT DEFAULT NULL,
            post_lang TEXT DEFAULT 'js',
            assertions TEXT NOT NULL DEFAULT '[]',
            follow_redirects INTEGER DEFAULT 1,
            timeout_ms INTEGER DEFAULT 30000,
            created_at TEXT NOT NULL
        )
    """)

    # 3. api_runs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_runs (
            id TEXT PRIMARY KEY,
            suite_run_id TEXT NOT NULL REFERENCES suite_runs(id) ON DELETE CASCADE,
            api_request_id TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
            order_index INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            status_code INTEGER,
            response_body TEXT,
            response_headers TEXT,
            duration_ms INTEGER,
            assertion_results TEXT,
            error_message TEXT,
            started_at TEXT,
            finished_at TEXT
        )
    """)

    # 4. Recreate suite_items with nullable script_id + item_type + api_request_id
    #    Guard: skip if item_type column already exists
    has_item_type = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('suite_items') WHERE name='item_type'"
    ).fetchone()[0]
    if not has_item_type:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ALTER TABLE suite_items RENAME TO _suite_items_old")
        conn.execute("""
            CREATE TABLE suite_items (
                id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL REFERENCES suites(id) ON DELETE CASCADE,
                script_id TEXT REFERENCES scripts(id) ON DELETE CASCADE,
                api_request_id TEXT REFERENCES api_requests(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL DEFAULT 'script',
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO suite_items (id, suite_id, script_id, item_type, order_index, created_at)
            SELECT id, suite_id, script_id, 'script', order_index, created_at
            FROM _suite_items_old
        """)
        conn.execute("DROP TABLE _suite_items_old")
        conn.execute("PRAGMA foreign_keys = ON")

    # 5. Add description column to suites (safe — nullable, no default needed)
    has_desc = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('suites') WHERE name='description'"
    ).fetchone()[0]
    if not has_desc:
        conn.execute("ALTER TABLE suites ADD COLUMN description TEXT")

    conn.commit()
```

- [ ] Step 2: Call the new function at the end of `init_db()` in `cli/db.py`. The last two lines of `init_db()` currently are:
```python
    _migrate_script_wait_timeout(conn)
    _migrate_error_detail(conn)
```
Change to:
```python
    _migrate_script_wait_timeout(conn)
    _migrate_error_detail(conn)
    _migrate_api_tables(conn)
```

- [ ] Step 3: Verify by running `python qaclan.py --help` (triggers `init_db()`) then:
```bash
sqlite3 ~/.qaclan/qaclan.db ".tables"
# should include: api_collections  api_requests  api_runs
sqlite3 ~/.qaclan/qaclan.db "PRAGMA table_info(suite_items);"
# should show item_type and api_request_id columns
```

- [ ] Step 4: Commit — `git add cli/db.py && git commit -m "feat: add api_collections, api_requests, api_runs tables; extend suite_items"`

---

### Task 2: Repository Layer

**Files:**
- Create: `web/api/__init__.py`
- Create: `web/api/routes/__init__.py`
- Create: `web/api/services/__init__.py`
- Create: `web/api/repositories/__init__.py`
- Create: `web/api/repositories/collection_repo.py`
- Create: `web/api/repositories/request_repo.py`
- Create: `web/api/repositories/api_run_repo.py`

**Interfaces:**
- Consumes: Task 1 (tables)
- Produces: repo classes consumed by Task 4 services

- [ ] Step 1: Create empty `__init__.py` files:

`web/api/__init__.py` — empty file.
`web/api/routes/__init__.py` — empty file.
`web/api/services/__init__.py` — empty file.
`web/api/repositories/__init__.py` — empty file.

- [ ] Step 2: Create `web/api/repositories/collection_repo.py`:

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.collection_repo")


class CollectionRepo:
    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ac.id, ac.name, ac.description, ac.created_at, "
            "COUNT(ar.id) AS request_count "
            "FROM api_collections ac "
            "LEFT JOIN api_requests ar ON ar.collection_id = ac.id "
            "WHERE ac.project_id = ? "
            "GROUP BY ac.id ORDER BY ac.created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, name, description, created_at FROM api_collections "
            "WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return dict(row) if row else None

    def create(self, project_id: str, name: str, description: str | None = None) -> dict:
        conn = get_conn()
        cid = generate_id("apicol")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_collections (id, project_id, name, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, project_id, name, description, now),
        )
        conn.commit()
        logger.info("CollectionRepo.create: %s (%s)", name, cid)
        return {"id": cid, "name": name, "description": description, "created_at": now, "request_count": 0}

    def update(self, id: str, name: str, description: str | None = None) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET name = ?, description = ? WHERE id = ?",
            (name, description, id),
        )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_collections WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
```

- [ ] Step 3: Create `web/api/repositories/request_repo.py`:

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.request_repo")

_DEFAULTS = {
    "method": "GET",
    "url": "",
    "headers": "[]",
    "params": "[]",
    "body_type": None,
    "body": None,
    "auth_type": "none",
    "auth_config": "{}",
    "pre_script": None,
    "pre_lang": "js",
    "post_script": None,
    "post_lang": "js",
    "assertions": "[]",
    "follow_redirects": 1,
    "timeout_ms": 30000,
}


def _serialize(data: dict) -> dict:
    """Ensure JSON list/dict fields are stored as TEXT."""
    out = dict(data)
    for key in ("headers", "params", "assertions"):
        if key in out and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    if "auth_config" in out and not isinstance(out["auth_config"], str):
        out["auth_config"] = json.dumps(out["auth_config"])
    return out


def _deserialize(row: dict) -> dict:
    out = dict(row)
    for key in ("headers", "params", "assertions"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = []
    if isinstance(out.get("auth_config"), str):
        try:
            out["auth_config"] = json.loads(out["auth_config"])
        except (ValueError, TypeError):
            out["auth_config"] = {}
    return out


class RequestRepo:
    def list(self, project_id: str, collection_id: str | None = None) -> list[dict]:
        conn = get_conn()
        if collection_id:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? AND collection_id = ? ORDER BY created_at",
                (project_id, collection_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [_deserialize(dict(r)) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_requests WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return _deserialize(dict(row)) if row else None

    def create(self, project_id: str, data: dict) -> dict:
        conn = get_conn()
        rid = generate_id("apireq")
        now = datetime.now(timezone.utc).isoformat()
        merged = {**_DEFAULTS, **_serialize(data)}
        conn.execute(
            "INSERT INTO api_requests (id, project_id, feature_id, collection_id, name, method, url, "
            "headers, params, body_type, body, auth_type, auth_config, pre_script, pre_lang, "
            "post_script, post_lang, assertions, follow_redirects, timeout_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, project_id,
             merged.get("feature_id"), merged.get("collection_id"),
             merged.get("name", "Unnamed"), merged["method"], merged["url"],
             merged["headers"], merged["params"], merged["body_type"], merged["body"],
             merged["auth_type"], merged["auth_config"],
             merged["pre_script"], merged["pre_lang"],
             merged["post_script"], merged["post_lang"],
             merged["assertions"], merged["follow_redirects"], merged["timeout_ms"],
             now),
        )
        conn.commit()
        logger.info("RequestRepo.create: %s (%s)", merged.get("name"), rid)
        return self.get(rid, project_id)

    def update(self, id: str, data: dict) -> bool:
        conn = get_conn()
        s = _serialize(data)
        fields = ["name", "method", "url", "headers", "params", "body_type", "body",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "post_script",
                  "post_lang", "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id"]
        updates = {f: s[f] for f in fields if f in s}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [id]
        cur = conn.execute(f"UPDATE api_requests SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_requests WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
```

Note: Request count per collection is retrieved via SQL COUNT in `CollectionRepo.list()` — no separate method needed.

- [ ] Step 4: Create `web/api/repositories/api_run_repo.py`:

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.api_run_repo")


def _deser(row: dict) -> dict:
    out = dict(row)
    for key in ("response_headers", "assertion_results"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = None
    return out


class ApiRunRepo:
    def create(self, suite_run_id: str, api_request_id: str, order_index: int, result: dict) -> dict:
        conn = get_conn()
        rid = generate_id("apirun")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_runs (id, suite_run_id, api_request_id, order_index, status, "
            "status_code, response_body, response_headers, duration_ms, assertion_results, "
            "error_message, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, suite_run_id, api_request_id, order_index,
             result.get("status"), result.get("status_code"),
             result.get("response_body"),
             json.dumps(result.get("response_headers")) if result.get("response_headers") is not None else None,
             result.get("duration_ms"),
             json.dumps(result.get("assertion_results")) if result.get("assertion_results") is not None else None,
             result.get("error_message"),
             result.get("started_at", now),
             result.get("finished_at", now)),
        )
        conn.commit()
        logger.info("ApiRunRepo.create: %s for suite_run %s", rid, suite_run_id)
        return self.get(rid)

    def list_by_suite_run(self, suite_run_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ar.*, req.name AS request_name, req.method, req.url "
            "FROM api_runs ar "
            "JOIN api_requests req ON ar.api_request_id = req.id "
            "WHERE ar.suite_run_id = ? ORDER BY ar.order_index",
            (suite_run_id,),
        ).fetchall()
        return [_deser(dict(r)) for r in rows]

    def get(self, id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT ar.*, req.name AS request_name, req.method, req.url "
            "FROM api_runs ar "
            "JOIN api_requests req ON ar.api_request_id = req.id "
            "WHERE ar.id = ?",
            (id,),
        ).fetchone()
        return _deser(dict(row)) if row else None
```

- [ ] Step 5: Commit — `git add web/api/ && git commit -m "feat: add repository layer for api_collections, api_requests, api_runs"`

---

### Task 3: API Runner (cli/api_runner.py)

**Files:**
- Create: `cli/api_runner.py`

**Interfaces:**
- Consumes: Task 1 (tables), active env vars dict, state.json dict
- Produces: `run_api_request()` called by Task 4 services and Task 10 suite runner

- [ ] Step 1: Create `cli/api_runner.py`:

```python
from __future__ import annotations
import json
import logging
import os
import re
import subprocess
import tempfile
import base64
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("qaclan.api_runner")

_SENSITIVE_KEY_RE = re.compile(
    r"(password|secret|token|authorization|api.?key|auth)", re.IGNORECASE
)
_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

def resolve_vars(text: str, env_vars: dict, state: dict) -> str:
    """Replace {{var_name}} in text. Order: env_vars → state.qaclan_vars → empty+warn."""
    if not text:
        return text or ""
    qc_vars = state.get("qaclan_vars", {}) if isinstance(state, dict) else {}

    def _replace(m):
        key = m.group(1).strip()
        if key in env_vars:
            return str(env_vars[key])
        if key in qc_vars:
            return str(qc_vars[key])
        logger.warning("resolve_vars: variable '%s' not found in env or state", key)
        return ""

    return _VAR_RE.sub(_replace, text)


def _resolve_list(items: list, env_vars: dict, state: dict) -> list:
    """Resolve vars in a list of {key, value, enabled} dicts."""
    out = []
    for item in items:
        if not item.get("enabled", True):
            continue
        out.append({
            "key": resolve_vars(str(item.get("key", "")), env_vars, state),
            "value": resolve_vars(str(item.get("value", "")), env_vars, state),
        })
    return out


# ---------------------------------------------------------------------------
# Auth injection
# ---------------------------------------------------------------------------

def _apply_auth(headers: dict, params: dict, auth_type: str, auth_config: dict,
                env_vars: dict, state: dict) -> tuple[dict, dict]:
    """Return updated (headers, params) with auth applied."""
    headers = dict(headers)
    params = dict(params)

    if auth_type == "bearer":
        token = resolve_vars(auth_config.get("token", ""), env_vars, state)
        headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "basic":
        username = resolve_vars(auth_config.get("username", ""), env_vars, state)
        password = resolve_vars(auth_config.get("password", ""), env_vars, state)
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    elif auth_type == "api_key":
        key_name = resolve_vars(auth_config.get("key", "X-API-Key"), env_vars, state)
        key_value = resolve_vars(auth_config.get("value", ""), env_vars, state)
        location = auth_config.get("in", "header")
        if location == "query":
            params[key_name] = key_value
        else:
            headers[key_name] = key_value

    elif auth_type == "oauth2":
        # Client credentials grant — POST to token_url, cache in state
        token_url = resolve_vars(auth_config.get("token_url", ""), env_vars, state)
        client_id = resolve_vars(auth_config.get("client_id", ""), env_vars, state)
        client_secret = resolve_vars(auth_config.get("client_secret", ""), env_vars, state)
        cache_key = f"__oauth2_token_{token_url}"
        qc_vars = state.setdefault("qaclan_vars", {})
        token = qc_vars.get(cache_key)
        if not token and token_url:
            try:
                import httpx
                resp = httpx.post(token_url, data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }, timeout=15)
                resp.raise_for_status()
                token = resp.json().get("access_token", "")
                qc_vars[cache_key] = token
            except Exception as e:
                logger.warning("OAuth2 token fetch failed: %s", e)
                token = ""
        headers["Authorization"] = f"Bearer {token or ''}"

    return headers, params


# ---------------------------------------------------------------------------
# Script sandbox
# ---------------------------------------------------------------------------

def _build_python_sandbox(script: str, context: dict) -> str:
    ctx_json = json.dumps(context)
    header = (
        "import json, os\n"
        "_ctx = " + ctx_json + "\n"
        '_output = {"headers": dict(_ctx.get("headers", {})), "params": dict(_ctx.get("params", {})), "state": {}}\n'
        "class _Qc:\n"
        "    def set(self, k, v): _output['state'][k] = v\n"
        "    def set_header(self, k, v): _output['headers'][k] = v\n"
        "    def set_param(self, k, v): _output['params'][k] = v\n"
        "qc = _Qc()\n"
        'response_body = _ctx.get("response_body", "")\n'
        'response_headers = _ctx.get("response_headers", {})\n'
        'status_code = _ctx.get("status_code", 0)\n'
        "class _Resp:\n"
        "    def json(s): return json.loads(response_body)\n"
        "    headers = response_headers\n"
        "response = _Resp()\n"
    )
    footer = (
        '\n_out = os.environ.get("QACLAN_SANDBOX_OUTPUT")\n'
        "if _out:\n"
        "    with open(_out, 'w') as _f: json.dump(_output, _f)\n"
    )
    return header + script + "\n" + footer


def _build_js_sandbox(script: str, context: dict) -> str:
    ctx_json = json.dumps(context)
    header = (
        "const _ctx = " + ctx_json + ";\n"
        "const _output = { headers: Object.assign({}, _ctx.headers), params: Object.assign({}, _ctx.params), state: {} };\n"
        "const qc = { set:(k,v)=>_output.state[k]=v, setHeader:(k,v)=>_output.headers[k]=v, setParam:(k,v)=>_output.params[k]=v };\n"
        "const response = { json:()=>JSON.parse(_ctx.response_body||'null'), headers:_ctx.response_headers||{}, status:_ctx.status_code||0 };\n"
    )
    footer = (
        "\nconst fs=require('fs'); const out=process.env.QACLAN_SANDBOX_OUTPUT;"
        " if(out) fs.writeFileSync(out,JSON.stringify(_output));\n"
    )
    return header + script + "\n" + footer


def _run_script_sandbox(script: str, lang: str, context: dict, state_path: str | None) -> dict:
    """Run pre/post script in subprocess sandbox. Returns {headers, params, state} or empty dict on error."""
    if not script or not script.strip():
        return {}

    from cli import runtime_setup

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = os.path.join(tmpdir, "output.json")
        env = os.environ.copy()
        env["QACLAN_SANDBOX_OUTPUT"] = output_file

        if lang == "python":
            wrapper = _build_python_sandbox(script, context)
            script_file = os.path.join(tmpdir, "sandbox.py")
            Path(script_file).write_text(wrapper, encoding="utf-8")
            venv_python = runtime_setup.venv_python()
            cmd = [str(venv_python) if venv_python else "python3", script_file]
        else:  # js (default)
            wrapper = _build_js_sandbox(script, context)
            script_file = os.path.join(tmpdir, "sandbox.js")
            Path(script_file).write_text(wrapper, encoding="utf-8")
            node = runtime_setup.node_bin("node")
            cmd = [str(node) if node else "node", script_file]

        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.warning("sandbox script failed (exit %d): %s", result.returncode, result.stderr[:500])
                return {}
            if os.path.exists(output_file):
                with open(output_file) as f:
                    return json.load(f)
            return {}
        except subprocess.TimeoutExpired:
            logger.warning("sandbox script timed out")
            return {}
        except Exception as e:
            logger.warning("sandbox script error: %s", e)
            return {}


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _compare(actual, op: str, expected) -> bool:
    if op == "eq":
        return str(actual) == str(expected)
    if op == "ne":
        return str(actual) != str(expected)
    if op == "lt":
        return float(actual) < float(expected)
    if op == "gt":
        return float(actual) > float(expected)
    if op == "contains":
        return str(expected) in str(actual)
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None
    if op == "matches":
        return bool(re.search(str(expected), str(actual)))
    return False


def _evaluate_assertions(assertions: list, status_code: int, response_body: str,
                          response_headers: dict, duration_ms: int) -> list[dict]:
    """Evaluate all assertions. Returns list of result dicts."""
    from jsonpath_ng import parse as jp_parse

    results = []
    try:
        body_json = json.loads(response_body) if response_body else None
    except (ValueError, TypeError):
        body_json = None

    for assertion in assertions:
        atype = assertion.get("type")
        op = assertion.get("op", "eq")
        expected = assertion.get("value")
        result = {"type": atype, "op": op, "value": expected, "passed": False, "actual": None}

        try:
            if atype == "status":
                actual = status_code
                result["actual"] = actual
                result["passed"] = _compare(actual, op, int(expected))

            elif atype == "json_path":
                path = assertion.get("path", "$")
                result["path"] = path
                if body_json is None:
                    result["passed"] = False
                    result["actual"] = None
                else:
                    expr = jp_parse(path)
                    matches = [m.value for m in expr.find(body_json)]
                    actual = matches[0] if matches else None
                    result["actual"] = actual
                    if op in ("exists", "not_exists"):
                        result["passed"] = _compare(actual if matches else None, op, expected)
                    else:
                        result["passed"] = _compare(actual, op, expected) if matches else False

            elif atype == "header":
                key = assertion.get("key", "")
                actual = response_headers.get(key) or response_headers.get(key.lower())
                result["key"] = key
                result["actual"] = actual
                result["passed"] = _compare(actual, op, expected)

            elif atype == "response_time":
                actual = duration_ms
                result["actual"] = actual
                result["passed"] = _compare(actual, op, int(expected))

            elif atype == "body_text":
                actual = response_body or ""
                result["actual"] = actual[:200]
                result["passed"] = _compare(actual, op, expected)

        except Exception as e:
            logger.warning("assertion eval error (%s): %s", atype, e)
            result["error"] = str(e)
            result["passed"] = False

        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_api_request(req: dict, env_vars: dict, state: dict, state_path: str | None = None) -> dict:
    """
    Execute a single API request.

    Args:
        req: api_request row dict (already deserialized JSON fields)
        env_vars: {key: value} from active environment
        state: parsed state.json dict (may contain qaclan_vars)
        state_path: path to state.json file (for sandbox scripts that write state)

    Returns:
        dict with keys: status, status_code, response_body, response_headers,
                        duration_ms, assertion_results, error_message, state_updates
    """
    import httpx

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    try:
        # 1. Resolve variables in URL, headers, params
        url = resolve_vars(req.get("url", ""), env_vars, state)

        raw_headers = req.get("headers", [])
        if isinstance(raw_headers, str):
            raw_headers = json.loads(raw_headers)
        resolved_headers_list = _resolve_list(raw_headers, env_vars, state)
        headers = {item["key"]: item["value"] for item in resolved_headers_list if item["key"]}

        raw_params = req.get("params", [])
        if isinstance(raw_params, str):
            raw_params = json.loads(raw_params)
        resolved_params_list = _resolve_list(raw_params, env_vars, state)
        params = {item["key"]: item["value"] for item in resolved_params_list if item["key"]}

        # 2. Apply auth
        auth_type = req.get("auth_type", "none")
        auth_config = req.get("auth_config", {})
        if isinstance(auth_config, str):
            auth_config = json.loads(auth_config)
        headers, params = _apply_auth(headers, params, auth_type, auth_config, env_vars, state)

        # 3. Pre-script
        pre_script = req.get("pre_script")
        pre_lang = req.get("pre_lang", "js")
        if pre_script:
            pre_context = {"headers": headers, "params": params, "env": env_vars}
            pre_out = _run_script_sandbox(pre_script, pre_lang, pre_context, state_path)
            if pre_out:
                headers.update(pre_out.get("headers", {}))
                params.update(pre_out.get("params", {}))
                state.setdefault("qaclan_vars", {}).update(pre_out.get("state", {}))

        # 4. Build request body
        body_type = req.get("body_type")
        body_raw = req.get("body")
        content = None
        data = None
        files = None

        if body_type == "raw" and body_raw:
            content = resolve_vars(body_raw, env_vars, state).encode()
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif body_type == "form" and body_raw:
            try:
                form_items = json.loads(body_raw)
                data = {item["key"]: resolve_vars(item["value"], env_vars, state)
                        for item in form_items if item.get("enabled", True)}
            except (ValueError, TypeError):
                data = {}
        elif body_type == "graphql" and body_raw:
            try:
                gql = json.loads(body_raw)
                content = json.dumps({
                    "query": resolve_vars(gql.get("query", ""), env_vars, state),
                    "variables": gql.get("variables", {}),
                }).encode()
                headers["Content-Type"] = "application/json"
            except (ValueError, TypeError):
                content = body_raw.encode() if body_raw else None

        # 5. Execute HTTP request
        method = req.get("method", "GET").upper()
        timeout_ms = req.get("timeout_ms", 30000)
        follow_redirects = bool(req.get("follow_redirects", 1))

        http_client = httpx.Client(
            follow_redirects=follow_redirects,
            timeout=timeout_ms / 1000.0,
        )

        with http_client:
            response = http_client.request(
                method=method,
                url=url,
                headers=headers,
                params=params or None,
                content=content,
                data=data,
                files=files,
            )

        duration_ms = int((time.time() - start_time) * 1000)
        finished_at = datetime.now(timezone.utc).isoformat()

        status_code = response.status_code
        response_body = response.text
        response_headers = dict(response.headers)

        # 6. Post-script
        state_updates = {}
        post_script = req.get("post_script")
        post_lang = req.get("post_lang", "js")
        if post_script:
            post_context = {
                "headers": headers,
                "params": params,
                "response_body": response_body,
                "response_headers": response_headers,
                "status_code": status_code,
                "env": env_vars,
            }
            post_out = _run_script_sandbox(post_script, post_lang, post_context, state_path)
            if post_out:
                state_updates = post_out.get("state", {})
                state.setdefault("qaclan_vars", {}).update(state_updates)

        # 7. Evaluate assertions
        assertions = req.get("assertions", [])
        if isinstance(assertions, str):
            assertions = json.loads(assertions)
        assertion_results = _evaluate_assertions(assertions, status_code, response_body, response_headers, duration_ms)

        all_passed = all(r["passed"] for r in assertion_results) if assertion_results else True
        status = "PASSED" if all_passed else "FAILED"

        logger.info("run_api_request: %s %s → %d (%dms) %s",
                    method, url, status_code, duration_ms, status)

        return {
            "status": status,
            "status_code": status_code,
            "response_body": response_body,
            "response_headers": response_headers,
            "duration_ms": duration_ms,
            "assertion_results": assertion_results,
            "error_message": None,
            "state_updates": state_updates,
            "started_at": started_at,
            "finished_at": finished_at,
        }

    except httpx.TimeoutException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Request timed out after {timeout_ms}ms"
        logger.error("run_api_request: timeout — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "response_body": None,
            "response_headers": {},
            "duration_ms": duration_ms,
            "assertion_results": [],
            "error_message": msg,
            "state_updates": {},
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = str(e)
        logger.error("run_api_request: error — %s", msg)
        return {
            "status": "ERROR",
            "status_code": None,
            "response_body": None,
            "response_headers": {},
            "duration_ms": duration_ms,
            "assertion_results": [],
            "error_message": msg,
            "state_updates": {},
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
```

- [ ] Step 2: Commit — `git add cli/api_runner.py && git commit -m "feat: add API runner with var resolution, auth injection, script sandbox, assertions"`

---

### Task 4: Service Layer

**Files:**
- Create: `web/api/services/collection_service.py`
- Create: `web/api/services/request_service.py`
- Create: `web/api/services/runner_service.py`

**Interfaces:**
- Consumes: Task 2 (repos), Task 3 (api_runner)
- Produces: service classes called by Task 7 routes
- Note: Collection runs are in-memory only — results NOT persisted to `api_runs`. Only suite-context runs (Task 10) write `api_runs` rows.

- [ ] Step 0: Create `cli/env_loader.py` (shared env loader — eliminates 3× duplication of decrypt+load logic):

```python
from __future__ import annotations
import logging
from cli.db import get_conn
from cli.crypto import decrypt

logger = logging.getLogger("qaclan.env_loader")


def load_env_vars(project_id: str, env_name: str | None) -> dict:
    """Load and decrypt env vars for a named environment. Returns {} if env_name is None."""
    if not env_name:
        return {}
    conn = get_conn()
    env_row = conn.execute(
        "SELECT id FROM environments WHERE project_id = ? AND name = ?",
        (project_id, env_name),
    ).fetchone()
    if not env_row:
        raise LookupError(f"Environment '{env_name}' not found")
    rows = conn.execute(
        "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
        (env_row["id"],),
    ).fetchall()
    result = {}
    for v in rows:
        val = v["value"]
        if v["is_secret"] and val:
            try:
                val = decrypt(val)
            except Exception:
                pass
        result[v["key"]] = val
    logger.debug("load_env_vars: loaded %d vars for env '%s'", len(result), env_name)
    return result
```

In `runner_service.py`: replace `_load_env_vars` function definition with `from cli.env_loader import load_env_vars` and replace all calls to `_load_env_vars(...)` with `load_env_vars(...)`.

In `api_cmd.py` (Task 11), replace the inline env-loading block in `api_run` command (the `env_vars = {}` / `if env:` / `env_row = conn.execute(...)` / loop block) with:
```python
from cli.env_loader import load_env_vars
env_vars = load_env_vars(pid, env)
```

- [ ] Step 1: Create `web/api/services/collection_service.py`:

```python
from __future__ import annotations
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.collection_service")
_col_repo = CollectionRepo()
_req_repo = RequestRepo()


class CollectionService:
    def list(self, project_id: str) -> list[dict]:
        return _col_repo.list(project_id)

    def get(self, id: str, project_id: str) -> dict:
        col = _col_repo.get(id, project_id)
        if col is None:
            raise LookupError(f"Collection {id} not found")
        col["requests"] = _req_repo.list(project_id, collection_id=id)
        return col

    def create(self, project_id: str, name: str, description: str | None = None) -> dict:
        if not name or not name.strip():
            raise ValueError("Collection name is required")
        return _col_repo.create(project_id, name.strip(), description)

    def update(self, id: str, project_id: str, name: str, description: str | None = None) -> dict:
        if not name or not name.strip():
            raise ValueError("Collection name is required")
        existing = _col_repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Collection {id} not found")
        _col_repo.update(id, name.strip(), description)
        return _col_repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        existing = _col_repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Collection {id} not found")
        return _col_repo.delete(id)
```

- [ ] Step 2: Create `web/api/services/request_service.py`:

```python
from __future__ import annotations
import logging
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.request_service")
_repo = RequestRepo()


class RequestService:
    def list(self, project_id: str, collection_id: str | None = None) -> list[dict]:
        return _repo.list(project_id, collection_id=collection_id)

    def get(self, id: str, project_id: str) -> dict:
        req = _repo.get(id, project_id)
        if req is None:
            raise LookupError(f"Request {id} not found")
        return req

    def create(self, project_id: str, data: dict) -> dict:
        if not data.get("name", "").strip():
            raise ValueError("Request name is required")
        if not data.get("url", "").strip():
            raise ValueError("URL is required")
        return _repo.create(project_id, data)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        _repo.update(id, data)
        return _repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        return _repo.delete(id)

    def send(self, id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single request ad-hoc (not stored in api_runs). Returns result dict."""
        from web.api.services.runner_service import RunnerService
        return RunnerService().run_request(id, project_id, env_name=env_name)
```

- [ ] Step 3: Create `web/api/services/runner_service.py`:

```python
from __future__ import annotations
import json
import logging
from cli.db import get_conn
from cli.config import get_active_project_id

logger = logging.getLogger("qaclan.runner_service")


def _load_env_vars(project_id: str, env_name: str | None) -> dict:
    """Load env vars from DB for a named environment. Returns {} if env_name is None."""
    if not env_name:
        return {}
    conn = get_conn()
    env_row = conn.execute(
        "SELECT id FROM environments WHERE project_id = ? AND name = ?",
        (project_id, env_name),
    ).fetchone()
    if not env_row:
        raise LookupError(f"Environment '{env_name}' not found")
    from cli.crypto import decrypt as _dec

    rows = conn.execute(
        "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
        (env_row["id"],),
    ).fetchall()
    result = {}
    for v in rows:
        val = v["value"]
        if v["is_secret"] and val:
            try:
                val = _dec(val)
            except Exception:
                pass
        result[v["key"]] = val
    return result


class RunnerService:
    def run_request(self, request_id: str, project_id: str, env_name: str | None = None) -> dict:
        """Run a single api_request ad-hoc. Result is NOT stored in api_runs."""
        from web.api.repositories.request_repo import RequestRepo
        from cli.api_runner import run_api_request

        req = RequestRepo().get(request_id, project_id)
        if req is None:
            raise LookupError(f"Request {request_id} not found")

        env_vars = _load_env_vars(project_id, env_name)
        state: dict = {}

        result = run_api_request(req, env_vars, state, state_path=None)
        return result

    def run_collection(self, collection_id: str, project_id: str,
                       env_name: str | None = None) -> dict:
        """Run all requests in a collection sequentially. Results returned in-memory, NOT stored in api_runs."""
        from web.api.repositories.collection_repo import CollectionRepo
        from web.api.repositories.request_repo import RequestRepo
        from cli.api_runner import run_api_request

        col = CollectionRepo().get(collection_id, project_id)
        if col is None:
            raise LookupError(f"Collection {collection_id} not found")

        requests = RequestRepo().list(project_id, collection_id=collection_id)
        env_vars = _load_env_vars(project_id, env_name)

        state: dict = {}
        results = []
        passed = failed = 0

        for idx, req in enumerate(requests):
            result = run_api_request(req, env_vars, state, state_path=None)
            results.append({
                "request_id": req["id"],
                "name": req["name"],
                "method": req["method"],
                "url": req["url"],
                **result,
            })
            if result["status"] == "PASSED":
                passed += 1
            else:
                failed += 1

        final_status = "PASSED" if failed == 0 else "FAILED"
        return {
            "collection_id": collection_id,
            "collection_name": col["name"],
            "status": final_status,
            "total": len(requests),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
```

- [ ] Step 4: Commit — `git add web/api/services/ && git commit -m "feat: add collection, request, runner services"`

---

### Task 5: Discovery Parsers

**Files:**
- Create: `cli/api_discovery/__init__.py`
- Create: `cli/api_discovery/har_parser.py`
- Create: `cli/api_discovery/openapi_parser.py`
- Create: `cli/api_discovery/postman_parser.py`
- Create: `cli/api_discovery/bruno_parser.py`

**Interfaces:**
- Consumes: nothing (pure parsing)
- Produces: `list[dict]` of request dicts consumed by Task 6 discovery service

- [ ] Step 1: Create `cli/api_discovery/__init__.py` — empty file.

- [ ] Step 2: Create `cli/api_discovery/har_parser.py`:

```python
from __future__ import annotations
import logging
import re

logger = logging.getLogger("qaclan.har_parser")

_STATIC_EXT_RE = re.compile(r"\.(css|js|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp|map)$", re.IGNORECASE)
_STATIC_PATH_RE = re.compile(r"/static/|/assets/|/_next/|/favicon")
_SENSITIVE_RE = re.compile(r"(password|secret|token|authorization|api.?key|auth)", re.IGNORECASE)
_STATIC_CONTENT_TYPES = {
    "text/css", "text/javascript", "application/javascript",
    "image/png", "image/jpeg", "image/gif", "image/svg+xml",
    "image/x-icon", "font/woff", "font/woff2",
}


def _is_static(entry: dict) -> bool:
    url = entry.get("request", {}).get("url", "")
    content_type = ""
    for h in entry.get("response", {}).get("headers", []):
        if h.get("name", "").lower() == "content-type":
            content_type = h.get("value", "").split(";")[0].strip().lower()
            break
    if _STATIC_EXT_RE.search(url):
        return True
    if _STATIC_PATH_RE.search(url):
        return True
    if content_type in _STATIC_CONTENT_TYPES:
        return True
    return False


def _redact_sensitive(key: str, value: str) -> str:
    if _SENSITIVE_RE.search(key):
        safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", key).upper()
        return "{{" + safe_key + "}}"
    return value


def parse_har(har_json: dict) -> list[dict]:
    """Parse HAR JSON → list of api_request dicts."""
    entries = har_json.get("log", {}).get("entries", [])
    results = []

    for entry in entries:
        if _is_static(entry):
            continue

        req = entry.get("request", {})
        method = req.get("method", "GET").upper()
        url = req.get("url", "")
        if not url:
            continue

        # Strip query string from URL — put params in params list
        qs_idx = url.find("?")
        base_url = url[:qs_idx] if qs_idx >= 0 else url

        # Params from queryString array
        params = []
        for qs in req.get("queryString", []):
            k = qs.get("name", "")
            v = _redact_sensitive(k, qs.get("value", ""))
            params.append({"key": k, "value": v, "enabled": True})

        # Headers — skip pseudo-headers and common browser headers
        skip_headers = {"accept-encoding", "connection", "host", ":method", ":path", ":scheme", ":authority"}
        headers = []
        for h in req.get("headers", []):
            name = h.get("name", "")
            if name.lower() in skip_headers or name.startswith(":"):
                continue
            v = _redact_sensitive(name, h.get("value", ""))
            headers.append({"key": name, "value": v, "enabled": True})

        # Body
        body_type = None
        body = None
        post_data = req.get("postData", {})
        if post_data:
            mime = post_data.get("mimeType", "")
            text = post_data.get("text", "")
            if "json" in mime:
                body_type = "raw"
                body = text
            elif "form" in mime:
                body_type = "form"
                params_list = []
                for p in post_data.get("params", []):
                    k = p.get("name", "")
                    v = _redact_sensitive(k, p.get("value", ""))
                    params_list.append({"key": k, "value": v, "enabled": True})
                body = str(params_list)
            else:
                body_type = "raw"
                body = text

        # Generate a name from method + path
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        path = parsed.path or "/"
        name = f"{method} {path}"

        results.append({
            "name": name,
            "method": method,
            "url": base_url,
            "headers": headers,
            "params": params,
            "body_type": body_type,
            "body": body,
            "auth_type": "none",
            "auth_config": "{}",
            "assertions": "[]",
        })

    logger.info("parse_har: extracted %d requests from %d entries", len(results), len(entries))
    return results
```

- [ ] Step 3: Create `cli/api_discovery/openapi_parser.py`:

```python
from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger("qaclan.openapi_parser")


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref string within the spec."""
    parts = ref.lstrip("#/").split("/")
    node = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _schema_to_example(schema: dict, spec: dict, depth: int = 0) -> object:
    """Generate a sample value from a JSON Schema node."""
    if depth > 5:
        return None
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    stype = schema.get("type", "object")
    if stype == "object":
        props = schema.get("properties", {})
        return {k: _schema_to_example(v, spec, depth + 1) for k, v in props.items()}
    if stype == "array":
        items = schema.get("items", {})
        return [_schema_to_example(items, spec, depth + 1)]
    if stype == "string":
        return schema.get("enum", ["string"])[0]
    if stype == "integer":
        return 0
    if stype == "number":
        return 0.0
    if stype == "boolean":
        return True
    return None


def _parse_openapi3(spec: dict) -> list[dict]:
    results = []
    servers = spec.get("servers", [{}])
    base_url = servers[0].get("url", "") if servers else ""

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            op = path_item.get(method)
            if not op:
                continue

            tags = op.get("tags", ["default"])
            collection_name = tags[0] if tags else "default"
            op_id = op.get("operationId", "")
            summary = op.get("summary", "")
            name = summary or op_id or f"{method.upper()} {path}"

            # Parameters → headers + query params
            headers = []
            params = []
            for param in op.get("parameters", []) + path_item.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(spec, param["$ref"])
                p_name = param.get("name", "")
                p_in = param.get("in", "query")
                example = _schema_to_example(param.get("schema", {}), spec)
                value = str(example) if example is not None else ""
                if p_in == "query":
                    params.append({"key": p_name, "value": value, "enabled": True})
                elif p_in == "header":
                    headers.append({"key": p_name, "value": value, "enabled": True})
                # path params — substitute in URL
                if p_in == "path":
                    path = path.replace("{" + p_name + "}", value or f"{{{p_name}}}")

            # Request body
            body_type = None
            body = None
            req_body = op.get("requestBody", {})
            if "$ref" in req_body:
                req_body = _resolve_ref(spec, req_body["$ref"])
            content = req_body.get("content", {})
            if "application/json" in content:
                schema = content["application/json"].get("schema", {})
                example = _schema_to_example(schema, spec)
                body_type = "raw"
                body = json.dumps(example, indent=2)
            elif "application/x-www-form-urlencoded" in content:
                body_type = "form"
                schema = content["application/x-www-form-urlencoded"].get("schema", {})
                example = _schema_to_example(schema, spec)
                form_items = []
                if isinstance(example, dict):
                    form_items = [{"key": k, "value": str(v), "enabled": True} for k, v in example.items()]
                body = json.dumps(form_items)

            # Generate status assertion from responses
            assertions = []
            for status_str in op.get("responses", {}):
                try:
                    code = int(status_str)
                    if 200 <= code < 300:
                        assertions.append({"type": "status", "op": "lt", "value": 400})
                        break
                except ValueError:
                    pass

            url = base_url.rstrip("/") + path

            results.append({
                "name": name,
                "method": method.upper(),
                "url": url,
                "headers": headers,
                "params": params,
                "body_type": body_type,
                "body": body,
                "auth_type": "none",
                "auth_config": "{}",
                "assertions": json.dumps(assertions),
                "collection_name": collection_name,
            })
    return results


def _parse_swagger2(spec: dict) -> list[dict]:
    results = []
    host = spec.get("host", "localhost")
    base_path = spec.get("basePath", "/")
    schemes = spec.get("schemes", ["https"])
    base_url = f"{schemes[0]}://{host}{base_path}".rstrip("/")

    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not op:
                continue

            tags = op.get("tags", ["default"])
            collection_name = tags[0] if tags else "default"
            name = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"

            params = []
            headers = []
            body_type = None
            body = None

            for param in op.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(spec, param["$ref"])
                p_name = param.get("name", "")
                p_in = param.get("in", "query")
                if p_in == "query":
                    params.append({"key": p_name, "value": "", "enabled": True})
                elif p_in == "header":
                    headers.append({"key": p_name, "value": "", "enabled": True})
                elif p_in == "body":
                    schema = param.get("schema", {})
                    example = _schema_to_example(schema, spec)
                    body_type = "raw"
                    body = json.dumps(example, indent=2)

            url = base_url + path
            results.append({
                "name": name,
                "method": method.upper(),
                "url": url,
                "headers": headers,
                "params": params,
                "body_type": body_type,
                "body": body,
                "auth_type": "none",
                "auth_config": "{}",
                "assertions": "[]",
                "collection_name": collection_name,
            })
    return results


def parse_openapi(spec: dict) -> list[dict]:
    """Parse OpenAPI 3.x or Swagger 2.x spec → list of request dicts."""
    if "openapi" in spec:
        return _parse_openapi3(spec)
    elif "swagger" in spec:
        return _parse_swagger2(spec)
    else:
        logger.warning("parse_openapi: unrecognised spec format")
        return []
```

- [ ] Step 4: Create `cli/api_discovery/postman_parser.py`:

```python
from __future__ import annotations
import json
import logging

logger = logging.getLogger("qaclan.postman_parser")


def _process_item(item: dict, collection_name: str, results: list):
    """Recursively process Postman collection items (folders and requests)."""
    # If item has sub-items, it's a folder
    if "item" in item:
        folder_name = item.get("name", collection_name)
        for sub in item["item"]:
            _process_item(sub, folder_name, results)
        return

    # It's a request
    req = item.get("request", {})
    if not req:
        return

    name = item.get("name", "Unnamed Request")

    # URL
    url_obj = req.get("url", {})
    if isinstance(url_obj, str):
        url = url_obj
        params = []
    else:
        raw = url_obj.get("raw", "")
        # Rebuild from parts if raw is empty
        if not raw:
            host = ".".join(url_obj.get("host", []))
            path = "/".join(url_obj.get("path", []))
            raw = f"https://{host}/{path}"
        url = raw.split("?")[0]
        params = []
        for q in url_obj.get("query", []):
            if not q.get("disabled", False):
                params.append({
                    "key": q.get("key", ""),
                    "value": q.get("value", ""),
                    "enabled": True,
                })

    method = req.get("method", "GET").upper()

    # Headers
    headers = []
    for h in req.get("header", []):
        if not h.get("disabled", False):
            headers.append({
                "key": h.get("key", ""),
                "value": h.get("value", ""),
                "enabled": True,
            })

    # Body
    body_type = None
    body = None
    body_obj = req.get("body", {})
    if body_obj:
        mode = body_obj.get("mode", "")
        if mode == "raw":
            body_type = "raw"
            body = body_obj.get("raw", "")
        elif mode == "urlencoded":
            body_type = "form"
            items = []
            for p in body_obj.get("urlencoded", []):
                if not p.get("disabled", False):
                    items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True})
            body = json.dumps(items)
        elif mode == "formdata":
            body_type = "multipart"
            items = []
            for p in body_obj.get("formdata", []):
                if not p.get("disabled", False):
                    items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True})
            body = json.dumps(items)
        elif mode == "graphql":
            body_type = "graphql"
            gql = body_obj.get("graphql", {})
            body = json.dumps({"query": gql.get("query", ""), "variables": gql.get("variables", {})})

    # Post-script from Postman test scripts
    post_script = None
    for event in item.get("event", []):
        if event.get("listen") == "test":
            script_lines = event.get("script", {}).get("exec", [])
            post_script = "\n".join(script_lines)
            break

    results.append({
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": "none",
        "auth_config": "{}",
        "assertions": "[]",
        "post_script": post_script,
        "post_lang": "js",
        "collection_name": collection_name,
    })


def parse_postman(collection: dict) -> list[dict]:
    """Parse Postman Collection v2.1 JSON → list of request dicts."""
    # Support both v2 and v2.1 wrappers
    info = collection.get("info", {})
    collection_name = info.get("name", "Imported Collection")

    items = collection.get("item", [])
    results = []
    for item in items:
        _process_item(item, collection_name, results)

    logger.info("parse_postman: extracted %d requests", len(results))
    return results
```

- [ ] Step 5: Create `cli/api_discovery/bruno_parser.py`:

```python
from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger("qaclan.bruno_parser")

# Section header regex: matches "meta {", "headers {", "body:json {", etc.
_SECTION_RE = re.compile(r"^(\w[\w:.-]*)\s*\{")
_KV_RE = re.compile(r"^\s*([\w\-\.]+)\s*:\s*(.*?)\s*$")


def _parse_bru_sections(text: str) -> dict:
    """Parse .bru text into a dict of section_name → list of lines."""
    sections: dict[str, list[str]] = {}
    current = None
    depth = 0

    for line in text.splitlines():
        stripped = line.strip()
        m = _SECTION_RE.match(stripped)
        if m and depth == 0:
            current = m.group(1)
            sections[current] = []
            depth = 1
            continue
        if stripped == "}" and depth == 1:
            depth = 0
            current = None
            continue
        if current is not None:
            sections[current].append(line)

    return sections


def parse_bruno(bru_text: str) -> list[dict]:
    """Parse a single .bru file → list with one request dict."""
    sections = _parse_bru_sections(bru_text)

    # meta section: name, method, url, seq
    meta = {}
    for line in sections.get("meta", []):
        m = _KV_RE.match(line)
        if m:
            meta[m.group(1)] = m.group(2)

    name = meta.get("name", "Imported Request")
    method = meta.get("method", "GET").upper()

    # http section has the URL
    url = ""
    for line in sections.get("http", []):
        m = _KV_RE.match(line)
        if m and m.group(1) == "url":
            url = m.group(2)
            break
    # Also check get/post/put/delete/patch direct sections
    for verb in ("get", "post", "put", "patch", "delete"):
        if verb in sections:
            for line in sections[verb]:
                m = _KV_RE.match(line)
                if m and m.group(1) == "url":
                    url = m.group(2)
                    method = verb.upper()
                    break

    # headers section
    headers = []
    for line in sections.get("headers", []):
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            if not key.startswith("~"):  # ~ prefix means disabled in Bruno
                headers.append({"key": key, "value": m.group(2), "enabled": True})
            else:
                headers.append({"key": key[1:], "value": m.group(2), "enabled": False})

    # params:query section
    params = []
    for line in sections.get("params:query", []):
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            enabled = not key.startswith("~")
            params.append({"key": key.lstrip("~"), "value": m.group(2), "enabled": enabled})

    # body:json section
    body_type = None
    body = None
    if "body:json" in sections:
        body_type = "raw"
        body = "\n".join(sections["body:json"]).strip()
    elif "body:form-urlencoded" in sections:
        body_type = "form"
        items = []
        for line in sections["body:form-urlencoded"]:
            m = _KV_RE.match(line)
            if m:
                items.append({"key": m.group(1), "value": m.group(2), "enabled": True})
        body = json.dumps(items)

    # script:post-response section
    post_script = None
    if "script:post-response" in sections:
        post_script = "\n".join(sections["script:post-response"]).strip()

    # assertions section (Bruno format: assert { path op value })
    assertions = []
    for line in sections.get("assert", []):
        parts = line.strip().split(None, 2)
        if len(parts) >= 3:
            path, op, value = parts[0], parts[1], parts[2]
            # Map Bruno operators to QAClan operators
            op_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "contains": "contains"}
            assertions.append({
                "type": "json_path",
                "path": path,
                "op": op_map.get(op, "eq"),
                "value": value,
            })

    result = {
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": "none",
        "auth_config": "{}",
        "assertions": json.dumps(assertions),
        "post_script": post_script,
        "post_lang": "js",
    }

    logger.info("parse_bruno: extracted request '%s' %s %s", name, method, url)
    return [result]


def request_to_bru(req: dict) -> str:
    """Convert a QAClan api_request dict to Bruno .bru format string."""
    import json as _json
    lines = [
        "meta {",
        f"  name: {req.get('name', 'Request')}",
        f"  method: {req.get('method', 'GET')}",
        "  seq: 1",
        "}",
        "",
        f"{req.get('method', 'GET').lower()} {{",
        f"  url: {req.get('url', '')}",
        "}",
        "",
    ]
    headers = req.get("headers", [])
    if isinstance(headers, str):
        headers = _json.loads(headers)
    if headers:
        lines.append("headers {")
        for h in headers:
            prefix = "" if h.get("enabled", True) else "~"
            lines.append(f"  {prefix}{h.get('key', '')}: {h.get('value', '')}")
        lines.append("}")
        lines.append("")
    body = req.get("body")
    body_type = req.get("body_type")
    if body and body_type == "raw":
        lines.append("body:json {")
        for line in body.splitlines():
            lines.append(f"  {line}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] Step 6: Commit — `git add cli/api_discovery/ && git commit -m "feat: add HAR, OpenAPI, Postman, Bruno discovery parsers"`

---

### Task 6: Discovery Service

**Files:**
- Create: `web/api/services/discovery_service.py`

**Interfaces:**
- Consumes: Task 5 (parsers), Task 2 (RequestRepo, CollectionRepo)
- Produces: `DiscoveryService` methods called by Task 8 routes

- [ ] Step 1: Create `web/api/services/discovery_service.py`:

```python
from __future__ import annotations
import json
import logging
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.discovery_service")

_col_repo = CollectionRepo()
_req_repo = RequestRepo()


def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        if collection_id:
            data["collection_id"] = collection_id
        # Ensure JSON fields are lists/dicts (RequestRepo.create handles serialization)
        for key in ("headers", "params"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except (ValueError, TypeError):
                    data[key] = []
        if isinstance(data.get("assertions"), str):
            try:
                data["assertions"] = json.loads(data["assertions"])
            except (ValueError, TypeError):
                data["assertions"] = []
        if isinstance(data.get("auth_config"), str):
            try:
                data["auth_config"] = json.loads(data["auth_config"])
            except (ValueError, TypeError):
                data["auth_config"] = {}
        _req_repo.create(project_id, data)
        saved += 1
    return saved


class DiscoveryService:
    def import_har(self, project_id: str, har_json: dict,
                   collection_name: str | None = None) -> dict:
        from cli.api_discovery.har_parser import parse_har
        requests = parse_har(har_json)
        col_id = None
        if collection_name and requests:
            col = _col_repo.create(project_id, collection_name)
            col_id = col["id"]
        count = _save_requests(project_id, requests, collection_id=col_id)
        logger.info("import_har: saved %d requests (collection_id=%s)", count, col_id)
        return {"imported": count, "collection_id": col_id}

    def import_openapi(self, project_id: str, spec_or_url) -> dict:
        from cli.api_discovery.openapi_parser import parse_openapi
        if isinstance(spec_or_url, str) and spec_or_url.startswith("http"):
            import httpx
            resp = httpx.get(spec_or_url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                spec = resp.json()
            else:
                import yaml
                spec = yaml.safe_load(resp.text)
        else:
            spec = spec_or_url

        requests = parse_openapi(spec)

        # Group by collection_name (tag)
        by_tag: dict[str, list] = {}
        for req in requests:
            tag = req.get("collection_name", "default")
            by_tag.setdefault(tag, []).append(req)

        collections_created = []
        total = 0
        for tag, tag_requests in by_tag.items():
            col = _col_repo.create(project_id, tag)
            count = _save_requests(project_id, tag_requests, collection_id=col["id"])
            total += count
            collections_created.append({"id": col["id"], "name": tag, "count": count})

        logger.info("import_openapi: saved %d requests across %d collections", total, len(collections_created))
        return {"imported": total, "collections": collections_created}

    def import_postman(self, project_id: str, collection_json: dict) -> dict:
        from cli.api_discovery.postman_parser import parse_postman
        requests = parse_postman(collection_json)

        # Group by collection_name (folder)
        by_folder: dict[str, list] = {}
        for req in requests:
            folder = req.get("collection_name", "Imported")
            by_folder.setdefault(folder, []).append(req)

        total = 0
        for folder, folder_reqs in by_folder.items():
            col = _col_repo.create(project_id, folder)
            total += _save_requests(project_id, folder_reqs, collection_id=col["id"])

        logger.info("import_postman: saved %d requests", total)
        return {"imported": total}

    def import_bruno(self, project_id: str, bru_files: list[dict]) -> dict:
        """bru_files: list of {name: str, content: str}"""
        from cli.api_discovery.bruno_parser import parse_bruno
        total = 0
        for f in bru_files:
            requests = parse_bruno(f.get("content", ""))
            # Use filename (without .bru) as request name if not set
            for req in requests:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = f.get("name", "Request").replace(".bru", "")
            total += _save_requests(project_id, requests)

        logger.info("import_bruno: saved %d requests from %d files", total, len(bru_files))
        return {"imported": total}

    # ------------------------------------------------------------------ recording
    def launch_recorder(self, url: str, har_path: str) -> "subprocess.Popen":
        """Non-blocking. Launch Playwright browser to record HAR. Stop via proc.terminate()."""
        harness = (
            "import asyncio, os, signal\n"
            "from playwright.async_api import async_playwright\n"
            "async def main():\n"
            "    stop = asyncio.Event()\n"
            "    loop = asyncio.get_event_loop()\n"
            "    loop.add_signal_handler(signal.SIGTERM, stop.set)\n"
            "    loop.add_signal_handler(signal.SIGINT, stop.set)\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        await (await ctx.new_page()).goto(os.environ['QACLAN_START_URL'])\n"
            "        await stop.wait()\n"
            "        await ctx.close()\n"
            "asyncio.run(main())\n"
        )
        return self._spawn_harness(url, har_path, harness, blocking=False)

    def record_sync(self, url: str, har_path: str) -> None:
        """Blocking. Returns when user closes browser. HAR flushed via ctx.close()."""
        harness = (
            "import asyncio, os\n"
            "from playwright.async_api import async_playwright\n"
            "async def main():\n"
            "    async with async_playwright() as pw:\n"
            "        browser = await pw.chromium.launch(headless=False)\n"
            "        ctx = await browser.new_context(record_har_path=os.environ['QACLAN_HAR_PATH'])\n"
            "        await (await ctx.new_page()).goto(os.environ['QACLAN_START_URL'])\n"
            "        await browser.wait_for_event('disconnected')\n"
            "        await ctx.close()\n"
            "asyncio.run(main())\n"
        )
        self._spawn_harness(url, har_path, harness, blocking=True)

    def _spawn_harness(self, url: str, har_path: str, harness_src: str, blocking: bool):
        import os, subprocess, tempfile
        from cli import runtime_setup
        d = tempfile.mkdtemp(prefix="qaclan_record_")
        f = os.path.join(d, "record.py")
        with open(f, "w") as fh:
            fh.write(harness_src)
        venv_py = runtime_setup.venv_python()
        env = dict(os.environ)
        env["QACLAN_HAR_PATH"] = har_path
        env["QACLAN_START_URL"] = url
        bp = runtime_setup.browsers_path_if_present()
        if bp:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(bp)
        cmd = [str(venv_py) if venv_py.exists() else "python3", f]
        if blocking:
            subprocess.run(cmd, cwd=d, env=env)
        else:
            return subprocess.Popen(cmd, cwd=d, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

- [ ] Step 2: Commit — `git add web/api/services/discovery_service.py && git commit -m "feat: add discovery service for HAR, OpenAPI, Postman, Bruno import"`

---

### Task 7: Collection & Request Routes

**Files:**
- Create: `web/api/routes/collections.py`
- Create: `web/api/routes/requests.py`

**Interfaces:**
- Consumes: Task 4 (CollectionService, RequestService, RunnerService)
- Produces: Flask blueprints registered in Task 9

- [ ] Step 1: Create `web/api/routes/collections.py`:

```python
from __future__ import annotations
import io
import json
import logging
import zipfile
from flask import Blueprint, request, jsonify, send_file
from cli.config import get_active_project_id
from web.api.services.collection_service import CollectionService
from web.api.services.runner_service import RunnerService

logger = logging.getLogger("qaclan.routes.collections")
bp = Blueprint("api_collections", __name__)
_svc = CollectionService()
_runner_svc = RunnerService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/collections", methods=["GET"])
def list_collections():
    try:
        return jsonify({"ok": True, "collections": _svc.list(_project_id())})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_collections")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections", methods=["POST"])
def create_collection():
    try:
        data = request.get_json(force=True)
        col = _svc.create(_project_id(), data.get("name", ""), data.get("description"))
        return jsonify({"ok": True, "collection": col}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["GET"])
def get_collection(col_id):
    try:
        return jsonify({"ok": True, "collection": _svc.get(col_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["PUT"])
def update_collection(col_id):
    try:
        data = request.get_json(force=True)
        col = _svc.update(col_id, _project_id(), data.get("name", ""), data.get("description"))
        return jsonify({"ok": True, "collection": col})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>", methods=["DELETE"])
def delete_collection(col_id):
    try:
        _svc.delete(col_id, _project_id())
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/run", methods=["POST"])
def run_collection(col_id):
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name")
        result = _runner_svc.run_collection(col_id, _project_id(), env_name=env_name)
        return jsonify({"ok": True, **result})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("run_collection")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/export", methods=["POST"])
def export_collection(col_id):
    """Export collection to Bruno .bru files, returned as a zip."""
    try:
        col = _svc.get(col_id, _project_id())
        requests = col.get("requests", [])

        from cli.api_discovery.bruno_parser import request_to_bru
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for req in requests:
                content = request_to_bru(req)
                safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in req.get("name", "request"))
                zf.writestr(f"{col['name']}/{safe_name}.bru", content)

        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{col['name']}.zip",
        )
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("export_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] Step 2: Create `web/api/routes/requests.py`:

```python
from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from web.api.services.request_service import RequestService
from web.api.services.runner_service import RunnerService

logger = logging.getLogger("qaclan.routes.requests")
bp = Blueprint("api_requests_bp", __name__)
_svc = RequestService()
_runner_svc = RunnerService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/api-requests", methods=["GET"])
def list_requests():
    try:
        collection_id = request.args.get("collection_id")
        return jsonify({"ok": True, "requests": _svc.list(_project_id(), collection_id=collection_id)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_requests")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests", methods=["POST"])
def create_request():
    try:
        data = request.get_json(force=True)
        req = _svc.create(_project_id(), data)
        return jsonify({"ok": True, "request": req}), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["GET"])
def get_request(req_id):
    try:
        return jsonify({"ok": True, "request": _svc.get(req_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["PUT"])
def update_request(req_id):
    try:
        data = request.get_json(force=True)
        req = _svc.update(req_id, _project_id(), data)
        return jsonify({"ok": True, "request": req})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>", methods=["DELETE"])
def delete_request(req_id):
    try:
        _svc.delete(req_id, _project_id())
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_request")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-requests/<req_id>/send", methods=["POST"])
def send_request(req_id):
    """Run a single request ad-hoc. Result is NOT stored in api_runs."""
    try:
        data = request.get_json(force=True) or {}
        env_name = data.get("env_name")
        result = _runner_svc.run_request(req_id, _project_id(), env_name=env_name)
        return jsonify({"ok": True, "result": result})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("send_request")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] Step 3: Commit — `git add web/api/routes/ && git commit -m "feat: add collection and request route blueprints"`

---

### Task 8: Discovery & API Runs Routes

**Files:**
- Create: `web/api/routes/discovery.py`
- Create: `web/api/routes/api_runs.py`

**Interfaces:**
- Consumes: Task 6 (DiscoveryService), Task 2 (ApiRunRepo)
- Produces: Flask blueprints registered in Task 9

- [ ] Step 1: Create `web/api/routes/discovery.py`:

```python
from __future__ import annotations
import json
import logging
import threading
import uuid
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from web.api.services.discovery_service import DiscoveryService

logger = logging.getLogger("qaclan.routes.discovery")
bp = Blueprint("api_discovery", __name__)
_svc = DiscoveryService()

# In-memory store for recording sessions: {session_id: {"status": "recording"|"stopped", "requests": [], "proc": proc}}
_recording_sessions: dict = {}
_sessions_lock = threading.Lock()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/discover/har", methods=["POST"])
def discover_har():
    """Multipart file upload. Field name: 'file'. Optional form field: collection_name."""
    try:
        pid = _project_id()
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        har_json = json.loads(f.read().decode("utf-8"))
        collection_name = request.form.get("collection_name") or f.filename.replace(".har", "")
        result = _svc.import_har(pid, har_json, collection_name=collection_name)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_har")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/openapi", methods=["POST"])
def discover_openapi():
    """JSON body {url: ...} OR multipart file upload (field: 'file')."""
    try:
        pid = _project_id()
        if request.files.get("file"):
            f = request.files["file"]
            raw = f.read().decode("utf-8")
            if f.filename.endswith(".yaml") or f.filename.endswith(".yml"):
                import yaml
                spec = yaml.safe_load(raw)
            else:
                spec = json.loads(raw)
            result = _svc.import_openapi(pid, spec)
        else:
            data = request.get_json(force=True) or {}
            url = data.get("url", "")
            if not url:
                return jsonify({"ok": False, "error": "Provide 'url' or upload a file"}), 400
            result = _svc.import_openapi(pid, url)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_openapi")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/postman", methods=["POST"])
def discover_postman():
    """Multipart file upload. Field name: 'file'."""
    try:
        pid = _project_id()
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file uploaded (field: 'file')"}), 400
        f = request.files["file"]
        collection_json = json.loads(f.read().decode("utf-8"))
        result = _svc.import_postman(pid, collection_json)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_postman")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/bruno", methods=["POST"])
def discover_bruno():
    """Multipart file upload of one or more .bru files. Field name: 'files'."""
    try:
        pid = _project_id()
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "No files uploaded (field: 'files')"}), 400
        bru_files = []
        for f in files:
            bru_files.append({"name": f.filename, "content": f.read().decode("utf-8")})
        result = _svc.import_bruno(pid, bru_files)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("discover_bruno")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/start", methods=["POST"])
def record_start():
    """Launch a Playwright browser in record mode, capture XHR traffic."""
    try:
        session_id = str(uuid.uuid4())
        data = request.get_json(force=True) or {}
        url = data.get("url", "about:blank")

        import tempfile, os
        capture_dir = tempfile.mkdtemp(prefix="qaclan_record_")
        har_file = os.path.join(capture_dir, "capture.har")

        from web.api.services.discovery_service import DiscoveryService
        proc = DiscoveryService().launch_recorder(url, har_file)

        with _sessions_lock:
            _recording_sessions[session_id] = {
                "status": "recording",
                "proc": proc,
                "capture_dir": capture_dir,
                "har_file": har_file,
            }

        logger.info("record_start: session %s launched (pid %d)", session_id, proc.pid)
        return jsonify({"ok": True, "session_id": session_id})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_start")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/stop", methods=["POST"])
def record_stop():
    """Stop recording session, parse captured HAR, return request list."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id", "")
        with _sessions_lock:
            session = _recording_sessions.pop(session_id, None)

        if not session:
            return jsonify({"ok": False, "error": f"Session {session_id} not found"}), 404

        proc = session.get("proc")
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        import time
        time.sleep(1)  # Give Playwright time to flush HAR

        har_file = session.get("har_file", "")
        requests_list = []
        if har_file and __import__("os").path.exists(har_file):
            with open(har_file) as hf:
                har_json = json.load(hf)
            from cli.api_discovery.har_parser import parse_har
            requests_list = parse_har(har_json)

        return jsonify({"ok": True, "requests": requests_list, "count": len(requests_list)})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_stop")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/record/status", methods=["GET"])
def record_status():
    """Poll recording session status and current capture count."""
    session_id = request.args.get("session_id", "")
    with _sessions_lock:
        session = _recording_sessions.get(session_id)
    if not session:
        return jsonify({"ok": False, "error": "Session not found"}), 404
    proc = session.get("proc")
    alive = proc is not None and proc.poll() is None
    return jsonify({"ok": True, "status": "recording" if alive else "stopped", "session_id": session_id})
```

- [ ] Step 2: Create `web/api/routes/api_runs.py`:

```python
from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from web.api.repositories.api_run_repo import ApiRunRepo

logger = logging.getLogger("qaclan.routes.api_runs")
bp = Blueprint("api_runs_bp", __name__)
_repo = ApiRunRepo()


@bp.route("/api/api-runs", methods=["GET"])
def list_api_runs():
    try:
        suite_run_id = request.args.get("suite_run_id", "")
        if not suite_run_id:
            return jsonify({"ok": False, "error": "suite_run_id query param required"}), 400
        rows = _repo.list_by_suite_run(suite_run_id)
        return jsonify({"ok": True, "api_runs": rows})
    except Exception as e:
        logger.exception("list_api_runs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-runs/<run_id>", methods=["GET"])
def get_api_run(run_id):
    try:
        row = _repo.get(run_id)
        if row is None:
            return jsonify({"ok": False, "error": f"API run {run_id} not found"}), 404
        return jsonify({"ok": True, "api_run": row})
    except Exception as e:
        logger.exception("get_api_run")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] Step 3: Commit — `git add web/api/routes/discovery.py web/api/routes/api_runs.py && git commit -m "feat: add discovery and api-runs route blueprints"`

---

### Task 9: Blueprint Registration & Requirements

**Files:**
- Modify: `web/server.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: Task 7, Task 8 (blueprints)
- Produces: all new routes live under Flask app

- [ ] Step 1: In `web/server.py`, add imports after the existing blueprint imports:

```python
# EXISTING imports (already present — do not change):
from .routes.projects import bp as projects_bp
from .routes.features import bp as features_bp
from .routes.scripts import bp as scripts_bp
from .routes.suites import bp as suites_bp
from .routes.runs import bp as runs_bp
from .routes.envs import bp as envs_bp
from .routes.auth import bp as auth_bp
from .routes.sync import bp as sync_bp

# ADD these lines immediately after the existing imports:
from .api.routes.collections import bp as api_collections_bp
from .api.routes.requests import bp as api_requests_bp
from .api.routes.discovery import bp as api_discovery_bp
from .api.routes.api_runs import bp as api_runs_bp
```

- [ ] Step 2: In `web/server.py`, change the blueprint registration list from:

```python
    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp, sync_bp]:
        app.register_blueprint(bp)
```

to:

```python
    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp, sync_bp,
               api_collections_bp, api_requests_bp, api_discovery_bp, api_runs_bp]:
        app.register_blueprint(bp)
```

- [ ] Step 3: In `requirements.txt`, add two lines at the end:

```
httpx>=0.27.0
jsonpath-ng>=1.6.0
```

- [ ] Step 4: Install the new dependencies:

```bash
pip install httpx>=0.27.0 jsonpath-ng>=1.6.0
```

- [ ] Step 5: Verify the server starts without import errors:

```bash
python qaclan.py serve --port 7823 &
sleep 2
curl -s http://localhost:7823/api/collections | python3 -m json.tool
# Expected: {"ok": false, "error": "No active project"} or {"ok": true, "collections": [...]}
# (No active project error is fine — it proves the route is registered)
kill %1
```

- [ ] Step 6: Commit — `git add web/server.py requirements.txt && git commit -m "feat: register API blueprints; add httpx and jsonpath-ng deps"`

---

(Tasks 10–17 continue in the next section of this plan.)

---

### Task 10: Suite Items Extension

**Files:**
- Modify: `web/routes/suites.py` (additive only — add two new endpoints + extend GET /api/suites/<id>)
- Modify: `web/routes/runs.py` (change items query + add api_request dispatch branch)

**Interfaces:**
- Consumes: Task 1 (suite_items with item_type), Task 3 (run_api_request)
- Produces: suite builder can add API request items; execute_run dispatches by item_type

- [ ] Step 1: Add two new endpoints to `web/routes/suites.py`. Add these after the existing `remove_script_from_suite` function (after line ~215). Do NOT modify any existing function:

```python
@bp.route('/api/suites/<suite_id>/items', methods=['POST'])
def add_suite_item(suite_id):
    """Add a script or api_request item to a suite."""
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        item_type = data.get("item_type", "script")
        script_id = data.get("script_id")
        api_request_id = data.get("api_request_id")

        if item_type not in ("script", "api_request"):
            return jsonify({"ok": False, "error": "item_type must be 'script' or 'api_request'"}), 400
        if item_type == "script" and not script_id:
            return jsonify({"ok": False, "error": "script_id required for item_type='script'"}), 400
        if item_type == "api_request" and not api_request_id:
            return jsonify({"ok": False, "error": "api_request_id required for item_type='api_request'"}), 400

        conn = get_conn()

        # Verify suite belongs to project
        suite = conn.execute(
            "SELECT id FROM suites WHERE id = ? AND project_id = ?", (suite_id, project_id)
        ).fetchone()
        if not suite:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        # Verify referenced entity exists
        if item_type == "script":
            ref = conn.execute(
                "SELECT id FROM scripts WHERE id = ? AND project_id = ?", (script_id, project_id)
            ).fetchone()
            if not ref:
                return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404
        else:
            ref = conn.execute(
                "SELECT id FROM api_requests WHERE id = ? AND project_id = ?", (api_request_id, project_id)
            ).fetchone()
            if not ref:
                return jsonify({"ok": False, "error": f"API request {api_request_id} not found"}), 404

        # Calculate next order_index
        max_order = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) FROM suite_items WHERE suite_id = ?", (suite_id,)
        ).fetchone()[0]
        order_index = max_order + 1

        item_id = generate_id("si")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_items (id, suite_id, script_id, api_request_id, item_type, order_index, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, suite_id, script_id, api_request_id, item_type, order_index, now),
        )
        conn.commit()

        return jsonify({"ok": True, "item_id": item_id, "order_index": order_index}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/suites/<suite_id>/items/<item_id>', methods=['DELETE'])
def remove_suite_item(suite_id, item_id):
    """Remove any suite item (script or api_request) by suite_items.id."""
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        suite = conn.execute(
            "SELECT id FROM suites WHERE id = ? AND project_id = ?", (suite_id, project_id)
        ).fetchone()
        if not suite:
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404

        cur = conn.execute(
            "DELETE FROM suite_items WHERE id = ? AND suite_id = ?", (item_id, suite_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"ok": False, "error": f"Item {item_id} not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] Step 2: Extend the existing `get_suite` endpoint in `web/routes/suites.py` to also return `api_request` items. The existing query is:

```python
        # Load ordered scripts
        items = conn.execute(
            "SELECT si.script_id, s.name, s.language, si.order_index "
            "FROM suite_items si JOIN scripts s ON si.script_id = s.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        suite["scripts"] = [dict(i) for i in items]
```

Replace that block with:

```python
        # Load all ordered items (scripts and api_requests)
        items = conn.execute(
            "SELECT si.id AS item_id, si.item_type, si.order_index, "
            "si.script_id, s.name AS script_name, s.language, "
            "si.api_request_id, ar.name AS api_request_name, ar.method, ar.url "
            "FROM suite_items si "
            "LEFT JOIN scripts s ON si.script_id = s.id "
            "LEFT JOIN api_requests ar ON si.api_request_id = ar.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        all_items = [dict(i) for i in items]
        # Backward-compatible: keep 'scripts' key for existing UI
        suite["scripts"] = [
            {"script_id": i["script_id"], "name": i["script_name"],
             "language": i["language"], "order_index": i["order_index"]}
            for i in all_items if i["item_type"] == "script"
        ]
        # New: all items with type info for the extended suite builder
        suite["items"] = all_items
```

- [ ] Step 3: Modify `web/routes/runs.py` — change the items query in `execute_run()`. Find this block (around line 273):

```python
        items = conn.execute(
            "SELECT si.order_index, sc.id AS script_id, sc.name AS script_name, sc.file_path, "
            "sc.language, sc.start_url_key, sc.start_url_value, sc.var_keys, sc.wait_timeout "
            "FROM suite_items si JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            logger.warning("execute_run: suite %s has no items", suite_id)
            return jsonify({"ok": False, "error": "Suite has no items"}), 400
```

Replace with:

```python
        items = conn.execute(
            "SELECT si.id AS item_id, si.order_index, si.item_type, "
            "si.script_id, si.api_request_id, "
            "sc.name AS script_name, sc.file_path, sc.language, sc.start_url_key, "
            "sc.start_url_value, sc.var_keys, sc.wait_timeout "
            "FROM suite_items si "
            "LEFT JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            logger.warning("execute_run: suite %s has no items", suite_id)
            return jsonify({"ok": False, "error": "Suite has no items"}), 400
```

- [ ] Step 4: In `web/routes/runs.py`, in the `execute_run()` loop, the existing loop currently starts with `for idx, item in enumerate(items):` and only handles script items. Add an `if item["item_type"] == "api_request":` branch at the TOP of the loop body, before the existing script logic. Find the line `for idx, item in enumerate(items):` and the `if stopped:` block that follows it. After the `if stopped: ... continue` block, add:

```python
            # --- API request item branch ---
            if item["item_type"] == "api_request":
                api_req_id = item["api_request_id"]
                api_run_now = datetime.now(timezone.utc).isoformat()
                api_start = time.time()

                try:
                    from cli.api_runner import run_api_request
                    from web.api.repositories.api_run_repo import ApiRunRepo

                    # Load the api_request row
                    api_req_row = conn.execute(
                        "SELECT * FROM api_requests WHERE id = ?", (api_req_id,)
                    ).fetchone()
                    if not api_req_row:
                        raise LookupError(f"api_request {api_req_id} not found")

                    import json as _json
                    api_req = dict(api_req_row)
                    for _key in ("headers", "params", "assertions"):
                        if isinstance(api_req.get(_key), str):
                            try:
                                api_req[_key] = _json.loads(api_req[_key])
                            except (ValueError, TypeError):
                                api_req[_key] = []
                    if isinstance(api_req.get("auth_config"), str):
                        try:
                            api_req["auth_config"] = _json.loads(api_req["auth_config"])
                        except (ValueError, TypeError):
                            api_req["auth_config"] = {}

                    # Load state.json and extract qaclan_vars
                    state_dict: dict = {}
                    if state_file.exists():
                        try:
                            state_dict = _json.loads(state_file.read_text(encoding="utf-8"))
                        except (ValueError, OSError):
                            state_dict = {}

                    api_result = run_api_request(
                        api_req, env_vars_dict, state_dict, state_path=str(state_file)
                    )

                    # Merge state_updates back into state.json qaclan_vars
                    state_updates = api_result.get("state_updates", {})
                    if state_updates:
                        state_dict.setdefault("qaclan_vars", {}).update(state_updates)
                        try:
                            state_file.write_text(_json.dumps(state_dict), encoding="utf-8")
                        except OSError as _ose:
                            logger.warning("execute_run: could not write state.json: %s", _ose)

                    # Persist api_run row
                    ApiRunRepo().create(run_id, api_req_id, item["order_index"], api_result)

                    api_duration_ms = int((time.time() - api_start) * 1000)
                    api_status = api_result.get("status", "ERROR")
                    if api_status == "PASSED":
                        passed += 1
                    else:
                        failed += 1
                        if stop_on_fail:
                            stopped = True

                    script_results.append({
                        "item_type": "api_request",
                        "api_request_id": api_req_id,
                        "name": api_req.get("name", api_req_id),
                        "status": api_status,
                        "duration_ms": api_duration_ms,
                        "status_code": api_result.get("status_code"),
                        "error_message": api_result.get("error_message"),
                        "assertion_results": api_result.get("assertion_results", []),
                    })
                    logger.info("execute_run: [%d/%d] API '%s' — %s (%dms)",
                                idx + 1, total, api_req.get("name"), api_status, api_duration_ms)

                except Exception as _api_exc:
                    failed += 1
                    if stop_on_fail:
                        stopped = True
                    err_msg = str(_api_exc)
                    logger.error("execute_run: [%d/%d] API item error: %s", idx + 1, total, err_msg)
                    script_results.append({
                        "item_type": "api_request",
                        "api_request_id": api_req_id,
                        "name": api_req_id,
                        "status": "ERROR",
                        "duration_ms": int((time.time() - api_start) * 1000),
                        "error_message": err_msg,
                    })
                continue  # skip rest of script-item logic
            # --- End API request item branch ---
```

- [ ] Step 5: For script items in the loop, inject `qaclan_vars` as `QACLAN_STATE_*` env vars. In the script branch, after the line `child_env["QACLAN_EXPECT_TIMEOUT"] = str(effective_wait_timeout)`, add:

```python
                # Inject qaclan_vars from state.json so scripts can read them as QACLAN_STATE_* env vars
                if state_file.exists():
                    try:
                        import json as _sjson
                        _state = _sjson.loads(state_file.read_text(encoding="utf-8"))
                        for _vk, _vv in _state.get("qaclan_vars", {}).items():
                            child_env[f"QACLAN_STATE_{_vk}"] = str(_vv)
                    except (ValueError, OSError):
                        pass
```

- [ ] Step 6: Commit:

```bash
git add web/routes/suites.py web/routes/runs.py
git commit -m "feat: extend suite_items for api_request type; dispatch by item_type in execute_run"
```

---

### Task 11: CLI Commands

**Files:**
- Create: `cli/commands/api_cmd.py`
- Modify: `qaclan.py` (add `api_group` registration — 2 lines)

**Interfaces:**
- Consumes: Task 6 (CollectionService), Task 7 (RequestService), Task 8 (RunnerService), Task 9 (DiscoveryService), Task 5 (bruno_parser for export)
- Produces: `qaclan api` command group

- [ ] Step 1: Create `cli/commands/api_cmd.py`:

```python
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cli.db import init_db
from cli.config import get_active_project_id

logger = logging.getLogger("qaclan.api_cmd")
console = Console()


def _require_project():
    init_db()
    pid = get_active_project_id()
    if not pid:
        console.print("[red]No active project. Run: qaclan project use <name>[/red]")
        sys.exit(1)
    return pid


def _print_request_result(r: dict):
    color = "green" if r["status"] == "PASSED" else "red"
    console.print(f"[{color}]{r['status']}[/{color}] {r.get('method','')} {r.get('url','')} → {r.get('status_code','')} ({r.get('duration_ms',0)}ms)")
    for a in r.get("assertions", []):
        mark = "✓" if a["passed"] else "✗"
        console.print(f"  {mark} {a['name']}: {a.get('message','')}")


def _print_collection_result(r: dict):
    color = "green" if r["status"] == "PASSED" else "red"
    console.print(f"[{color}]{r['status']}[/{color}] {r['passed']}/{r['total']} passed")
    for item in r.get("results", []):
        _print_request_result(item)


@click.group("api")
def api_group():
    """API testing commands."""
    pass


@api_group.command("list")
@click.option("--collection", "-c", help="Show requests inside this collection")
def api_list(collection):
    """List API collections or requests in the active project."""
    pid = _require_project()
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService

    if collection:
        cols = CollectionService().list(pid)
        col = next((c for c in cols if c["name"] == collection), None)
        if col is None:
            console.print(f"[red]Collection '{collection}' not found[/red]")
            sys.exit(1)
        reqs = RequestService().list(pid, collection_id=col["id"])
        if not reqs:
            console.print("[yellow]No requests found in this collection.[/yellow]")
            return
        table = Table(title=f"Requests in '{collection}'", show_header=True, header_style="bold cyan")
        table.add_column("Name", style="bold")
        table.add_column("Method", width=8)
        table.add_column("URL", max_width=60)
        table.add_column("ID", style="dim")
        for r in reqs:
            method_style = {
                "GET": "green", "POST": "blue", "PUT": "yellow",
                "PATCH": "yellow", "DELETE": "red",
            }.get(r["method"], "white")
            table.add_row(
                r["name"],
                f"[{method_style}]{r['method']}[/{method_style}]",
                r["url"],
                r["id"],
            )
        console.print(table)
    else:
        cols = CollectionService().list(pid)
        if not cols:
            console.print("[yellow]No collections found.[/yellow]")
            return
        table = Table(title="Collections", show_header=True, header_style="bold cyan")
        table.add_column("Name", style="bold")
        table.add_column("Requests", justify="right")
        table.add_column("ID", style="dim")
        for c in cols:
            table.add_row(c["name"], str(c.get("request_count", 0)), c["id"])
        console.print(table)


@api_group.command("run")
@click.argument("name_or_id")
@click.option("--collection", "-c", help="Collection name (required when running full collection)")
@click.option("--env", "-e", help="Environment name")
def api_run(name_or_id, collection, env):
    """Run a single API request or all requests in a collection."""
    pid = _require_project()
    from web.api.services.runner_service import RunnerService
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService
    svc = RunnerService()

    if collection:
        # run whole collection
        cols = CollectionService().list(pid)
        col = next((c for c in cols if c["name"] == collection or c["id"] == collection), None)
        if col is None:
            console.print(f"[red]Collection '{collection}' not found[/red]")
            sys.exit(1)
        console.print(f"[cyan]Running collection '{collection}'...[/cyan]\n")
        result = svc.run_collection(col["id"], pid, env_name=env)
        _print_collection_result(result)
    else:
        # run single request by id or name
        reqs = RequestService().list(pid)
        req = next((r for r in reqs if r["id"] == name_or_id or r["name"] == name_or_id), None)
        if req is None:
            console.print(f"[red]Request '{name_or_id}' not found[/red]")
            sys.exit(1)
        console.print(f"[cyan]Running '{req['name']}' ({req['method']} {req['url']})...[/cyan]")
        result = svc.run_request(req["id"], pid, env_name=env)
        _print_request_result(result)
        if result.get("response_body"):
            console.print("\n[bold]Response Body:[/bold]")
            try:
                parsed = json.loads(result["response_body"])
                console.print_json(json.dumps(parsed, indent=2))
            except (ValueError, TypeError):
                console.print(result["response_body"][:1000])


@api_group.command("export")
@click.argument("collection")
@click.option("--output", "-o", default=".", help="Output directory for .bru files")
def api_export(collection, output):
    """Export a collection as Bruno .bru files."""
    pid = _require_project()
    from web.api.services.collection_service import CollectionService
    from web.api.services.request_service import RequestService
    from cli.api_discovery.bruno_parser import request_to_bru

    cols = CollectionService().list(pid)
    col = next((c for c in cols if c["name"] == collection or c["id"] == collection), None)
    if col is None:
        console.print(f"[red]Collection '{collection}' not found[/red]")
        sys.exit(1)

    reqs = RequestService().list(pid, collection_id=col["id"])
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for req in reqs:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in req["name"])
        (out_dir / f"{safe_name}.bru").write_text(request_to_bru(req), encoding="utf-8")
    console.print(f"[green]Exported {len(reqs)} requests to {out_dir}[/green]")


@api_group.command("import")
@click.argument("file_or_url")
@click.option("--format", "fmt", default="auto",
              type=click.Choice(["auto", "har", "openapi", "postman", "bruno"]),
              help="Import format (default: auto-detect)")
@click.option("--collection", default=None, help="Collection name (for HAR import)")
def api_import(file_or_url, fmt, collection):
    """Import API requests from HAR, OpenAPI, Postman, or Bruno files."""
    pid = _require_project()

    # Auto-detect format
    if fmt == "auto":
        lower = file_or_url.lower()
        if lower.startswith("http"):
            fmt = "openapi"
        elif lower.endswith(".har"):
            fmt = "har"
        elif lower.endswith(".yaml") or lower.endswith(".yml") or "openapi" in lower or "swagger" in lower:
            fmt = "openapi"
        elif lower.endswith(".bru"):
            fmt = "bruno"
        else:
            # Try to detect from file content
            try:
                content = Path(file_or_url).read_text(encoding="utf-8")
                data = json.loads(content)
                if "log" in data and "entries" in data.get("log", {}):
                    fmt = "har"
                elif "info" in data and "item" in data:
                    fmt = "postman"
                elif "openapi" in data or "swagger" in data:
                    fmt = "openapi"
                else:
                    fmt = "har"
            except (ValueError, OSError):
                fmt = "openapi"

    from web.api.services.discovery_service import DiscoveryService
    svc = DiscoveryService()

    if fmt == "har":
        content = Path(file_or_url).read_text(encoding="utf-8")
        har_json = json.loads(content)
        col_name = collection or Path(file_or_url).stem
        result = svc.import_har(pid, har_json, collection_name=col_name)
        console.print(f"[green]Imported {result['imported']} requests[/green]")

    elif fmt == "openapi":
        if file_or_url.startswith("http"):
            result = svc.import_openapi(pid, file_or_url)
        else:
            content = Path(file_or_url).read_text(encoding="utf-8")
            if file_or_url.endswith((".yaml", ".yml")):
                import yaml
                spec = yaml.safe_load(content)
            else:
                spec = json.loads(content)
            result = svc.import_openapi(pid, spec)
        console.print(f"[green]Imported {result['imported']} requests across {len(result.get('collections', []))} collections[/green]")

    elif fmt == "postman":
        content = Path(file_or_url).read_text(encoding="utf-8")
        col_json = json.loads(content)
        result = svc.import_postman(pid, col_json)
        console.print(f"[green]Imported {result['imported']} requests[/green]")

    elif fmt == "bruno":
        content = Path(file_or_url).read_text(encoding="utf-8")
        result = svc.import_bruno(pid, [{"name": Path(file_or_url).name, "content": content}])
        console.print(f"[green]Imported {result['imported']} requests[/green]")


@api_group.command("record")
@click.option("--url", default="about:blank", help="Starting URL for recording browser")
def api_record(url):
    """Launch a browser, capture API requests, then prompt to save them."""
    pid = _require_project()
    console.print(f"[cyan]Opening browser at {url}...[/cyan]")
    console.print("[yellow]Interact with the app, then close the browser window to stop recording.[/yellow]")

    import os, time
    from cli.api_discovery.har_parser import parse_har

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        har_file = os.path.join(tmpdir, "captured.har")

        from web.api.services.discovery_service import DiscoveryService
        DiscoveryService().record_sync(url, har_file)

        if not os.path.exists(har_file):
            console.print("[red]No HAR file captured.[/red]")
            return

        with open(har_file) as f:
            har_json = json.load(f)

        requests = parse_har(har_json)
        if not requests:
            console.print("[yellow]No API requests captured.[/yellow]")
            return

        console.print(f"\n[green]Captured {len(requests)} requests.[/green]")
        for i, r in enumerate(requests[:20]):
            console.print(f"  {i+1}. {r['method']} {r['url'][:80]}")
        if len(requests) > 20:
            console.print(f"  ... and {len(requests) - 20} more")

        col_name = click.prompt("\nCollection name to save as", default="Recorded APIs")
        save = click.confirm(f"Save {len(requests)} requests to collection '{col_name}'?", default=True)
        if save:
            from web.api.services.discovery_service import DiscoveryService
            result = DiscoveryService().import_har(pid, har_json, collection_name=col_name)
            console.print(f"[green]Saved {result['imported']} requests.[/green]")
```

- [ ] Step 2: Add `api_group` to `qaclan.py`. Open `qaclan.py` and find the section where other command groups are added (e.g., lines like `cli.add_command(project_group)`). Add:

```python
from cli.commands.api_cmd import api_group
# ... (existing add_command calls) ...
cli.add_command(api_group)
```

Show the exact two lines to add — the import at the top with the other imports, and the `cli.add_command(api_group)` call at the bottom with the other `add_command` calls.

- [ ] Step 3: Test:

```bash
python qaclan.py api --help
python qaclan.py api list
```

- [ ] Step 4: Commit — `git add cli/commands/api_cmd.py qaclan.py && git commit -m "feat: add qaclan api CLI command group (list, run, export, import, record)"`

---

### Task 12: UI Shared Components

**Files:**
- Create: `web/static/api/components/key-value-table.js`
- Create: `web/static/api/components/assertion-builder.js`
- Create: `web/static/api/components/response-panel.js`

**Interfaces:**
- Consumes: nothing (pure DOM components)
- Produces: reusable components used by Task 14 request editor

- [ ] Step 1: Create `web/static/api/components/key-value-table.js`:

```js
/**
 * createKeyValueTable(options) → { el, getRows, setRows }
 * options: { placeholder?: { key, value }, readOnly?: bool }
 * getRows() → [{key, value, enabled}]
 * setRows(rows)
 */
export function createKeyValueTable(options = {}) {
  const { placeholder = { key: 'Key', value: 'Value' }, readOnly = false } = options;

  const wrapper = document.createElement('div');
  wrapper.className = 'kv-table-wrapper';

  const table = document.createElement('table');
  table.className = 'kv-table';
  table.innerHTML = `<thead><tr>
    <th style="width:32px"></th>
    <th>Key</th>
    <th>Value</th>
    ${readOnly ? '' : '<th style="width:32px"></th>'}
  </tr></thead>`;
  const tbody = document.createElement('tbody');
  table.appendChild(tbody);
  wrapper.appendChild(table);

  if (!readOnly) {
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-xs btn-ghost';
    addBtn.style.marginTop = '6px';
    addBtn.textContent = '+ Add Row';
    addBtn.onclick = () => _addRow({}, true);
    wrapper.appendChild(addBtn);
  }

  function _addRow(data = {}, enabled = true) {
    const tr = document.createElement('tr');
    tr.className = 'kv-row';

    const enabledTd = document.createElement('td');
    if (!readOnly) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = data.enabled !== false;
      cb.className = 'kv-enabled';
      enabledTd.appendChild(cb);
    }
    tr.appendChild(enabledTd);

    const keyTd = document.createElement('td');
    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.className = 'kv-key input-sm';
    keyInput.placeholder = placeholder.key;
    keyInput.value = data.key || '';
    keyInput.readOnly = readOnly;
    keyTd.appendChild(keyInput);
    tr.appendChild(keyTd);

    const valTd = document.createElement('td');
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'kv-value input-sm';
    valInput.placeholder = placeholder.value;
    valInput.value = data.value || '';
    valInput.readOnly = readOnly;
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      const delTd = document.createElement('td');
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
      delBtn.textContent = '×';
      delBtn.onclick = () => tr.remove();
      delTd.appendChild(delBtn);
      tr.appendChild(delTd);
    }

    tbody.appendChild(tr);
    return tr;
  }

  function getRows() {
    const rows = [];
    tbody.querySelectorAll('tr.kv-row').forEach(tr => {
      const key = tr.querySelector('.kv-key')?.value?.trim() || '';
      const value = tr.querySelector('.kv-value')?.value || '';
      const enabledCb = tr.querySelector('.kv-enabled');
      const enabled = enabledCb ? enabledCb.checked : true;
      if (key) rows.push({ key, value, enabled });
    });
    return rows;
  }

  function setRows(rows = []) {
    tbody.innerHTML = '';
    rows.forEach(r => _addRow(r));
  }

  return { el: wrapper, getRows, setRows };
}
```

- [ ] Step 2: Create `web/static/api/components/assertion-builder.js`:

```js
/**
 * createAssertionBuilder() → { el, getAssertions, setAssertions }
 * Assertion shape: {type, path?, key?, op, value}
 */
export function createAssertionBuilder() {
  const wrapper = document.createElement('div');
  wrapper.className = 'assertion-builder';

  const list = document.createElement('div');
  list.className = 'assertion-list';
  wrapper.appendChild(list);

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'btn btn-xs btn-ghost';
  addBtn.style.marginTop = '6px';
  addBtn.textContent = '+ Add Assertion';
  addBtn.onclick = () => _addRow({});
  wrapper.appendChild(addBtn);

  const TYPE_OPS = {
    status:        ['eq', 'ne', 'lt', 'gt'],
    json_path:     ['eq', 'ne', 'lt', 'gt', 'contains', 'exists', 'not_exists', 'matches'],
    header:        ['eq', 'ne', 'contains', 'exists', 'not_exists'],
    response_time: ['lt', 'gt', 'eq'],
    body_text:     ['contains', 'eq', 'matches'],
  };

  const OP_LABELS = {
    eq: '= equals', ne: '≠ not equals', lt: '< less than', gt: '> greater than',
    contains: '⊃ contains', exists: '∃ exists', not_exists: '∄ not exists', matches: '~ matches regex',
  };

  function _addRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'assertion-row';

    // Type select
    const typeSelect = document.createElement('select');
    typeSelect.className = 'assertion-type input-sm';
    ['status', 'json_path', 'header', 'response_time', 'body_text'].forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = data.type || 'status';
    row.appendChild(typeSelect);

    // Dynamic path/key field (shown for json_path and header)
    const extraInput = document.createElement('input');
    extraInput.type = 'text';
    extraInput.className = 'assertion-extra input-sm';
    extraInput.placeholder = '$.path or header-key';
    extraInput.value = data.path || data.key || '';
    row.appendChild(extraInput);

    // Operator select
    const opSelect = document.createElement('select');
    opSelect.className = 'assertion-op input-sm';
    row.appendChild(opSelect);

    // Value input
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'assertion-value input-sm';
    valInput.placeholder = 'expected value';
    valInput.value = data.value !== undefined ? String(data.value) : '';
    row.appendChild(valInput);

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
    delBtn.textContent = '×';
    delBtn.onclick = () => row.remove();
    row.appendChild(delBtn);

    function _updateUI() {
      const t = typeSelect.value;
      const ops = TYPE_OPS[t] || ['eq'];

      // Rebuild op options
      opSelect.innerHTML = '';
      ops.forEach(op => {
        const opt = document.createElement('option');
        opt.value = op;
        opt.textContent = OP_LABELS[op] || op;
        opSelect.appendChild(opt);
      });
      if (data.op && ops.includes(data.op)) opSelect.value = data.op;

      // Show/hide extra input
      const needsExtra = (t === 'json_path' || t === 'header');
      extraInput.style.display = needsExtra ? '' : 'none';
      extraInput.placeholder = t === 'json_path' ? '$.path' : 'Header-Name';

      // Show/hide value (exists/not_exists don't need it)
      const op = opSelect.value;
      valInput.style.display = (op === 'exists' || op === 'not_exists') ? 'none' : '';
    }

    typeSelect.onchange = _updateUI;
    opSelect.onchange = _updateUI;
    _updateUI();

    list.appendChild(row);
    return row;
  }

  function getAssertions() {
    const results = [];
    list.querySelectorAll('.assertion-row').forEach(row => {
      const type = row.querySelector('.assertion-type').value;
      const op = row.querySelector('.assertion-op').value;
      const value = row.querySelector('.assertion-value').value;
      const extra = row.querySelector('.assertion-extra').value.trim();
      const assertion = { type, op };
      if (op !== 'exists' && op !== 'not_exists') {
        const parsed = isNaN(value) ? value : Number(value);
        assertion.value = parsed;
      }
      if (type === 'json_path' && extra) assertion.path = extra;
      if (type === 'header' && extra) assertion.key = extra;
      results.push(assertion);
    });
    return results;
  }

  function setAssertions(assertions = []) {
    list.innerHTML = '';
    assertions.forEach(a => _addRow(a));
  }

  return { el: wrapper, getAssertions, setAssertions };
}
```

- [ ] Step 3: Create `web/static/api/components/response-panel.js`:

```js
/**
 * createResponsePanel() → { el, show(result) }
 * result: {status_code, duration_ms, response_body, response_headers, assertion_results}
 */
export function createResponsePanel() {
  const panel = document.createElement('div');
  panel.className = 'response-panel';
  panel.style.display = 'none';

  const tabBar = document.createElement('div');
  tabBar.className = 'response-tabs';
  panel.appendChild(tabBar);

  const contentArea = document.createElement('div');
  contentArea.className = 'response-content';
  panel.appendChild(contentArea);

  let _currentResult = null;

  function _renderTab(label, key, active) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'response-tab' + (active ? ' active' : '');
    tab.textContent = label;
    tab.onclick = () => {
      tabBar.querySelectorAll('.response-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _renderContent(key);
    };
    return tab;
  }

  function _esc(s) {
    return String(s || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function _renderContent(tab) {
    if (!_currentResult) return;
    const r = _currentResult;
    contentArea.innerHTML = '';

    if (tab === 'body') {
      const pre = document.createElement('pre');
      pre.className = 'response-body-pre';
      let text = r.response_body || '';
      try {
        text = JSON.stringify(JSON.parse(text), null, 2);
      } catch(e) { /* not JSON */ }
      pre.textContent = text;
      contentArea.appendChild(pre);

    } else if (tab === 'headers') {
      const headers = r.response_headers || {};
      const table = document.createElement('table');
      table.className = 'kv-table';
      table.innerHTML = '<thead><tr><th>Header</th><th>Value</th></tr></thead>';
      const tbody = document.createElement('tbody');
      Object.entries(headers).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      contentArea.appendChild(table);

    } else if (tab === 'assertions') {
      const results = r.assertion_results || [];
      if (!results.length) {
        contentArea.innerHTML = '<p class="text-muted text-sm">No assertions configured.</p>';
        return;
      }
      results.forEach(ar => {
        const row = document.createElement('div');
        row.className = 'assertion-result-row ' + (ar.passed ? 'assertion-pass' : 'assertion-fail');
        const icon = ar.passed ? '✓' : '✗';
        const detail = ar.path ? `${ar.path} ` : ar.key ? `${ar.key} ` : '';
        const actual = ar.actual !== undefined && ar.actual !== null ? ` (actual: ${_esc(String(ar.actual).slice(0,80))})` : '';
        row.innerHTML = `<span class="assertion-icon">${icon}</span>
          <span class="assertion-desc">${_esc(ar.type)} ${detail}${_esc(ar.op)} ${_esc(String(ar.value ?? ''))}</span>
          <span class="assertion-actual">${actual}</span>`;
        contentArea.appendChild(row);
      });
    }
  }

  function show(result) {
    _currentResult = result;
    panel.style.display = '';

    // Build status line
    const statusCode = result.status_code;
    const duration = result.duration_ms;
    const assertCount = (result.assertion_results || []).length;
    const assertPass = (result.assertion_results || []).filter(a => a.passed).length;
    const statusClass = statusCode >= 200 && statusCode < 300 ? 'response-status-ok'
                      : statusCode >= 400 ? 'response-status-err' : 'response-status-warn';

    tabBar.innerHTML = '';

    const statusSpan = document.createElement('span');
    statusSpan.className = `response-status ${statusClass}`;
    statusSpan.textContent = statusCode ? `${statusCode} · ${duration}ms` : `ERROR · ${duration}ms`;
    tabBar.appendChild(statusSpan);

    tabBar.appendChild(_renderTab('Body', 'body', true));
    tabBar.appendChild(_renderTab('Headers', 'headers', false));
    tabBar.appendChild(_renderTab(
      `Assertions (${assertPass}/${assertCount})`, 'assertions', false
    ));

    _renderContent('body');
  }

  return { el: panel, show };
}
```

- [ ] Step 4: Commit — `git add web/static/api/components/ && git commit -m "feat: add key-value-table, assertion-builder, response-panel UI components"`

---

### Task 13: API Section Entry Point & app.js Integration

**Files:**
- Create: `web/static/api/api-section.js`
- Modify: `web/static/app.js` (2 additive changes)
- Modify: `web/static/index.html` (1 line)
- Modify: `web/static/style.css` (new CSS section)

**Interfaces:**
- Consumes: Task 12 (components), Task 14 (views — forward reference, imported lazily)
- Produces: `window.__qaclanApi` global; API nav item in sidebar

- [ ] Step 1: Create `web/static/api/api-section.js`:

```js
/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container) }
 * Loaded as <script type="module"> so it does not block the classic app.js.
 */

// Lazy import views to keep initial load fast
async function _loadViews() {
  const [
    { renderCollectionsView },
    { renderRequestEditor },
    { showDiscoverModal },
  ] = await Promise.all([
    import('./views/collections-view.js'),
    import('./views/request-editor-view.js'),
    import('./views/discover-modal.js'),
  ]);
  return { renderCollectionsView, renderRequestEditor, showDiscoverModal };
}

let _views = null;
async function _getViews() {
  if (!_views) _views = await _loadViews();
  return _views;
}

function renderApiPage(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  layout.className = 'api-layout';

  // Sidebar
  const sidebar = document.createElement('div');
  sidebar.className = 'api-sidebar';
  sidebar.innerHTML = `
    <div class="api-sidebar-header">
      <span class="api-sidebar-title">API Testing</span>
      <button class="btn btn-xs btn-primary" id="api-discover-btn">+ Discover</button>
    </div>
    <div id="api-collections-panel"></div>`;
  layout.appendChild(sidebar);

  // Main content
  const main = document.createElement('div');
  main.className = 'api-main';
  main.id = 'api-main-content';
  main.innerHTML = '<div class="empty-state"><p>Select a request or collection to get started.</p></div>';
  layout.appendChild(main);

  container.appendChild(layout);

  // Load collections view into sidebar
  _getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal }) => {
    renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId) => {
        renderRequestEditor(document.getElementById('api-main-content'), requestId);
      }
    );

    document.getElementById('api-discover-btn').onclick = () => showDiscoverModal();
  }).catch(err => {
    console.error('API section load error:', err);
    main.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Failed to load API module: ${err.message}</p></div>`;
  });
}

// Register global API
window.__qaclanApi = { render: renderApiPage };
```

- [ ] Step 2: Modify `web/static/app.js` — **Addition 1**: add the `api` route to the `routes` object. Find the existing routes object:

```js
const routes = {
  features: renderFeaturesPage,
  scripts:  renderScriptsPage,
  suites:   renderSuitesPage,
  runs:     renderRunsPage,
  envs:     renderEnvsPage,
  settings: renderSettingsPage,
}
```

Change to (add the `api` entry):

```js
const routes = {
  features: renderFeaturesPage,
  scripts:  renderScriptsPage,
  suites:   renderSuitesPage,
  runs:     renderRunsPage,
  envs:     renderEnvsPage,
  settings: renderSettingsPage,
  api: () => {
    if (window.__qaclanApi) {
      window.__qaclanApi.render(document.getElementById('page-content'));
    } else {
      document.getElementById('page-content').innerHTML = '<div class="empty-state">Loading API module...</div>';
    }
  },
}
```

- [ ] Step 3: Modify `web/static/app.js` — **Addition 2**: add the API nav item in `renderSidebar()`. Find the existing nav HTML inside `renderSidebar()`:

```js
      <div class="nav-item sub ${p==='runs'?'active':''}" onclick="navigate('runs')">
        ${iconRun()} Runs
      </div>
    </div>
    <div class="nav-section nav-section-bottom">
```

Change to:

```js
      <div class="nav-item sub ${p==='runs'?'active':''}" onclick="navigate('runs')">
        ${iconRun()} Runs
      </div>
    </div>
    <div class="nav-section">
      <div class="nav-label">API Testing</div>
      <div class="nav-item sub ${p==='api'?'active':''}" onclick="navigate('api')">
        ${iconDiscover()} API
      </div>
    </div>
    <div class="nav-section nav-section-bottom">
```

- [ ] Step 4: Modify `web/static/index.html` — add before the closing `</body>` tag:

```html
<script type="module" src="api/api-section.js"></script>
```

- [ ] Step 5: Add to `web/static/style.css` (append at end of file):

```css
/* ── API Testing Section ──────────────────────────────────────── */
.api-layout {
  display: flex;
  height: 100%;
  overflow: hidden;
}
.api-sidebar {
  width: 280px;
  min-width: 220px;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 12px 0;
  flex-shrink: 0;
}
.api-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 8px;
}
.api-sidebar-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}
.api-main {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
.request-editor {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.request-editor-url-bar {
  display: flex;
  gap: 8px;
  align-items: center;
}
.method-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
}
.method-GET    { background: #d1fae5; color: #065f46; }
.method-POST   { background: #dbeafe; color: #1e40af; }
.method-PUT    { background: #fef3c7; color: #92400e; }
.method-PATCH  { background: #fef3c7; color: #92400e; }
.method-DELETE { background: #fee2e2; color: #991b1b; }
.response-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-top: 8px;
}
.response-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  background: var(--surface-2, var(--bg-secondary));
  border-bottom: 1px solid var(--border);
}
.response-tab {
  background: none;
  border: none;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
.response-tab.active {
  background: var(--primary-light, #dbeafe);
  color: var(--primary, #2563eb);
  font-weight: 600;
}
.response-status {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  margin-right: 8px;
}
.response-status-ok  { background: #d1fae5; color: #065f46; }
.response-status-err { background: #fee2e2; color: #991b1b; }
.response-status-warn { background: #fef3c7; color: #92400e; }
.response-content {
  padding: 12px;
  overflow: auto;
  max-height: 380px;
}
.response-body-pre {
  margin: 0;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.assertion-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.assertion-result-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
  font-size: 13px;
}
.assertion-pass { background: #f0fdf4; }
.assertion-fail { background: #fef2f2; }
.assertion-icon { font-weight: 700; }
.assertion-pass .assertion-icon { color: #16a34a; }
.assertion-fail .assertion-icon { color: #dc2626; }
.assertion-actual { color: var(--text-muted); font-size: 11px; margin-left: auto; }
.kv-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.kv-table th { text-align: left; padding: 4px 6px; color: var(--text-muted); font-weight: 500; }
.kv-table td { padding: 3px 6px; }
.kv-table .kv-key,
.kv-table .kv-value { width: 100%; }
.input-sm { padding: 4px 8px; font-size: 13px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-input, #fff); }
.input-sm:focus { outline: none; border-color: var(--primary, #2563eb); }
.api-collection-item {
  padding: 6px 14px;
  cursor: pointer;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 0;
}
.api-collection-item:hover { background: var(--bg-hover); }
.api-request-item {
  padding: 5px 14px 5px 28px;
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.api-request-item:hover { background: var(--bg-hover); }
.api-request-item.active { background: var(--primary-light, #dbeafe); }
.editor-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  padding: 10px 0 4px;
  cursor: pointer;
  user-select: none;
}
.discover-modal-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  padding: 8px 0;
}
.discover-option-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px 14px;
  cursor: pointer;
  text-align: center;
  transition: border-color .15s, background .15s;
}
.discover-option-card:hover {
  border-color: var(--primary, #2563eb);
  background: var(--primary-light, #dbeafe);
}
.discover-option-icon { font-size: 28px; margin-bottom: 8px; }
.discover-option-title { font-weight: 600; font-size: 13px; }
.discover-option-desc { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.record-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.record-status-badge.recording { background: #fee2e2; color: #dc2626; }
.record-status-badge.stopped   { background: #f0fdf4; color: #16a34a; }
```

- [ ] Step 6: Commit:

```bash
git add web/static/api/api-section.js web/static/app.js web/static/index.html web/static/style.css
git commit -m "feat: add API section entry point, sidebar nav item, and CSS"
```

---

### Task 14: Collections View & Request Editor

**Files:**
- Create: `web/static/api/views/collections-view.js`
- Create: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: Task 12 (key-value-table, assertion-builder, response-panel)
- Produces: collection sidebar + full request editor rendered by Task 13

- [ ] Step 1: Create `web/static/api/views/collections-view.js`:

```js
/**
 * renderCollectionsView(container, onSelectRequest)
 * container: DOM element to render into
 * onSelectRequest: (requestId) => void
 */
export function renderCollectionsView(container, onSelectRequest) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  async function reload() {
    const res = await window.api('GET', '/collections');
    const collections = res.collections || [];
    container.innerHTML = '';

    if (!collections.length) {
      container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">No collections yet.</div>';
      return;
    }

    collections.forEach(col => {
      const section = document.createElement('div');
      section.className = 'api-collection-section';

      // Collection header row
      const header = document.createElement('div');
      header.className = 'api-collection-item';

      const leftSide = document.createElement('span');
      leftSide.innerHTML = `<strong>${_esc(col.name)}</strong> <span class="text-muted text-sm">(${col.request_count})</span>`;
      header.appendChild(leftSide);

      const rightSide = document.createElement('span');
      rightSide.style.display = 'flex';
      rightSide.style.gap = '4px';

      const runBtn = document.createElement('button');
      runBtn.className = 'btn btn-xs btn-ghost';
      runBtn.textContent = '▶ Run';
      runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name); };
      rightSide.appendChild(runBtn);

      const expandBtn = document.createElement('button');
      expandBtn.className = 'btn btn-xs btn-ghost';
      expandBtn.textContent = '▾';
      rightSide.appendChild(expandBtn);
      header.appendChild(rightSide);

      section.appendChild(header);

      // Requests list (togglable)
      const reqList = document.createElement('div');
      reqList.className = 'api-requests-list';
      let expanded = true;

      function _toggleExpand() {
        expanded = !expanded;
        reqList.style.display = expanded ? '' : 'none';
        expandBtn.textContent = expanded ? '▾' : '▸';
      }
      header.onclick = (e) => {
        if (e.target === runBtn || e.target === expandBtn) return;
        _toggleExpand();
      };
      expandBtn.onclick = (e) => { e.stopPropagation(); _toggleExpand(); };

      // Load requests for this collection
      window.api('GET', `/api-requests?collection_id=${col.id}`).then(r => {
        const reqs = r.requests || [];
        reqs.forEach(req => {
          const item = document.createElement('div');
          item.className = 'api-request-item';
          item.dataset.requestId = req.id;
          const methodClass = `method-${req.method}`;
          item.innerHTML = `<span class="method-badge ${methodClass}">${_esc(req.method)}</span> <span>${_esc(req.name)}</span>`;
          item.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            onSelectRequest(req.id);
          };
          reqList.appendChild(item);
        });

        // "New request in collection" button
        const newReqBtn = document.createElement('div');
        newReqBtn.className = 'api-request-item';
        newReqBtn.innerHTML = `<span style="color:var(--text-muted)">+ New Request</span>`;
        newReqBtn.onclick = () => {
          container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
          newReqBtn.classList.add('active');
          onSelectRequest(null, col.id);
        };
        reqList.appendChild(newReqBtn);
      });

      section.appendChild(reqList);
      container.appendChild(section);
    });

    // "New collection" at bottom
    const newColBtn = document.createElement('div');
    newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
    newColBtn.textContent = '+ New Collection';
    newColBtn.onclick = _createCollection;
    container.appendChild(newColBtn);
  }

  async function _runCollection(colId, colName) {
    const confirmed = confirm(`Run all requests in '${colName}'?`);
    if (!confirmed) return;
    const res = await window.api('POST', `/collections/${colId}/run`, {});
    if (res.ok === false) {
      alert('Run failed: ' + res.error);
    } else {
      alert(`Collection run complete: ${res.passed}/${res.total} passed`);
    }
  }

  async function _createCollection() {
    const name = prompt('Collection name:');
    if (!name) return;
    const res = await window.api('POST', '/collections', { name: name.trim() });
    if (res.ok === false) { alert('Error: ' + res.error); return; }
    reload();
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  reload();
}
```

- [ ] Step 2: Create `web/static/api/views/request-editor-view.js`:

```js
import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';

/**
 * renderRequestEditor(container, requestId, defaultCollectionId)
 * requestId: string|null (null = new request)
 * defaultCollectionId: string|null (pre-select collection when creating new)
 */
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:20px">Loading...</div>';

  // Load existing request data if editing
  let existing = null;
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
  }

  const r = existing || {};

  // Build editor shell
  container.innerHTML = '';
  const editor = document.createElement('div');
  editor.className = 'request-editor';

  // ── Name row ──
  const nameRow = document.createElement('div');
  nameRow.className = 'request-editor-name-row';
  nameRow.style.cssText = 'display:flex;gap:8px;align-items:center';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'input-sm';
  nameInput.style.flex = '1';
  nameInput.placeholder = 'Request name';
  nameInput.value = r.name || '';
  nameRow.appendChild(nameInput);

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-sm btn-ghost';
  saveBtn.textContent = 'Save';
  nameRow.appendChild(saveBtn);
  editor.appendChild(nameRow);

  // ── URL bar ──
  const urlBar = document.createElement('div');
  urlBar.className = 'request-editor-url-bar';

  const methodSelect = document.createElement('select');
  methodSelect.className = 'input-sm';
  methodSelect.style.width = '90px';
  ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    methodSelect.appendChild(opt);
  });
  methodSelect.value = r.method || 'GET';
  urlBar.appendChild(methodSelect);

  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'input-sm';
  urlInput.style.flex = '1';
  urlInput.placeholder = 'https://api.example.com/endpoint';
  urlInput.value = r.url || '';
  urlBar.appendChild(urlInput);

  const sendBtn = document.createElement('button');
  sendBtn.className = 'btn btn-sm btn-primary';
  sendBtn.textContent = 'Send';
  urlBar.appendChild(sendBtn);
  editor.appendChild(urlBar);

  // ── Tabbed sections ──
  const sections = ['Params', 'Headers', 'Body', 'Auth', 'Pre-Script', 'Post-Script', 'Assertions'];
  const tabBar = document.createElement('div');
  tabBar.className = 'response-tabs';
  const sectionContent = document.createElement('div');
  sectionContent.style.cssText = 'border:1px solid var(--border);border-top:none;border-radius:0 0 6px 6px;padding:12px;';
  editor.appendChild(tabBar);
  editor.appendChild(sectionContent);

  // Create component instances
  const paramsTable = createKeyValueTable({ placeholder: { key: 'Parameter', value: 'Value' } });
  paramsTable.setRows(r.params || []);

  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' } });
  headersTable.setRows(r.headers || []);

  const assertionBuilder = createAssertionBuilder();
  assertionBuilder.setAssertions(r.assertions || []);

  // Body section
  const bodySection = document.createElement('div');
  const bodyTypeSelect = document.createElement('select');
  bodyTypeSelect.className = 'input-sm';
  bodyTypeSelect.style.marginBottom = '8px';
  ['none', 'raw', 'form', 'graphql'].forEach(bt => {
    const opt = document.createElement('option');
    opt.value = bt;
    opt.textContent = bt;
    bodyTypeSelect.appendChild(opt);
  });
  bodyTypeSelect.value = r.body_type || 'none';
  const bodyTextarea = document.createElement('textarea');
  bodyTextarea.className = 'input-sm';
  bodyTextarea.style.cssText = 'width:100%;min-height:120px;font-family:var(--font-mono,monospace);font-size:12px;';
  bodyTextarea.value = r.body || '';
  bodySection.appendChild(bodyTypeSelect);
  bodySection.appendChild(bodyTextarea);

  // Auth section
  const authSection = document.createElement('div');
  const authTypeSelect = document.createElement('select');
  authTypeSelect.className = 'input-sm';
  authTypeSelect.style.marginBottom = '8px';
  ['none', 'bearer', 'basic', 'api_key', 'oauth2'].forEach(at => {
    const opt = document.createElement('option');
    opt.value = at;
    opt.textContent = at;
    authTypeSelect.appendChild(opt);
  });
  authTypeSelect.value = r.auth_type || 'none';
  const authConfigArea = document.createElement('textarea');
  authConfigArea.className = 'input-sm';
  authConfigArea.style.cssText = 'width:100%;min-height:80px;font-family:var(--font-mono,monospace);font-size:12px;';
  authConfigArea.placeholder = '{"token": "{{API_TOKEN}}"}';
  authConfigArea.value = typeof r.auth_config === 'object'
    ? JSON.stringify(r.auth_config, null, 2)
    : r.auth_config || '{}';
  authSection.appendChild(authTypeSelect);
  authSection.appendChild(authConfigArea);

  // Script sections
  function makeScriptSection(lang, code) {
    const div = document.createElement('div');
    const langSelect = document.createElement('select');
    langSelect.className = 'input-sm';
    langSelect.style.marginBottom = '8px';
    ['js', 'python'].forEach(l => {
      const opt = document.createElement('option');
      opt.value = l;
      opt.textContent = l === 'js' ? 'JavaScript' : 'Python';
      langSelect.appendChild(opt);
    });
    langSelect.value = lang || 'js';
    const textarea = document.createElement('textarea');
    textarea.className = 'input-sm';
    textarea.style.cssText = 'width:100%;min-height:100px;font-family:var(--font-mono,monospace);font-size:12px;';
    textarea.placeholder = 'qc.set("token", response.json().access_token)';
    textarea.value = code || '';
    div.appendChild(langSelect);
    div.appendChild(textarea);
    div._getLang = () => langSelect.value;
    div._getCode = () => textarea.value;
    return div;
  }

  const preScriptSection = makeScriptSection(r.pre_lang, r.pre_script);
  const postScriptSection = makeScriptSection(r.post_lang, r.post_script);

  const sectionMap = {
    'Params': paramsTable.el,
    'Headers': headersTable.el,
    'Body': bodySection,
    'Auth': authSection,
    'Pre-Script': preScriptSection,
    'Post-Script': postScriptSection,
    'Assertions': assertionBuilder.el,
  };

  let activeSection = 'Params';

  sections.forEach(name => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'response-tab' + (name === activeSection ? ' active' : '');
    tab.textContent = name;
    tab.onclick = () => {
      tabBar.querySelectorAll('.response-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeSection = name;
      sectionContent.innerHTML = '';
      sectionContent.appendChild(sectionMap[name]);
    };
    tabBar.appendChild(tab);
  });
  sectionContent.appendChild(sectionMap[activeSection]);

  // ── Response panel ──
  const responsePanel = createResponsePanel();
  editor.appendChild(responsePanel.el);

  container.appendChild(editor);

  // ── Wire up Send ──
  sendBtn.onclick = async () => {
    // Auto-save first if new
    let rid = requestId;
    if (!rid) {
      const saved = await _save();
      if (!saved) return;
      rid = saved;
    }
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    try {
      const res = await window.api('POST', `/api-requests/${rid}/send`, {});
      if (res.ok === false) {
        alert('Send error: ' + res.error);
      } else {
        responsePanel.show(res.result);
      }
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  };

  // ── Wire up Save ──
  async function _save() {
    const payload = {
      name: nameInput.value.trim() || 'Unnamed Request',
      method: methodSelect.value,
      url: urlInput.value.trim(),
      params: paramsTable.getRows(),
      headers: headersTable.getRows(),
      body_type: bodyTypeSelect.value !== 'none' ? bodyTypeSelect.value : null,
      body: bodyTextarea.value || null,
      auth_type: authTypeSelect.value,
      auth_config: (() => { try { return JSON.parse(authConfigArea.value); } catch(e) { return {}; } })(),
      pre_lang: preScriptSection._getLang(),
      pre_script: preScriptSection._getCode() || null,
      post_lang: postScriptSection._getLang(),
      post_script: postScriptSection._getCode() || null,
      assertions: assertionBuilder.getAssertions(),
    };
    if (defaultCollectionId) payload.collection_id = defaultCollectionId;

    let res;
    if (requestId) {
      res = await window.api('PUT', `/api-requests/${requestId}`, payload);
    } else {
      res = await window.api('POST', '/api-requests', payload);
    }

    if (res.ok === false) {
      alert('Save failed: ' + res.error);
      return null;
    }
    return res.request?.id || requestId;
  }

  saveBtn.onclick = async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    try {
      const id = await _save();
      if (id) saveBtn.textContent = 'Saved ✓';
      else saveBtn.textContent = 'Save';
    } finally {
      saveBtn.disabled = false;
      setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
    }
  };
}
```

- [ ] Step 3: Commit — `git add web/static/api/views/ && git commit -m "feat: add collections-view and request-editor-view ES modules"`

---

### Task 15: Discover Modal & Import Views

**Files:**
- Create: `web/static/api/views/discover-modal.js`
- Create: `web/static/api/views/har-import-view.js`
- Create: `web/static/api/views/openapi-import-view.js`
- Create: `web/static/api/views/postman-import-view.js`
- Create: `web/static/api/views/record-apis-view.js`

**Interfaces:**
- Consumes: Task 8 (discovery backend routes)
- Produces: discover modal called by Task 13 "Discover" button

- [ ] Step 1: Create `web/static/api/views/discover-modal.js`:

```js
import { showHarImport } from './har-import-view.js';
import { showOpenApiImport } from './openapi-import-view.js';
import { showPostmanImport } from './postman-import-view.js';
import { showRecordApis } from './record-apis-view.js';

export function showDiscoverModal() {
  // Use the existing showModal from app.js (classic script, available as window.showModal)
  const options = [
    { icon: '⏺', title: 'Record APIs', desc: 'Live browser capture', action: showRecordApis },
    { icon: '📄', title: 'Import HAR', desc: 'Chrome DevTools HAR export', action: showHarImport },
    { icon: '📋', title: 'Import OpenAPI', desc: 'OpenAPI 3.x / Swagger 2.x', action: showOpenApiImport },
    { icon: '📮', title: 'Import Postman', desc: 'Postman Collection v2.1', action: showPostmanImport },
    { icon: '🟤', title: 'Import Bruno', desc: '.bru collection files', action: () => showBrunoImport() },
    { icon: '🎭', title: 'From Playwright Run', desc: 'Extract APIs from recorded runs', action: () => alert('Coming soon') },
  ];

  const grid = document.createElement('div');
  grid.className = 'discover-modal-grid';

  options.forEach(opt => {
    const card = document.createElement('div');
    card.className = 'discover-option-card';
    card.innerHTML = `
      <div class="discover-option-icon">${opt.icon}</div>
      <div class="discover-option-title">${opt.title}</div>
      <div class="discover-option-desc">${opt.desc}</div>`;
    card.onclick = () => {
      window.closeModal();
      opt.action();
    };
    grid.appendChild(card);
  });

  const container = document.createElement('div');
  container.appendChild(grid);

  window.showModal('Discover APIs', container.innerHTML, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
  ]);

  // Re-attach click handlers after modal renders
  requestAnimationFrame(() => {
    document.querySelectorAll('.discover-option-card').forEach((card, i) => {
      card.onclick = () => {
        window.closeModal();
        options[i].action();
      };
    });
  });
}

async function showBrunoImport() {
  const { showBrunoImportView } = await import('./postman-import-view.js');
  showBrunoImportView();
}
```

- [ ] Step 2: Create `web/static/api/views/har-import-view.js`:

```js
export function showHarImport() {
  const body = `
    <div id="har-drop-zone" style="border:2px dashed var(--border);border-radius:8px;padding:32px;text-align:center;cursor:pointer;margin-bottom:12px;">
      <p style="margin:0;color:var(--text-muted)">Drag & drop .har file here, or <strong>click to browse</strong></p>
      <input type="file" id="har-file-input" accept=".har,application/json" style="display:none">
    </div>
    <div id="har-preview" style="display:none">
      <p id="har-summary" style="font-size:13px;color:var(--text-muted)"></p>
      <div id="har-request-list" style="max-height:280px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;"></div>
    </div>`;

  window.showModal('Import HAR', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import Selected', cls: 'btn-primary', action: _doImport },
  ]);

  let _parsedRequests = [];

  requestAnimationFrame(() => {
    const dropZone = document.getElementById('har-drop-zone');
    const fileInput = document.getElementById('har-file-input');

    dropZone.onclick = () => fileInput.click();
    fileInput.onchange = (e) => e.target.files[0] && _loadHarFile(e.target.files[0]);

    dropZone.ondragover = (e) => { e.preventDefault(); dropZone.style.borderColor = 'var(--primary)'; };
    dropZone.ondragleave = () => { dropZone.style.borderColor = 'var(--border)'; };
    dropZone.ondrop = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border)';
      const f = e.dataTransfer.files[0];
      if (f) _loadHarFile(f);
    };
  });

  async function _loadHarFile(file) {
    const text = await file.text();
    let har;
    try { har = JSON.parse(text); } catch(e) { alert('Invalid HAR file'); return; }

    const entries = har.log?.entries || [];
    const preview = document.getElementById('har-preview');
    const summary = document.getElementById('har-summary');
    const list = document.getElementById('har-request-list');

    summary.textContent = `Found ${entries.length} network entries. Static assets unchecked by default.`;
    list.innerHTML = '';
    _parsedRequests = [];

    entries.forEach((entry, i) => {
      const req = entry.request || {};
      const method = req.method || 'GET';
      const url = req.url || '';
      const isStatic = /\.(css|js|png|jpg|jpeg|gif|ico|woff|woff2|svg|webp)$/i.test(url)
                    || url.includes('/static/');

      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !isStatic;
      cb.id = `har-req-${i}`;

      const label = document.createElement('label');
      label.htmlFor = `har-req-${i}`;
      label.style.cssText = 'flex:1;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      label.innerHTML = `<span class="method-badge method-${method}" style="font-size:10px;padding:1px 5px;">${method}</span> ${url.replace(/\?.*/, '')}`;

      row.appendChild(cb);
      row.appendChild(label);
      list.appendChild(row);
      _parsedRequests.push({ entry, cb });
    });

    preview.style.display = '';
    window._harData = har;
    window._harFile = file;
  }

  async function _doImport() {
    if (!window._harFile) { alert('Please select a HAR file first.'); return; }

    // Build filtered HAR with only checked entries
    const har = window._harData;
    har.log.entries = har.log.entries.filter((_, i) => {
      return _parsedRequests[i]?.cb?.checked;
    });

    const formData = new FormData();
    formData.append('file', new Blob([JSON.stringify(har)], { type: 'application/json' }), 'import.har');
    formData.append('collection_name', window._harFile.name.replace('.har', ''));

    const res = await fetch('/api/discover/har', { method: 'POST', body: formData });
    const data = await res.json();
    window.closeModal();
    if (data.ok) {
      alert(`Imported ${data.imported} requests.`);
    } else {
      alert('Import failed: ' + data.error);
    }
  }
}
```

- [ ] Step 3: Create `web/static/api/views/openapi-import-view.js`:

```js
export function showOpenApiImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Import from URL</label>
      <input id="openapi-url" type="url" class="input-sm" style="width:100%" placeholder="https://api.example.com/openapi.json">
    </div>
    <div style="text-align:center;color:var(--text-muted);margin:8px 0;font-size:12px;">— or —</div>
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload file (.json, .yaml)</label>
      <input id="openapi-file" type="file" accept=".json,.yaml,.yml" class="input-sm">
    </div>
    <div id="openapi-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import OpenAPI / Swagger', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const urlInput = document.getElementById('openapi-url');
    const fileInput = document.getElementById('openapi-file');
    const resultDiv = document.getElementById('openapi-result');

    let res;
    if (fileInput?.files[0]) {
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      res = await fetch('/api/discover/openapi', { method: 'POST', body: formData });
      res = await res.json();
    } else if (urlInput?.value.trim()) {
      res = await window.api('POST', '/discover/openapi', { url: urlInput.value.trim() });
    } else {
      alert('Provide a URL or upload a file.');
      return;
    }

    resultDiv.style.display = '';
    if (res.ok) {
      const cols = res.collections || [];
      resultDiv.innerHTML = `<strong>Imported ${res.imported} requests</strong> across ${cols.length} collections.<br>
        ${cols.map(c => `• ${c.name} (${c.count})`).join('<br>')}`;
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${res.error}</span>`;
    }
  }
}
```

- [ ] Step 4: Create `web/static/api/views/postman-import-view.js`:

```js
export function showPostmanImport() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload Postman Collection v2.1 (.json)</label>
      <input id="postman-file" type="file" accept=".json" class="input-sm">
    </div>
    <div id="postman-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import Postman Collection', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const fileInput = document.getElementById('postman-file');
    if (!fileInput?.files[0]) { alert('Please select a Postman collection file.'); return; }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    const res = await fetch('/api/discover/postman', { method: 'POST', body: formData });
    const data = await res.json();

    const resultDiv = document.getElementById('postman-result');
    resultDiv.style.display = '';
    if (data.ok) {
      resultDiv.innerHTML = `<strong>Imported ${data.imported} requests.</strong>`;
      setTimeout(() => window.closeModal(), 1500);
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${data.error}</span>`;
    }
  }
}

export function showBrunoImportView() {
  const body = `
    <div style="margin-bottom:12px;">
      <label class="form-label">Upload .bru files (select multiple)</label>
      <input id="bruno-files" type="file" accept=".bru" multiple class="input-sm">
    </div>
    <div id="bruno-result" style="display:none;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:13px;"></div>`;

  window.showModal('Import Bruno Files', body, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Import', cls: 'btn-primary', action: _doImport },
  ]);

  async function _doImport() {
    const fileInput = document.getElementById('bruno-files');
    if (!fileInput?.files.length) { alert('Please select .bru files.'); return; }

    const formData = new FormData();
    for (const f of fileInput.files) formData.append('files', f);

    const res = await fetch('/api/discover/bruno', { method: 'POST', body: formData });
    const data = await res.json();

    const resultDiv = document.getElementById('bruno-result');
    resultDiv.style.display = '';
    if (data.ok) {
      resultDiv.innerHTML = `<strong>Imported ${data.imported} requests.</strong>`;
      setTimeout(() => window.closeModal(), 1500);
    } else {
      resultDiv.innerHTML = `<span style="color:var(--danger)">${data.error}</span>`;
    }
  }
}
```

- [ ] Step 5: Create `web/static/api/views/record-apis-view.js`:

```js
export function showRecordApis() {
  const body = `
    <div id="record-status-area">
      <p style="color:var(--text-muted);font-size:13px">Starting browser... this may take a moment.</p>
    </div>`;

  window.showModal('Record APIs', body, [
    { label: 'Stop Recording', cls: 'btn-outline-danger', action: _stopRecording },
    { label: 'Cancel', cls: 'btn-ghost', action: () => { _stopRecording(); window.closeModal(); } },
  ], null, 'md');

  let _sessionId = null;
  let _pollTimer = null;
  let _captured = 0;

  async function _startRecording() {
    const res = await window.api('POST', '/discover/record/start', { url: 'about:blank' });
    const statusArea = document.getElementById('record-status-area');
    if (!statusArea) return;

    if (!res.ok) {
      statusArea.innerHTML = `<p style="color:var(--danger)">Failed to start recording: ${res.error}</p>`;
      return;
    }

    _sessionId = res.session_id;
    statusArea.innerHTML = `
      <div class="record-status-badge recording">⏺ Recording</div>
      <p style="margin-top:10px;font-size:13px;color:var(--text-muted)">
        Interact with the browser window. Network requests are being captured.
      </p>
      <p id="record-count" style="font-size:13px">Captured: <strong>0</strong> requests</p>`;

    _pollTimer = setInterval(_pollStatus, 3000);
  }

  async function _pollStatus() {
    if (!_sessionId) return;
    const res = await window.api('GET', `/discover/record/status?session_id=${_sessionId}`);
    if (!res.ok) return;
    if (res.status === 'stopped') {
      clearInterval(_pollTimer);
      document.getElementById('record-status-area').innerHTML =
        '<div class="record-status-badge stopped">● Stopped</div>';
    }
  }

  async function _stopRecording() {
    if (_pollTimer) clearInterval(_pollTimer);
    if (!_sessionId) { window.closeModal(); return; }

    const res = await window.api('POST', '/discover/record/stop', { session_id: _sessionId });
    _sessionId = null;

    window.closeModal();

    if (!res.ok || !res.requests?.length) {
      alert('No API requests captured.');
      return;
    }

    _showCapturedResults(res.requests);
  }

  function _showCapturedResults(requests) {
    const body = `
      <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">${requests.length} requests captured. Select which to save:</p>
      <div id="captured-list" style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;">
        ${requests.map((r, i) => `
          <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid var(--border);font-size:12px;">
            <input type="checkbox" id="cap-${i}" checked>
            <label for="cap-${i}" style="flex:1;cursor:pointer">
              <span class="method-badge method-${r.method}" style="font-size:10px;padding:1px 5px;">${r.method}</span>
              ${r.url.replace(/\?.*/, '')}
            </label>
          </div>`).join('')}
      </div>
      <div style="margin-top:10px;">
        <label class="form-label">Collection name</label>
        <input id="capture-col-name" type="text" class="input-sm" style="width:100%" value="Recorded APIs">
      </div>`;

    window.showModal('Save Captured Requests', body, [
      { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
      { label: 'Save Selected', cls: 'btn-primary', action: async () => {
        const colName = document.getElementById('capture-col-name').value.trim() || 'Recorded APIs';
        const selected = requests.filter((_, i) => document.getElementById(`cap-${i}`)?.checked);
        if (!selected.length) { alert('No requests selected.'); return; }

        // Build a minimal HAR from selected requests and POST to /discover/har
        const har = {
          log: {
            version: '1.2',
            entries: selected.map(r => ({
              request: {
                method: r.method,
                url: r.url,
                headers: (r.headers || []).map(h => ({ name: h.key, value: h.value })),
                queryString: (r.params || []).map(p => ({ name: p.key, value: p.value })),
                postData: r.body ? { mimeType: 'application/json', text: r.body } : undefined,
              },
              response: { headers: [], content: { mimeType: 'text/plain' } },
            })),
          },
        };
        const formData = new FormData();
        formData.append('file', new Blob([JSON.stringify(har)], { type: 'application/json' }), 'captured.har');
        formData.append('collection_name', colName);
        const res = await fetch('/api/discover/har', { method: 'POST', body: formData });
        const data = await res.json();
        window.closeModal();
        if (data.ok) alert(`Saved ${data.imported} requests to '${colName}'.`);
        else alert('Save failed: ' + data.error);
      }},
    ]);
  }

  // Auto-start recording after modal renders
  requestAnimationFrame(() => _startRecording());
}
```

- [ ] Step 6: Commit — `git add web/static/api/views/ && git commit -m "feat: add discover modal and all import/record views"`

---

### Task 16: Suite Builder Extension & Unified Run Report

**Files:**
- Modify: `web/static/app.js` (additive changes to suite modal and run detail)

**Interfaces:**
- Consumes: Task 10 (POST /api/suites/<id>/items), Task 2 (ApiRunRepo via GET /api/api-runs)
- Produces: suite builder shows [API] badge items; run detail shows mixed script+API results

- [ ] Step 1: In `app.js`, find `editSuiteModal` (around line 3690). The existing modal loads scripts. After the existing `api('GET', '/suites/' + id)` call, the suite data has `suite.items` (added in Task 10). Locate the section where scripts are listed in the edit modal and extend it. Find this pattern in `editSuiteModal`:

```js
async function editSuiteModal(id) {
  const [suiteRes, scriptsRes] = await Promise.all([
    api('GET', '/suites/' + id),
    api('GET', '/scripts')
  ])
```

After loading `suiteRes`, the `suite.items` array now contains both script and api_request items. Add a helper to display them. Find where the modal body is built (the `showModal` call inside `editSuiteModal`) and add `[API]` badge rendering for api_request items. The change is additive — wrap the existing script list render to also include api_request items:

In the modal body HTML where the suite scripts are listed (look for `suite.scripts.map` or similar), replace the existing list render with:

```js
// In editSuiteModal, replace the items list section with:
const allItems = (suite.items || suite.scripts?.map(s => ({...s, item_type:'script', script_id:s.script_id, script_name:s.name})) || [])
  .sort((a,b) => a.order_index - b.order_index)

const itemsHtml = allItems.length === 0
  ? '<p class="text-muted text-sm">No items yet.</p>'
  : allItems.map(item => {
      if (item.item_type === 'api_request') {
        return `<div class="suite-item-row" data-item-id="${item.item_id}" data-item-type="api_request">
          <span class="badge badge-neutral" style="font-size:10px">API</span>
          <span>${escHtml(item.api_request_name || item.api_request_id)}</span>
          <span class="text-muted text-sm">${escHtml(item.method||'')} ${escHtml(item.url||'').slice(0,40)}</span>
          <button class="btn btn-xs btn-outline-danger" onclick="removeSuiteItem('${id}','${item.item_id}')">×</button>
        </div>`
      }
      return `<div class="suite-item-row" data-item-id="${item.item_id}" data-item-type="script">
        <span class="badge badge-neutral" style="font-size:10px">E2E</span>
        <span>${escHtml(item.script_name || item.name || '')}</span>
        <button class="btn btn-xs btn-ghost" onclick="viewScriptModal('${item.script_id}')">View</button>
        <button class="btn btn-xs btn-outline-danger" onclick="removeSuiteScript('${id}','${item.script_id}')">×</button>
      </div>`
    }).join('')
```

Also add an "Add API Request" button in the edit modal. Find where the existing "Add Script" dropdown/button is rendered and add alongside it:

```js
// Add after the existing "Add Script" button in editSuiteModal:
`<button class="btn btn-sm btn-ghost" onclick="addApiRequestToSuite('${id}')">+ Add API Request</button>`
```

Then add the `addApiRequestToSuite` function to `app.js`:

```js
async function addApiRequestToSuite(suiteId) {
  const res = await api('GET', '/api-requests')
  const requests = res.requests || []
  if (!requests.length) {
    toast('No API requests found. Create one in the API section first.', 'error')
    return
  }
  const options = requests.map(r => `<option value="${r.id}">[${r.method}] ${escHtml(r.name)}</option>`).join('')
  showModal('Add API Request to Suite', `
    <div class="form-group">
      <label class="form-label">Select API Request</label>
      <select id="api-req-select" class="input-sm" style="width:100%">${options}</select>
    </div>`, [
    { label: 'Cancel', cls: 'btn-ghost', action: closeModal },
    { label: 'Add', cls: 'btn-primary', action: async () => {
      const reqId = document.getElementById('api-req-select').value
      const res = await api('POST', `/suites/${suiteId}/items`, { item_type: 'api_request', api_request_id: reqId })
      if (res.ok === false) { toast(res.error, 'error'); return }
      closeModal()
      toast('API request added to suite')
      editSuiteModal(suiteId)
    }}
  ])
}
```

- [ ] Step 2: Add `removeSuiteItem` function to `app.js` (additive):

```js
async function removeSuiteItem(suiteId, itemId) {
  if (!confirm('Remove this item from the suite?')) return
  const res = await api('DELETE', `/suites/${suiteId}/items/${itemId}`)
  if (res.ok === false) { toast(res.error, 'error'); return }
  toast('Item removed')
  editSuiteModal(suiteId)
}
```

- [ ] Step 3: Extend `showRunResults` in `app.js` to show API run results interleaved. Find the `showRunResults` function. After the `scripts.map(s => { ... })` block that renders the existing script results, add support for `run.api_runs`. The `scripts` array from the API now includes items with `item_type: 'api_request'`. Extend the map to handle them:

In `showRunResults`, find:
```js
  const scripts = run.scripts || []
```

Change to:
```js
  const scripts = run.scripts || []
  // Merge api_request items from run.scripts that have item_type='api_request'
  // (execute_run now appends them to the scripts array for backward compat)
```

In the `.map(s => { ... })` block inside `showRunResults`, add a branch at the top for api_request items:

```js
// At the top of the scripts.map callback, before existing logic:
if (s.item_type === 'api_request') {
  const cls = s.status === 'PASSED' ? 'pass' : s.status === 'FAILED' ? 'fail' : 'skip'
  const badge = s.status === 'PASSED'
    ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
    : s.status === 'FAILED'
    ? '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'
    : '<span class="badge badge-neutral">ERROR</span>'
  const assertCount = (s.assertion_results || []).length
  const assertPass = (s.assertion_results || []).filter(a => a.passed).length
  return `<div class="script-result-row ${cls}">
    <div class="script-result-header">
      <div class="script-result-name">
        <span class="badge badge-neutral" style="font-size:10px">API</span>
        <strong>${escHtml(s.name)}</strong>
      </div>
      <div class="script-result-meta">
        ${badge}
        ${s.status_code ? `<span class="text-muted text-sm">${s.status_code}</span>` : ''}
        <span class="text-muted text-sm">${s.duration_ms || 0}ms</span>
        ${assertCount ? `<span class="text-muted text-sm">${assertPass}/${assertCount} assertions</span>` : ''}
      </div>
    </div>
    ${s.error_message ? `<div class="script-result-error">${escHtml(s.error_message)}</div>` : ''}
  </div>`
}
// ... existing script item rendering continues below
```

- [ ] Step 4: Commit:

```bash
git add web/static/app.js
git commit -m "feat: extend suite builder with API request items; show API results in run report"
```

---

### Task 17: Individual Script Run

**Files:**
- Modify: `web/routes/scripts.py` (add `POST /api/scripts/<id>/run` endpoint)
- Modify: `web/static/app.js` (add Run Script button in `viewScriptModal`)

**Interfaces:**
- Consumes: existing execute_run logic; script data from DB
- Produces: solo script run from the View Script modal

- [ ] Step 1: Add `POST /api/scripts/<script_id>/run` to `web/routes/scripts.py`. Add this after the last existing `@bp.route` in the file:

```python
@bp.route('/api/scripts/<script_id>/run', methods=['POST'])
def run_script_solo(script_id):
    """Run a single script ad-hoc without a suite. Creates a temporary suite_run."""
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True) or {}
        env_name = data.get("env_name")
        browser_type = data.get("browser", "chromium")
        headless = data.get("headless", False)
        resolution = data.get("resolution") or None

        conn = get_conn()
        script_row = conn.execute(
            "SELECT * FROM scripts WHERE id = ? AND project_id = ?",
            (script_id, project_id),
        ).fetchone()
        if not script_row:
            return jsonify({"ok": False, "error": f"Script {script_id} not found"}), 404

        script = dict(script_row)

        # Find or create a solo-run suite
        solo_suite = conn.execute(
            "SELECT id FROM suites WHERE project_id = ? AND name = '__solo_runs__' LIMIT 1",
            (project_id,),
        ).fetchone()
        if not solo_suite:
            solo_suite_id = generate_id("suite")
            now_ts = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO suites (id, project_id, channel, name, created_at) VALUES (?, ?, 'web', '__solo_runs__', ?)",
                (solo_suite_id, project_id, now_ts),
            )
            conn.commit()
        else:
            solo_suite_id = solo_suite["id"]

        # Delegate to execute_run logic by posting to /api/runs internally
        # We build a minimal suite_items entry temporarily
        # Simpler: inline the run logic here for the single script case
        import os, time, json, subprocess
        from pathlib import Path
        from cli.script_strategies import get_strategy
        from cli.db import generate_id as gen_id
        from cli.commands.web.env_utils import substitute_template_vars
        from web.routes.runs import (
            RUNS_DIR, SCREENSHOTS_DIR, PER_SCRIPT_TIMEOUT_SEC,
            DEFAULT_RECORD_RESOLUTION, _read_artifacts, _build_error_detail,
            get_default_playwright_browsers_path, is_frozen_binary,
        )
        from cli import runtime_setup

        language = script.get("language") or "python"
        try:
            get_strategy(language).validate_runtime()
        except (ValueError, RuntimeError) as e:
            payload = {"ok": False, "error": str(e)}
            if not runtime_setup.runtime_initialized():
                payload["needs_setup"] = True
                payload["setup_command"] = "qaclan setup --runtime-only"
            return jsonify(payload), 400

        env_vars_dict = {}
        environment_id = None
        if env_name:
            env_row = conn.execute(
                "SELECT * FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment '{env_name}' not found"}), 404
            environment_id = env_row["id"]
            from cli.crypto import decrypt
            for v in conn.execute("SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
                                  (env_row["id"],)).fetchall():
                val = v["value"]
                if v["is_secret"] and val:
                    val = decrypt(val)
                env_vars_dict[v["key"]] = val

        run_id = gen_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', 1, ?, ?, ?, ?)",
            (run_id, solo_suite_id, project_id, environment_id, now, browser_type, resolution, 1 if headless else 0),
        )
        conn.commit()

        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        state_file = run_dir / "state.json"

        srun_id = gen_id("srun")
        script_now = now
        script_start = time.time()
        screenshot_path = SCREENSHOTS_DIR / f"{srun_id}.png"
        artifacts_path = run_dir / f"{srun_id}.artifacts.json"

        try:
            strategy = get_strategy(language)
            script_path = script.get("file_path")
            if not script_path or not os.path.exists(script_path):
                raise FileNotFoundError(f"Script file not found: {script_path}")
            source = Path(script_path).read_text(encoding="utf-8")

            try:
                script_var_keys = json.loads(script.get("var_keys") or "[]")
            except (TypeError, ValueError):
                script_var_keys = []
            if script_var_keys:
                source, _ = substitute_template_vars(
                    source, script_var_keys, env_vars_dict,
                    script.get("start_url_key"), script.get("start_url_value"),
                    escape_fn=strategy.escape_for_literal,
                )

            rendered_path = run_dir / f"{srun_id}{strategy.file_extension}"
            rendered_path.write_text(source, encoding="utf-8")

            child_env = os.environ.copy()
            child_env.update(env_vars_dict)
            child_env["QACLAN_STORAGE_STATE"] = str(state_file)
            child_env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
            child_env["QACLAN_SCREENSHOT_PATH"] = str(screenshot_path)
            child_env["QACLAN_BROWSER"] = browser_type
            child_env["QACLAN_HEADLESS"] = "1" if headless else "0"
            child_env["QACLAN_VIEWPORT"] = resolution or DEFAULT_RECORD_RESOLUTION
            child_env["QACLAN_EXPECT_TIMEOUT"] = "15000"
            child_env["QACLAN_ACTION_TIMEOUT"] = "15000"

            pw_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            rt_browsers = runtime_setup.browsers_path_if_present()
            if not pw_browsers_path and rt_browsers:
                child_env["PLAYWRIGHT_BROWSERS_PATH"] = str(rt_browsers)
            elif is_frozen_binary() and not pw_browsers_path:
                default_browsers = get_default_playwright_browsers_path()
                if os.path.isdir(default_browsers):
                    child_env["PLAYWRIGHT_BROWSERS_PATH"] = default_browsers

            child_env.update(strategy.extra_env())
            cmd = strategy.build_run_command(str(rendered_path))

            proc = subprocess.run(cmd, env=child_env, capture_output=True, text=True, timeout=PER_SCRIPT_TIMEOUT_SEC)
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)

            if proc.returncode == 0:
                status = "PASSED"
                error_msg = None
                error_detail = None
                saved_screenshot = None
            else:
                status = "FAILED"
                error_detail, error_msg = _build_error_detail(
                    kind="subprocess", returncode=proc.returncode,
                    stdout=proc.stdout, stderr=proc.stderr,
                    artifacts_error=artifacts_error,
                    has_network_failures=bool(network_failures),
                )
                saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None

            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, console_errors, network_failures, "
                "screenshot_path, started_at, finished_at) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, status, duration_ms,
                 error_msg, json.dumps(error_detail) if error_detail else None,
                 len(console_errors), len(network_failures), saved_screenshot,
                 script_now, finished_at),
            )
            final_status = status
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            error_detail, error_msg = _build_error_detail(kind="timeout")
            status = "FAILED"
            saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
            console_errors, network_failures, _ = _read_artifacts(artifacts_path)
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, console_errors, network_failures, "
                "screenshot_path, started_at, finished_at) VALUES (?, ?, ?, 0, 'FAILED', ?, ?, ?, ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, duration_ms, error_msg,
                 json.dumps(error_detail), len(console_errors), len(network_failures),
                 saved_screenshot, script_now, finished_at),
            )
            final_status = "FAILED"
        except Exception as exc:
            duration_ms = int((time.time() - script_start) * 1000)
            finished_at = datetime.now(timezone.utc).isoformat()
            error_detail, error_msg = _build_error_detail(kind="internal", exc=exc)
            conn.execute(
                "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                "duration_ms, error_message, error_detail, started_at, finished_at) "
                "VALUES (?, ?, ?, 0, 'FAILED', ?, ?, ?, ?, ?)",
                (srun_id, run_id, script_id, duration_ms, error_msg,
                 json.dumps(error_detail), script_now, finished_at),
            )
            final_status = "FAILED"

        env_vars_dict.clear()
        conn.execute(
            "UPDATE suite_runs SET status=?, passed=?, failed=?, finished_at=? WHERE id=?",
            (final_status, 1 if final_status == "PASSED" else 0,
             0 if final_status == "PASSED" else 1, finished_at, run_id),
        )
        conn.commit()

        return jsonify({
            "ok": True,
            "result": {
                "run_id": run_id,
                "script_id": script_id,
                "name": script.get("name"),
                "status": final_status,
                "duration_ms": duration_ms,
                "error_message": error_msg if final_status != "PASSED" else None,
                "error_detail": error_detail if final_status != "PASSED" else None,
                "screenshot_path": saved_screenshot if final_status != "PASSED" else None,
            },
        })

    except Exception as e:
        logger.exception("run_script_solo")
        return jsonify({"ok": False, "error": str(e)}), 500
```

Also add the missing imports at the top of the `run_script_solo` function's outer scope — `datetime` and `timezone` are already imported in `scripts.py`. Check the existing imports and add only what's missing. The function uses `generate_id` and `get_conn` which are already imported.

- [ ] Step 2: Modify `web/static/app.js` — add a "Run Script" button to `viewScriptModal`. The existing `viewScriptModal` ends with:

```js
  ], 'Script ID: ' + s.id, 'lg')
```

Change the modal footer buttons from:
```js
    { label: 'Close', cls: 'btn-ghost', action: closeModal }
```

to:
```js
    { label: 'Close', cls: 'btn-ghost', action: closeModal },
    { label: '▶ Run Script', cls: 'btn-primary', action: () => runScriptSolo(s.id, s.name) }
```

Then add the `runScriptSolo` function to `app.js` (additive):

```js
async function runScriptSolo(scriptId, scriptName) {
  // Replace modal footer to show running state
  const footer = document.querySelector('.modal-footer')
  if (footer) {
    footer.innerHTML = '<span class="text-muted text-sm">Running...</span>'
  }

  const res = await api('POST', `/scripts/${scriptId}/run`, { headless: false })

  if (res.ok === false) {
    toast('Run failed: ' + res.error, 'error')
    if (footer) footer.innerHTML = `<button class="btn btn-ghost" onclick="closeModal()">Close</button>`
    return
  }

  const r = res.result
  const statusColor = r.status === 'PASSED' ? 'var(--success, #16a34a)' : 'var(--danger, #dc2626)'
  const statusBadge = r.status === 'PASSED'
    ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
    : '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'

  // Inject result panel into modal body
  const body = document.querySelector('.modal-body')
  if (body) {
    const resultDiv = document.createElement('div')
    resultDiv.style.cssText = 'margin-top:16px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-secondary)'
    resultDiv.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
        ${statusBadge}
        <span class="text-muted text-sm">${r.duration_ms || 0}ms</span>
      </div>
      ${r.error_message ? `<pre style="font-size:11px;color:var(--danger);white-space:pre-wrap;margin:0">${escHtml(r.error_message)}</pre>` : ''}
      ${r.screenshot_path ? (() => {
        const filename = r.screenshot_path.split(/[\\/]/).pop()
        return `<div style="margin-top:8px"><img src="/api/screenshots/${encodeURIComponent(filename)}" style="max-width:100%;border-radius:4px;cursor:pointer" onclick="window.open(this.src,'_blank')" alt="Screenshot"></div>`
      })() : ''}
    `
    body.appendChild(resultDiv)
  }

  if (footer) {
    footer.innerHTML = `
      <button class="btn btn-ghost" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" onclick="runScriptSolo('${scriptId}','${escHtml(scriptName)}')">▶ Run Again</button>
    `
  }
}
```

- [ ] Step 3: Commit:

```bash
git add web/routes/scripts.py web/static/app.js
git commit -m "feat: add solo script run endpoint and Run Script button in view modal"
```

---

## Self-Review Checklist

Confirm all spec sections are covered before marking this plan complete:

- [ ] **DB schema** — `api_collections`, `api_requests`, `api_runs` tables created (Task 1)
- [ ] **suite_items migration** — nullable `script_id`, added `item_type` + `api_request_id` (Task 1)
- [ ] **suites.description** — ALTER TABLE migration (Task 1)
- [ ] **3-layer architecture** — repos (Task 2), services (Task 4), routes (Task 7, 8) all separate
- [ ] **API runner** — var resolution, auth (all 5 types), sandbox (JS+Python), assertions (all 6 types, 8 ops), httpx HTTP call (Task 3)
- [ ] **Assertions JSON shape** — status, json_path, header, response_time, body_text with all 8 operators (Task 3)
- [ ] **Variable resolution order** — env_vars → state.qaclan_vars → empty+warn (Task 3)
- [ ] **Auth injection** — bearer, basic, api_key (header+query), oauth2 client_credentials (Task 3)
- [ ] **Script sandbox** — Python wrapper, JS wrapper, subprocess run, output JSON read (Task 3)
- [ ] **Collection CRUD + run + export** — all 7 endpoints (Task 7)
- [ ] **Request CRUD + send** — all 6 endpoints (Task 7)
- [ ] **HAR parser** — static asset filtering, sensitive key redaction (Task 5)
- [ ] **OpenAPI parser** — 3.x + 2.x, grouped by tag, sample body from schema (Task 5)
- [ ] **Postman parser** — v2.1, folders→collection_name, pm.test→post_script (Task 5)
- [ ] **Bruno parser** — meta/headers/body:json/script:post-response/assert sections (Task 5)
- [ ] **Discovery routes** — HAR, OpenAPI, Postman, Bruno file upload, record start/stop (Task 8)
- [ ] **API runs routes** — list by suite_run_id, get by id (Task 8)
- [ ] **Blueprint registration** — all 4 new blueprints registered in server.py (Task 9)
- [ ] **requirements.txt** — httpx>=0.27.0, jsonpath-ng>=1.6.0 added (Task 9)
- [ ] **Suite items POST/DELETE** — new endpoints in suites.py (Task 10)
- [ ] **get_suite extended** — returns both scripts and api_request items (Task 10)
- [ ] **execute_run dispatch** — LEFT JOIN, api_request branch, state.json bridge, QACLAN_STATE_* injection (Task 10)
- [ ] **state.json qaclan_vars bridge** — api runner writes state_updates, scripts read as QACLAN_STATE_* (Task 10)
- [ ] **CLI commands** — api list, run, export, import (auto-detect), record (Task 11)
- [ ] **key-value-table.js** — enabled checkbox, add/delete rows (Task 12)
- [ ] **assertion-builder.js** — dynamic op select per type, exists/not_exists hides value (Task 12)
- [ ] **response-panel.js** — 3 tabs (Body/Headers/Assertions), JSON formatting (Task 12)
- [ ] **api-section.js** — window.__qaclanApi registered, lazy-loads views (Task 13)
- [ ] **app.js route** — api route added to routes object (Task 13)
- [ ] **renderSidebar** — API nav item added after Runs (Task 13)
- [ ] **index.html** — `<script type="module">` for api-section.js (Task 13)
- [ ] **style.css** — all required classes present (.api-layout, .method-badge, .assertion-pass/fail, etc.) (Task 13)
- [ ] **collections-view.js** — sidebar list, expand/collapse, Run button, New Collection (Task 14)
- [ ] **request-editor-view.js** — full editor: method, URL, all tabs, Send, Save (Task 14)
- [ ] **discover-modal.js** — 6 option cards (Task 15)
- [ ] **har-import-view.js** — drag-drop, static assets unchecked by default, Import Selected (Task 15)
- [ ] **openapi-import-view.js** — URL OR file, shows grouped results (Task 15)
- [ ] **postman-import-view.js** — file upload (Task 15)
- [ ] **record-apis-view.js** — start recording, poll status, stop, save captured (Task 15)
- [ ] **Suite builder [API] badge** — edit modal shows [E2E] and [API] items (Task 16)
- [ ] **Add API Request to Suite** — `addApiRequestToSuite` + `removeSuiteItem` functions (Task 16)
- [ ] **showRunResults API items** — api_request items shown with [API] badge, status_code, assertions (Task 16)
- [ ] **POST /api/scripts/<id>/run** — solo run endpoint in scripts.py (Task 17)
- [ ] **Run Script button** — in viewScriptModal footer; shows inline result panel (Task 17)

---

## Revision Notes (applied after initial draft)

1. **Sandbox f-string bug fixed** — `_build_python_sandbox` and `_build_js_sandbox` now use string concatenation to avoid f-string misinterpreting `{` and `}` in user scripts.
2. **`runtime_setup` API corrected** — `venv_python()`, `node_bin("node")`, `NODE_MODULES` are the correct names.
3. **`decrypt` import corrected** — `from cli.crypto import decrypt` (not `cli.commands.web.auth`).
4. **Collection run made in-memory** — `run_collection()` no longer creates bogus `suite_runs` rows.
5. **Env loading extracted** — `cli/env_loader.py` eliminates 3× duplication of decrypt+load logic.
6. **Bruno export extracted** — `request_to_bru()` in `bruno_parser.py` eliminates duplicate .bru building in route and CLI.
7. **`RequestRepo.count_by_collection()` removed** — dead code; `CollectionRepo.list()` already counts via SQL.
8. **CLI uses `RequestRepo`** — no more manual JSON deserialization in CLI commands.
9. **`from __future__ import annotations` added** — all new Python files, for Python < 3.10 compatibility.
10. **`PRAGMA foreign_keys = OFF/ON`** — wrapped around suite_items table recreation in migration.
11. **"Suite has no items"** — corrected guard error message after LEFT JOIN change.
