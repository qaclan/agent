# Nested Folders + Drag-and-Drop Reordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a collection contain an unlimited-depth tree of folders holding requests, and let the user drag-and-drop collections/folders/requests to reorder siblings or move them into a different folder within the same collection.

**Architecture:** New `api_folders` table (self-referencing `parent_folder_id`) plus `order_index`/`folder_id` columns on the existing `api_requests`/`api_collections` tables. Backend follows the existing 3-layer pattern (`web/api/routes` → `services` → `repositories`). Frontend rewrites `collections-view.js` to fetch one flat `{folders, requests}` tree per collection and render it recursively, reusing the native-HTML5-DnD pattern already proven for suite-script reordering (`app.js:3838-3880`, `PUT /api/suites/<id>/order`) — no new dependency.

**Tech Stack:** Flask (routes/services/repos, existing 3-layer pattern), raw `sqlite3` via `cli/db.py`, vanilla JS ES modules (no build step, no framework).

**Spec:** `docs/superpowers/specs/2026-07-11-nested-folders-drag-drop-design.md`

## Global Constraints

- No automated test framework exists in this repo — every task's verification step uses `python3 -c` inline assertions (backend) or `node --check` + a manual browser checklist (frontend), matching this repo's established convention (see `docs/superpowers/plans/2026-07-10-api-variant-library-plan.md`).
- Python targets 3.10+ typing style (`str | None`, `list[dict]`) — every new/modified Python file starts with `from __future__ import annotations`.
- Follow the existing 3-layer backend pattern: routes parse request/response and handle errors (`{"ok": false, "error": ...}` + status code), services hold business rules, repos own SQL. Routes never touch a repo directly.
- New SQL changes are one new `_migrate_xxx(conn)` function in `cli/db.py`, appended to the end of the call chain inside `init_db()` — never reorder or remove existing `_migrate_*` calls.
- Reuse `generate_id(prefix)` from `cli.db` for every new row ID. Prefix for the new table is `"apifold"`.
- All new Python modules: `logger = logging.getLogger("qaclan.<module_name>")`.
- Frontend files are loaded directly as ES modules (no bundler). Verify syntax with `node --check <file>`; DOM-touching logic is verified by manually running the app (`python qaclan.py serve --port 7823`) and clicking through the flow.
- `window.api()` never throws — it returns `{ok: false, error}` on failure. Always check `res.ok === false`.
- Error surfacing in `collections-view.js` always uses `await window._alertDialog('Error: ' + res.error)` on failure — this file never uses `window._toast` for errors (confirmed: every existing error path in this file uses `_alertDialog`). Match this exactly; do not introduce `_toast` for errors.
- No new task changes `web/routes/suites.py`, `cli/api_discovery/*`, `web/api/services/discovery_service.py`, `web/api/services/runner_service.py`, or any Postman/Bruno/HAR import/export code — those are out of scope per the spec and are covered only by the regression check in the final task.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `cli/db.py` | Modify | New `_migrate_nested_folders` migration |
| `web/api/repositories/folder_repo.py` | Create | `FolderRepo` — CRUD + scoped order writes for `api_folders` |
| `web/api/services/folder_service.py` | Create | `FolderService` — validation (name, same-collection parent, cycle guard), tree assembly, reorder orchestration |
| `web/api/routes/folders.py` | Create | `GET .../tree`, `POST .../folders`, `PATCH/DELETE /api-folders/<id>`, `PUT .../tree-order` |
| `web/api/repositories/collection_repo.py` | Modify | Add `set_order`; order-aware `list()` |
| `web/api/services/collection_service.py` | Modify | Add `reorder()` |
| `web/api/routes/collections.py` | Modify | Add `PUT /api/collections/order` |
| `web/api/repositories/request_repo.py` | Modify | Add `folder_id`/`order_index` columns, `set_order`, order-aware `list()` |
| `web/api/services/request_service.py` | Modify | Validate `folder_id` belongs to the request's collection on create/update |
| `web/server.py` | Modify | Register the new `folders` blueprint |
| `web/static/api/views/collections-view.js` | Modify (full rewrite) | Recursive folder tree render, folder CRUD, drag-and-drop (reorder + reparent), collection-level drag reorder |
| `web/static/api/views/request-editor-view.js` | Modify | Accept and submit a target `folder_id` when creating a request |
| `web/static/api/api-section.js` | Modify | Thread the new `defaultFolderId` argument from the sidebar into the request editor |
| `web/static/style.css` | Modify | Folder-row, drag-handle, and drop-target styles |
| `cli/api_discovery/folder_suggester.py` | Create | `suggest_folder_name(url)` — one-level folder-name heuristic, reuses `url_normalizer` |
| `web/api/services/discovery_service.py` | Modify | `organize_into_folders` param on `_save_requests`/`save_library`, shared `folder_cache` |
| `web/api/routes/discovery.py` | Modify | Thread `organize_into_folders` through `save_requests`/`save_library_route` |
| `web/static/api/views/request-review-modal.js` | Modify | "Organize into folders by endpoint" checkbox, checked by default |
| `web/static/api/views/variant-comparison-modal.js` | Modify | Forward `organizeIntoFolders` into its own `/discover/save-library` call |

---

## Task 1: DB schema — `api_folders` table and ordering columns

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: table `api_folders(id, project_id, collection_id, parent_folder_id, name, order_index, created_at)`; `api_requests.folder_id`, `api_requests.order_index`; `api_collections.order_index` — every later task depends on this exact shape.

- [ ] **Step 1: Add the migration function**

Add to `cli/db.py`, directly after the `_migrate_api_request_examples` function body (its closing `conn.commit()` at line 189), before `def _migrate_var_picker`:

```python
def _migrate_nested_folders(conn):
    """Create api_folders (unlimited-depth folder tree inside a collection) and add
    folder_id/order_index to api_requests, order_index to api_collections.
    See docs/superpowers/specs/2026-07-11-nested-folders-drag-drop-design.md."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_folders (
            id               TEXT PRIMARY KEY,
            project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            collection_id    TEXT NOT NULL REFERENCES api_collections(id) ON DELETE CASCADE,
            parent_folder_id TEXT REFERENCES api_folders(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            order_index      INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT NOT NULL
        )
    """)
    try:
        conn.execute(
            "ALTER TABLE api_requests ADD COLUMN folder_id TEXT REFERENCES api_folders(id) ON DELETE CASCADE"
        )
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE api_requests ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE api_collections ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists
    conn.commit()
```

- [ ] **Step 2: Wire it into the migration chain**

In `cli/db.py`, change the end of `init_db()` from:

```python
    _migrate_collection_run_progress(conn)
    _migrate_api_request_examples(conn)
```

to:

```python
    _migrate_collection_run_progress(conn)
    _migrate_api_request_examples(conn)
    _migrate_nested_folders(conn)
```

- [ ] **Step 3: Verify manually**

```bash
python3 -c "
from cli.db import get_conn, init_db
init_db()
conn = get_conn()
cols = {r['name'] for r in conn.execute(\"PRAGMA table_info('api_folders')\").fetchall()}
assert cols == {'id','project_id','collection_id','parent_folder_id','name','order_index','created_at'}, cols
req_cols = {r['name'] for r in conn.execute(\"PRAGMA table_info('api_requests')\").fetchall()}
assert 'folder_id' in req_cols and 'order_index' in req_cols, req_cols
col_cols = {r['name'] for r in conn.execute(\"PRAGMA table_info('api_collections')\").fetchall()}
assert 'order_index' in col_cols, col_cols
print('PASS: nested-folder schema in place')
"
```

Expected output: `PASS: nested-folder schema in place`

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat(db): add api_folders table and ordering columns for nested folders"
```

---

## Task 2: `FolderRepo`

**Files:**
- Create: `web/api/repositories/folder_repo.py`

**Interfaces:**
- Consumes: `api_folders` table (Task 1).
- Produces: `FolderRepo` with `list_for_collection(collection_id) -> list[dict]`, `get(id, project_id) -> dict|None`, `create(project_id, collection_id, name, parent_folder_id=None) -> dict`, `get_or_create_root(project_id, collection_id, name) -> dict`, `update(id, data: dict) -> bool` (fields: `name`, `parent_folder_id`), `set_order(id, collection_id, parent_folder_id, order_index) -> bool`, `delete(id) -> bool` — consumed by Task 3 (`FolderService`) and Task 11 (discovery folder suggestion, which uses `get_or_create_root` specifically).

- [ ] **Step 1: Write the repo**

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.folder_repo")


class FolderRepo:
    def list_for_collection(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_folders WHERE collection_id = ? ORDER BY order_index, created_at",
            (collection_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, id: str, project_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_folders WHERE id = ? AND project_id = ?",
            (id, project_id),
        ).fetchone()
        return dict(row) if row else None

    def create(self, project_id: str, collection_id: str, name: str,
               parent_folder_id: str | None = None) -> dict:
        conn = get_conn()
        fid = generate_id("apifold")
        now = datetime.now(timezone.utc).isoformat()
        if parent_folder_id:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM api_folders "
                "WHERE collection_id = ? AND parent_folder_id = ?",
                (collection_id, parent_folder_id),
            ).fetchone()[0]
        else:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM api_folders "
                "WHERE collection_id = ? AND parent_folder_id IS NULL",
                (collection_id,),
            ).fetchone()[0]
        conn.execute(
            "INSERT INTO api_folders (id, project_id, collection_id, parent_folder_id, name, order_index, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fid, project_id, collection_id, parent_folder_id, name, max_order + 1, now),
        )
        conn.commit()
        logger.info("FolderRepo.create: %s (%s)", name, fid)
        return self.get(fid, project_id)

    def get_or_create_root(self, project_id: str, collection_id: str, name: str) -> dict:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM api_folders WHERE collection_id = ? AND parent_folder_id IS NULL AND name = ?",
            (collection_id, name),
        ).fetchone()
        if row:
            return dict(row)
        return self.create(project_id, collection_id, name)

    def update(self, id: str, data: dict) -> bool:
        conn = get_conn()
        fields = ["name", "parent_folder_id"]
        updates = {f: data[f] for f in fields if f in data}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [id]
        cur = conn.execute(f"UPDATE api_folders SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cur.rowcount > 0

    def set_order(self, id: str, collection_id: str, parent_folder_id: str | None, order_index: int) -> bool:
        conn = get_conn()
        if parent_folder_id:
            cur = conn.execute(
                "UPDATE api_folders SET order_index = ? WHERE id = ? AND collection_id = ? AND parent_folder_id = ?",
                (order_index, id, collection_id, parent_folder_id),
            )
        else:
            cur = conn.execute(
                "UPDATE api_folders SET order_index = ? WHERE id = ? AND collection_id = ? AND parent_folder_id IS NULL",
                (order_index, id, collection_id),
            )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, id: str) -> bool:
        conn = get_conn()
        cur = conn.execute("DELETE FROM api_folders WHERE id = ?", (id,))
        conn.commit()
        return cur.rowcount > 0
```

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
from web.api.repositories.folder_repo import FolderRepo

init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
cid = generate_id('apicol')
conn.execute('INSERT INTO api_collections (id, project_id, name, created_at) VALUES (?, ?, ?, ?)', (cid, pid, 'Col', datetime.now(timezone.utc).isoformat()))
conn.commit()

repo = FolderRepo()
root = repo.create(pid, cid, 'Auth')
assert root['parent_folder_id'] is None
assert root['order_index'] == 0
child = repo.create(pid, cid, 'Login', parent_folder_id=root['id'])
assert child['parent_folder_id'] == root['id']
assert child['order_index'] == 0

second_root = repo.create(pid, cid, 'Users')
assert second_root['order_index'] == 1, second_root['order_index']

# get_or_create_root: first call creates, second call with the same name reuses it
first_call = repo.get_or_create_root(pid, cid, 'Orders')
second_call = repo.get_or_create_root(pid, cid, 'Orders')
assert first_call['id'] == second_call['id'], (first_call, second_call)
assert len([f for f in repo.list_for_collection(cid) if f['name'] == 'Orders']) == 1

assert repo.update(root['id'], {'name': 'Auth Flows'})
assert repo.get(root['id'], pid)['name'] == 'Auth Flows'

assert repo.set_order(second_root['id'], cid, None, 0)
assert repo.get(second_root['id'], pid)['order_index'] == 0

listed = repo.list_for_collection(cid)
assert len(listed) == 4, listed  # Auth, Login, Users, Orders

assert repo.delete(child['id'])
assert repo.get(child['id'], pid) is None
print('PASS: FolderRepo CRUD + ordering round-trip')
"
```

Expected output: `PASS: FolderRepo CRUD + ordering round-trip`

- [ ] **Step 3: Commit**

```bash
git add web/api/repositories/folder_repo.py
git commit -m "feat(api): add FolderRepo for nested api_folders CRUD"
```

---

## Task 3: `FolderService`

**Files:**
- Create: `web/api/services/folder_service.py`

**Interfaces:**
- Consumes: `FolderRepo` (Task 2), `CollectionRepo` (existing), `RequestRepo` (existing, extended in Task 6 — only `list`/`set_order` are used here and `set_order` must exist before this task's reorder path is exercised end-to-end; `list` already exists).
- Produces: `FolderService` with `tree(collection_id, project_id) -> dict`, `create(project_id, collection_id, name, parent_folder_id=None) -> dict`, `update(id, project_id, data: dict) -> dict` (handles rename and/or reparent, with a cycle guard), `delete(id, project_id) -> bool`, `reorder(collection_id, project_id, parent_folder_id, items: list[dict]) -> None` — consumed by Task 4 (routes).

- [ ] **Step 1: Write the service**

```python
from __future__ import annotations
import logging
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.folder_service")
_folder_repo = FolderRepo()
_col_repo = CollectionRepo()
_req_repo = RequestRepo()


class FolderService:
    def tree(self, collection_id: str, project_id: str) -> dict:
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        return {
            "folders": _folder_repo.list_for_collection(collection_id),
            "requests": _req_repo.list(project_id, collection_id=collection_id),
        }

    def create(self, project_id: str, collection_id: str, name: str,
               parent_folder_id: str | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("Folder name is required")
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        if parent_folder_id:
            self._validate_parent(collection_id, project_id, parent_folder_id)
        return _folder_repo.create(project_id, collection_id, name, parent_folder_id)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        folder = _folder_repo.get(id, project_id)
        if folder is None:
            raise LookupError(f"Folder {id} not found")

        updates = {}
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                raise ValueError("Folder name is required")
            updates["name"] = name

        if "parent_folder_id" in data:
            parent_folder_id = data["parent_folder_id"]
            if parent_folder_id:
                if parent_folder_id == id:
                    raise ValueError("A folder cannot be its own parent")
                self._validate_parent(folder["collection_id"], project_id, parent_folder_id)
                self._assert_not_descendant(id, project_id, parent_folder_id)
            updates["parent_folder_id"] = parent_folder_id

        if updates:
            _folder_repo.update(id, updates)
        return _folder_repo.get(id, project_id)

    def delete(self, id: str, project_id: str) -> bool:
        if _folder_repo.get(id, project_id) is None:
            raise LookupError(f"Folder {id} not found")
        return _folder_repo.delete(id)

    def reorder(self, collection_id: str, project_id: str,
                parent_folder_id: str | None, items: list[dict]) -> None:
        if _col_repo.get(collection_id, project_id) is None:
            raise LookupError(f"Collection {collection_id} not found")
        if parent_folder_id:
            self._validate_parent(collection_id, project_id, parent_folder_id)
        for idx, item in enumerate(items):
            item_type, item_id = item.get("type"), item.get("id")
            if item_type == "folder":
                _folder_repo.set_order(item_id, collection_id, parent_folder_id, idx)
            elif item_type == "request":
                _req_repo.set_order(item_id, collection_id, parent_folder_id, idx)
            else:
                raise ValueError(f"Invalid item type: {item_type}")

    def _validate_parent(self, collection_id: str, project_id: str, parent_folder_id: str) -> None:
        parent = _folder_repo.get(parent_folder_id, project_id)
        if parent is None or parent["collection_id"] != collection_id:
            raise ValueError("Parent folder not found in this collection")

    def _assert_not_descendant(self, folder_id: str, project_id: str, target_parent_id: str) -> None:
        """Walk target_parent_id's ancestor chain; reject if folder_id appears in it —
        that would move a folder into its own descendant and create a cycle."""
        cursor_id = target_parent_id
        seen = set()
        while cursor_id:
            if cursor_id == folder_id:
                raise ValueError("Cannot move a folder into its own descendant")
            if cursor_id in seen:
                break  # defensive: already-corrupt chain, stop rather than loop forever
            seen.add(cursor_id)
            cursor = _folder_repo.get(cursor_id, project_id)
            cursor_id = cursor.get("parent_folder_id") if cursor else None
```

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
cid = generate_id('apicol')
conn.execute('INSERT INTO api_collections (id, project_id, name, created_at) VALUES (?, ?, ?, ?)', (cid, pid, 'Col', datetime.now(timezone.utc).isoformat()))
conn.commit()

from web.api.services.folder_service import FolderService
svc = FolderService()

root = svc.create(pid, cid, 'Auth')
child = svc.create(pid, cid, 'Login', root['id'])
grandchild = svc.create(pid, cid, 'Edge cases', child['id'])

# Cycle guard: cannot move 'Auth' (root) inside its own grandchild
try:
    svc.update(root['id'], pid, {'parent_folder_id': grandchild['id']})
    assert False, 'expected ValueError'
except ValueError as e:
    assert 'descendant' in str(e)

# Valid rename + reparent
updated = svc.update(grandchild['id'], pid, {'name': 'Edge Cases', 'parent_folder_id': None})
assert updated['name'] == 'Edge Cases'
assert updated['parent_folder_id'] is None

t = svc.tree(cid, pid)
assert len(t['folders']) == 3 and t['requests'] == []

svc.reorder(cid, pid, None, [
    {'type': 'folder', 'id': updated['id']},
    {'type': 'folder', 'id': root['id']},
])
folders_by_id = {f['id']: f for f in svc.tree(cid, pid)['folders']}
assert folders_by_id[updated['id']]['order_index'] == 0
assert folders_by_id[root['id']]['order_index'] == 1

assert svc.delete(root['id'], pid)
assert svc.tree(cid, pid)['folders'] == [] or all(f['id'] != root['id'] for f in svc.tree(cid, pid)['folders'])
print('PASS: FolderService create/update/cycle-guard/reorder/delete')
"
```

Expected output: `PASS: FolderService create/update/cycle-guard/reorder/delete`

- [ ] **Step 3: Commit**

```bash
git add web/api/services/folder_service.py
git commit -m "feat(api): add FolderService with cycle-guarded move and reorder"
```

---

## Task 4: Folder routes + blueprint registration

**Files:**
- Create: `web/api/routes/folders.py`
- Modify: `web/server.py`

**Interfaces:**
- Consumes: `FolderService` (Task 3).
- Produces: `GET /api/collections/<col_id>/tree`, `POST /api/collections/<col_id>/folders`, `PATCH /api/api-folders/<folder_id>`, `DELETE /api/api-folders/<folder_id>`, `PUT /api/collections/<col_id>/tree-order` — consumed by Task 7 (frontend).

- [ ] **Step 1: Write the routes**

```python
from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
from cli.config import get_active_project_id
from web.api.services.folder_service import FolderService

logger = logging.getLogger("qaclan.routes.folders")
bp = Blueprint("api_folders_bp", __name__)
_svc = FolderService()


def _project_id():
    pid = get_active_project_id()
    if not pid:
        raise ValueError("No active project")
    return pid


@bp.route("/api/collections/<col_id>/tree", methods=["GET"])
def get_collection_tree(col_id):
    try:
        return jsonify({"ok": True, **_svc.tree(col_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("get_collection_tree")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/folders", methods=["POST"])
def create_folder(col_id):
    try:
        data = request.get_json(force=True) or {}
        folder = _svc.create(_project_id(), col_id, data.get("name", ""), data.get("parent_folder_id"))
        return jsonify({"ok": True, "folder": folder}), 201
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-folders/<folder_id>", methods=["PATCH"])
def update_folder(folder_id):
    try:
        data = request.get_json(force=True) or {}
        folder = _svc.update(folder_id, _project_id(), data)
        return jsonify({"ok": True, "folder": folder})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("update_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/api-folders/<folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    try:
        _svc.delete(folder_id, _project_id())
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_folder")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/collections/<col_id>/tree-order", methods=["PUT"])
def reorder_tree(col_id):
    try:
        data = request.get_json(force=True) or {}
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "items array is required"}), 400
        _svc.reorder(col_id, _project_id(), data.get("parent_folder_id"), items)
        return jsonify({"ok": True})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reorder_tree")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Register the blueprint**

In `web/server.py`, change:

```python
from .api.routes.api_collection_runs import bp as api_collection_runs_bp
```

to:

```python
from .api.routes.api_collection_runs import bp as api_collection_runs_bp
from .api.routes.folders import bp as api_folders_bp
```

And change:

```python
    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp, sync_bp,
               api_collections_bp, api_requests_bp, api_discovery_bp, api_runs_bp, api_docs_bp,
               api_collection_runs_bp]:
```

to:

```python
    for bp in [projects_bp, features_bp, scripts_bp, suites_bp, runs_bp, envs_bp, auth_bp, sync_bp,
               api_collections_bp, api_requests_bp, api_discovery_bp, api_runs_bp, api_docs_bp,
               api_collection_runs_bp, api_folders_bp]:
```

- [ ] **Step 3: Verify manually**

```bash
python qaclan.py serve --port 7823 &
sleep 2
# Substitute a real collection id from your local DB (e.g. qaclan project use <name> then create one via the UI, or POST /api/collections)
curl -s -X POST http://localhost:7823/api/collections -H 'Content-Type: application/json' -d '{"name":"Folder Test"}'
# copy the returned collection id into COL below
COL=apicol_XXXXXXXX
curl -s -X POST http://localhost:7823/api/collections/$COL/folders -H 'Content-Type: application/json' -d '{"name":"Auth"}'
curl -s http://localhost:7823/api/collections/$COL/tree
kill %1
```

Expected: the `POST .../folders` call returns `{"ok":true,"folder":{...,"name":"Auth","parent_folder_id":null,"order_index":0,...}}`; the `.../tree` call returns `{"ok":true,"folders":[{...}],"requests":[]}`.

- [ ] **Step 4: Commit**

```bash
git add web/api/routes/folders.py web/server.py
git commit -m "feat(api): add folder routes and register blueprint"
```

---

## Task 5: Collection-level drag ordering

**Files:**
- Modify: `web/api/repositories/collection_repo.py`
- Modify: `web/api/services/collection_service.py`
- Modify: `web/api/routes/collections.py`

**Interfaces:**
- Consumes: existing `CollectionRepo`/`CollectionService` (this task extends both in place).
- Produces: `CollectionRepo.set_order(id, project_id, order_index) -> bool`; order-aware `CollectionRepo.list()`; `CollectionService.reorder(project_id, ids: list[str]) -> None`; route `PUT /api/collections/order` — consumed by Task 7 (frontend, collection-level drag).

- [ ] **Step 1: Add `set_order` and make `list()` order-aware**

In `web/api/repositories/collection_repo.py`, replace the `list` method:

```python
    def list(self, project_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT ac.id, ac.name, ac.description, ac.env_name, ac.auth_type, ac.auth_config, "
            "ac.order_index, ac.created_at, "
            "COUNT(ar.id) AS request_count "
            "FROM api_collections ac "
            "LEFT JOIN api_requests ar ON ar.collection_id = ac.id "
            "WHERE ac.project_id = ? "
            "GROUP BY ac.id ORDER BY ac.order_index, ac.created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

Then add a new method, directly after `delete`:

```python
    def set_order(self, id: str, project_id: str, order_index: int) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE api_collections SET order_index = ? WHERE id = ? AND project_id = ?",
            (order_index, id, project_id),
        )
        conn.commit()
        return cur.rowcount > 0
```

- [ ] **Step 2: Add `reorder` to the service**

In `web/api/services/collection_service.py`, add inside `class CollectionService`, after `delete`:

```python
    def reorder(self, project_id: str, ids: list[str]) -> None:
        for idx, cid in enumerate(ids):
            _col_repo.set_order(cid, project_id, idx)
```

- [ ] **Step 3: Add the route**

In `web/api/routes/collections.py`, add after `export_collection`:

```python
@bp.route("/api/collections/order", methods=["PUT"])
def reorder_collections():
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("collection_ids", [])
        if not ids:
            return jsonify({"ok": False, "error": "collection_ids array is required"}), 400
        _svc.reorder(_project_id(), ids)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reorder_collections")
        return jsonify({"ok": False, "error": str(e)}), 500
```

Note: Flask/Werkzeug matches the static path `/api/collections/order` ahead of the dynamic `/api/collections/<col_id>` regardless of registration order — static segments always outrank variable ones in routing precedence, so this is safe without special ordering.

- [ ] **Step 4: Verify manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
conn.commit()

from web.api.services.collection_service import CollectionService
svc = CollectionService()
a = svc.create(pid, 'A')
b = svc.create(pid, 'B')
svc.reorder(pid, [b['id'], a['id']])
listed = svc.list(pid)
assert [c['id'] for c in listed] == [b['id'], a['id']], listed
print('PASS: CollectionService.reorder persists order')
"
```

Expected output: `PASS: CollectionService.reorder persists order`

- [ ] **Step 5: Commit**

```bash
git add web/api/repositories/collection_repo.py web/api/services/collection_service.py web/api/routes/collections.py
git commit -m "feat(api): add collection-level drag ordering"
```

---

## Task 6: `RequestRepo`/`RequestService` — folder placement and ordering

**Files:**
- Modify: `web/api/repositories/request_repo.py`
- Modify: `web/api/services/request_service.py`

**Interfaces:**
- Consumes: `api_requests.folder_id`/`order_index` (Task 1), `FolderRepo` (Task 2).
- Produces: `RequestRepo._DEFAULTS['folder_id']`, order-aware `create`/`list`, `RequestRepo.set_order(id, collection_id, folder_id, order_index) -> bool`; `RequestService` validates `folder_id` on create/update — consumed by Task 7 (frontend) and by `FolderService.reorder` (Task 3, already calls `_req_repo.set_order`).
- **This task also fixes collection-run ordering**: `RunnerService` (`web/api/services/runner_service.py`) calls `RequestRepo.list(project_id, collection_id=...)` in three places (`start_collection_run`, `_execute_collection`, `run_collection`) with no changes needed there — once `list()`'s `ORDER BY` respects `order_index`, collection runs automatically execute in the user's drag-arranged order. No `runner_service.py` edit in this plan; verified by inline test below and again in Task 12's regression pass.

- [ ] **Step 1: Add `folder_id` to defaults and order-aware `create`**

In `web/api/repositories/request_repo.py`, add `"folder_id": None,` to `_DEFAULTS` (after `"collection_id"` isn't in `_DEFAULTS` today — add it right after `"path_params": "[]",`):

```python
_DEFAULTS = {
    "method": "GET",
    "url": "",
    "headers": "[]",
    "params": "[]",
    "path_params": "[]",
    "folder_id": None,
    "body_type": None,
    ...
```

(Leave every other existing key in `_DEFAULTS` unchanged — only the `"folder_id": None,` line is new.)

Replace the `create` method:

```python
    def create(self, project_id: str, data: dict) -> dict:
        conn = get_conn()
        rid = generate_id("apireq")
        now = datetime.now(timezone.utc).isoformat()
        merged = {**_DEFAULTS, **_serialize(data)}

        collection_id = merged.get("collection_id")
        folder_id = merged.get("folder_id")
        if collection_id:
            if folder_id:
                max_order = conn.execute(
                    "SELECT COALESCE(MAX(order_index), -1) FROM api_requests WHERE collection_id = ? AND folder_id = ?",
                    (collection_id, folder_id),
                ).fetchone()[0]
            else:
                max_order = conn.execute(
                    "SELECT COALESCE(MAX(order_index), -1) FROM api_requests WHERE collection_id = ? AND folder_id IS NULL",
                    (collection_id,),
                ).fetchone()[0]
            order_index = max_order + 1
        else:
            order_index = 0

        conn.execute(
            "INSERT INTO api_requests (id, project_id, feature_id, collection_id, folder_id, order_index, name, method, url, "
            "headers, params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, pre_extractor, "
            "post_script, post_lang, post_extractor, request_schema, response_schema, "
            "assertions, follow_redirects, timeout_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, project_id,
             merged.get("feature_id"), collection_id, folder_id, order_index,
             merged.get("name", "Unnamed"), merged["method"], merged["url"],
             merged["headers"], merged["params"], merged["path_params"],
             merged["body_type"], merged["body"],
             merged["auth_type"], merged["auth_config"],
             merged["pre_script"], merged["pre_lang"], merged["pre_extractor"],
             merged["post_script"], merged["post_lang"], merged["post_extractor"],
             merged.get("request_schema"), merged.get("response_schema"),
             merged["assertions"], merged["follow_redirects"], merged["timeout_ms"],
             now),
        )
        conn.commit()
        logger.info("RequestRepo.create: %s (%s)", merged.get("name"), rid)
        return self.get(rid, project_id)
```

- [ ] **Step 2: Add `folder_id` to the `update` allowlist**

In the `update` method, change:

```python
        fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "pre_extractor", "post_script",
                  "post_lang", "post_extractor", "request_schema", "response_schema",
                  "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id"]
```

to:

```python
        fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "pre_extractor", "post_script",
                  "post_lang", "post_extractor", "request_schema", "response_schema",
                  "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id", "folder_id"]
```

`order_index` is intentionally excluded from this allowlist — it is only ever written through the scoped `set_order` method below, never through the generic passthrough update, so a reorder always goes through the same validated, WHERE-scoped path.

- [ ] **Step 3: Add `set_order` and make `list` order-aware**

Change both `list` queries:

```python
    def list(self, project_id: str, collection_id: str | None = None) -> list[dict]:
        conn = get_conn()
        if collection_id:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? AND collection_id = ? ORDER BY order_index, created_at",
                (project_id, collection_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM api_requests WHERE project_id = ? ORDER BY order_index, created_at",
                (project_id,),
            ).fetchall()
        return [_deserialize(dict(r)) for r in rows]
```

Add, directly after `delete_by_collection`:

```python
    def set_order(self, id: str, collection_id: str, folder_id: str | None, order_index: int) -> bool:
        conn = get_conn()
        if folder_id:
            cur = conn.execute(
                "UPDATE api_requests SET order_index = ? WHERE id = ? AND collection_id = ? AND folder_id = ?",
                (order_index, id, collection_id, folder_id),
            )
        else:
            cur = conn.execute(
                "UPDATE api_requests SET order_index = ? WHERE id = ? AND collection_id = ? AND folder_id IS NULL",
                (order_index, id, collection_id),
            )
        conn.commit()
        return cur.rowcount > 0
```

- [ ] **Step 4: Validate `folder_id` in `RequestService`**

In `web/api/services/request_service.py`, add a module-level helper and use it from both `create` and `update`:

```python
from __future__ import annotations
import logging
from web.api.repositories.request_repo import RequestRepo

logger = logging.getLogger("qaclan.request_service")
_repo = RequestRepo()


def _validate_folder(project_id: str, folder_id: str, collection_id: str | None) -> None:
    from web.api.repositories.folder_repo import FolderRepo
    folder = FolderRepo().get(folder_id, project_id)
    if folder is None or folder["collection_id"] != collection_id:
        raise ValueError("Target folder not found in this collection")


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
        if data.get("folder_id"):
            _validate_folder(project_id, data["folder_id"], data.get("collection_id"))
        return _repo.create(project_id, data)

    def update(self, id: str, project_id: str, data: dict) -> dict:
        existing = _repo.get(id, project_id)
        if existing is None:
            raise LookupError(f"Request {id} not found")
        if data.get("folder_id"):
            collection_id = data.get("collection_id", existing.get("collection_id"))
            _validate_folder(project_id, data["folder_id"], collection_id)
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

    def list_examples(self, request_id: str, project_id: str) -> list[dict]:
        existing = _repo.get(request_id, project_id)
        if existing is None:
            raise LookupError(f"Request {request_id} not found")
        from web.api.repositories.request_example_repo import RequestExampleRepo
        return RequestExampleRepo().list_for_request(request_id)
```

- [ ] **Step 5: Verify manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
conn.commit()

from web.api.services.collection_service import CollectionService
from web.api.services.folder_service import FolderService
from web.api.services.request_service import RequestService

col = CollectionService().create(pid, 'Col')
folder = FolderService().create(pid, col['id'], 'Auth')
svc = RequestService()

# Request placed directly in a folder at creation time
r1 = svc.create(pid, {'name': 'Login', 'url': 'https://x/login', 'collection_id': col['id'], 'folder_id': folder['id']})
assert r1['folder_id'] == folder['id']
assert r1['order_index'] == 0

r2 = svc.create(pid, {'name': 'Logout', 'url': 'https://x/logout', 'collection_id': col['id'], 'folder_id': folder['id']})
assert r2['order_index'] == 1, r2['order_index']

# Rejects a folder that belongs to a different collection
other_col = CollectionService().create(pid, 'Other')
try:
    svc.create(pid, {'name': 'Bad', 'url': 'https://x', 'collection_id': other_col['id'], 'folder_id': folder['id']})
    assert False, 'expected ValueError'
except ValueError as e:
    assert 'folder' in str(e).lower()

# Collection run order respects order_index (RunnerService reuses RequestRepo.list unchanged)
from web.api.repositories.request_repo import RequestRepo
RequestRepo().set_order(r2['id'], col['id'], folder['id'], 0)
RequestRepo().set_order(r1['id'], col['id'], folder['id'], 1)
ordered = RequestRepo().list(pid, collection_id=col['id'])
assert [r['id'] for r in ordered] == [r2['id'], r1['id']], ordered
print('PASS: RequestRepo/RequestService folder placement + order-respecting list')
"
```

Expected output: `PASS: RequestRepo/RequestService folder placement + order-respecting list`

- [ ] **Step 6: Commit**

```bash
git add web/api/repositories/request_repo.py web/api/services/request_service.py
git commit -m "feat(api): add folder placement and drag ordering to api_requests"
```

---

## Task 7: `collections-view.js` — recursive tree, folder CRUD, drag-and-drop

**Files:**
- Modify: `web/static/api/views/collections-view.js` (full rewrite)

**Interfaces:**
- Consumes: `GET /collections`, `GET /collections/<id>/tree`, `POST /collections/<id>/folders`, `PATCH /api-folders/<id>`, `DELETE /api-folders/<id>`, `PUT /collections/<id>/tree-order`, `PUT /collections/order` (Tasks 4–6), `POST /collections/<id>/run`, `DELETE /collections/<id>`, `POST /collections` (existing, unchanged).
- Produces: `renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection)` — same exported name, but `onSelectRequest` now receives a 5th argument: `(requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId)`. Consumed by Task 8 (`api-section.js` must pass the 5th argument through).

- [ ] **Step 1: Replace the file**

```js
/**
 * renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection)
 * container: DOM element to render into
 * onSelectRequest: (requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId) => void
 * defaultFolderId: string|null — which folder a "+ New Request" click was made from
 */
export function renderCollectionsView(container, onSelectRequest, onRunStarted, onSelectCollection) {
  container.innerHTML = '<div class="text-muted text-sm" style="padding:10px 14px">Loading...</div>';

  let _runningByColId = {};
  let _runningPollTimer = null;

  async function _refreshRunningStatus() {
    try {
      const res = await window.api('GET', '/api-collection-runs?status=RUNNING');
      const runs = res.runs || [];
      const fresh = {};
      runs.forEach(r => { if (r.collection_id) fresh[r.collection_id] = r.id; });
      const changed = JSON.stringify(fresh) !== JSON.stringify(_runningByColId);
      _runningByColId = fresh;
      if (changed) _updateRunningDots();
      if (Object.keys(_runningByColId).length === 0 && _runningPollTimer) {
        clearInterval(_runningPollTimer);
        _runningPollTimer = null;
      }
    } catch (_) {}
  }

  function _updateRunningDots() {
    document.querySelectorAll('[data-col-dot]').forEach(dot => {
      const colId = dot.dataset.colDot;
      dot.style.display = _runningByColId[colId] ? '' : 'none';
    });
  }

  async function reload() {
    const res = await window.api('GET', '/collections');
    const collections = res.collections || [];
    container.innerHTML = '';

    if (!document.getElementById('cdot-style')) {
      const st = document.createElement('style');
      st.id = 'cdot-style';
      st.textContent = '@keyframes cdot-pulse{0%,100%{opacity:1}50%{opacity:.3}}';
      document.head.appendChild(st);
    }

    if (!collections.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'padding:10px 14px;';
      empty.textContent = 'No collections yet.';
      container.appendChild(empty);
      _appendNewCollectionButton();
      return;
    }

    collections.forEach(col => container.appendChild(_renderCollectionSection(col)));
    _appendNewCollectionButton();
    _wireCollectionOrderDrag();

    if (_runningPollTimer) clearInterval(_runningPollTimer);
    await _refreshRunningStatus();
    _runningPollTimer = setInterval(_refreshRunningStatus, 3000);
  }

  function _appendNewCollectionButton() {
    const newColBtn = document.createElement('div');
    newColBtn.style.cssText = 'padding:8px 14px;cursor:pointer;font-size:12px;color:var(--text-muted)';
    newColBtn.textContent = '+ New Collection';
    newColBtn.onclick = _createCollection;
    container.appendChild(newColBtn);
  }

  // ---- Collection section (header + tree) ----

  function _renderCollectionSection(col) {
    const section = document.createElement('div');
    section.className = 'api-collection-section';
    section.dataset.collectionId = col.id;

    const header = document.createElement('div');
    header.className = 'api-collection-item api-collection-header';
    header.draggable = true;

    const leftSide = document.createElement('span');
    leftSide.style.cssText = 'display:flex;align-items:center;gap:5px;cursor:pointer;flex:1;min-width:0;';
    leftSide.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span data-col-dot="${_esc(col.id)}" style="display:none;width:7px;height:7px;border-radius:50%;
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

    const rightSide = document.createElement('span');
    rightSide.style.cssText = 'display:flex;gap:2px;align-items:center;';

    const runBtn = document.createElement('button');
    runBtn.className = 'btn btn-xs btn-ghost';
    runBtn.title = 'Run collection';
    runBtn.textContent = '▶';
    runBtn.onclick = (e) => { e.stopPropagation(); _runCollection(col.id, col.name, col.env_name); };
    rightSide.appendChild(runBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-xs btn-ghost';
    delBtn.title = 'Delete collection';
    delBtn.style.color = 'var(--danger,#e53e3e)';
    delBtn.textContent = '🗑';
    delBtn.onclick = (e) => { e.stopPropagation(); _deleteCollection(col.id, col.name); };
    rightSide.appendChild(delBtn);

    const expandBtn = document.createElement('button');
    expandBtn.className = 'btn btn-xs btn-ghost';
    expandBtn.textContent = '▾';
    rightSide.appendChild(expandBtn);
    header.appendChild(rightSide);

    section.appendChild(header);

    const treeRoot = document.createElement('div');
    treeRoot.className = 'api-tree-root';
    let expanded = true;

    function _toggleExpand() {
      expanded = !expanded;
      treeRoot.style.display = expanded ? '' : 'none';
      expandBtn.textContent = expanded ? '▾' : '▸';
    }
    header.onclick = (e) => {
      if (rightSide.contains(e.target)) return;
      if (leftSide.contains(e.target)) return;
      _toggleExpand();
    };
    expandBtn.onclick = (e) => { e.stopPropagation(); _toggleExpand(); };

    section.appendChild(treeRoot);

    let allFolders = [];
    let allRequests = [];
    const rerender = () => _renderTreeLevel(treeRoot, col, null, allFolders, allRequests);

    window.api('GET', `/collections/${col.id}/tree`).then(treeRes => {
      allFolders = treeRes.folders || [];
      allRequests = treeRes.requests || [];
      rerender();
      _wireCollectionTreeDrag(treeRoot, col, allFolders, allRequests, rerender);
    });

    return section;
  }

  // ---- Tree rendering (recursive) ----

  function _renderTreeLevel(containerEl, col, parentFolderId, allFolders, allRequests) {
    containerEl.dataset.parentFolderId = parentFolderId || '';
    containerEl.innerHTML = '';

    const childFolders = allFolders.filter(f => (f.parent_folder_id || null) === parentFolderId);
    const childRequests = allRequests.filter(r => (r.folder_id || null) === parentFolderId);
    const nodes = [
      ...childFolders.map(f => ({ type: 'folder', order_index: f.order_index, data: f })),
      ...childRequests.map(r => ({ type: 'request', order_index: r.order_index, data: r })),
    ].sort((a, b) => a.order_index - b.order_index);

    nodes.forEach(node => {
      containerEl.appendChild(node.type === 'folder'
        ? _renderFolderNode(col, node.data, allFolders, allRequests)
        : _renderRequestNode(col, node.data, parentFolderId));
    });

    containerEl.appendChild(_renderNewRequestRow(col, parentFolderId));
    containerEl.appendChild(_renderNewFolderRow(col, parentFolderId, allFolders, allRequests, containerEl));
  }

  function _renderFolderNode(col, folder, allFolders, allRequests) {
    // Returns a DocumentFragment of two siblings — [row, childrenEl] — rather than a
    // wrapping <div>. This matters for drag-and-drop: dragEl.parentElement must be the
    // shared level container (containerEl) for BOTH folder rows and request rows, so the
    // "same level = plain reorder" check in _wireCollectionTreeDrag works uniformly. A
    // wrapping div would put a folder row one level deeper in the DOM than a request row.
    const row = document.createElement('div');
    row.className = 'api-folder-item';
    row.draggable = true;
    row.dataset.nodeType = 'folder';
    row.dataset.nodeId = folder.id;
    row.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span class="api-folder-toggle">▾</span>
      <span class="api-folder-name">${_esc(folder.name)}</span>`;

    const actions = document.createElement('span');
    actions.className = 'api-folder-actions';

    const renameBtn = document.createElement('button');
    renameBtn.className = 'btn btn-xs btn-ghost';
    renameBtn.title = 'Rename folder';
    renameBtn.textContent = '✎';
    renameBtn.onclick = async (e) => { e.stopPropagation(); await _renameFolder(folder); };
    actions.appendChild(renameBtn);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-xs btn-ghost';
    delBtn.title = 'Delete folder';
    delBtn.style.color = 'var(--danger,#e53e3e)';
    delBtn.textContent = '🗑';
    delBtn.onclick = async (e) => { e.stopPropagation(); await _deleteFolder(folder); };
    actions.appendChild(delBtn);

    row.appendChild(actions);

    const childrenEl = document.createElement('div');
    childrenEl.className = 'api-folder-children';

    let expanded = true;
    const toggle = row.querySelector('.api-folder-toggle');
    row.onclick = (e) => {
      if (actions.contains(e.target)) return;
      expanded = !expanded;
      childrenEl.style.display = expanded ? '' : 'none';
      toggle.textContent = expanded ? '▾' : '▸';
    };

    _renderTreeLevel(childrenEl, col, folder.id, allFolders, allRequests);

    const frag = document.createDocumentFragment();
    frag.appendChild(row);
    frag.appendChild(childrenEl);
    return frag;
  }

  function _renderRequestNode(col, req, parentFolderId) {
    const item = document.createElement('div');
    item.className = 'api-request-item';
    item.draggable = true;
    item.dataset.nodeType = 'request';
    item.dataset.nodeId = req.id;
    item.innerHTML = `
      <span class="api-drag-handle">⠿</span>
      <span class="method-badge method-${req.method}">${req.method}</span>
      <span>${_esc(req.name)}</span>`;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-from-col-btn';
    removeBtn.title = 'Remove from collection';
    removeBtn.innerHTML = '&#x2715;';
    removeBtn.onclick = async (e) => {
      e.stopPropagation();
      const confirmed = await window._confirmDialog(
        'Remove from collection?',
        `"${req.name}" will be removed from this collection but not deleted.`,
        'Remove'
      );
      if (!confirmed) return;
      const res = await window.api('PATCH', `/api-requests/${req.id}`, { collection_id: null, folder_id: null });
      if (res.ok === false) {
        await window._alertDialog('Error: ' + (res.error || 'unknown error'));
        return;
      }
      item.remove();
    };
    item.appendChild(removeBtn);

    item.onclick = (e) => {
      if (removeBtn.contains(e.target)) return;
      container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      onSelectRequest(req.id, null, col.id, col.env_name, parentFolderId);
    };

    return item;
  }

  function _renderNewRequestRow(col, parentFolderId) {
    const row = document.createElement('div');
    row.className = 'api-request-item api-new-item-row';
    row.innerHTML = `<span style="color:var(--text-muted)">+ New Request</span>`;
    row.onclick = () => {
      container.querySelectorAll('.api-request-item').forEach(i => i.classList.remove('active'));
      row.classList.add('active');
      onSelectRequest(null, col.id, col.id, col.env_name, parentFolderId);
    };
    return row;
  }

  function _renderNewFolderRow(col, parentFolderId, allFolders, allRequests, containerEl) {
    const row = document.createElement('div');
    row.className = 'api-request-item api-new-item-row';
    row.innerHTML = `<span style="color:var(--text-muted)">+ New Folder</span>`;
    row.onclick = async () => {
      const name = await window._promptDialog('Folder name:');
      if (!name) return;
      const res = await window.api('POST', `/collections/${col.id}/folders`, {
        name: name.trim(), parent_folder_id: parentFolderId,
      });
      if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
      allFolders.push(res.folder);
      _renderTreeLevel(containerEl, col, parentFolderId, allFolders, allRequests);
    };
    return row;
  }

  async function _renameFolder(folder) {
    const name = await window._promptDialog('Rename folder:', folder.name);
    if (!name || name.trim() === folder.name) return;
    const res = await window.api('PATCH', `/api-folders/${folder.id}`, { name: name.trim() });
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  async function _deleteFolder(folder) {
    const confirmed = await window._confirmDialog(
      `Delete '${folder.name}'?`,
      'This folder and everything inside it (sub-folders and requests) will be permanently deleted.',
      'Delete', 'btn btn-sm btn-danger'
    );
    if (!confirmed) return;
    const res = await window.api('DELETE', `/api-folders/${folder.id}`);
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  // ---- Drag-and-drop: folders + requests within one collection ----
  // One delegated listener per collection (attached to that collection's treeRoot),
  // not one per level — avoids nested-listener event-bubbling conflicts entirely.

  function _isDescendant(folderId, allFolders, candidateId) {
    let cursor = allFolders.find(f => f.id === candidateId);
    while (cursor) {
      if (cursor.id === folderId) return true;
      cursor = allFolders.find(f => f.id === cursor.parent_folder_id);
    }
    return false;
  }

  function _wireCollectionTreeDrag(treeRoot, col, allFolders, allRequests, rerender) {
    let dragEl = null;
    let hoverFolderRow = null;

    treeRoot.addEventListener('dragstart', e => {
      const row = e.target.closest('[data-node-type]');
      if (!row) return;
      dragEl = row;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    treeRoot.addEventListener('dragover', e => {
      if (!dragEl) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';

      if (hoverFolderRow) { hoverFolderRow.classList.remove('drop-target-folder'); hoverFolderRow = null; }

      const targetRow = e.target.closest('[data-node-type]');
      if (!targetRow || targetRow === dragEl) return;

      const rect = targetRow.getBoundingClientRect();
      const topZone = rect.top + rect.height * 0.25;
      const bottomZone = rect.top + rect.height * 0.75;
      const draggingFolder = dragEl.dataset.nodeType === 'folder';
      const wouldCycle = draggingFolder && _isDescendant(dragEl.dataset.nodeId, allFolders, targetRow.dataset.nodeId);

      if (targetRow.dataset.nodeType === 'folder' && e.clientY > topZone && e.clientY < bottomZone && !wouldCycle) {
        targetRow.classList.add('drop-target-folder');
        hoverFolderRow = targetRow;
        return;
      }

      const targetList = targetRow.parentElement;
      if (targetList !== dragEl.parentElement) return; // plain reorder only within the same level
      if (e.clientY < rect.top + rect.height / 2) {
        targetList.insertBefore(dragEl, targetRow);
      } else {
        targetList.insertBefore(dragEl, targetRow.nextSibling);
      }
    });

    treeRoot.addEventListener('dragend', async () => {
      if (!dragEl) return;
      dragEl.classList.remove('dragging');
      const draggedType = dragEl.dataset.nodeType;
      const draggedId = dragEl.dataset.nodeId;
      const sourceList = dragEl.parentElement;

      if (hoverFolderRow) {
        const targetFolderId = hoverFolderRow.dataset.nodeId;
        hoverFolderRow.classList.remove('drop-target-folder');
        hoverFolderRow = null;
        dragEl = null;
        await _reparentNode(col, allFolders, allRequests, rerender, draggedType, draggedId, targetFolderId);
        return;
      }

      dragEl = null;
      const parentFolderId = sourceList.dataset.parentFolderId || null;
      const items = [...sourceList.querySelectorAll(':scope > [data-node-type]')].map(el => ({
        type: el.dataset.nodeType, id: el.dataset.nodeId,
      }));
      const res = await window.api('PUT', `/collections/${col.id}/tree-order`, { parent_folder_id: parentFolderId, items });
      if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
      items.forEach((it, idx) => {
        const arr = it.type === 'folder' ? allFolders : allRequests;
        const n = arr.find(x => x.id === it.id);
        if (n) n.order_index = idx;
      });
    });
  }

  async function _reparentNode(col, allFolders, allRequests, rerender, draggedType, draggedId, newParentFolderId) {
    const patchUrl = draggedType === 'folder' ? `/api-folders/${draggedId}` : `/api-requests/${draggedId}`;
    const patchBody = draggedType === 'folder' ? { parent_folder_id: newParentFolderId } : { folder_id: newParentFolderId };
    const res = await window.api('PATCH', patchUrl, patchBody);
    if (res.ok === false) { await window._alertDialog('Move failed: ' + res.error); return; }

    const movedList = draggedType === 'folder' ? allFolders : allRequests;
    const moved = movedList.find(n => n.id === draggedId);
    if (moved) {
      if (draggedType === 'folder') moved.parent_folder_id = newParentFolderId;
      else moved.folder_id = newParentFolderId;
    }

    const siblingFolders = allFolders.filter(f => f.parent_folder_id === newParentFolderId && f.id !== draggedId);
    const siblingRequests = allRequests.filter(r => r.folder_id === newParentFolderId && r.id !== draggedId);
    const destItems = [
      ...siblingFolders.map(f => ({ type: 'folder', id: f.id })),
      ...siblingRequests.map(r => ({ type: 'request', id: r.id })),
      { type: draggedType, id: draggedId },
    ];
    const orderRes = await window.api('PUT', `/collections/${col.id}/tree-order`, {
      parent_folder_id: newParentFolderId, items: destItems,
    });
    if (orderRes.ok === false) { await window._alertDialog('Error: ' + orderRes.error); return; }
    destItems.forEach((it, idx) => {
      const arr = it.type === 'folder' ? allFolders : allRequests;
      const n = arr.find(x => x.id === it.id);
      if (n) n.order_index = idx;
    });

    rerender();
  }

  // ---- Drag-and-drop: collections themselves ----

  function _wireCollectionOrderDrag() {
    let dragEl = null;

    container.addEventListener('dragstart', e => {
      const header = e.target.closest('.api-collection-header');
      if (!header) return;
      dragEl = header.closest('.api-collection-section');
      dragEl.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    container.addEventListener('dragover', e => {
      if (!dragEl) return;
      const targetHeader = e.target.closest('.api-collection-header');
      const target = targetHeader ? targetHeader.closest('.api-collection-section') : null;
      if (!target || target === dragEl || target.parentElement !== container) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = target.getBoundingClientRect();
      if (e.clientY < rect.top + rect.height / 2) {
        container.insertBefore(dragEl, target);
      } else {
        container.insertBefore(dragEl, target.nextSibling);
      }
    });

    container.addEventListener('dragend', async () => {
      if (!dragEl) return;
      dragEl.classList.remove('dragging');
      dragEl = null;
      const ids = [...container.querySelectorAll('.api-collection-section')].map(s => s.dataset.collectionId);
      const res = await window.api('PUT', '/collections/order', { collection_ids: ids });
      if (res.ok === false) await window._alertDialog('Error: ' + res.error);
    });
  }

  // ---- Collection-level actions (unchanged from before this rewrite) ----

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

  async function _deleteCollection(colId, colName) {
    const confirmed = await window._confirmDialog(`Delete '${colName}'?`, 'All requests in this collection will be permanently deleted.', 'Delete', 'btn btn-sm btn-danger');
    if (!confirmed) return;
    const res = await window.api('DELETE', `/collections/${colId}`);
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  async function _createCollection() {
    const name = await window._promptDialog('Collection name:');
    if (!name) return;
    const res = await window.api('POST', '/collections', { name: name.trim() });
    if (res.ok === false) { await window._alertDialog('Error: ' + res.error); return; }
    reload();
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  reload();
  return { reload };
}
```

- [ ] **Step 2: Verify syntax**

```bash
node --check web/static/api/views/collections-view.js
```

Expected: no output (exit code 0).

- [ ] **Step 3: Manual browser verification**

Run `python qaclan.py serve --port 7823`, open the web UI, select/create a project, and confirm:
1. An existing (or newly created) collection still shows its requests at the root, exactly as before.
2. Click "+ New Folder" at a collection's root — a folder appears with "+ New Request"/"+ New Folder" rows nested inside it.
3. Click "+ New Folder" again *inside* that folder — a sub-folder appears, nested one level deeper. Repeat once more to confirm depth is unlimited.
4. Click "+ New Request" inside a nested folder — the request editor opens; save it — reload the page and confirm the new request appears inside that exact folder (not at collection root).
5. Rename a folder via "✎" — name updates in place.
6. Drag a request onto the middle of a folder row — it moves inside that folder (test by expanding the folder and seeing the request appear there, and confirm it's gone from its old location).
7. Drag two requests within the same folder to swap their order — reload the page and confirm the new order persisted.
8. Attempt to drag a parent folder onto one of its own sub-folders — confirm the drop-highlight never appears for that combination (cycle guard blocks it visually).
9. Delete a folder that has a sub-folder and a request inside it — confirm a warning appears, and after confirming, everything inside is gone.
10. Drag one collection above another in the sidebar — reload the page and confirm the new collection order persisted.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "feat(api-ui): add nested folder tree and drag-and-drop reordering"
```

---

## Task 8: Thread `defaultFolderId` into request creation

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`
- Modify: `web/static/api/api-section.js`

**Interfaces:**
- Consumes: the 5th `defaultFolderId` argument now passed by `collections-view.js` (Task 7).
- Produces: `renderRequestEditor(container, requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId)` — a new request created from inside a folder is saved with that `folder_id`.

- [ ] **Step 1: Accept the new parameter in `request-editor-view.js`**

Replace:

```js
/**
 * renderRequestEditor(container, requestId, defaultCollectionId, collectionId, collectionEnvName)
 * requestId: string|null  (null = new request)
 * defaultCollectionId: string|null  (pre-select collection when creating new)
 * collectionId: string|null  (resolved collection for var loading)
 * collectionEnvName: string|null  (env bound to the collection)
 */
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null, collectionId = null, collectionEnvName = null) {
```

with:

```js
/**
 * renderRequestEditor(container, requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId)
 * requestId: string|null  (null = new request)
 * defaultCollectionId: string|null  (pre-select collection when creating new)
 * collectionId: string|null  (resolved collection for var loading)
 * collectionEnvName: string|null  (env bound to the collection)
 * defaultFolderId: string|null  (pre-select the folder a new request is created into)
 */
export async function renderRequestEditor(container, requestId = null, defaultCollectionId = null, collectionId = null, collectionEnvName = null, defaultFolderId = null) {
```

- [ ] **Step 2: Include `folder_id` in the create payload**

Replace:

```js
    if (defaultCollectionId) payload.collection_id = defaultCollectionId;

    const res = requestId
      ? await window.api('PUT', `/api-requests/${requestId}`, payload)
      : await window.api('POST', '/api-requests', payload);
```

with:

```js
    if (defaultCollectionId) payload.collection_id = defaultCollectionId;
    if (!requestId && defaultFolderId) payload.folder_id = defaultFolderId;

    const res = requestId
      ? await window.api('PUT', `/api-requests/${requestId}`, payload)
      : await window.api('POST', '/api-requests', payload);
```

(`folder_id` is only set on the create path — `defaultFolderId` reflects where the "+ New Request" click originated, not a value that should overwrite an existing request's folder on every save.)

- [ ] **Step 3: Thread the argument through `api-section.js`**

Replace:

```js
    const { reload: _reloadCollections } = renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId, defaultCollectionId, collectionId, collectionEnvName) => {
        _teardown();
        renderRequestEditor(mainEl(), requestId, defaultCollectionId, collectionId, collectionEnvName);
      },
      (runId, colId, colName) => _showRunDetail(runId, colId, colName),
      (col, runId) => _showCollectionDetail(col, runId)
    );
```

with:

```js
    const { reload: _reloadCollections } = renderCollectionsView(
      document.getElementById('api-collections-panel'),
      (requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId) => {
        _teardown();
        renderRequestEditor(mainEl(), requestId, defaultCollectionId, collectionId, collectionEnvName, defaultFolderId);
      },
      (runId, colId, colName) => _showRunDetail(runId, colId, colName),
      (col, runId) => _showCollectionDetail(col, runId)
    );
```

- [ ] **Step 4: Verify syntax**

```bash
node --check web/static/api/views/request-editor-view.js
node --check web/static/api/api-section.js
```

Expected: no output (exit code 0) for both.

- [ ] **Step 5: Manual browser verification**

In the running app, click "+ New Request" nested two folders deep inside a collection, fill in a name/URL, save. Reload the page and confirm the new request appears in that exact nested folder (not at the collection root). Then open an *existing* request from a different folder, change its name, save — confirm it stays in its original folder (proves `folder_id` is only applied on create, never silently overwritten on update).

- [ ] **Step 6: Commit**

```bash
git add web/static/api/views/request-editor-view.js web/static/api/api-section.js
git commit -m "feat(api-ui): create requests directly inside a target folder"
```

---

## Task 9: CSS for folder rows and drag affordances

**Files:**
- Modify: `web/static/style.css`

**Interfaces:**
- Consumes: nothing.
- Produces: `.api-folder-item`, `.api-folder-toggle`, `.api-folder-name`, `.api-folder-actions`, `.api-folder-children`, `.api-new-item-row`, `.api-drag-handle`, `.dragging`, `.drop-target-folder` — consumed by Task 7's markup.

- [ ] **Step 1: Add the styles**

In `web/static/style.css`, add directly after the existing `.api-request-item.active { ... }` block (the block ending around line 1485):

```css
/* Folder tree */
.api-tree-root { padding-left: 0; }
.api-folder-children { padding-left: 14px; }
.api-folder-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--text-primary);
}
.api-folder-item:hover { background: var(--bg-panel); }
.api-folder-toggle { font-size: 10px; color: var(--text-muted); width: 10px; flex-shrink: 0; }
.api-folder-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.api-folder-actions { display: none; gap: 2px; flex-shrink: 0; }
.api-folder-item:hover .api-folder-actions { display: flex; }
.api-new-item-row { opacity: 0.75; }
.api-new-item-row:hover { opacity: 1; }

/* Shared drag affordances (collections, folders, requests) */
.api-drag-handle {
  cursor: grab;
  color: var(--text-muted);
  font-size: 12px;
  flex-shrink: 0;
  user-select: none;
}
.api-drag-handle:active { cursor: grabbing; }
.dragging { opacity: 0.4; }
.drop-target-folder { background: var(--accent-subtle); outline: 2px dashed var(--accent); outline-offset: -2px; }
```

- [ ] **Step 2: Verify manually**

```bash
python qaclan.py serve --port 7823 &
sleep 2
curl -s http://localhost:7823/style.css | grep -c "api-folder-item"
kill %1
```

Expected: a number ≥ 1 (confirms the CSS was served, i.e. no syntax error broke the stylesheet load). Then in the browser, confirm folder rows are indented, show a grab-cursor drag handle, and highlight with a dashed accent outline when another row is dragged over their center.

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "feat(api-ui): style nested folder tree and drag affordances"
```

---

## Task 10: `folder_suggester.py` — one-level folder-name heuristic

**Files:**
- Create: `cli/api_discovery/folder_suggester.py`

**Interfaces:**
- Consumes: `url_normalizer.normalize_url(url) -> str` (existing — already collapses numeric/UUID/hex path segments to `{param}` placeholders, so this task adds no new ID-detection logic).
- Produces: `suggest_folder_name(url: str) -> str | None` — consumed by Task 11 (`discovery_service.py`).

- [ ] **Step 1: Write the module**

```python
from __future__ import annotations
import re
from cli.api_discovery.url_normalizer import normalize_url

_SKIP_SEGMENTS = {"api", "rest", "graphql", "gateway", "gql"}
_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$", re.IGNORECASE)


def suggest_folder_name(url: str) -> str | None:
    """Derive a one-level folder name from a request URL's first meaningful path
    segment. Reuses url_normalizer's dynamic-segment detection (IDs/UUIDs/hashes
    already collapsed to {param} placeholders) so numeric/UUID segments are
    skipped without re-implementing that heuristic. Returns None when no
    meaningful segment exists (root path, or every segment is a namespace/
    version/ID) — caller should leave the request at collection root."""
    path = normalize_url(url)
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith("{") and seg.endswith("}"):
            continue
        if seg.lower() in _SKIP_SEGMENTS:
            continue
        if _VERSION_RE.match(seg):
            continue
        return seg
    return None
```

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.api_discovery.folder_suggester import suggest_folder_name

assert suggest_folder_name('https://api.example.com/api/v1/users/123') == 'users'
assert suggest_folder_name('https://api.example.com/orders/5/cancel') == 'orders'
assert suggest_folder_name('https://api.example.com/api/v1/graphql') is None
assert suggest_folder_name('https://api.example.com/') is None
assert suggest_folder_name('https://api.example.com/550e8400-e29b-41d4-a716-446655440000') is None
print('PASS: suggest_folder_name derives one-level folder names')
"
```

Expected output: `PASS: suggest_folder_name derives one-level folder names`

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/folder_suggester.py
git commit -m "feat(discovery): add suggest_folder_name for one-level folder placement"
```

---

## Task 11: Discovery save integration — "Organize into folders by endpoint"

**Files:**
- Modify: `web/api/services/discovery_service.py`
- Modify: `web/api/routes/discovery.py`
- Modify: `web/static/api/views/request-review-modal.js`
- Modify: `web/static/api/views/variant-comparison-modal.js`

**Interfaces:**
- Consumes: `folder_suggester.suggest_folder_name` (Task 10), `FolderRepo.get_or_create_root` (Task 2).
- Produces: `_save_requests(project_id, requests, collection_id=None, organize_into_folders=False, folder_cache=None) -> int`; `save_library(project_id, groups, collection_name, include_in_docs=1, organize_into_folders=False) -> dict` (same return shape as before); routes accept `organize_into_folders` in their JSON body; `showVariantComparisonModal(groups, collectionName, includeInDocs, organizeIntoFolders)` (new 4th param).
- This task does **not** touch the CLI `qaclan api import` path (`DiscoveryService.import_openapi`/`import_postman`/`import_bruno`/`import_har`, which call `_save_requests` with its own pre-existing per-tag/per-folder collection grouping) — `organize_into_folders` defaults to `False`, and only the two routes below ever pass a non-default value. The web UI's HAR/OpenAPI/Postman/Bruno/cURL import views, by contrast, all route through `/discover/*/preview` → the same shared `request-review-modal.js` as Record APIs, so they *do* pick up the new checkbox — this is intended, not a scope leak, since it's the exact same modal.

- [ ] **Step 1: Add the shared folder-resolution helper and thread it through `_save_requests`**

In `web/api/services/discovery_service.py`, add after the `_MULTIPART_CDP_CAPTURE_SRC` block, directly before `_save_requests`:

```python
def _resolve_folder_id(project_id: str, collection_id: str, url: str, folder_cache: dict) -> str | None:
    """Get-or-create a root-level folder named after url's first meaningful path
    segment, memoized in folder_cache for the duration of one save call so that
    many requests mapping to the same folder name share one folder instead of
    creating duplicates."""
    from cli.api_discovery.folder_suggester import suggest_folder_name
    from web.api.repositories.folder_repo import FolderRepo

    name = suggest_folder_name(url)
    if not name:
        return None
    if name in folder_cache:
        return folder_cache[name]
    folder = FolderRepo().get_or_create_root(project_id, collection_id, name)
    folder_cache[name] = folder["id"]
    return folder["id"]
```

Replace the `_save_requests` function:

```python
def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None,
                    organize_into_folders: bool = False, folder_cache: dict | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    if folder_cache is None:
        folder_cache = {}
    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        if collection_id:
            data["collection_id"] = collection_id
            if organize_into_folders:
                data["folder_id"] = _resolve_folder_id(project_id, collection_id, data.get("url", ""), folder_cache)
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

        saved_req = _req_repo.create(project_id, data)

        # Sync to API docs if flagged (default: include)
        try:
            sync_doc_entry(project_id, {**data, 'id': saved_req['id']})
        except Exception as e:
            logger.warning("sync_doc_entry failed for %s: %s", data.get('url'), e)

        saved += 1
    return saved
```

- [ ] **Step 2: Thread it through `save_library`'s merge branch**

Replace:

```python
def save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1) -> dict:
```

with:

```python
def save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1,
                  organize_into_folders: bool = False) -> dict:
```

Replace:

```python
    col = _col_repo.create(project_id, collection_name)
    example_repo = RequestExampleRepo()
    saved = 0
```

with:

```python
    col = _col_repo.create(project_id, collection_name)
    example_repo = RequestExampleRepo()
    folder_cache: dict = {}
    saved = 0
```

Replace:

```python
            merged_req["collection_id"] = col["id"]
            merged_req["include_in_docs"] = include_in_docs
            for k in ("response_status", "response_headers", "response_body", "duration_ms"):
                merged_req.pop(k, None)
```

with:

```python
            merged_req["collection_id"] = col["id"]
            merged_req["include_in_docs"] = include_in_docs
            if organize_into_folders:
                merged_req["folder_id"] = _resolve_folder_id(project_id, col["id"], merged_req.get("url", ""), folder_cache)
            for k in ("response_status", "response_headers", "response_body", "duration_ms"):
                merged_req.pop(k, None)
```

Replace:

```python
            saved += _save_requests(project_id, reqs, collection_id=col["id"])
```

with:

```python
            saved += _save_requests(project_id, reqs, collection_id=col["id"],
                                     organize_into_folders=organize_into_folders, folder_cache=folder_cache)
```

- [ ] **Step 3: Thread `organize_into_folders` through both routes**

In `web/api/routes/discovery.py`, replace:

```python
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
```

with:

```python
        include_in_docs = int(data.get("include_in_docs", 1))
        organize_into_folders = bool(data.get("organize_into_folders", False))
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        # Stamp include_in_docs on each request
        for r in requests_list:
            r['include_in_docs'] = include_in_docs
        from web.api.services.discovery_service import _save_requests
        from web.api.repositories.collection_repo import CollectionRepo
        col = CollectionRepo().create(pid, collection_name)
        saved = _save_requests(pid, requests_list, collection_id=col["id"], organize_into_folders=organize_into_folders)
```

Replace:

```python
        include_in_docs = int(data.get("include_in_docs", 1))
        if not groups:
            return jsonify({"ok": False, "error": "No groups provided"}), 400
        from web.api.services.discovery_service import save_library
        result = save_library(pid, groups, collection_name, include_in_docs=include_in_docs)
```

with:

```python
        include_in_docs = int(data.get("include_in_docs", 1))
        organize_into_folders = bool(data.get("organize_into_folders", False))
        if not groups:
            return jsonify({"ok": False, "error": "No groups provided"}), 400
        from web.api.services.discovery_service import save_library
        result = save_library(pid, groups, collection_name, include_in_docs=include_in_docs,
                               organize_into_folders=organize_into_folders)
```

- [ ] **Step 4: Verify the backend manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
conn.commit()

from web.api.services.discovery_service import _save_requests
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

col = CollectionRepo().create(pid, 'Recorded')
reqs = [
    {'name': 'List users', 'method': 'GET', 'url': 'https://api.example.com/api/v1/users', 'headers': [], 'params': []},
    {'name': 'Get user', 'method': 'GET', 'url': 'https://api.example.com/api/v1/users/123', 'headers': [], 'params': []},
    {'name': 'List orders', 'method': 'GET', 'url': 'https://api.example.com/api/v1/orders', 'headers': [], 'params': []},
]
saved = _save_requests(pid, reqs, collection_id=col['id'], organize_into_folders=True)
assert saved == 3

rows = RequestRepo().list(pid, collection_id=col['id'])
users_folder_ids = {r['folder_id'] for r in rows if 'users' in r['url']}
assert len(users_folder_ids) == 1 and None not in users_folder_ids, users_folder_ids
orders_folder_ids = {r['folder_id'] for r in rows if 'orders' in r['url']}
assert len(orders_folder_ids) == 1 and None not in orders_folder_ids, orders_folder_ids
assert users_folder_ids != orders_folder_ids

# organize_into_folders=False (default) — untouched, matches every other existing caller
col2 = CollectionRepo().create(pid, 'Flat')
_save_requests(pid, reqs, collection_id=col2['id'])
rows2 = RequestRepo().list(pid, collection_id=col2['id'])
assert all(r['folder_id'] is None for r in rows2)
print('PASS: discovery save honors organize_into_folders, defaults to flat')
"
```

Expected output: `PASS: discovery save honors organize_into_folders, defaults to flat`

- [ ] **Step 5: Add the checkbox to the review modal**

In `web/static/api/views/request-review-modal.js`, replace:

```js
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
      <input type="checkbox" id="rev-include-docs" checked>
      Include in API Documentation
    </label>
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-subtle);">
```

with:

```js
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
      <input type="checkbox" id="rev-include-docs" checked>
      Include in API Documentation
    </label>
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;margin-top:6px;">
      <input type="checkbox" id="rev-organize-folders" checked>
      Organize into folders by endpoint
    </label>
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-subtle);">
```

- [ ] **Step 6: Read the checkbox and forward it on both save paths**

Replace:

```js
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value || 'flow';

      if (mode === 'library') {
        const plainRequests = selected.map(({ _idx, ...rest }) => rest);
        const grouped = await window.api('POST', '/discover/group-requests', { requests: plainRequests });
        if (grouped.ok === false) { await window._alertDialog('Grouping failed: ' + grouped.error); return; }
        window.closeModal();
        showVariantComparisonModal(grouped.groups, colName, includeInDocs);
        return;
      }

      const data = await window.api('POST', '/discover/save-requests', {
        requests: selected,
        collection_name: colName,
        include_in_docs: includeInDocs,
      });
```

with:

```js
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const organizeIntoFolders = document.getElementById('rev-organize-folders')?.checked ? 1 : 0;
      const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value || 'flow';

      if (mode === 'library') {
        const plainRequests = selected.map(({ _idx, ...rest }) => rest);
        const grouped = await window.api('POST', '/discover/group-requests', { requests: plainRequests });
        if (grouped.ok === false) { await window._alertDialog('Grouping failed: ' + grouped.error); return; }
        window.closeModal();
        showVariantComparisonModal(grouped.groups, colName, includeInDocs, organizeIntoFolders);
        return;
      }

      const data = await window.api('POST', '/discover/save-requests', {
        requests: selected,
        collection_name: colName,
        include_in_docs: includeInDocs,
        organize_into_folders: organizeIntoFolders,
      });
```

- [ ] **Step 7: Forward the flag from Modal 2**

In `web/static/api/views/variant-comparison-modal.js`, replace:

```js
export function showVariantComparisonModal(groups, collectionName, includeInDocs) {
```

with:

```js
export function showVariantComparisonModal(groups, collectionName, includeInDocs, organizeIntoFolders) {
```

Replace:

```js
      const data = await window.api('POST', '/discover/save-library', {
        groups: payloadGroups,
        collection_name: collectionName,
        include_in_docs: includeInDocs,
      });
```

with:

```js
      const data = await window.api('POST', '/discover/save-library', {
        groups: payloadGroups,
        collection_name: collectionName,
        include_in_docs: includeInDocs,
        organize_into_folders: organizeIntoFolders,
      });
```

- [ ] **Step 8: Verify syntax**

```bash
node --check web/static/api/views/request-review-modal.js
node --check web/static/api/views/variant-comparison-modal.js
```

Expected: no output (exit code 0) for both.

- [ ] **Step 9: Manual browser verification**

Run `python qaclan.py serve --port 7823`, run a Record APIs session (or HAR import) against a site with at least two distinct API resources (e.g. `/api/users/...` and `/api/orders/...`), and confirm:
1. The review modal shows "Organize into folders by endpoint", checked by default, next to "Include in API Documentation".
2. With it checked, choosing "Save as Flow" creates folders named after each resource and places requests inside them (check the sidebar tree).
3. With it checked, choosing "Save as Library" → Modal 2 → Save does the same, regardless of which groups were merged vs. kept separate.
4. Unchecking it before saving (either mode) saves everything flat at the collection root — no folders created.
5. Two requests that both suggest the same folder name (e.g. `GET /api/users` and `POST /api/users`) land in the *same* folder, not two folders with the same name.

- [ ] **Step 10: Commit**

```bash
git add web/api/services/discovery_service.py web/api/routes/discovery.py web/static/api/views/request-review-modal.js web/static/api/views/variant-comparison-modal.js
git commit -m "feat(discovery): suggest folders by endpoint on Save as Flow/Library"
```

---

## Task 12: End-to-end verification and full API-testing business-logic regression review

**Files:** none (verification only).

This task exists specifically to confirm the new folder/ordering columns and queries do not break any existing API-testing behavior — every consumer of `api_requests`/`api_collections` that this plan did not intentionally modify.

- [ ] **Step 1: Fresh nested-folder + drag-drop walkthrough**

1. `python qaclan.py serve --port 7823`, open the web UI, set an active project.
2. Create a collection "Checkout Flow". Create folder "Setup" at root, then folder "Cleanup" at root. Inside "Setup", create a sub-folder "Auth".
3. Add requests: "POST /login" inside Setup/Auth, "POST /cart" at Setup's root, "DELETE /cart" inside Cleanup.
4. Drag "POST /cart" so it moves inside Setup/Auth, ordered above "POST /login". Reload the page — confirm both persisted (folder placement and order).
5. Run the collection (▶) — confirm all three requests execute, and that "POST /cart" runs before "POST /login" (order now matches the drag from step 4), read from the run detail view's per-request order.
6. Delete the "Setup" folder — confirm the warning mentions its contents, and after confirming, "Auth" and both requests inside it are gone; "Cleanup" and "DELETE /cart" remain untouched.

- [ ] **Step 2: Regression pass over existing API-testing business logic**

Confirm each of the following still behaves exactly as before this plan (all are consumers of `api_requests`/`api_collections` that were deliberately NOT modified, aside from the two `ORDER BY` changes in Tasks 5–6):

1. **Suite builder "Add API Request" picker** (`web/static/app.js` suite-edit modal) — open a suite, click "+ Add API Request", confirm the dropdown still lists every request in the project regardless of which folder it's in.
2. **Collection detail page → "Set all requests → Inherit auth"** (`collection-detail-view.js`) — click it on a collection with folders, confirm it still updates every request in that collection (including ones nested in folders), since it fetches by `collection_id` alone.
3. **Bruno export** (`POST /api/collections/<id>/export`) — export a collection containing folders, confirm the zip still contains every request (folders are not reflected in the export path structure — that's expected, out of scope per the spec).
4. **Discovery "Save as Flow"/"Save as Library"** — run a HAR import or Record APIs session, uncheck "Organize into folders by endpoint" in the review modal, save to a new collection, confirm every created request lands at that collection's root (`folder_id` is `NULL`) — exactly as before Task 11 existed. Then repeat leaving the checkbox checked and confirm folders get created instead (this is the new behavior from Task 11, not a regression, but confirms the opt-out path still reproduces the old behavior exactly).
5. **CLI `qaclan api import`** (`--format openapi`/`postman`/`bruno`) — run one import, confirm it still saves via its own existing per-tag/per-folder collection grouping (separate collections, as before) with no `api_folders` rows created — this path never passes `organize_into_folders` and is untouched by Task 11.
6. **Variant library "Examples" dropdown** (`GET /api-requests/<id>/examples`) — open a request that has saved examples (from a prior "Save as Library" merge), confirm the dropdown still works — this endpoint never touches `folder_id`/`order_index`.
7. **Collection vars / auth config** — open a collection's Auth and Variables tabs, confirm both still load and save correctly (untouched code paths).
8. **Suite run report** — run a suite containing both scripts and API requests, confirm the unified timeline still shows correct order (this exercises `suite_items.order_index`, a separate column from the new `api_requests.order_index`, untouched by this plan).

- [ ] **Step 3: Confirm no server startup regression**

```bash
python qaclan.py --help
```

Expected: help text prints with no traceback (confirms `init_db()` — and the new `_migrate_nested_folders` — run cleanly on a real, possibly-already-migrated database).
