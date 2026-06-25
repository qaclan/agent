# Variable Picker & Collection-Level Environment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users reference variables anywhere a value appears in a request (body, headers, query params, path params) via two entry points: a `{}` picker button and `{{` autocomplete while typing. Two variable sources: **Environment Variables** (static config, named sets) and **Collection Variables** (runtime chain values with optional initial/seed value). Environment is set once per collection; collection vars are defined per collection and seeded into state before each run.

**What we're NOT building (v1):**
- JSON body tree editor — deferred. Raw textarea + `{}` insert at cursor is sufficient.
- `{{VAR}}` in keys — not a real use case.

**Design decisions:**
- `{{VAR_NAME}}` syntax already established — keep everywhere.
- Env owned by **collection**, not per-request. Request editor inherits.
- Collection vars: flat key+initial_value list per collection. `qc.set()` overrides during run; initial_value seeds state before run starts.
- Picker shows both sources in labelled groups: `── Environment ──` and `── Collection Vars ──`.
- Picker API: `createVarPicker({ getVars: async () => [{key, value, group?, is_secret?}] })` — caller merges sources.
- Two entry points: `{}` button (explicit) + `{{` autocomplete (while typing).
- `{{VAR}}` values get blue tint in all input fields.
- Path params (`{param}` segments in URL) stored separately as `path_params`; runner substitutes.
- Use existing `GET /api/envs` + `GET /api/envs/<env_name>` — no new env infrastructure.

**7 tasks. 6 backend files, 3 frontend files, 2 new components, 1 new repo.**

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `cli/db.py` | Modify | Add `env_name` to `api_collections`; `path_params` to `api_requests`; create `collection_vars` table |
| `cli/api_runner.py` | Modify | Substitute `{param}` path segments; accept pre-seeded state (no change needed if RunnerService seeds) |
| `web/api/repositories/collection_repo.py` | Modify | `env_name` in all CRUD |
| `web/api/repositories/request_repo.py` | Modify | `path_params` in serialize/deserialize/CRUD |
| `web/api/repositories/collection_vars_repo.py` | **Create** | CRUD for `collection_vars` table |
| `web/api/routes/collections.py` | Modify | `run` seeds state from collection vars + uses `env_name`; `PATCH` route; `vars` sub-routes |
| `web/api/routes/requests.py` | Modify | `send` inherits env from parent collection; seeds state from collection vars |
| `web/static/api/components/var-picker.js` | **Create** | Floating picker — single `getVars` callback, grouped rendering |
| `web/static/api/components/key-value-table.js` | Modify | `{}` button + `{{` autocomplete; `getVars` option |
| `web/static/api/views/request-editor-view.js` | Modify | Path vars; body `{}` + autocomplete; merged `getAllVars`; 4th param `collectionId` |
| `web/static/api/views/collections-view.js` | Modify | Env selector; collection vars panel; thread IDs to request editor |

---

## Task 1: DB Migration

**File:** `cli/db.py`

**Produces:**
- `env_name TEXT DEFAULT NULL` on `api_collections`
- `path_params TEXT NOT NULL DEFAULT '[]'` on `api_requests`
- New table `collection_vars(id, collection_id, key, initial_value, created_at)`

- [ ] **Step 1:** Add migration function in `cli/db.py` after `_migrate_api_docs`:

```python
def _migrate_var_picker(conn):
    """Add env_name to api_collections, path_params to api_requests, create collection_vars."""
    try:
        conn.execute("ALTER TABLE api_collections ADD COLUMN env_name TEXT DEFAULT NULL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN path_params TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_vars (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            key TEXT NOT NULL,
            initial_value TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(collection_id, key),
            FOREIGN KEY(collection_id) REFERENCES api_collections(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
```

- [ ] **Step 2:** Call in `init_db()` after `_migrate_api_docs(conn)`:

```python
    _migrate_var_picker(conn)
```

- [ ] **Step 3:** Verify:

```bash
python -c "
from cli.db import init_db; init_db()
from cli.db import get_conn; c = get_conn()
cols_col = [r[1] for r in c.execute('PRAGMA table_info(api_collections)').fetchall()]
cols_req = [r[1] for r in c.execute('PRAGMA table_info(api_requests)').fetchall()]
tables = [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'env_name' in cols_col
assert 'path_params' in cols_req
assert 'collection_vars' in tables
print('OK')
"
```

- [ ] **Step 4:** Commit: `git add cli/db.py && git commit -m "feat: add env_name, path_params, collection_vars migration"`

---

## Task 2: Backend

**Files:** `cli/api_runner.py`, `web/api/repositories/collection_repo.py`, `web/api/repositories/request_repo.py`, `web/api/repositories/collection_vars_repo.py`, `web/api/routes/collections.py`, `web/api/routes/requests.py`

### 2a — Runner: path param substitution

- [ ] **Step 1:** In `cli/api_runner.py`, add after the `_VAR_RE` line:

```python
_PATH_PARAM_RE = re.compile(r'\{([^}]+)\}')


def _substitute_path_params(url: str, path_params: list, env_vars: dict, state: dict) -> str:
    """Replace {param} URL segments with values from path_params list.
    Values may contain {{VAR}} references — resolve those first.
    """
    if not path_params or not url:
        return url
    lookup = {
        item['key']: resolve_vars(str(item.get('value', '')), env_vars, state)
        for item in path_params
        if item.get('enabled', True) and item.get('key', '').strip()
    }
    return _PATH_PARAM_RE.sub(lambda m: lookup.get(m.group(1), m.group(0)), url)
```

- [ ] **Step 2:** In `run_api_request`, immediately after `url = resolve_vars(...)`:

```python
        raw_path_params = req.get('path_params', [])
        if isinstance(raw_path_params, str):
            raw_path_params = json.loads(raw_path_params)
        if raw_path_params:
            url = _substitute_path_params(url, raw_path_params, env_vars, state)
```

### 2b — Collection repo: env_name

- [ ] **Step 3:** In `web/api/repositories/collection_repo.py` make these 4 changes:

`list()` SELECT — add `ac.env_name`:
```python
"SELECT ac.id, ac.name, ac.description, ac.env_name, ac.created_at, COUNT(ar.id) AS request_count ..."
```

`get()` SELECT — add `env_name`:
```python
"SELECT id, name, description, env_name, created_at FROM api_collections WHERE id = ? AND project_id = ?"
```

`create()` — add `env_name` param + INSERT + return value:
```python
def create(self, project_id: str, name: str, description: str | None = None, env_name: str | None = None) -> dict:
    ...
    conn.execute(
        "INSERT INTO api_collections (id, project_id, name, description, env_name, created_at) VALUES (?,?,?,?,?,?)",
        (cid, project_id, name, description, env_name, now),
    )
    ...
    return {"id": cid, "name": name, "description": description, "env_name": env_name, "created_at": now, "request_count": 0}
```

`update()` — add `env_name` param + SET:
```python
def update(self, id: str, name: str, description: str | None = None, env_name: str | None = None) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE api_collections SET name = ?, description = ?, env_name = ? WHERE id = ?",
        (name, description, env_name, id),
    )
    conn.commit()
    return cur.rowcount > 0
```

### 2c — Request repo: path_params

- [ ] **Step 4:** In `web/api/repositories/request_repo.py`:

Add to `_DEFAULTS`:
```python
    "path_params": "[]",
```

Add `path_params` to the JSON field lists in `_serialize` and `_deserialize` (same treatment as `headers`/`params`):
```python
    for key in ("headers", "params", "path_params", "assertions"):
```

Add `path_params` to `create()` INSERT — extend column list and values tuple (after `params`):
```python
"INSERT INTO api_requests (id, project_id, feature_id, collection_id, name, method, url, "
"headers, params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, "
"post_script, post_lang, assertions, follow_redirects, timeout_ms, created_at) "
"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
(rid, project_id,
 merged.get("feature_id"), merged.get("collection_id"),
 merged.get("name", "Unnamed"), merged["method"], merged["url"],
 merged["headers"], merged["params"], merged["path_params"],
 merged["body_type"], merged["body"],
 merged["auth_type"], merged["auth_config"],
 merged["pre_script"], merged["pre_lang"],
 merged["post_script"], merged["post_lang"],
 merged["assertions"], merged["follow_redirects"], merged["timeout_ms"],
 now),
```

Add `path_params` to `fields` list in `update()`:
```python
fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
          "auth_type", "auth_config", "pre_script", "pre_lang", "post_script",
          "post_lang", "assertions", "follow_redirects", "timeout_ms",
          "feature_id", "collection_id"]
```

### 2d — CollectionVarsRepo (new file)

- [ ] **Step 5:** Create `web/api/repositories/collection_vars_repo.py`:

```python
from __future__ import annotations

from cli.db import get_conn, generate_id
from datetime import datetime, timezone


class CollectionVarsRepo:

    def list(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, key, initial_value, created_at FROM collection_vars WHERE collection_id = ? ORDER BY key",
            (collection_id,),
        ).fetchall()
        return [{"id": r[0], "key": r[1], "initial_value": r[2], "created_at": r[3]} for r in rows]

    def upsert(self, collection_id: str, key: str, initial_value: str) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ? WHERE collection_id = ? AND key = ?",
                (initial_value, collection_id, key),
            )
            conn.commit()
            return {"id": existing[0], "key": key, "initial_value": initial_value}
        vid = generate_id("cv")
        conn.execute(
            "INSERT INTO collection_vars (id, collection_id, key, initial_value, created_at) VALUES (?,?,?,?,?)",
            (vid, collection_id, key, initial_value, now),
        )
        conn.commit()
        return {"id": vid, "key": key, "initial_value": initial_value, "created_at": now}

    def delete(self, collection_id: str, key: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def as_seed_dict(self, collection_id: str) -> dict[str, str]:
        """Return {key: initial_value} for seeding state before a run."""
        return {v["key"]: v["initial_value"] for v in self.list(collection_id)}
```

### 2e — Collection routes: PATCH, run with seed, vars sub-routes

- [ ] **Step 6:** In `web/api/routes/collections.py`, add imports at top if missing:
```python
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
```

Replace the `run_collection` route — reads `env_name` from collection, seeds state from `collection_vars`:

```python
@bp.route("/api/collections/<collection_id>/run", methods=["POST"])
def run_collection(collection_id):
    try:
        pid = _project_id()
        col = CollectionRepo().get(collection_id, pid)
        if not col:
            return jsonify({"ok": False, "error": "Collection not found"}), 404
        body = request.get_json(force=True) or {}
        env_name = body.get("env_name") or col.get("env_name")
        seed_vars = CollectionVarsRepo().as_seed_dict(collection_id)
        result = RunnerService().run_collection(collection_id, pid, env_name=env_name, seed_vars=seed_vars)
        return jsonify({"ok": True, **result})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("run_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

Add `PATCH /api/collections/<collection_id>` route:

```python
@bp.route("/api/collections/<collection_id>", methods=["PATCH"])
def patch_collection(collection_id):
    try:
        pid = _project_id()
        col = CollectionRepo().get(collection_id, pid)
        if not col:
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        CollectionRepo().update(
            collection_id,
            body.get("name", col["name"]),
            body.get("description", col.get("description")),
            body.get("env_name", col.get("env_name")),
        )
        return jsonify({"ok": True, "collection": CollectionRepo().get(collection_id, pid)})
    except Exception as e:
        logger.exception("patch_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

Add collection vars sub-routes:

```python
@bp.route("/api/collections/<collection_id>/vars", methods=["GET"])
def list_collection_vars(collection_id):
    try:
        pid = _project_id()
        if not CollectionRepo().get(collection_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        vars_ = CollectionVarsRepo().list(collection_id)
        return jsonify({"ok": True, "vars": vars_})
    except Exception as e:
        logger.exception("list_collection_vars")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<collection_id>/vars/<path:key>", methods=["PUT"])
def upsert_collection_var(collection_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(collection_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        result = CollectionVarsRepo().upsert(collection_id, key, body.get("initial_value", ""))
        return jsonify({"ok": True, "var": result})
    except Exception as e:
        logger.exception("upsert_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<collection_id>/vars/<path:key>", methods=["DELETE"])
def delete_collection_var(collection_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(collection_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        CollectionVarsRepo().delete(collection_id, key)
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("delete_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500
```

### 2f — Runner service: accept seed_vars, seed state

- [ ] **Step 7:** Find `RunnerService` (likely `web/api/services/runner_service.py`). Update `run_collection` and `run_request` to accept and apply `seed_vars`.

In `run_collection(collection_id, pid, env_name=None, seed_vars=None)`:
```python
# Before iterating requests, seed state:
state = {}
if seed_vars:
    state['qaclan_vars'] = dict(seed_vars)
# Pass state to run_api_request for each request in the collection
```

In `run_request(request_id, pid, env_name=None)` (standalone send):
```python
# Load collection vars if request belongs to a collection:
req_row = RequestRepo().get(request_id, pid)
seed_vars = {}
if req_row and req_row.get('collection_id'):
    seed_vars = CollectionVarsRepo().as_seed_dict(req_row['collection_id'])
state = {'qaclan_vars': seed_vars} if seed_vars else {}
```

> **Note for implementer:** Check the actual `RunnerService` implementation to see how state is initialized and passed to `run_api_request`. The goal is that `state['qaclan_vars']` is pre-populated from `collection_vars.initial_value` before any request in the run executes. `qc.set()` calls in post-scripts will then override these during the run.

### 2g — Request send route: inherit collection env

- [ ] **Step 8:** In `web/api/routes/requests.py`, update the send route. Add imports if missing:
```python
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
```

```python
@bp.route("/api/api-requests/<request_id>/send", methods=["POST"])
def send_request(request_id):
    try:
        pid = _project_id()
        body = request.get_json(force=True) or {}
        env_name = body.get("env_name")
        req_row = RequestRepo().get(request_id, pid)
        if req_row and req_row.get("collection_id"):
            col = CollectionRepo().get(req_row["collection_id"], pid)
            if col:
                if not env_name:
                    env_name = col.get("env_name")
        result = RunnerService().run_request(request_id, pid, env_name=env_name)
        return jsonify({"ok": True, "result": result})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("send_request")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 9:** Commit:

```bash
git add cli/api_runner.py \
        web/api/repositories/collection_repo.py \
        web/api/repositories/request_repo.py \
        web/api/repositories/collection_vars_repo.py \
        web/api/routes/collections.py \
        web/api/routes/requests.py
git commit -m "feat: path_params runner, collection env+vars propagation, CollectionVarsRepo + routes"
```

---

## Task 3: `var-picker.js` — Shared Popover Component

**File:** `web/static/api/components/var-picker.js`

**Interface:**
```
createVarPicker(opts) → { open(anchorEl, onSelect, initialQuery?), close() }

opts.getVars: async () => [{key, value, is_secret?, group?}]
  group: 'Environment' | 'Collection' | undefined
```

When items have a `group` field, the picker renders section headers between groups. Ungrouped items render flat.

Two call modes:
1. **Button click**: `picker.open(btnEl, onSelect)` — opens at button position
2. **Autocomplete**: `picker.open(inputEl, onSelect, 'partialName')` — pre-filters, opens below input

Vars cached 30s. If already open and called again (autocomplete re-trigger): update filter, don't reposition.

**UX:**
- Floats below anchor (flips above if no room)
- Group headers: `── Environment ──` and `── Collection ──` (only when grouped)
- Search input pre-filled with `initialQuery`
- Keyboard: ↑↓ navigate, Enter select, Escape close
- Click outside closes
- Secrets shown as `••••••••`
- Collection vars show `initial value` preview or `(empty)` if blank

- [ ] **Step 1:** Create `web/static/api/components/var-picker.js`:

```javascript
/**
 * createVarPicker(opts) → { open(anchorEl, onSelect, initialQuery?), close() }
 * opts.getVars: async () => [{key, value, is_secret?, group?}]
 * group: 'Environment' | 'Collection' | undefined — renders section headers when present
 */
export function createVarPicker(opts = {}) {
  const { getVars = async () => [] } = opts;

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:1000;pointer-events:none;';
  overlay.style.display = 'none';
  document.body.appendChild(overlay);

  const pop = document.createElement('div');
  pop.style.cssText = [
    'position:fixed;z-index:1001;pointer-events:all;',
    'background:var(--surface-1,#fff);',
    'border:1px solid var(--border);border-radius:7px;',
    'box-shadow:0 4px 18px rgba(0,0,0,.18);',
    'width:300px;overflow:hidden;',
    'display:flex;flex-direction:column;',
  ].join('');
  document.body.appendChild(pop);
  pop.style.display = 'none';

  document.addEventListener('mousedown', (e) => {
    if (overlay.style.display !== 'none' && !pop.contains(e.target)) _close();
  });

  const searchWrap = document.createElement('div');
  searchWrap.style.cssText = 'padding:7px 10px;border-bottom:1px solid var(--border);';
  const searchInp = document.createElement('input');
  searchInp.type = 'text';
  searchInp.placeholder = 'Filter variables…';
  searchInp.style.cssText = 'width:100%;font-size:12px;border:none;outline:none;background:transparent;color:var(--text);';
  searchWrap.appendChild(searchInp);
  pop.appendChild(searchWrap);

  const list = document.createElement('div');
  list.style.cssText = 'max-height:240px;overflow-y:auto;';
  pop.appendChild(list);

  let _allVars = [];
  let _onSelect = null;
  let _cacheTs = 0;
  let _activeIdx = -1;
  let _itemEls = [];  // flat list of selectable row elements (not headers)

  function _renderList(filter) {
    list.innerHTML = '';
    _activeIdx = -1;
    _itemEls = [];

    const q = (filter || '').trim().toLowerCase();
    const filtered = q ? _allVars.filter(v => v.key.toLowerCase().includes(q)) : _allVars;

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:10px 12px;font-size:12px;color:var(--text-muted);';
      empty.textContent = _allVars.length ? 'No matching variables.' : 'No variables available. Select an environment or add collection variables.';
      list.appendChild(empty);
      return;
    }

    // Detect if any item has a group — enables sectioned rendering
    const hasGroups = filtered.some(v => v.group);

    if (!hasGroups) {
      filtered.forEach(v => _addItemRow(v));
      return;
    }

    // Group items
    const groups = {};
    const groupOrder = [];
    filtered.forEach(v => {
      const g = v.group || 'Other';
      if (!groups[g]) { groups[g] = []; groupOrder.push(g); }
      groups[g].push(v);
    });

    groupOrder.forEach((g, gi) => {
      const hdr = document.createElement('div');
      hdr.style.cssText = [
        'padding:4px 12px 2px;font-size:10px;font-weight:600;',
        'text-transform:uppercase;letter-spacing:.07em;',
        'color:var(--text-muted);',
        gi > 0 ? 'border-top:1px solid var(--border);margin-top:2px;' : '',
      ].join('');
      hdr.textContent = g;
      list.appendChild(hdr);
      groups[g].forEach(v => _addItemRow(v));
    });
  }

  function _addItemRow(v) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;font-size:12px;';
    row.onmouseenter = () => { _clearHighlight(); row.style.background = 'var(--surface-2)'; _activeIdx = _itemEls.indexOf(row); };
    row.onmouseleave = () => { if (_itemEls[_activeIdx] !== row) row.style.background = ''; };
    row.onclick = () => _pick(v.key);

    const keyEl = document.createElement('span');
    keyEl.style.cssText = 'font-family:var(--font-mono);font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    keyEl.textContent = v.key;

    const valEl = document.createElement('span');
    valEl.style.cssText = 'color:var(--text-muted);max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;font-size:11px;';
    const displayVal = v.is_secret ? '••••••••' : (String(v.value || ''));
    valEl.textContent = displayVal || '(empty)';
    if (!displayVal) valEl.style.fontStyle = 'italic';

    row.appendChild(keyEl);
    row.appendChild(valEl);
    list.appendChild(row);
    _itemEls.push(row);
  }

  function _clearHighlight() {
    _itemEls.forEach(r => r.style.background = '');
  }

  function _pick(key) {
    if (_onSelect) _onSelect(`{{${key}}}`);
    _close();
  }

  function _close() {
    overlay.style.display = 'none';
    pop.style.display = 'none';
    searchInp.value = '';
  }

  searchInp.oninput = () => _renderList(searchInp.value);

  searchInp.onkeydown = (e) => {
    if (!_itemEls.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _activeIdx = Math.min(_activeIdx + 1, _itemEls.length - 1);
      _clearHighlight();
      _itemEls[_activeIdx].style.background = 'var(--surface-2)';
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _activeIdx = Math.max(_activeIdx - 1, 0);
      _clearHighlight();
      _itemEls[_activeIdx].style.background = 'var(--surface-2)';
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (_itemEls[_activeIdx]) _itemEls[_activeIdx].click();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      _close();
    }
  };

  function open(anchorEl, onSelect, initialQuery = '') {
    _onSelect = onSelect;
    const isAlreadyOpen = overlay.style.display !== 'none';

    overlay.style.display = '';
    pop.style.display = 'flex';

    if (!isAlreadyOpen) {
      const rect = anchorEl.getBoundingClientRect();
      const popH = 300;
      const below = window.innerHeight - rect.bottom;
      const top = below >= popH || rect.top < popH
        ? rect.bottom + 4
        : rect.top - popH - 4;
      const left = Math.min(rect.left, window.innerWidth - 310);
      pop.style.top = top + 'px';
      pop.style.left = left + 'px';
    }

    searchInp.value = initialQuery;
    _renderList(initialQuery);

    const now = Date.now();
    if (!_allVars.length || now - _cacheTs > 30000) {
      getVars().then(vars => {
        _allVars = vars || [];
        _cacheTs = Date.now();
        _renderList(searchInp.value);
        if (!isAlreadyOpen) searchInp.focus();
      }).catch(() => { _allVars = []; _renderList(''); });
    } else {
      if (!isAlreadyOpen) searchInp.focus();
    }
  }

  return { open, close: _close };
}
```

- [ ] **Step 2:** Verify:
```javascript
import('/static/api/components/var-picker.js').then(m => console.log('ok', Object.keys(m)))
// Expected: ok ['createVarPicker']
```

- [ ] **Step 3:** Commit: `git add web/static/api/components/var-picker.js && git commit -m "feat: var-picker with grouped env+collection var rendering"`

---

## Task 4: Enhance `key-value-table.js`

**File:** `web/static/api/components/key-value-table.js`

**Changes:**
- New options: `varPickerEnabled` (default false) + `getVars` callback (merged source, caller builds it)
- When enabled: `{}` button per value cell + `{{` autocomplete on value input
- `kv-value--var-ref` CSS class when value contains `{{...}}`

**`{{` autocomplete logic:**
1. Find last `{{` before cursor with no closing `}}`
2. Extract partial name → call `picker.open(valInput, onSelect, partial)`
3. `onSelect`: replace from `{{` position to cursor with `{{VAR_NAME}}`
4. No open `{{` → `picker.close()`

- [ ] **Step 1:** Replace entire file content:

```javascript
import { createVarPicker } from './var-picker.js';

/**
 * createKeyValueTable(options) → { el, getRows, setRows }
 * options:
 *   placeholder?: { key, value }
 *   readOnly?: bool
 *   varPickerEnabled?: bool
 *   getVars?: async () => [{key, value, is_secret?, group?}]
 */
export function createKeyValueTable(options = {}) {
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
  } = options;

  const _picker = varPickerEnabled ? createVarPicker({ getVars }) : null;

  const wrapper = document.createElement('div');
  wrapper.className = 'kv-table-wrapper';

  const table = document.createElement('table');
  table.className = 'kv-table';
  table.innerHTML = `<thead><tr>
    <th style="width:32px"></th>
    <th>Key</th>
    <th>Value</th>
    ${varPickerEnabled && !readOnly ? '<th style="width:30px"></th>' : ''}
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
    addBtn.onclick = () => _addRow({});
    wrapper.appendChild(addBtn);
  }

  function _isVarRef(v) { return /\{\{[^}]+\}\}/.test(v || ''); }

  function _applyVarStyle(inp) {
    inp.classList.toggle('kv-value--var-ref', _isVarRef(inp.value));
  }

  function _addRow(data = {}) {
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
    _applyVarStyle(valInput);
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => {
        _applyVarStyle(valInput);
        if (varPickerEnabled) _handleAutocomplete(valInput);
      });
    }

    if (varPickerEnabled && !readOnly) {
      const pickerTd = document.createElement('td');
      const pickerBtn = document.createElement('button');
      pickerBtn.type = 'button';
      pickerBtn.title = 'Insert variable';
      pickerBtn.style.cssText = 'background:none;border:1px solid var(--border);border-radius:4px;padding:1px 5px;cursor:pointer;font-size:10px;color:var(--text-muted);line-height:1.4;';
      pickerBtn.textContent = '{}';
      pickerBtn.onclick = () => {
        _picker.open(pickerBtn, (varToken) => {
          valInput.value = varToken;
          valInput.dispatchEvent(new Event('input'));
        });
      };
      pickerTd.appendChild(pickerBtn);
      tr.appendChild(pickerTd);
    }

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

  function _handleAutocomplete(inp) {
    const val = inp.value;
    const caret = inp.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const openAt = before.lastIndexOf('{{');
    if (openAt !== -1 && !before.slice(openAt).includes('}}')) {
      const partial = before.slice(openAt + 2);
      _picker.open(inp, (varToken) => {
        const after = val.slice(caret);
        inp.value = val.slice(0, openAt) + varToken + after;
        const newPos = openAt + varToken.length;
        inp.setSelectionRange(newPos, newPos);
        inp.dispatchEvent(new Event('input'));
      }, partial);
    } else {
      _picker.close();
    }
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

- [ ] **Step 2:** Add CSS (find stylesheet with `grep -r "kv-table" web/static/ --include="*.css" -l`):

```css
.kv-value--var-ref {
  background: color-mix(in srgb, var(--primary, #5C6BC0) 8%, transparent) !important;
  border-color: var(--primary, #5C6BC0) !important;
  font-family: var(--font-mono);
}
```

- [ ] **Step 3:** Verify existing KV tables (no `varPickerEnabled`) still render unchanged.

- [ ] **Step 4:** Commit: `git add web/static/api/components/key-value-table.js && git commit -m "feat: var picker button and {{ autocomplete in key-value-table; getVars unified interface"`

---

## Task 5: Enhance `request-editor-view.js`

**File:** `web/static/api/views/request-editor-view.js`

**Changes:**
1. Accept `collectionId` as 4th param (renamed from `collectionEnvName`) + `collectionEnvName` as 5th
2. Build merged `getAllVars()` combining env vars (group: 'Environment') + collection vars (group: 'Collection')
3. Enable var picker on `paramsTable` and `headersTable` with `getVars: getAllVars`
4. Add **Path Variables section** in Params tab (above query params)
5. Add `{}` insert button + `{{` autocomplete on body textarea
6. Upgrade form body to use KV table with `getVars: getAllVars`
7. Save `path_params` in `_save()`

> **Signature change note:** The caller (`api-section.js` and `collections-view.js`) must pass `collectionId` and `collectionEnvName` separately. See Task 6 for how they thread through.

### Signature + imports

- [ ] **Step 1:** Add imports at top:

```javascript
import { createVarPicker } from '../components/var-picker.js';
```

- [ ] **Step 2:** Update function signature:

```javascript
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null, collectionId = null, collectionEnvName = null) {
```

### Merged getVars

- [ ] **Step 3:** After `const r = existing || {};`, add:

```javascript
  const _effectiveCollectionId = r.collection_id || collectionId || defaultCollectionId;

  async function getAllVars() {
    const results = [];

    if (collectionEnvName) {
      try {
        const res = await window.api('GET', `/envs/${encodeURIComponent(collectionEnvName)}`);
        // Check web/routes/envs.py get_env_vars() for exact field name
        const envVars = res.vars || res.env_vars || res.variables || [];
        envVars.forEach(v => results.push({
          key: v.key,
          value: v.value,
          is_secret: !!v.is_secret,
          group: 'Environment',
        }));
      } catch(e) { /* no env selected or fetch failed */ }
    }

    if (_effectiveCollectionId) {
      try {
        const res = await window.api('GET', `/collections/${_effectiveCollectionId}/vars`);
        (res.vars || []).forEach(v => results.push({
          key: v.key,
          value: v.initial_value || '',
          is_secret: false,
          group: 'Collection',
        }));
      } catch(e) { /* collection has no vars */ }
    }

    return results;
  }
```

### KV tables: enable var picker

- [ ] **Step 4:** Update `paramsTable` and `headersTable` creation:

```javascript
  const paramsTable = createKeyValueTable({
    placeholder: { key: 'Parameter', value: 'Value' },
    varPickerEnabled: true,
    getVars: getAllVars,
  });
  paramsTable.setRows(r.params || []);

  const headersTable = createKeyValueTable({
    placeholder: { key: 'Header', value: 'Value' },
    varPickerEnabled: true,
    getVars: getAllVars,
  });
  headersTable.setRows(r.headers || []);
```

### Path Variables section

- [ ] **Step 5:** Add AFTER `headersTable` setup, BEFORE `assertionBuilder` creation:

```javascript
  const pathVarsTable = createKeyValueTable({
    placeholder: { key: 'param', value: 'value or {{VAR}}' },
    varPickerEnabled: true,
    getVars: getAllVars,
  });
  const pathVarsSection = document.createElement('div');
  {
    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:8px 0 4px;';
    hdr.textContent = 'Path Variables';
    const hint = document.createElement('p');
    hint.className = 'req-section-hint';
    hint.textContent = 'Values for {param} segments in the URL. Supports {{VAR}} syntax.';
    pathVarsSection.appendChild(hdr);
    pathVarsSection.appendChild(hint);
    pathVarsSection.appendChild(pathVarsTable.el);
  }
  pathVarsSection.style.display = 'none';

  const queryParamsHdr = document.createElement('div');
  queryParamsHdr.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);padding:12px 0 4px;';
  queryParamsHdr.textContent = 'Query Parameters';

  const paramsWrapper = document.createElement('div');
  paramsWrapper.appendChild(pathVarsSection);
  paramsWrapper.appendChild(queryParamsHdr);
  paramsWrapper.appendChild(paramsTable.el);

  const _storedPathParams = r.path_params || [];

  function _syncPathVars() {
    const matches = [...urlInput.value.matchAll(/\{([^}]+)\}/g)].map(m => m[1]);
    const keys = [...new Set(matches)];
    if (!keys.length) { pathVarsSection.style.display = 'none'; return; }
    pathVarsSection.style.display = '';
    const current = {};
    pathVarsTable.getRows().forEach(row => { current[row.key] = row.value; });
    const stored = {};
    _storedPathParams.forEach(p => { stored[p.key] = p.value; });
    pathVarsTable.setRows(keys.map(key => ({
      key,
      value: current[key] ?? stored[key] ?? '',
      enabled: true,
    })));
  }
```

- [ ] **Step 6:** After `urlBar` appended to editor:
```javascript
  urlInput.addEventListener('input', _syncPathVars);
  _syncPathVars();
```

### Body: `{}` button + autocomplete on textarea

- [ ] **Step 7:** Replace body section (find block from `const bodySection = document.createElement('div');` through end of body setup):

```javascript
  const bodySection = document.createElement('div');
  const BODY_TYPES = ['none', 'raw', 'form', 'graphql'];
  let activeBodyType = r.body_type || 'none';

  const bodyTypeGroup = document.createElement('div');
  bodyTypeGroup.className = 'req-body-type-group';
  bodyTypeGroup.style.display = 'flex';
  bodyTypeGroup.style.alignItems = 'center';

  BODY_TYPES.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'req-body-type-btn';
    btn.textContent = t;
    btn.dataset.type = t;
    btn.onclick = () => _setBodyType(t);
    bodyTypeGroup.appendChild(btn);
  });

  const _bodyVarPicker = createVarPicker({ getVars: getAllVars });
  const bodyVarBtn = document.createElement('button');
  bodyVarBtn.type = 'button';
  bodyVarBtn.title = 'Insert variable at cursor';
  bodyVarBtn.style.cssText = 'margin-left:auto;font-size:11px;padding:3px 8px;border:1px solid var(--border);border-radius:4px;background:none;cursor:pointer;color:var(--text-muted);';
  bodyVarBtn.textContent = '{ }';
  bodyVarBtn.style.display = 'none';
  bodyVarBtn.onclick = () => {
    _bodyVarPicker.open(bodyVarBtn, (varToken) => {
      const start = bodyTextarea.selectionStart;
      const end = bodyTextarea.selectionEnd;
      bodyTextarea.value = bodyTextarea.value.slice(0, start) + varToken + bodyTextarea.value.slice(end);
      const newPos = start + varToken.length;
      bodyTextarea.setSelectionRange(newPos, newPos);
      bodyTextarea.focus();
    });
  };
  bodyTypeGroup.appendChild(bodyVarBtn);

  const bodyTextarea = document.createElement('textarea');
  bodyTextarea.className = 'input-sm';
  bodyTextarea.style.cssText = 'width:100%;min-height:140px;font-family:var(--font-mono);font-size:12px;margin-top:4px;';
  bodyTextarea.value = r.body || '';
  bodyTextarea.addEventListener('input', () => {
    const val = bodyTextarea.value;
    const caret = bodyTextarea.selectionStart ?? val.length;
    const before = val.slice(0, caret);
    const openAt = before.lastIndexOf('{{');
    if (openAt !== -1 && !before.slice(openAt).includes('}}')) {
      const partial = before.slice(openAt + 2);
      _bodyVarPicker.open(bodyTextarea, (varToken) => {
        const after = val.slice(caret);
        bodyTextarea.value = val.slice(0, openAt) + varToken + after;
        const newPos = openAt + varToken.length;
        bodyTextarea.setSelectionRange(newPos, newPos);
        bodyTextarea.focus();
      }, partial);
    } else {
      _bodyVarPicker.close();
    }
  });

  let _formBodyRows = [];
  try {
    const parsed = JSON.parse(r.body || '[]');
    _formBodyRows = Array.isArray(parsed) ? parsed : [];
  } catch(e) { _formBodyRows = []; }
  const formBodyTable = createKeyValueTable({
    placeholder: { key: 'field', value: 'value' },
    varPickerEnabled: true,
    getVars: getAllVars,
  });
  formBodyTable.setRows(_formBodyRows);
  formBodyTable.el.style.display = 'none';

  function _setBodyType(type) {
    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
    bodyTextarea.style.display = (type === 'raw' || type === 'graphql') ? '' : 'none';
    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    bodyVarBtn.style.display = (type === 'raw' || type === 'graphql') ? '' : 'none';
    if (type === 'none') bodyTextarea.style.display = 'none';
    bodyTextarea.placeholder = type === 'graphql'
      ? '{ "query": "{ users { id name } }" }'
      : '{\n  "key": "value"\n}';
  }

  bodySection.appendChild(bodyTypeGroup);
  bodySection.appendChild(bodyTextarea);
  bodySection.appendChild(formBodyTable.el);
  _setBodyType(activeBodyType);
```

### sectionMap + _save

- [ ] **Step 8:** Update `sectionMap` — replace `paramsTable.el` with `paramsWrapper`:
```javascript
  const sectionMap = {
    'Params':   paramsWrapper,
    'Headers':  headersTable.el,
    'Body':     bodySection,
    // ... rest unchanged
  };
```

- [ ] **Step 9:** In `_save()` payload, add `path_params` and update body:
```javascript
      path_params: pathVarsTable.getRows(),
      body_type: activeBodyType === 'none' ? null : activeBodyType,
      body: activeBodyType === 'form'
            ? JSON.stringify(formBodyTable.getRows())
            : (activeBodyType === 'none' ? null : bodyTextarea.value),
```

- [ ] **Step 10:** Commit:
```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: path vars, body var picker, merged env+collection vars in request editor"
```

---

## Task 6: Enhance `collections-view.js` — Env Selector + Collection Vars Panel

**File:** `web/static/api/views/collections-view.js`

**Changes:**
1. Load env list at reload start
2. Add compact env `<select>` to each collection header
3. PATCH collection on env change
4. Add "Vars" toggle button per collection → inline panel with key+initial_value table
5. Pass both `col.id` (as collectionId) and `col.env_name` to `onSelectRequest`

### Env name loading

- [ ] **Step 1:** Before `reload()`, add:

```javascript
  let _envNames = [];

  async function _loadEnvNames() {
    try {
      const res = await window.api('GET', '/envs');
      // Check web/routes/envs.py list_envs() for exact field
      const envs = res.environments || res.envs || [];
      _envNames = envs.map(e => (typeof e === 'string' ? e : (e.name || '')));
    } catch(e) { _envNames = []; }
  }
```

- [ ] **Step 2:** Make `reload()` async and await env load at start:
```javascript
  async function reload() {
    await _loadEnvNames();
    const res = await window.api('GET', '/collections');
    // ... rest unchanged
```

### Per-collection: env selector + vars panel

- [ ] **Step 3:** Inside `collections.forEach(col => { ... })`, after `leftSide` creation and before `runBtn`:

```javascript
      // Env selector
      const envSel = document.createElement('select');
      envSel.title = 'Environment';
      envSel.style.cssText = 'font-size:11px;padding:2px 4px;border:1px solid var(--border);border-radius:4px;background:var(--surface-1);color:var(--text-muted);max-width:90px;';
      envSel.innerHTML = '<option value="">No env</option>';
      _envNames.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        if (name === col.env_name) opt.selected = true;
        envSel.appendChild(opt);
      });
      envSel.addEventListener('change', async (e) => {
        e.stopPropagation();
        col.env_name = envSel.value || null;
        await window.api('PATCH', `/collections/${col.id}`, { env_name: col.env_name });
      });
      rightSide.insertBefore(envSel, runBtn);

      // Vars toggle button
      const varsBtn = document.createElement('button');
      varsBtn.className = 'btn btn-xs btn-ghost';
      varsBtn.textContent = 'Vars';
      varsBtn.title = 'Collection variables (used with qc.set / {{VAR}})';
      let varsExpanded = false;
      rightSide.insertBefore(varsBtn, runBtn);
```

- [ ] **Step 4:** After `section.appendChild(header)` and before `section.appendChild(reqList)`, add the vars panel:

```javascript
      // ── Collection Vars Panel ──
      const varsPanel = document.createElement('div');
      varsPanel.style.cssText = 'display:none;padding:8px 14px 6px;border-bottom:1px solid var(--border);background:var(--surface-0,inherit);';

      const varsPanelHdr = document.createElement('div');
      varsPanelHdr.style.cssText = 'font-size:10px;color:var(--text-muted);margin-bottom:6px;';
      varsPanelHdr.textContent = 'Define initial values for {{VAR}} tokens set by post-scripts (qc.set). Values are seeded before each run.';
      varsPanel.appendChild(varsPanelHdr);

      const varsTable = document.createElement('table');
      varsTable.style.cssText = 'width:100%;font-size:11px;border-collapse:collapse;';
      varsTable.innerHTML = '<thead><tr><th style="text-align:left;padding:0 4px 3px;color:var(--text-muted)">Variable</th><th style="text-align:left;padding:0 4px 3px;color:var(--text-muted)">Initial value</th><th style="width:24px"></th></tr></thead>';
      const varsTbody = document.createElement('tbody');
      varsTable.appendChild(varsTbody);
      varsPanel.appendChild(varsTable);

      const addVarBtn = document.createElement('button');
      addVarBtn.type = 'button';
      addVarBtn.className = 'btn btn-xs btn-ghost';
      addVarBtn.style.marginTop = '4px';
      addVarBtn.textContent = '+ Add Variable';
      varsPanel.appendChild(addVarBtn);

      let _colVars = [];

      function _renderVarsTable() {
        varsTbody.innerHTML = '';
        _colVars.forEach(v => _addVarRow(v));
      }

      function _addVarRow(v = { key: '', initial_value: '' }) {
        const tr = document.createElement('tr');

        const keyTd = document.createElement('td');
        keyTd.style.padding = '2px 4px';
        const keyInp = document.createElement('input');
        keyInp.type = 'text';
        keyInp.placeholder = 'var_name';
        keyInp.value = v.key || '';
        keyInp.style.cssText = 'font-family:var(--font-mono);font-size:11px;width:100%;';
        keyInp.className = 'input-sm';
        keyTd.appendChild(keyInp);

        const valTd = document.createElement('td');
        valTd.style.padding = '2px 4px';
        const valInp = document.createElement('input');
        valInp.type = 'text';
        valInp.placeholder = '(empty — set by post-script)';
        valInp.value = v.initial_value || '';
        valInp.style.cssText = 'font-size:11px;width:100%;';
        valInp.className = 'input-sm';
        valTd.appendChild(valInp);

        const delTd = document.createElement('td');
        delTd.style.padding = '2px 0';
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
        delBtn.textContent = '×';
        delTd.appendChild(delBtn);

        async function _saveRow() {
          const key = keyInp.value.trim();
          if (!key) return;
          await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, {
            initial_value: valInp.value,
          });
        }

        async function _deleteRow() {
          const key = keyInp.value.trim();
          if (key) {
            await window.api('DELETE', `/collections/${col.id}/vars/${encodeURIComponent(key)}`);
          }
          tr.remove();
        }

        keyInp.addEventListener('blur', _saveRow);
        valInp.addEventListener('blur', _saveRow);
        delBtn.onclick = _deleteRow;

        tr.appendChild(keyTd);
        tr.appendChild(valTd);
        tr.appendChild(delTd);
        varsTbody.appendChild(tr);
      }

      addVarBtn.onclick = (e) => { e.stopPropagation(); _addVarRow(); };

      async function _toggleVarsPanel() {
        varsExpanded = !varsExpanded;
        varsPanel.style.display = varsExpanded ? '' : 'none';
        varsBtn.classList.toggle('active', varsExpanded);
        if (varsExpanded && !_colVars.length) {
          const res = await window.api('GET', `/collections/${col.id}/vars`);
          _colVars = res.vars || [];
          _renderVarsTable();
        }
      }

      varsBtn.onclick = (e) => { e.stopPropagation(); _toggleVarsPanel(); };
      section.appendChild(varsPanel);
```

- [ ] **Step 5:** Update `runBtn.onclick`:
```javascript
      runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name, col.env_name); };
```

- [ ] **Step 6:** Update `header.onclick` to also skip `varsBtn`:
```javascript
      header.onclick = (e) => {
        if (e.target === runBtn || e.target === expandBtn || e.target === varsBtn || e.target === envSel) return;
        _toggleExpand();
      };
```

- [ ] **Step 7:** Update `onSelectRequest` calls — pass `col.id` as 3rd arg, `col.env_name` as 4th:
```javascript
          item.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            onSelectRequest(req.id, null, col.id, col.env_name);
          };
```
```javascript
          newReqBtn.onclick = () => {
            container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
            newReqBtn.classList.add('active');
            onSelectRequest(null, col.id, col.id, col.env_name);
          };
```

- [ ] **Step 8:** Update `_runCollection`:
```javascript
  async function _runCollection(colId, colName, envName) {
    const confirmed = await window._confirmDialog(`Run '${colName}'?`, 'All requests will execute in order.', 'Run');
    if (!confirmed) return;
    const res = await window.api('POST', `/collections/${colId}/run`, { env_name: envName || null });
    if (res.ok === false) {
      await window._alertDialog('Run failed: ' + res.error);
    } else {
      window._toast(`Run complete: ${res.passed}/${res.total} passed`);
    }
  }
```

- [ ] **Step 9:** In `web/static/api/api-section.js`, thread all args to `renderRequestEditor`:
```javascript
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

- [ ] **Step 10:** Commit:
```bash
git add web/static/api/views/collections-view.js web/static/api/api-section.js
git commit -m "feat: collection vars panel, env selector, wire IDs through to request editor"
```

---

## Task 7: End-to-End Verification

- [ ] Start server: `python qaclan.py serve --port 7823`

**DB:**
- [ ] `collection_vars` table exists, FOREIGN KEY to `api_collections` ON DELETE CASCADE

**Collection vars panel:**
- [ ] "Vars" button appears per collection → click expands panel
- [ ] Add variable row `auth_token` with empty initial value → blur saves (PUT fires)
- [ ] Add `user_id` with value `123` → blur saves
- [ ] Delete row → DELETE fires, row gone
- [ ] Close and re-open panel → rows persist

**Env selector:**
- [ ] Env `<select>` visible in each collection header
- [ ] Change env → PATCH fires, persists on reload
- [ ] Vars panel and env selector both visible without layout clash

**Picker — environment vars:**
- [ ] Click request in collection with env set → editor opens
- [ ] Headers tab: `{}` button → picker shows `── Environment ──` group with env vars
- [ ] Select a var → `{{KEY}}` inserted, input shows blue tint

**Picker — collection vars:**
- [ ] With `auth_token` defined as collection var: `{}` button → picker shows `── Collection ──` group with `auth_token (empty)`
- [ ] `user_id` with initial value `123` → picker shows `user_id  123`
- [ ] Select collection var → `{{auth_token}}` inserted

**Autocomplete:**
- [ ] Type `{{` in header value → picker opens, pre-filtered
- [ ] Type `{{au` → shows only `auth_token`
- [ ] Enter selects → replaces `{{au` with `{{auth_token}}`
- [ ] Type `{{` in body textarea → same behavior

**Path vars:**
- [ ] URL with `/users/{id}` → Path Variables section appears with `id` row
- [ ] Set `id` value to `{{user_id}}` → blue tint, `{}` button works

**Runner:**
- [ ] Collection with `user_id = 123` in vars + env set → run collection → state pre-seeded with `user_id: "123"` → `{{user_id}}` in requests resolves to `123`
- [ ] Post-script `qc.set('auth_token', res.token)` in request 1 → `{{auth_token}}` in request 2 resolves to the set value (overrides empty initial)

---

## Global Constraints

- Check `web/routes/envs.py` `get_env_vars()` response shape — confirm field name for vars array before using in `getAllVars()`
- Check `web/routes/envs.py` `list_envs()` response shape — confirm field for env list
- Check `RunnerService` to find where state is initialized before requests run — seed `state['qaclan_vars']` from `seed_vars` there
- `PATCH /api/collections/<id>` is new — confirm Blueprint registration in `web/server.py`
- `createVarPicker` uses `getVars` (not `getEnvVars`) — all call sites must pass `getVars`
- All existing KV tables without `varPickerEnabled` are unaffected
- `collection_vars` ON DELETE CASCADE handles cleanup when collection deleted — no manual cleanup needed
