# API Documentation Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-generate living API documentation from Playwright HAR recordings, with schema merging across sessions, a dedicated Docs tab in the API section, and OpenAPI 3.0 export.

**Architecture:** Recorded API requests carry `request_schema`/`response_schema` (already implemented). A new `api_doc_entries` table stores one normalized row per (project, method, path-pattern); a sync step runs after every import/record, merging schemas and updating the entry. A new Docs tab in `api-section.js` renders a two-column view (endpoint list → detail) and offers YAML export.

**Tech Stack:** Python/Flask backend, SQLite via existing `cli/db.py` pattern, vanilla JS ES modules frontend, PyYAML for YAML export (already a project dep via openapi import).

## Global Constraints

- No automated test runner — verify manually by running `python qaclan.py serve --port 7823` and exercising the UI.
- All DB changes use idempotent `ALTER TABLE … ADD COLUMN` or `CREATE TABLE IF NOT EXISTS` migrations called from `init_db()` in `cli/db.py`.
- Frontend is vanilla JS ES modules — no build step, no npm for frontend.
- Follow existing Flask Blueprint + Repository pattern: route → service/repo → `cli/db.py`.
- No new Python packages unless already importable — `pyyaml`, `httpx`, `jsonpath_ng` are available.
- All JSON columns stored as TEXT in SQLite; serialize on write, deserialize on read.
- `generate_id(prefix)` from `cli/db.py` for all new row IDs.
- `get_active_project_id()` from `cli/config` for project scoping in routes.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `cli/db.py` | Modify | Add `_migrate_api_docs()` — new table + new column |
| `cli/api_discovery/url_normalizer.py` | Create | `normalize_url(url) -> str` path-pattern extraction |
| `cli/api_discovery/schema_merger.py` | Create | `merge_schemas(existing, incoming) -> schema` |
| `cli/api_discovery/openapi_exporter.py` | Create | `export_openapi(entries, project_name) -> dict` |
| `web/api/repositories/doc_repo.py` | Create | `DocRepo` — CRUD on `api_doc_entries` |
| `web/api/services/doc_service.py` | Create | `sync_doc_entry(project_id, req_dict)` orchestrator |
| `web/api/services/discovery_service.py` | Modify | Call `sync_doc_entry` after `_save_requests` |
| `web/api/routes/docs.py` | Create | `GET /api/docs`, `GET /api/docs/<id>`, `GET /api/docs/export/openapi` |
| `web/api/routes/discovery.py` | Modify | Pass `include_in_docs` flag through `save_requests` route |
| `web/server.py` | Modify | Register `docs` blueprint |
| `web/static/api/views/record-apis-view.js` | Modify | Add "Include in docs" checkbox to save modal |
| `web/static/api/views/docs-view.js` | Create | Two-column docs tab UI |
| `web/static/api/api-section.js` | Modify | Add "API Docs" tab to sidebar header, wire up docs view |
| `web/static/api/components/response-panel.js` | Modify | Add "Schema" tab showing `response_schema` tree |
| `web/static/api/views/request-editor-view.js` | Modify | Pass `r.response_schema` to `createResponsePanel` |

---

## Task 1: Response Schema Tab in Response Panel

**Files:**
- Modify: `web/static/api/components/response-panel.js`
- Modify: `web/static/api/views/request-editor-view.js:524`

**Interfaces:**
- Consumes: `r.response_schema` (object | null) from existing request data
- Produces: `createResponsePanel(opts)` where `opts = { schema: null }` — schema shown as read-only tree in "Schema" tab

- [ ] **Step 1: Update `createResponsePanel` signature and add Schema tab**

Replace the entire `createResponsePanel` function in `web/static/api/components/response-panel.js`:

```javascript
/**
 * createResponsePanel(opts?) → { el, show(result) }
 * opts.schema: response_schema dict from stored request (shown read-only in Schema tab)
 */
export function createResponsePanel(opts = {}) {
  const _storedSchema = opts.schema || null;

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

  function _renderSchemaTree(schema, path) {
    const ul = document.createElement('ul');
    ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
    const isArray = Array.isArray(schema);
    const entries = isArray
      ? (schema.length ? [['0', schema[0]]] : [['0', '?']])
      : (schema && typeof schema === 'object' ? Object.entries(schema) : []);
    for (const [key, val] of entries) {
      const li = document.createElement('li');
      li.style.cssText = 'padding:1px 0;';
      const displayKey = isArray ? '[item]' : key;
      const currentPath = path ? `${path}.${key}` : key;
      if (val && typeof val === 'object') {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;padding:1px 2px;border-radius:3px;';
        row.onmouseenter = () => row.style.background = 'var(--surface-2)';
        row.onmouseleave = () => row.style.background = '';
        const arrow = document.createElement('span');
        arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:10px;';
        arrow.textContent = '▶';
        const keySpan = document.createElement('span');
        keySpan.style.cssText = 'font-family:var(--font-mono);font-size:12px;';
        keySpan.textContent = displayKey;
        const typeTag = document.createElement('span');
        typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
        typeTag.textContent = Array.isArray(val) ? 'array' : 'object';
        row.appendChild(arrow); row.appendChild(keySpan); row.appendChild(typeTag);
        const children = _renderSchemaTree(val, currentPath);
        children.style.display = 'none';
        row.onclick = () => {
          const open = children.style.display === 'none';
          children.style.display = open ? '' : 'none';
          arrow.textContent = open ? '▼' : '▶';
        };
        li.appendChild(row); li.appendChild(children);
      } else {
        const isNullType = val === 'null' || val === '?';
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:1px 2px;border-radius:3px;';
        const dot = document.createElement('span');
        dot.style.cssText = `font-size:9px;width:10px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
        dot.textContent = '●';
        const keySpan = document.createElement('span');
        keySpan.style.cssText = `font-family:var(--font-mono);font-size:12px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
        keySpan.textContent = displayKey;
        const typeTag = document.createElement('span');
        typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
        typeTag.textContent = val || 'any';
        row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeTag);
        li.appendChild(row);
      }
      ul.appendChild(li);
    }
    return ul;
  }

  function _renderContent(tab) {
    if (!_currentResult) return;
    const r = _currentResult;
    contentArea.innerHTML = '';

    if (tab === 'body') {
      if (!r.status_code && r.error_message) {
        const errDiv = document.createElement('div');
        errDiv.className = 'response-error-message';
        errDiv.textContent = r.error_message;
        contentArea.appendChild(errDiv);
        return;
      }
      const pre = document.createElement('pre');
      pre.className = 'response-body-pre';
      let text = r.response_body || '';
      try { text = JSON.stringify(JSON.parse(text), null, 2); } catch(e) {}
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
        const actual = ar.actual !== undefined && ar.actual !== null
          ? ` (actual: ${_esc(String(ar.actual).slice(0,80))})` : '';
        row.innerHTML = `<span class="assertion-icon">${icon}</span>
          <span class="assertion-desc">${_esc(ar.type)} ${detail}${_esc(ar.op)} ${_esc(String(ar.value ?? ''))}</span>
          <span class="assertion-actual">${actual}</span>`;
        contentArea.appendChild(row);
      });

    } else if (tab === 'schema') {
      const schema = r._responseSchema || _storedSchema;
      if (!schema || (typeof schema === 'object' && !Array.isArray(schema) && !Object.keys(schema).length)) {
        contentArea.innerHTML = '<p class="text-muted text-sm" style="padding:8px">No schema available. Record or run this request to capture response shape.</p>';
        return;
      }
      const wrap = document.createElement('div');
      wrap.style.cssText = 'padding:8px 10px;font-size:12px;';
      wrap.appendChild(_renderSchemaTree(schema, ''));
      contentArea.appendChild(wrap);
    }
  }

  function show(result) {
    _currentResult = result;
    panel.style.display = '';

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
    tabBar.appendChild(_renderTab(`Assertions (${assertPass}/${assertCount})`, 'assertions', false));
    tabBar.appendChild(_renderTab('Schema', 'schema', false));

    _renderContent('body');
  }

  // Show schema tab even before a run if stored schema exists
  if (_storedSchema) {
    panel.style.display = '';
    tabBar.innerHTML = '';
    const statusSpan = document.createElement('span');
    statusSpan.className = 'response-status';
    statusSpan.textContent = 'Not yet run';
    statusSpan.style.cssText = 'color:var(--text-muted);font-size:11px;padding:4px 8px;';
    tabBar.appendChild(statusSpan);
    tabBar.appendChild(_renderTab('Schema', 'schema', true));
    _currentResult = {};
    _renderContent('schema');
  }

  return { el: panel, show };
}
```

- [ ] **Step 2: Pass `response_schema` to `createResponsePanel` in request editor**

In `web/static/api/views/request-editor-view.js`, find line ~524:
```javascript
  const responsePanel = createResponsePanel();
```
Change to:
```javascript
  const responsePanel = createResponsePanel({ schema: r.response_schema || null });
```

- [ ] **Step 3: Verify manually**

Start server: `python qaclan.py serve --port 7823`
- Open a request that has `response_schema` stored (one recorded from HAR).
- Schema tab should appear in response panel immediately (before sending).
- Send the request → all 4 tabs appear: Body, Headers, Assertions, Schema.
- Schema tab shows the type tree read-only.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/components/response-panel.js web/static/api/views/request-editor-view.js
git commit -m "feat: add Schema tab to response panel showing stored response_schema"
```

---

## Task 2: DB Migration — `api_doc_entries` table + `include_in_docs` column

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: `api_doc_entries` table with columns `id, project_id, method, path_pattern, description, request_schema, response_schema, headers_schema, params_schema, source_request_ids, include_in_docs, first_seen_at, last_seen_at`
- Produces: `include_in_docs INTEGER DEFAULT 1` column on `api_requests`

- [ ] **Step 1: Add migration function to `cli/db.py`**

Add this function after `_migrate_api_schemas`:

```python
def _migrate_api_docs(conn):
    """Create api_doc_entries table and add include_in_docs to api_requests."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_doc_entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            method TEXT NOT NULL,
            path_pattern TEXT NOT NULL,
            description TEXT,
            request_schema TEXT DEFAULT NULL,
            response_schema TEXT DEFAULT NULL,
            headers_schema TEXT DEFAULT NULL,
            params_schema TEXT DEFAULT NULL,
            source_request_ids TEXT DEFAULT '[]',
            include_in_docs INTEGER DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
    """)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_doc_entries_unique "
            "ON api_doc_entries(project_id, method, path_pattern)"
        )
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN include_in_docs INTEGER DEFAULT 1")
    except Exception:
        pass  # Column already exists
    conn.commit()
```

- [ ] **Step 2: Call the migration in `init_db()`**

In `cli/db.py`, find the `init_db()` function. After the line:
```python
    _migrate_api_schemas(conn)
```
Add:
```python
    _migrate_api_docs(conn)
```

- [ ] **Step 3: Verify**

```bash
python -c "from cli.db import init_db; init_db(); from cli.db import get_conn; c = get_conn(); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
```
Expected output includes `api_doc_entries`.

```bash
python -c "from cli.db import init_db; init_db(); from cli.db import get_conn; c = get_conn(); print([r[1] for r in c.execute(\"PRAGMA table_info('api_requests')\").fetchall()])"
```
Expected output includes `include_in_docs`.

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat: add api_doc_entries table and include_in_docs column via migration"
```

---

## Task 3: URL Normalizer

**Files:**
- Create: `cli/api_discovery/url_normalizer.py`

**Interfaces:**
- Produces: `normalize_url(url: str) -> str` — returns path pattern like `/users/{user_id}/posts/{id}`

- [ ] **Step 1: Create `cli/api_discovery/url_normalizer.py`**

```python
from __future__ import annotations
import re
from urllib.parse import urlparse

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_INT_RE = re.compile(r'^\d+$')
_HEX_RE = re.compile(r'^[0-9a-f]{20,}$', re.IGNORECASE)
_SEMVER_RE = re.compile(r'^v\d+(\.\d+)*$')


def _prev_segment_name(result: list[str]) -> str:
    """Return a param name based on the preceding path segment."""
    for seg in reversed(result):
        if not (seg.startswith('{') and seg.endswith('}')):
            clean = seg.rstrip('s')  # naive singularize: users → user
            return clean + '_id' if not clean.endswith('_id') else clean
    return 'id'


def normalize_path(path: str) -> str:
    """Replace dynamic segments (IDs, UUIDs, hashes) with {param} placeholders."""
    segments = path.strip('/').split('/')
    result = []
    for seg in segments:
        if not seg:
            continue
        if _UUID_RE.match(seg):
            result.append('{uuid}')
        elif _INT_RE.match(seg):
            result.append('{' + _prev_segment_name(result) + '}')
        elif _HEX_RE.match(seg):
            result.append('{hash}')
        elif _SEMVER_RE.match(seg):
            result.append(seg)  # keep version literals: v1, v2.0
        else:
            result.append(seg)
    return '/' + '/'.join(result) if result else '/'


def normalize_url(url: str) -> str:
    """Extract and normalize the path from a full URL."""
    try:
        parsed = urlparse(url)
        return normalize_path(parsed.path or '/')
    except Exception:
        return '/'
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.api_discovery.url_normalizer import normalize_url
tests = [
    ('https://api.example.com/v1/users/123', '/v1/users/{user_id}'),
    ('https://api.example.com/v1/users/abc123def456abc123def456', '/v1/users/{hash}'),
    ('https://api.example.com/v1/posts/f47ac10b-58cc-4372-a567-0e02b2c3d479', '/v1/posts/{uuid}'),
    ('https://api.example.com/v1/users/123/posts/456', '/v1/users/{user_id}/posts/{post_id}'),
    ('https://api.example.com/api/v1/me', '/api/v1/me'),
]
for url, expected in tests:
    result = normalize_url(url)
    status = 'OK' if result == expected else f'FAIL got {result!r}'
    print(f'{status}: {url}')
"
```
Expected: all lines show `OK`.

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/url_normalizer.py
git commit -m "feat: add URL normalizer for API doc path pattern extraction"
```

---

## Task 4: Schema Merger

**Files:**
- Create: `cli/api_discovery/schema_merger.py`

**Interfaces:**
- Produces: `merge_schemas(existing: dict | list | str | None, incoming: dict | list | str | None) -> dict | list | str | None`

- [ ] **Step 1: Create `cli/api_discovery/schema_merger.py`**

```python
from __future__ import annotations


def merge_schemas(existing, incoming):
    """Merge two inferred type-tree schemas. Union of fields; union of types on conflict.

    Both inputs use the format produced by har_parser._infer_schema():
    - primitive types: "string", "number", "boolean", "null", "?"
    - objects: {"key": <schema>, ...}
    - arrays:  [<item_schema>]  (single-element list)
    - depth sentinel: "..."
    """
    if existing is None:
        return incoming
    if incoming is None:
        return existing

    # Both primitives (type strings)
    if isinstance(existing, str) and isinstance(incoming, str):
        if existing == incoming:
            return existing
        # Prefer a real type over null/unknown
        if existing in ('null', '?', '...'):
            return incoming
        if incoming in ('null', '?', '...'):
            return existing
        return existing  # Keep first seen on true conflict

    # Both arrays
    if isinstance(existing, list) and isinstance(incoming, list):
        ex_item = existing[0] if existing else None
        in_item = incoming[0] if incoming else None
        merged = merge_schemas(ex_item, in_item)
        return [merged] if merged is not None else []

    # Both objects
    if isinstance(existing, dict) and isinstance(incoming, dict):
        result = dict(existing)
        for k, v in incoming.items():
            result[k] = merge_schemas(result.get(k), v)
        return result

    # Type mismatch (e.g. one is object, other is primitive) — keep existing
    return existing
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.api_discovery.schema_merger import merge_schemas

# Merging null with real type → real type wins
r = merge_schemas('null', 'string')
assert r == 'string', r

# Same types stay same
r = merge_schemas('number', 'number')
assert r == 'number', r

# New field in incoming added to result
r = merge_schemas({'a': 'string'}, {'a': 'string', 'b': 'number'})
assert r == {'a': 'string', 'b': 'number'}, r

# Array item schemas merged
r = merge_schemas([{'id': 'null'}], [{'id': 'string', 'name': 'string'}])
assert r == [{'id': 'string', 'name': 'string'}], r

print('All merge_schemas tests passed')
"
```
Expected: `All merge_schemas tests passed`

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/schema_merger.py
git commit -m "feat: add schema merger for union of API doc type-tree schemas"
```

---

## Task 5: Doc Entry Repository

**Files:**
- Create: `web/api/repositories/doc_repo.py`

**Interfaces:**
- Consumes: `get_conn`, `generate_id` from `cli.db`
- Produces:
  - `DocRepo().upsert(project_id: str, method: str, path_pattern: str, data: dict) -> dict`
  - `DocRepo().list(project_id: str) -> list[dict]`
  - `DocRepo().get(project_id: str, entry_id: str) -> dict | None`
  - `DocRepo().delete(project_id: str, entry_id: str) -> bool`

`data` dict keys for `upsert`: `request_schema`, `response_schema`, `headers_schema`, `params_schema`, `description`, `source_request_ids` (list of str).

- [ ] **Step 1: Create `web/api/repositories/doc_repo.py`**

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.doc_repo")

_JSON_COLS = ('request_schema', 'response_schema', 'headers_schema', 'params_schema', 'source_request_ids')


def _serialize(data: dict) -> dict:
    out = dict(data)
    for key in _JSON_COLS:
        if key in out and out[key] is not None and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    return out


def _deserialize(row: dict) -> dict:
    out = dict(row)
    for key in _JSON_COLS:
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except (ValueError, TypeError):
                out[key] = [] if key == 'source_request_ids' else None
    return out


class DocRepo:
    def upsert(self, project_id: str, method: str, path_pattern: str, data: dict) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        method = method.upper()

        existing = conn.execute(
            "SELECT * FROM api_doc_entries WHERE project_id = ? AND method = ? AND path_pattern = ?",
            (project_id, method, path_pattern),
        ).fetchone()

        s = _serialize(data)

        if existing:
            row_id = existing['id']
            updates = {
                k: s.get(k)
                for k in ('request_schema', 'response_schema', 'headers_schema',
                          'params_schema', 'description', 'source_request_ids')
                if k in s
            }
            updates['last_seen_at'] = now
            set_clause = ', '.join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE api_doc_entries SET {set_clause} WHERE id = ?",
                list(updates.values()) + [row_id],
            )
            conn.commit()
            return self.get(project_id, row_id)

        row_id = generate_id('apidoc')
        conn.execute(
            "INSERT INTO api_doc_entries "
            "(id, project_id, method, path_pattern, description, "
            "request_schema, response_schema, headers_schema, params_schema, "
            "source_request_ids, include_in_docs, first_seen_at, last_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id, project_id, method, path_pattern,
                s.get('description'),
                s.get('request_schema'), s.get('response_schema'),
                s.get('headers_schema'), s.get('params_schema'),
                s.get('source_request_ids', '[]'),
                1, now, now,
            ),
        )
        conn.commit()
        logger.info("DocRepo.upsert: %s %s (%s)", method, path_pattern, row_id)
        return self.get(project_id, row_id)

    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_doc_entries WHERE project_id = ? ORDER BY path_pattern, method",
            (project_id,),
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]

    def get(self, project_id: str, entry_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_doc_entries WHERE id = ? AND project_id = ?",
            (entry_id, project_id),
        ).fetchone()
        return _deserialize(dict(row)) if row else None

    def delete(self, project_id: str, entry_id: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM api_doc_entries WHERE id = ? AND project_id = ?",
            (entry_id, project_id),
        )
        conn.commit()
        return cur.rowcount > 0
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import init_db
init_db()
from cli.config import get_active_project_id
from web.api.repositories.doc_repo import DocRepo

repo = DocRepo()
pid = get_active_project_id()
if not pid:
    print('SKIP: no active project')
else:
    entry = repo.upsert(pid, 'GET', '/v1/users/{user_id}', {
        'response_schema': {'id': 'string', 'name': 'string'},
        'source_request_ids': ['test-id-1'],
    })
    print('Created:', entry['id'], entry['path_pattern'])
    entries = repo.list(pid)
    print('Listed:', len(entries), 'entries')
    fetched = repo.get(pid, entry['id'])
    print('Fetched schema:', fetched['response_schema'])
"
```
Expected: prints created entry, lists it, and shows the schema dict.

- [ ] **Step 3: Commit**

```bash
git add web/api/repositories/doc_repo.py
git commit -m "feat: add DocRepo for api_doc_entries CRUD"
```

---

## Task 6: Doc Sync Service

**Files:**
- Create: `web/api/services/doc_service.py`

**Interfaces:**
- Consumes: `normalize_url` from `cli.api_discovery.url_normalizer`
- Consumes: `merge_schemas` from `cli.api_discovery.schema_merger`
- Consumes: `DocRepo` from `web.api.repositories.doc_repo`
- Produces: `sync_doc_entry(project_id: str, req: dict) -> None` — call after saving any request where `include_in_docs` is truthy

`req` dict keys used: `id`, `method`, `url`, `request_schema`, `response_schema`, `headers`, `params`, `include_in_docs`

- [ ] **Step 1: Create `web/api/services/doc_service.py`**

```python
from __future__ import annotations
import logging

logger = logging.getLogger("qaclan.doc_service")


def sync_doc_entry(project_id: str, req: dict) -> None:
    """Upsert an api_doc_entries row from a saved api_request dict.

    Merges schemas with any existing doc entry for the same (method, path_pattern).
    No-op if include_in_docs is falsy.
    """
    if not req.get('include_in_docs', 1):
        return

    from cli.api_discovery.url_normalizer import normalize_url
    from cli.api_discovery.schema_merger import merge_schemas
    from web.api.repositories.doc_repo import DocRepo

    method = req.get('method', 'GET').upper()
    url = req.get('url', '')
    if not url:
        return

    path_pattern = normalize_url(url)
    repo = DocRepo()

    # Get existing entry to merge schemas
    existing_entries = [
        e for e in repo.list(project_id)
        if e['method'] == method and e['path_pattern'] == path_pattern
    ]
    existing = existing_entries[0] if existing_entries else None

    # Merge schemas
    new_req_schema = req.get('request_schema')
    new_resp_schema = req.get('response_schema')

    merged_req_schema = merge_schemas(
        existing.get('request_schema') if existing else None,
        new_req_schema,
    )
    merged_resp_schema = merge_schemas(
        existing.get('response_schema') if existing else None,
        new_resp_schema,
    )

    # Build headers schema (merge common request header keys)
    headers = req.get('headers', [])
    if isinstance(headers, str):
        import json
        try:
            headers = json.loads(headers)
        except Exception:
            headers = []
    headers_schema = {h['key']: 'string' for h in headers if h.get('key')}
    merged_headers = merge_schemas(
        existing.get('headers_schema') if existing else None,
        headers_schema or None,
    )

    # Build params schema
    params = req.get('params', [])
    if isinstance(params, str):
        import json
        try:
            params = json.loads(params)
        except Exception:
            params = []
    params_schema = {p['key']: 'string' for p in params if p.get('key')}
    merged_params = merge_schemas(
        existing.get('params_schema') if existing else None,
        params_schema or None,
    )

    # Track source request IDs
    source_ids = list(existing.get('source_request_ids', []) if existing else [])
    req_id = req.get('id')
    if req_id and req_id not in source_ids:
        source_ids.append(req_id)

    repo.upsert(project_id, method, path_pattern, {
        'request_schema': merged_req_schema,
        'response_schema': merged_resp_schema,
        'headers_schema': merged_headers,
        'params_schema': merged_params,
        'source_request_ids': source_ids,
    })
    logger.info("sync_doc_entry: %s %s → %s", method, url, path_pattern)
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import init_db
init_db()
from cli.config import get_active_project_id
pid = get_active_project_id()
if not pid:
    print('SKIP: no active project')
else:
    from web.api.services.doc_service import sync_doc_entry
    sync_doc_entry(pid, {
        'id': 'test-req-1',
        'method': 'GET',
        'url': 'https://api.example.com/v1/users/123',
        'response_schema': {'id': 'string', 'email': 'null'},
        'headers': [{'key': 'Authorization', 'value': '...', 'enabled': True}],
        'params': [],
        'include_in_docs': 1,
    })
    sync_doc_entry(pid, {
        'id': 'test-req-2',
        'method': 'GET',
        'url': 'https://api.example.com/v1/users/456',
        'response_schema': {'id': 'string', 'email': 'string', 'name': 'string'},
        'headers': [{'key': 'Authorization', 'value': '...', 'enabled': True}],
        'params': [],
        'include_in_docs': 1,
    })
    from web.api.repositories.doc_repo import DocRepo
    entries = DocRepo().list(pid)
    print('Entries:', len(entries))
    e = entries[-1]
    print('path_pattern:', e['path_pattern'])
    print('merged response_schema:', e['response_schema'])
    print('source_request_ids:', e['source_request_ids'])
"
```
Expected:
- `Entries: 1` (both calls merged into one `/v1/users/{user_id}` entry)
- `response_schema` shows `{'id': 'string', 'email': 'string', 'name': 'string'}` (null merged to string)
- `source_request_ids: ['test-req-1', 'test-req-2']`

- [ ] **Step 3: Commit**

```bash
git add web/api/services/doc_service.py
git commit -m "feat: add doc_service.sync_doc_entry with URL normalization and schema merging"
```

---

## Task 7: Auto-sync on Import / Record Save

**Files:**
- Modify: `web/api/services/discovery_service.py`
- Modify: `web/api/routes/discovery.py` (the `save_requests` route)

**Interfaces:**
- Consumes: `sync_doc_entry` from `web.api.services.doc_service`
- `include_in_docs` field on each request dict controls whether sync fires

- [ ] **Step 1: Call `sync_doc_entry` after `_save_requests` in `discovery_service.py`**

In `web/api/services/discovery_service.py`, modify `_save_requests`:

```python
def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)
        if collection_id:
            data["collection_id"] = collection_id
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

        saved_req = _req_repo.create(project_id, data)

        # Sync to API docs if flagged (default: include)
        try:
            sync_doc_entry(project_id, {**data, 'id': saved_req['id']})
        except Exception as e:
            logger.warning("sync_doc_entry failed for %s: %s", data.get('url'), e)

        saved += 1
    return saved
```

- [ ] **Step 2: Pass `include_in_docs` through `save_requests` route**

In `web/api/routes/discovery.py`, in the `save_requests` route, pass `include_in_docs` from request body into each request dict:

```python
@bp.route("/api/discover/save-requests", methods=["POST"])
def save_requests():
    """Save pre-parsed request objects directly (no re-parsing). Body: {requests, collection_name, include_in_docs}."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        requests_list = data.get("requests", [])
        collection_name = data.get("collection_name", "Recorded APIs")
        include_in_docs = int(data.get("include_in_docs", 1))
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        # Stamp include_in_docs on each request
        for r in requests_list:
            r['include_in_docs'] = include_in_docs
        from web.api.services.discovery_service import _save_requests
        from web.api.repositories.collection_repo import CollectionRepo
        col = CollectionRepo().create(pid, collection_name)
        saved = _save_requests(pid, requests_list, collection_id=col["id"])
        logger.info("save_requests: saved %d to collection %s", saved, col["id"])
        return jsonify({"ok": True, "imported": saved, "collection_id": col["id"]})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("save_requests")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 3: Verify**

Start server and record a session. After saving, check that `api_doc_entries` is populated:

```bash
python -c "
from cli.db import init_db; init_db()
from cli.config import get_active_project_id
from web.api.repositories.doc_repo import DocRepo
entries = DocRepo().list(get_active_project_id())
for e in entries[:5]:
    print(e['method'], e['path_pattern'], '— resp schema keys:', list((e.get('response_schema') or {}).keys())[:5])
"
```

- [ ] **Step 4: Commit**

```bash
git add web/api/services/discovery_service.py web/api/routes/discovery.py
git commit -m "feat: auto-sync api_doc_entries after import/record save"
```

---

## Task 8: Recording Opt-in UI ("Include in Docs" checkbox)

**Files:**
- Modify: `web/static/api/views/record-apis-view.js`

**Interfaces:**
- Consumes: `include_in_docs` boolean → sent as `include_in_docs: 1|0` in the `save-requests` payload

- [ ] **Step 1: Add checkbox to the save modal in `record-apis-view.js`**

Find the `modalBodyHTML` string in `_showCapturedResults`. After the collection name input block:
```html
      <div style="margin-top:10px;">
        <label class="form-label">Save to collection</label>
        <input id="capture-col-name" type="text" class="input-sm" style="width:100%" value="Recorded APIs">
      </div>`;
```

Change to:
```javascript
      <div style="margin-top:10px;">
        <label class="form-label">Save to collection</label>
        <input id="capture-col-name" type="text" class="input-sm" style="width:100%" value="Recorded APIs">
      </div>
      <label style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:12px;cursor:pointer;">
        <input type="checkbox" id="capture-include-docs" checked>
        Include in API Documentation
      </label>`;
```

- [ ] **Step 2: Read checkbox value when saving**

In the "Save Selected" action (same file), change the `window.api` call to pass the flag:

```javascript
        const includeInDocs = document.getElementById('capture-include-docs')?.checked ? 1 : 0;
        const data = await window.api('POST', '/discover/save-requests', {
          requests: selected,
          collection_name: colName,
          include_in_docs: includeInDocs,
        });
```

- [ ] **Step 3: Verify**

Record a session. In the save modal, uncheck "Include in API Documentation". Save. Verify that no new `api_doc_entries` row was created for those requests (or existing entry was not updated).

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/record-apis-view.js
git commit -m "feat: add Include in API Documentation opt-in checkbox to recording save modal"
```

---

## Task 9: OpenAPI Exporter

**Files:**
- Create: `cli/api_discovery/openapi_exporter.py`

**Interfaces:**
- Produces: `export_openapi(doc_entries: list[dict], project_name: str) -> dict` — returns OpenAPI 3.0 dict
- Produces: `export_openapi_yaml(doc_entries: list[dict], project_name: str) -> str` — returns YAML string

- [ ] **Step 1: Create `cli/api_discovery/openapi_exporter.py`**

```python
from __future__ import annotations
import re


def _schema_to_openapi(schema) -> dict:
    """Convert our type-string schema tree to OpenAPI JSON Schema format."""
    if schema is None or schema == '?':
        return {}
    if isinstance(schema, str):
        _type_map = {
            'string': 'string', 'number': 'number', 'boolean': 'boolean',
            'null': 'string', '...': 'string',
        }
        # Handle union types like "string|number" from merge
        if '|' in schema:
            types = [t.strip() for t in schema.split('|')]
            non_null = [t for t in types if t != 'null']
            t = _type_map.get(non_null[0], 'string') if non_null else 'string'
        else:
            t = _type_map.get(schema, 'string')
        return {'type': t}
    if isinstance(schema, list):
        item_schema = _schema_to_openapi(schema[0]) if schema else {}
        return {'type': 'array', 'items': item_schema}
    if isinstance(schema, dict):
        props = {k: _schema_to_openapi(v) for k, v in schema.items()}
        return {'type': 'object', 'properties': props}
    return {}


def export_openapi(doc_entries: list[dict], project_name: str = 'API') -> dict:
    """Generate an OpenAPI 3.0 spec dict from api_doc_entries rows."""
    paths: dict = {}

    for entry in doc_entries:
        if not entry.get('include_in_docs', 1):
            continue

        path = entry['path_pattern']
        method = entry['method'].lower()

        operation: dict = {
            'summary': f"{entry['method']} {path}",
            'operationId': re.sub(r'[^a-zA-Z0-9]', '_', f"{entry['method']}_{path}").strip('_'),
            'responses': {'200': {'description': 'Success'}},
        }

        # Path parameters
        path_params = re.findall(r'\{([^}]+)\}', path)
        if path_params:
            operation['parameters'] = [
                {'name': p, 'in': 'path', 'required': True, 'schema': {'type': 'string'}}
                for p in path_params
            ]

        # Query parameters from params_schema
        params_schema = entry.get('params_schema') or {}
        if isinstance(params_schema, dict) and params_schema:
            query_params = operation.setdefault('parameters', [])
            for k in params_schema:
                query_params.append({'name': k, 'in': 'query', 'schema': {'type': 'string'}})

        # Request body (POST/PUT/PATCH only)
        if method in ('post', 'put', 'patch') and entry.get('request_schema'):
            operation['requestBody'] = {
                'content': {
                    'application/json': {
                        'schema': _schema_to_openapi(entry['request_schema'])
                    }
                }
            }

        # Response schema
        if entry.get('response_schema'):
            operation['responses']['200']['content'] = {
                'application/json': {
                    'schema': _schema_to_openapi(entry['response_schema'])
                }
            }

        if path not in paths:
            paths[path] = {}
        paths[path][method] = operation

    return {
        'openapi': '3.0.0',
        'info': {'title': project_name, 'version': '1.0.0'},
        'paths': paths,
    }


def export_openapi_yaml(doc_entries: list[dict], project_name: str = 'API') -> str:
    """Return OpenAPI 3.0 as a YAML string."""
    import yaml
    return yaml.dump(export_openapi(doc_entries, project_name), sort_keys=False, allow_unicode=True)
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from cli.db import init_db; init_db()
from cli.config import get_active_project_id
from web.api.repositories.doc_repo import DocRepo
from cli.api_discovery.openapi_exporter import export_openapi_yaml
entries = DocRepo().list(get_active_project_id())
print(export_openapi_yaml(entries, 'My API')[:800])
"
```
Expected: valid YAML starting with `openapi: 3.0.0` with paths from your recorded entries.

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/openapi_exporter.py
git commit -m "feat: add OpenAPI 3.0 exporter from api_doc_entries"
```

---

## Task 10: Docs API Routes

**Files:**
- Create: `web/api/routes/docs.py`
- Modify: `web/server.py`

**Interfaces:**
- Produces:
  - `GET /api/docs` → `{ok: true, entries: [...]}`
  - `GET /api/docs/<entry_id>` → `{ok: true, entry: {...}}`
  - `DELETE /api/docs/<entry_id>` → `{ok: true}`
  - `GET /api/docs/export/openapi` → YAML file download

- [ ] **Step 1: Create `web/api/routes/docs.py`**

```python
from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request, Response
from cli.config import get_active_project_id
from web.api.repositories.doc_repo import DocRepo

logger = logging.getLogger("qaclan.routes.docs")
bp = Blueprint("api_docs", __name__)
_repo = DocRepo()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/docs", methods=["GET"])
def list_docs():
    try:
        entries = _repo.list(_project_id())
        return jsonify({"ok": True, "entries": entries})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_docs")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/<entry_id>", methods=["GET"])
def get_doc(entry_id):
    try:
        entry = _repo.get(_project_id(), entry_id)
        if not entry:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "entry": entry})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_doc")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/<entry_id>", methods=["DELETE"])
def delete_doc(entry_id):
    try:
        deleted = _repo.delete(_project_id(), entry_id)
        if not deleted:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_doc")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/docs/export/openapi", methods=["GET"])
def export_openapi():
    try:
        from cli.config import get_active_project
        from cli.api_discovery.openapi_exporter import export_openapi_yaml
        project = get_active_project()
        project_name = project.get('name', 'API') if project else 'API'
        entries = _repo.list(_project_id())
        yaml_str = export_openapi_yaml(entries, project_name)
        return Response(
            yaml_str,
            mimetype='application/x-yaml',
            headers={'Content-Disposition': 'attachment; filename="openapi.yaml"'},
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("export_openapi")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Register blueprint in `web/server.py`**

Find where existing blueprints are registered. Look for lines like:
```python
from web.api.routes.collections import bp as collections_bp
app.register_blueprint(collections_bp)
```

Add the docs blueprint in the same pattern:
```python
from web.api.routes.docs import bp as docs_bp
app.register_blueprint(docs_bp)
```

- [ ] **Step 3: Verify**

```bash
python qaclan.py serve --port 7823 &
sleep 2
curl -s http://localhost:7823/api/docs | python -m json.tool | head -20
curl -s "http://localhost:7823/api/docs/export/openapi" | head -20
kill %1
```
Expected: JSON with `ok: true, entries: [...]` and valid YAML starting with `openapi: 3.0.0`.

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/docs.py web/server.py
git commit -m "feat: add API docs routes — list, get, delete, OpenAPI YAML export"
```

---

## Task 11: Docs Tab UI

**Files:**
- Create: `web/static/api/views/docs-view.js`

**Interfaces:**
- Consumes: `window.api('GET', '/docs')` → `{entries: [...]}`
- Consumes: `window.api('GET', '/docs/export/openapi')` → file download via `<a href>` trick
- Produces: `renderDocsView(container)` — two-column layout (endpoint list + detail panel)

- [ ] **Step 1: Create `web/static/api/views/docs-view.js`**

```javascript
function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _renderSchemaTree(schema, path) {
  const ul = document.createElement('ul');
  ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
  if (!schema || typeof schema !== 'object') {
    if (schema) {
      const li = document.createElement('li');
      li.style.cssText = 'font-family:var(--font-mono);font-size:12px;color:var(--text-muted);padding:2px 0;';
      li.textContent = String(schema);
      ul.appendChild(li);
    }
    return ul;
  }
  const isArray = Array.isArray(schema);
  const entries = isArray
    ? (schema.length ? [['0', schema[0]]] : [['0', '?']])
    : Object.entries(schema);
  for (const [key, val] of entries) {
    const li = document.createElement('li');
    li.style.cssText = 'padding:1px 0;';
    const displayKey = isArray ? '[item]' : key;
    const currentPath = path ? `${path}.${key}` : key;
    if (val && typeof val === 'object') {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;padding:1px 2px;border-radius:3px;';
      row.onmouseenter = () => row.style.background = 'var(--surface-2)';
      row.onmouseleave = () => row.style.background = '';
      const arrow = document.createElement('span');
      arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:10px;';
      arrow.textContent = '▶';
      const keySpan = document.createElement('span');
      keySpan.style.cssText = 'font-family:var(--font-mono);font-size:12px;';
      keySpan.textContent = displayKey;
      const typeTag = document.createElement('span');
      typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
      typeTag.textContent = Array.isArray(val) ? 'array' : 'object';
      row.appendChild(arrow); row.appendChild(keySpan); row.appendChild(typeTag);
      const children = _renderSchemaTree(val, currentPath);
      children.style.display = 'none';
      row.onclick = () => {
        const open = children.style.display === 'none';
        children.style.display = open ? '' : 'none';
        arrow.textContent = open ? '▼' : '▶';
      };
      li.appendChild(row); li.appendChild(children);
    } else {
      const isNullType = val === 'null' || val === '?';
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:1px 2px;';
      const dot = document.createElement('span');
      dot.style.cssText = `font-size:9px;width:10px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
      dot.textContent = '●';
      const keySpan = document.createElement('span');
      keySpan.style.cssText = `font-family:var(--font-mono);font-size:12px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
      keySpan.textContent = displayKey;
      const typeTag = document.createElement('span');
      typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
      typeTag.textContent = val || 'any';
      row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeTag);
      li.appendChild(row);
    }
    ul.appendChild(li);
  }
  return ul;
}

function _methodClass(method) {
  return `method-${(method || 'get').toLowerCase()}`;
}

export function renderDocsView(container) {
  container.innerHTML = '';

  const layout = document.createElement('div');
  layout.style.cssText = 'display:flex;height:100%;overflow:hidden;';

  // Left: endpoint list
  const listPanel = document.createElement('div');
  listPanel.style.cssText = 'width:280px;min-width:200px;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0;';

  // Right: detail
  const detailPanel = document.createElement('div');
  detailPanel.style.cssText = 'flex:1;overflow-y:auto;padding:20px 24px;';
  detailPanel.innerHTML = '<p class="text-muted text-sm">Select an endpoint to view documentation.</p>';

  layout.appendChild(listPanel);
  layout.appendChild(detailPanel);
  container.appendChild(layout);

  function _renderDetail(entry) {
    detailPanel.innerHTML = '';

    // Header
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:16px;';
    const methodBadge = document.createElement('span');
    methodBadge.className = `method-badge ${_methodClass(entry.method)}`;
    methodBadge.style.cssText = 'font-size:13px;padding:3px 10px;';
    methodBadge.textContent = entry.method;
    const pathEl = document.createElement('code');
    pathEl.style.cssText = 'font-size:15px;font-weight:500;word-break:break-all;';
    pathEl.textContent = entry.path_pattern;
    hdr.appendChild(methodBadge);
    hdr.appendChild(pathEl);
    detailPanel.appendChild(hdr);

    const meta = document.createElement('p');
    meta.style.cssText = 'font-size:11px;color:var(--text-muted);margin-bottom:16px;';
    const seenAt = entry.last_seen_at ? new Date(entry.last_seen_at).toLocaleDateString() : '—';
    meta.textContent = `Last seen: ${seenAt} · Sources: ${(entry.source_request_ids || []).length} recording(s)`;
    detailPanel.appendChild(meta);

    function _section(title, content) {
      const sec = document.createElement('div');
      sec.style.cssText = 'margin-bottom:20px;';
      const h = document.createElement('h4');
      h.style.cssText = 'font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin:0 0 8px;';
      h.textContent = title;
      sec.appendChild(h);
      const body = document.createElement('div');
      body.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:8px 12px;background:var(--surface-1,var(--bg));';
      if (typeof content === 'string') {
        body.innerHTML = `<p class="text-muted text-sm">${_esc(content)}</p>`;
      } else {
        body.appendChild(content);
      }
      sec.appendChild(body);
      detailPanel.appendChild(sec);
    }

    // Request schema
    if (entry.request_schema) {
      _section('Request Body Schema', _renderSchemaTree(entry.request_schema, ''));
    }

    // Response schema
    if (entry.response_schema) {
      _section('Response Schema', _renderSchemaTree(entry.response_schema, ''));
    } else {
      _section('Response Schema', 'Not yet captured.');
    }

    // Headers
    if (entry.headers_schema && Object.keys(entry.headers_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Header</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.headers_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Common Request Headers', t);
    }

    // Query params
    if (entry.params_schema && Object.keys(entry.params_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Param</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.params_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Query Parameters', t);
    }

    // Delete
    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-ghost';
    delBtn.style.color = 'var(--danger, #e53e3e)';
    delBtn.textContent = 'Remove from docs';
    delBtn.onclick = async () => {
      if (!confirm('Remove this endpoint from API documentation?')) return;
      const res = await window.api('DELETE', `/docs/${entry.id}`);
      if (res.ok === false) { alert('Error: ' + res.error); return; }
      detailPanel.innerHTML = '<p class="text-muted text-sm">Endpoint removed.</p>';
      _load();
    };
    detailPanel.appendChild(delBtn);
  }

  async function _load() {
    listPanel.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading…</div>';
    const res = await window.api('GET', '/docs');
    const entries = res.entries || [];
    listPanel.innerHTML = '';

    // Export button at top
    const exportBar = document.createElement('div');
    exportBar.style.cssText = 'padding:8px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:flex-end;';
    const exportBtn = document.createElement('a');
    exportBtn.href = '/api/docs/export/openapi';
    exportBtn.download = 'openapi.yaml';
    exportBtn.className = 'btn btn-xs btn-ghost';
    exportBtn.textContent = '⬇ OpenAPI YAML';
    exportBar.appendChild(exportBtn);
    listPanel.appendChild(exportBar);

    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'padding:12px 14px;';
      empty.textContent = 'No documented endpoints yet. Record APIs with "Include in Documentation" checked.';
      listPanel.appendChild(empty);
      return;
    }

    // Group by resource prefix (first two non-param segments)
    const groups = {};
    for (const e of entries) {
      const segs = e.path_pattern.split('/').filter(Boolean);
      const groupKey = '/' + segs.slice(0, 2).join('/');
      (groups[groupKey] = groups[groupKey] || []).push(e);
    }

    for (const [groupKey, groupEntries] of Object.entries(groups)) {
      const groupEl = document.createElement('div');
      const groupHdr = document.createElement('div');
      groupHdr.style.cssText = 'padding:6px 14px 4px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);font-weight:600;';
      groupHdr.textContent = groupKey;
      groupEl.appendChild(groupHdr);

      for (const entry of groupEntries) {
        const item = document.createElement('div');
        item.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 14px;cursor:pointer;border-radius:0;font-size:12px;';
        item.onmouseenter = () => item.style.background = 'var(--surface-2)';
        item.onmouseleave = () => item.style.background = '';
        const badge = document.createElement('span');
        badge.className = `method-badge ${_methodClass(entry.method)}`;
        badge.style.cssText = 'font-size:10px;padding:1px 5px;flex-shrink:0;';
        badge.textContent = entry.method;
        const path = document.createElement('span');
        path.style.cssText = 'font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
        path.textContent = entry.path_pattern;
        item.appendChild(badge);
        item.appendChild(path);
        item.onclick = () => {
          listPanel.querySelectorAll('[data-selected]').forEach(el => el.removeAttribute('data-selected'));
          item.setAttribute('data-selected', '1');
          item.style.background = 'var(--surface-3, var(--surface-2))';
          _renderDetail(entry);
        };
        groupEl.appendChild(item);
      }
      listPanel.appendChild(groupEl);
    }
  }

  _load();
}
```

- [ ] **Step 2: Verify manually**

After wiring (next task), open the API Docs tab in the browser. Should see:
- Left panel: grouped endpoint list with method badges
- Right panel: "Select an endpoint" placeholder
- Clicking an endpoint shows schemas, headers, params, last seen date
- "⬇ OpenAPI YAML" link downloads the YAML file
- "Remove from docs" removes entry and re-loads list

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/docs-view.js
git commit -m "feat: add API Docs view with endpoint list, schema detail, and OpenAPI export"
```

---

## Task 12: Wire API Docs Tab into `api-section.js`

**Files:**
- Modify: `web/static/api/api-section.js`

**Interfaces:**
- Consumes: `renderDocsView` from `./views/docs-view.js`
- Produces: top-level tab bar in API section — "Collections" tab and "API Docs" tab

- [ ] **Step 1: Replace `renderApiPage` in `web/static/api/api-section.js`**

```javascript
/**
 * API Section entry point.
 * Exposes window.__qaclanApi = { render(container), refresh() }
 */

if (!window.api) {
  window.api = async function api(method, path, body = null) {
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const res = await fetch('/api' + path, opts);
      const data = await res.json();
      return data;
    } catch (e) {
      return { ok: false, error: e.message };
    }
  };
}

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

let _views = null;
async function _getViews() {
  if (!_views) _views = await _loadViews();
  return _views;
}

function renderApiPage(container) {
  container.innerHTML = '';

  // Top tab bar: Collections | API Docs
  const topBar = document.createElement('div');
  topBar.style.cssText = 'display:flex;align-items:center;gap:0;border-bottom:1px solid var(--border);padding:0 14px;background:var(--surface-1,var(--bg));flex-shrink:0;';

  const tabCollections = document.createElement('button');
  tabCollections.type = 'button';
  tabCollections.className = 'req-tab active';
  tabCollections.textContent = 'Collections';

  const tabDocs = document.createElement('button');
  tabDocs.type = 'button';
  tabDocs.className = 'req-tab';
  tabDocs.textContent = 'API Docs';

  topBar.appendChild(tabCollections);
  topBar.appendChild(tabDocs);

  const pageWrap = document.createElement('div');
  pageWrap.style.cssText = 'display:flex;flex-direction:column;height:100%;overflow:hidden;';
  pageWrap.appendChild(topBar);

  // Collections panel (api-layout with sidebar + main)
  const collectionsPanel = document.createElement('div');
  collectionsPanel.style.cssText = 'flex:1;overflow:hidden;display:flex;';
  collectionsPanel.innerHTML = `
    <div class="api-layout" style="flex:1;overflow:hidden;">
      <div class="api-sidebar">
        <div class="api-sidebar-header">
          <span class="api-sidebar-title">Collections</span>
          <button class="btn btn-xs btn-primary" id="api-discover-btn">+ Discover</button>
        </div>
        <div id="api-collections-panel"></div>
      </div>
      <div class="api-main" id="api-main-content">
        <div class="empty-state"><p>Select a request or collection to get started.</p></div>
      </div>
    </div>`;

  // Docs panel
  const docsPanel = document.createElement('div');
  docsPanel.style.cssText = 'flex:1;overflow:hidden;display:none;';

  pageWrap.appendChild(collectionsPanel);
  pageWrap.appendChild(docsPanel);
  container.appendChild(pageWrap);

  function _switchTab(tab) {
    if (tab === 'collections') {
      tabCollections.classList.add('active');
      tabDocs.classList.remove('active');
      collectionsPanel.style.display = 'flex';
      docsPanel.style.display = 'none';
    } else {
      tabDocs.classList.add('active');
      tabCollections.classList.remove('active');
      collectionsPanel.style.display = 'none';
      docsPanel.style.display = 'flex';
      // Re-render docs each time tab is opened so it picks up new recordings
      _getViews().then(({ renderDocsView }) => renderDocsView(docsPanel));
    }
  }

  tabCollections.onclick = () => _switchTab('collections');
  tabDocs.onclick = () => _switchTab('docs');

  // Wire collections view
  _getViews().then(({ renderCollectionsView, renderRequestEditor, showDiscoverModal }) => {
    renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId, defaultCollectionId) => {
        renderRequestEditor(document.getElementById('api-main-content'), requestId, defaultCollectionId);
      }
    );
    document.getElementById('api-discover-btn').onclick = () => showDiscoverModal();
  }).catch(err => {
    console.error('API section load error:', err);
    document.getElementById('api-main-content').innerHTML =
      `<div class="empty-state"><p style="color:var(--danger)">Failed to load API module: ${err.message}</p></div>`;
  });
}

window.__qaclanApi = { render: renderApiPage };
```

- [ ] **Step 2: Verify full feature**

Start server: `python qaclan.py serve --port 7823`

1. Navigate to API section.
2. Two tabs at top: "Collections" and "API Docs".
3. Record or import a HAR — ensure "Include in API Documentation" is checked.
4. Click "API Docs" tab → see grouped endpoint list.
5. Click an endpoint → see method, path, response schema tree, last seen date.
6. Click "⬇ OpenAPI YAML" → browser downloads `openapi.yaml`.
7. Open `openapi.yaml` in a text editor — verify valid YAML with correct endpoints.
8. Click "Remove from docs" → entry disappears from list.
9. Return to "Collections" tab → works as before.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/api-section.js
git commit -m "feat: wire API Docs tab into API section with Collections/API Docs switcher"
```

---

## Task 13: Edit Doc Entry (Description + Manual Schema Overrides)

**Files:**
- Modify: `web/api/repositories/doc_repo.py`
- Modify: `web/api/routes/docs.py`
- Modify: `web/static/api/views/docs-view.js`

**Interfaces:**
- Consumes: `DocRepo().update(project_id, entry_id, data)` — partial update of editable fields
- Produces: `PUT /api/docs/<entry_id>` → `{ok: true, entry: {...}}`
- Produces: inline edit UI in detail panel for `description` and manual schema field type overrides

**Design note:** `merge_schemas` never downgrades a real type to `"null"`, so manual type corrections survive re-recordings automatically. Editing `response_schema` directly lets users fix fields that were always null during recording.

- [ ] **Step 1: Add `update()` to `DocRepo` in `web/api/repositories/doc_repo.py`**

Add this method inside the `DocRepo` class, after `delete()`:

```python
    def update(self, project_id: str, entry_id: str, data: dict) -> dict | None:
        """Partial update of editable fields: description, request_schema, response_schema,
        headers_schema, params_schema."""
        conn = get_conn()
        s = _serialize(data)
        editable = ('description', 'request_schema', 'response_schema',
                    'headers_schema', 'params_schema')
        updates = {k: s[k] for k in editable if k in s}
        if not updates:
            return self.get(project_id, entry_id)
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE api_doc_entries SET {set_clause} WHERE id = ? AND project_id = ?",
            list(updates.values()) + [entry_id, project_id],
        )
        conn.commit()
        return self.get(project_id, entry_id)
```

- [ ] **Step 2: Add `PUT /api/docs/<entry_id>` route in `web/api/routes/docs.py`**

Add after `get_doc`:

```python
@bp.route("/api/docs/<entry_id>", methods=["PUT"])
def update_doc(entry_id):
    try:
        data = request.get_json(force=True) or {}
        updated = _repo.update(_project_id(), entry_id, data)
        if not updated:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "entry": updated})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_doc")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 3: Add inline edit UI to `_renderDetail` in `web/static/api/views/docs-view.js`**

Replace the `hdr` + `meta` block in `_renderDetail` with this version that includes an editable description and schema field type editing:

```javascript
  function _renderDetail(entry) {
    detailPanel.innerHTML = '';

    // ── Header row ──
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;gap:10px;margin-bottom:12px;';
    const methodBadge = document.createElement('span');
    methodBadge.className = `method-badge ${_methodClass(entry.method)}`;
    methodBadge.style.cssText = 'font-size:13px;padding:3px 10px;';
    methodBadge.textContent = entry.method;
    const pathEl = document.createElement('code');
    pathEl.style.cssText = 'font-size:15px;font-weight:500;word-break:break-all;';
    pathEl.textContent = entry.path_pattern;
    hdr.appendChild(methodBadge);
    hdr.appendChild(pathEl);
    detailPanel.appendChild(hdr);

    // ── Editable description ──
    const descWrap = document.createElement('div');
    descWrap.style.cssText = 'margin-bottom:14px;';
    let _editing = false;
    const descText = document.createElement('p');
    descText.style.cssText = 'font-size:13px;color:var(--text);margin:0;cursor:text;min-height:20px;';
    descText.textContent = entry.description || '';
    descText.title = 'Click to edit description';
    if (!entry.description) {
      descText.style.color = 'var(--text-muted)';
      descText.textContent = 'Click to add description…';
    }

    const descInput = document.createElement('textarea');
    descInput.style.cssText = 'width:100%;font-size:13px;border:1px solid var(--border);border-radius:4px;padding:4px 6px;resize:vertical;min-height:48px;display:none;box-sizing:border-box;background:var(--surface-1,var(--bg));color:var(--text);';
    descInput.value = entry.description || '';

    const descActions = document.createElement('div');
    descActions.style.cssText = 'display:none;gap:6px;margin-top:4px;';
    const saveDescBtn = document.createElement('button');
    saveDescBtn.type = 'button';
    saveDescBtn.className = 'btn btn-xs btn-primary';
    saveDescBtn.textContent = 'Save';
    const cancelDescBtn = document.createElement('button');
    cancelDescBtn.type = 'button';
    cancelDescBtn.className = 'btn btn-xs btn-ghost';
    cancelDescBtn.textContent = 'Cancel';
    descActions.appendChild(saveDescBtn);
    descActions.appendChild(cancelDescBtn);

    function _startEdit() {
      if (_editing) return;
      _editing = true;
      descInput.value = entry.description || '';
      descText.style.display = 'none';
      descInput.style.display = '';
      descActions.style.display = 'flex';
      descInput.focus();
    }
    function _cancelEdit() {
      _editing = false;
      descInput.style.display = 'none';
      descActions.style.display = 'none';
      descText.style.display = '';
    }
    saveDescBtn.onclick = async () => {
      const newDesc = descInput.value.trim();
      const res = await window.api('PUT', `/docs/${entry.id}`, { description: newDesc });
      if (res.ok === false) { alert('Save failed: ' + res.error); return; }
      entry.description = newDesc;
      descText.textContent = newDesc || '';
      if (!newDesc) { descText.style.color = 'var(--text-muted)'; descText.textContent = 'Click to add description…'; }
      else descText.style.color = 'var(--text)';
      _cancelEdit();
    };
    cancelDescBtn.onclick = _cancelEdit;
    descText.onclick = _startEdit;

    descWrap.appendChild(descText);
    descWrap.appendChild(descInput);
    descWrap.appendChild(descActions);
    detailPanel.appendChild(descWrap);

    // ── Meta line ──
    const meta = document.createElement('p');
    meta.style.cssText = 'font-size:11px;color:var(--text-muted);margin-bottom:16px;';
    const seenAt = entry.last_seen_at ? new Date(entry.last_seen_at).toLocaleDateString() : '—';
    meta.textContent = `Last seen: ${seenAt} · Sources: ${(entry.source_request_ids || []).length} recording(s)`;
    detailPanel.appendChild(meta);

    function _section(title, content) {
      const sec = document.createElement('div');
      sec.style.cssText = 'margin-bottom:20px;';
      const h = document.createElement('h4');
      h.style.cssText = 'font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin:0 0 8px;';
      h.textContent = title;
      sec.appendChild(h);
      const body = document.createElement('div');
      body.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:8px 12px;background:var(--surface-1,var(--bg));';
      if (typeof content === 'string') {
        body.innerHTML = `<p class="text-muted text-sm">${_esc(content)}</p>`;
      } else {
        body.appendChild(content);
      }
      sec.appendChild(body);
      detailPanel.appendChild(sec);
    }

    // ── Schema sections with inline type editing ──
    function _renderEditableSchemaTree(schema, path, schemaKey) {
      const ul = document.createElement('ul');
      ul.style.cssText = `list-style:none;margin:0;padding-left:${path ? '14px' : '0'};`;
      if (!schema || typeof schema !== 'object') return ul;
      const isArray = Array.isArray(schema);
      const entries2 = isArray
        ? (schema.length ? [['0', schema[0]]] : [['0', '?']])
        : Object.entries(schema);
      for (const [key, val] of entries2) {
        const li = document.createElement('li');
        li.style.cssText = 'padding:1px 0;';
        const displayKey = isArray ? '[item]' : key;
        const currentPath = path ? `${path}.${key}` : key;
        if (val && typeof val === 'object') {
          const row = document.createElement('div');
          row.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;padding:1px 2px;border-radius:3px;';
          row.onmouseenter = () => row.style.background = 'var(--surface-2)';
          row.onmouseleave = () => row.style.background = '';
          const arrow = document.createElement('span');
          arrow.style.cssText = 'font-size:9px;color:var(--text-muted);width:10px;';
          arrow.textContent = '▶';
          const keySpan = document.createElement('span');
          keySpan.style.cssText = 'font-family:var(--font-mono);font-size:12px;';
          keySpan.textContent = displayKey;
          const typeTag = document.createElement('span');
          typeTag.style.cssText = 'font-size:10px;color:var(--text-muted);background:var(--surface-2);padding:1px 5px;border-radius:3px;';
          typeTag.textContent = Array.isArray(val) ? 'array' : 'object';
          row.appendChild(arrow); row.appendChild(keySpan); row.appendChild(typeTag);
          const children = _renderEditableSchemaTree(val, currentPath, schemaKey);
          children.style.display = 'none';
          row.onclick = () => {
            const open = children.style.display === 'none';
            children.style.display = open ? '' : 'none';
            arrow.textContent = open ? '▼' : '▶';
          };
          li.appendChild(row); li.appendChild(children);
        } else {
          // Leaf: show type with inline dropdown to override
          const isNullType = val === 'null' || val === '?';
          const row = document.createElement('div');
          row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:1px 2px;';
          const dot = document.createElement('span');
          dot.style.cssText = `font-size:9px;width:10px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
          dot.textContent = '●';
          const keySpan = document.createElement('span');
          keySpan.style.cssText = `font-family:var(--font-mono);font-size:12px;color:${isNullType ? 'var(--text-muted)' : 'var(--primary)'};`;
          keySpan.textContent = displayKey;

          // Editable type select (shown on hover)
          const typeSelect = document.createElement('select');
          typeSelect.style.cssText = 'font-size:10px;border:1px solid var(--border);border-radius:3px;background:var(--surface-2);color:var(--text-muted);padding:0 2px;cursor:pointer;';
          ['string','number','boolean','null','array','object'].forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            if (t === val) opt.selected = true;
            typeSelect.appendChild(opt);
          });
          typeSelect.onchange = async () => {
            const newType = typeSelect.value;
            // Deep-set the type in a copy of the schema
            const updatedSchema = JSON.parse(JSON.stringify(entry[schemaKey] || {}));
            const pathParts = currentPath.split('.');
            let node = updatedSchema;
            for (let i = 0; i < pathParts.length - 1; i++) {
              const p = pathParts[i];
              node = Array.isArray(node) ? node[parseInt(p)] : node[p];
              if (!node) break;
            }
            const lastKey = pathParts[pathParts.length - 1];
            if (Array.isArray(node)) node[parseInt(lastKey)] = newType;
            else if (node) node[lastKey] = newType;
            const res = await window.api('PUT', `/docs/${entry.id}`, { [schemaKey]: updatedSchema });
            if (res.ok === false) { alert('Save failed: ' + res.error); typeSelect.value = val; return; }
            entry[schemaKey] = res.entry[schemaKey];
            dot.style.color = newType === 'null' ? 'var(--text-muted)' : 'var(--primary)';
            keySpan.style.color = newType === 'null' ? 'var(--text-muted)' : 'var(--primary)';
          };

          row.appendChild(dot); row.appendChild(keySpan); row.appendChild(typeSelect);
          li.appendChild(row);
        }
        ul.appendChild(li);
      }
      return ul;
    }

    if (entry.request_schema) {
      _section('Request Body Schema', _renderEditableSchemaTree(entry.request_schema, '', 'request_schema'));
    }
    if (entry.response_schema) {
      _section('Response Schema', _renderEditableSchemaTree(entry.response_schema, '', 'response_schema'));
    } else {
      _section('Response Schema', 'Not yet captured.');
    }

    if (entry.headers_schema && Object.keys(entry.headers_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Header</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.headers_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Common Request Headers', t);
    }

    if (entry.params_schema && Object.keys(entry.params_schema).length) {
      const t = document.createElement('table');
      t.className = 'kv-table';
      t.innerHTML = '<thead><tr><th>Param</th><th>Type</th></tr></thead>';
      const tb = document.createElement('tbody');
      Object.entries(entry.params_schema).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${_esc(k)}</td><td>${_esc(v)}</td>`;
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      _section('Query Parameters', t);
    }

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-ghost';
    delBtn.style.color = 'var(--danger, #e53e3e)';
    delBtn.textContent = 'Remove from docs';
    delBtn.onclick = async () => {
      if (!confirm('Remove this endpoint from API documentation?')) return;
      const res = await window.api('DELETE', `/docs/${entry.id}`);
      if (res.ok === false) { alert('Error: ' + res.error); return; }
      detailPanel.innerHTML = '<p class="text-muted text-sm">Endpoint removed.</p>';
      _load();
    };
    detailPanel.appendChild(delBtn);
  }
```

- [ ] **Step 4: Verify manually**

Start server: `python qaclan.py serve --port 7823`

1. Open API Docs tab, click an endpoint.
2. Click the description area → textarea appears, type a description, click Save → description persists on re-click.
3. Click Cancel → description reverts to previous.
4. In Response Schema, find a field showing `null` type → change dropdown to `string` → saves immediately without Save button, dot turns blue.
5. Re-record the same endpoint → null field stays `string` (merge never downgrades).
6. Export OpenAPI YAML → description appears in `summary` field.

- [ ] **Step 5: Commit**

```bash
git add web/api/repositories/doc_repo.py web/api/routes/docs.py web/static/api/views/docs-view.js
git commit -m "feat: inline edit description and schema field types in API docs detail view"
```

---

## Self-Review

### 1. Spec Coverage

| Requirement | Task |
|---|---|
| Response schema shown as sample in request editor | Task 1 |
| Recording opt-in for docs | Task 8 |
| API docs tab, project-specific | Tasks 10, 12 |
| Docs update with new recordings | Task 7 |
| Deduplication — same endpoint merges | Tasks 3, 4, 6 |
| Same endpoint, new path param → normalized | Task 3 |
| Request + response + headers tracked | Tasks 5, 6 |
| OpenAPI export | Tasks 9, 10 |
| Edit doc entries (description + type overrides) | Task 13 |

### 2. Placeholder Scan

No TBDs found. All code blocks are complete and self-contained.

### 3. Type Consistency

- `normalize_url(url: str) -> str` used in Task 3, consumed in Task 6 ✓
- `merge_schemas(existing, incoming) -> schema` used in Task 4, consumed in Task 6 ✓
- `DocRepo().upsert(project_id, method, path_pattern, data)` defined in Task 5, consumed in Task 6 ✓
- `DocRepo().update(project_id, entry_id, data)` defined in Task 13, consumed in Task 13 (route + UI) ✓
- `sync_doc_entry(project_id, req)` defined in Task 6, consumed in Task 7 ✓
- `export_openapi_yaml(entries, project_name) -> str` defined in Task 9, consumed in Task 10 ✓
- `renderDocsView(container)` defined in Task 11, consumed in Task 12 ✓
- `createResponsePanel(opts)` modified in Task 1, consumed in Task 1 (request-editor-view.js) ✓
