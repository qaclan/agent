# Collection Variable Secrets + Env/Collection Token Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let collection variables be marked/stored as secrets (mirroring `env_vars.is_secret`), and make resolved `{{var}}` tokens in the UI visually distinguishable by source (environment vs. collection) via color + letter badge, not just tooltip text.

**Architecture:** Backend: add `collection_vars.is_secret`, reuse `cli/crypto.py` Fernet encryption exactly as `env_vars` does (encrypt on write, mask in list responses, decrypt only at run-resolution time or via an explicit reveal endpoint). Import/export: Postman `"type":"secret"` maps to `is_secret`; both Postman and Bruno export write decrypted plaintext (explicit product decision — exported files are as sensitive as a `.env` file). Frontend: two existing hardcoded `is_secret: false` sites start forwarding the real value (masking then "just works" since `var-picker.js`/`inline-var-drop.js` are already source-agnostic); the collection-vars editor table gets a secret checkbox + reveal-on-uncheck, mirroring the existing env-var editor pattern in `web/static/app.js`; `var-token-overlay.js`'s token renderer gains a source-based CSS class + `data-src` badge (`E`/`C`) driven by the `group` field already present on every suggestion entry.

**Tech Stack:** Python/Flask backend, SQLite (via `cli/db.py`), vanilla JS frontend, `cryptography` (Fernet) for encryption. No automated test suite in this repo — every task's tests are manual verification commands (`python3 -c`, `curl`, or explicit browser steps).

## Global Constraints

- No automated test suite exists in this repo (per `CLAUDE.md`) — every task verifies manually, not via `pytest`.
- Reuse `cli/crypto.py`'s existing `encrypt`/`decrypt`/`is_encrypted` (Fernet, `enc:v1:` sentinel, key at `~/.qaclan/secret.key`) — do not add new crypto code.
- Secret collection vars export as **decrypted plaintext** into Postman JSON / Bruno `.bru` — this is an explicit, confirmed product decision, not an oversight. Do not add masking/omission logic on export.
- Do not add a CLI surface for editing collection var values — none exists today (verified: `cli/commands/api_cmd.py` only has `list`/`run`/`export`/`import`/`record` for the `api` group), and none is being requested.
- Do not change the single-active-environment-per-collection model (`api_collections.env_name`).
- Bruno's `.bru` collection-var format (`vars:pre-request` block) has no secret marker — Bruno import never sets `is_secret`; only Postman's `"type": "secret"` does.
- Per `CLAUDE.md`'s maintenance rule, any change touching `pre_script`/`post_script`/`qc.*`-adjacent variable behavior must be reflected in `docs/api-script-reference.md` in the same change (Task 10 covers this — no script-binding code changes are needed since `state`/`env` bindings already receive decrypted plaintext).

---

### Task 1: DB migration — `collection_vars.is_secret`

**Files:**
- Modify: `cli/db.py:29-156` (add migration call in `init_db()`), add new function after `_migrate_api_cloud_id`

**Interfaces:**
- Produces: `collection_vars` table gains column `is_secret INTEGER DEFAULT 0`, consumed by Task 2's repo layer.

- [ ] **Step 1: Add the migration function**

In `cli/db.py`, find the end of the `_migrate_api_cloud_id` function (it's the last migration function in the file, immediately followed by `_migrate_cascade`):

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


def _migrate_cascade(conn):
```

Insert a new function between them, so the result reads:

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


def _migrate_collection_var_secret(conn):
    """Add is_secret to collection_vars, mirroring env_vars.is_secret."""
    try:
        conn.execute("ALTER TABLE collection_vars ADD COLUMN is_secret INTEGER DEFAULT 0")
    except Exception:
        pass  # already exists
    conn.commit()


def _migrate_cascade(conn):
```

- [ ] **Step 2: Call it from `init_db()`**

In `cli/db.py`, find this line inside `init_db()`:

```python
    _migrate_api_cloud_id(conn)
```

It is the last line of the migration call sequence. Add a new line immediately after it:

```python
    _migrate_api_cloud_id(conn)
    _migrate_collection_var_secret(conn)
```

- [ ] **Step 3: Verify the column exists**

Run:
```bash
python3 -c "
from cli.db import init_db, get_conn
init_db()
conn = get_conn()
cols = [r[1] for r in conn.execute('PRAGMA table_info(collection_vars)')]
print(cols)
assert 'is_secret' in cols, 'is_secret column missing'
print('OK')
"
```
Expected output: a column list containing `is_secret`, then `OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat(api-db): add is_secret column to collection_vars

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Repo layer — encrypt/decrypt/reveal in `CollectionVarsRepo`

**Files:**
- Modify: `web/api/repositories/collection_vars_repo.py` (full rewrite, currently 54 lines)

**Interfaces:**
- Consumes: Task 1's `collection_vars.is_secret` column; `cli/crypto.encrypt`, `cli/crypto.decrypt`, `cli/crypto.is_encrypted`.
- Produces (consumed by Tasks 3, 4, 5, 7):
  - `CollectionVarsRepo.list(collection_id: str) -> list[dict]` — each dict now includes `is_secret` (0/1), value is raw (ciphertext if secret).
  - `CollectionVarsRepo.upsert(collection_id: str, key: str, initial_value: str, is_secret: bool = False, unchanged: bool = False) -> dict`
  - `CollectionVarsRepo.delete(collection_id: str, key: str) -> bool` (unchanged signature)
  - `CollectionVarsRepo.as_seed_dict(collection_id: str) -> dict[str, str]` — now decrypts secret values.
  - `CollectionVarsRepo.reveal(collection_id: str, key: str) -> str | None` — new method, returns decrypted plaintext or `None` if not found.

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `web/api/repositories/collection_vars_repo.py` with:

```python
from __future__ import annotations

from datetime import datetime, timezone

from cli.db import generate_id, get_conn
from cli.crypto import encrypt, decrypt, is_encrypted


class CollectionVarsRepo:

    def list(self, collection_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, key, initial_value, is_secret, created_at FROM collection_vars "
            "WHERE collection_id = ? ORDER BY key",
            (collection_id,),
        ).fetchall()
        return [
            {"id": r[0], "key": r[1], "initial_value": r[2], "is_secret": r[3], "created_at": r[4]}
            for r in rows
        ]

    def upsert(self, collection_id: str, key: str, initial_value: str,
               is_secret: bool = False, unchanged: bool = False) -> dict:
        conn = get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id, initial_value FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()

        if unchanged and is_secret and existing:
            # UI signalled no edit — retain existing ciphertext
            value = existing["initial_value"]
        else:
            raw = initial_value or ""
            if is_secret and raw and not is_encrypted(raw):
                value = encrypt(raw)
            else:
                value = raw

        is_secret_int = int(bool(is_secret))

        if existing:
            conn.execute(
                "UPDATE collection_vars SET initial_value = ?, is_secret = ? "
                "WHERE collection_id = ? AND key = ?",
                (value, is_secret_int, collection_id, key),
            )
            conn.commit()
            return {"id": existing["id"], "key": key, "initial_value": value, "is_secret": is_secret_int}

        vid = generate_id("cv")
        conn.execute(
            "INSERT INTO collection_vars (id, collection_id, key, initial_value, is_secret, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (vid, collection_id, key, value, is_secret_int, now),
        )
        conn.commit()
        return {"id": vid, "key": key, "initial_value": value, "is_secret": is_secret_int, "created_at": now}

    def delete(self, collection_id: str, key: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def as_seed_dict(self, collection_id: str) -> dict[str, str]:
        """Return {key: initial_value} for seeding state before a run, decrypting secrets."""
        result: dict[str, str] = {}
        for v in self.list(collection_id):
            val = v["initial_value"]
            if v["is_secret"] and val:
                val = decrypt(val)
            result[v["key"]] = val
        return result

    def reveal(self, collection_id: str, key: str) -> str | None:
        """Return decrypted plaintext for a single var, or None if it doesn't exist."""
        conn = get_conn()
        row = conn.execute(
            "SELECT initial_value, is_secret FROM collection_vars WHERE collection_id = ? AND key = ?",
            (collection_id, key),
        ).fetchone()
        if not row:
            return None
        value = row["initial_value"] or ""
        if row["is_secret"] and value:
            value = decrypt(value)
        return value
```

- [ ] **Step 2: Verify encrypt/decrypt/unchanged/seed-dict round trip**

Run (uses a throwaway `collection_id` that doesn't need to exist as a real row elsewhere, since this repo has no FK-existence check itself):
```bash
python3 -c "
from cli.db import init_db
init_db()
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from cli.crypto import is_encrypted

repo = CollectionVarsRepo()
cid = 'test_col_secret_verify'

# Create secret
r = repo.upsert(cid, 'API_KEY', 'sk-live-12345', is_secret=True)
assert is_encrypted(r['initial_value']), 'value should be encrypted at rest'
print('encrypted at rest: OK')

# List returns raw ciphertext + is_secret flag
rows = repo.list(cid)
row = next(v for v in rows if v['key'] == 'API_KEY')
assert row['is_secret'] == 1
assert is_encrypted(row['initial_value'])
print('list() raw ciphertext + is_secret flag: OK')

# Reveal decrypts
plain = repo.reveal(cid, 'API_KEY')
assert plain == 'sk-live-12345', f'expected plaintext, got {plain!r}'
print('reveal() decrypts: OK')

# as_seed_dict decrypts
seed = repo.as_seed_dict(cid)
assert seed['API_KEY'] == 'sk-live-12345'
print('as_seed_dict() decrypts: OK')

# unchanged=True with placeholder value preserves ciphertext
before = repo.list(cid)[0]['initial_value']
repo.upsert(cid, 'API_KEY', '••••••••', is_secret=True, unchanged=True)
after = repo.list(cid)[0]['initial_value']
assert before == after, 'unchanged upsert must not alter stored ciphertext'
print('unchanged=True preserves ciphertext: OK')

# Cleanup
repo.delete(cid, 'API_KEY')
print('ALL OK')
"
```
Expected output: six `OK` lines ending in `ALL OK`, no assertion errors.

- [ ] **Step 3: Commit**

```bash
git add web/api/repositories/collection_vars_repo.py
git commit -m "feat(api-repo): encrypt/decrypt collection var secrets, add reveal()

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Routes — mask on list, accept `is_secret`/`unchanged` on upsert, add reveal endpoint

**Files:**
- Modify: `web/api/routes/collections.py:1-188`

**Interfaces:**
- Consumes: Task 2's `CollectionVarsRepo.list/upsert/reveal`.
- Produces (consumed by Tasks 6, 7): `GET /api/collections/<col_id>/vars` (masks secret values), `PUT /api/collections/<col_id>/vars/<key>` (body: `{initial_value, is_secret, unchanged}`), `GET /api/collections/<col_id>/vars/<key>/reveal` (new).

- [ ] **Step 1: Add the masked-display constant**

In `web/api/routes/collections.py`, find:
```python
logger = logging.getLogger("qaclan.routes.collections")
bp = Blueprint("api_collections", __name__)
_svc = CollectionService()
_runner_svc = RunnerService()
```
Replace with:
```python
logger = logging.getLogger("qaclan.routes.collections")
bp = Blueprint("api_collections", __name__)
_svc = CollectionService()
_runner_svc = RunnerService()

MASKED_DISPLAY = "•" * 8
```

- [ ] **Step 2: Mask secret values in `list_collection_vars`**

Find:
```python
@bp.route("/api/collections/<col_id>/vars", methods=["GET"])
def list_collection_vars(col_id):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "vars": CollectionVarsRepo().list(col_id)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_collection_vars")
        return jsonify({"ok": False, "error": str(e)}), 500
```
Replace with:
```python
@bp.route("/api/collections/<col_id>/vars", methods=["GET"])
def list_collection_vars(col_id):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        rows = CollectionVarsRepo().list(col_id)
        for v in rows:
            if v.get("is_secret"):
                v["initial_value"] = MASKED_DISPLAY
        return jsonify({"ok": True, "vars": rows})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_collection_vars")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 3: Accept `is_secret`/`unchanged` in `upsert_collection_var`**

Find:
```python
@bp.route("/api/collections/<col_id>/vars/<path:key>", methods=["PUT"])
def upsert_collection_var(col_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        result = CollectionVarsRepo().upsert(col_id, key, body.get("initial_value", ""))
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True, "var": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("upsert_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500
```
Replace with:
```python
@bp.route("/api/collections/<col_id>/vars/<path:key>", methods=["PUT"])
def upsert_collection_var(col_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        body = request.get_json(force=True) or {}
        result = CollectionVarsRepo().upsert(
            col_id, key, body.get("initial_value", ""),
            is_secret=bool(body.get("is_secret", False)),
            unchanged=bool(body.get("unchanged", False)),
        )
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True, "var": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("upsert_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 4: Add the reveal endpoint**

Find:
```python
@bp.route("/api/collections/<col_id>/vars/<path:key>", methods=["DELETE"])
def delete_collection_var(col_id, key):
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        CollectionVarsRepo().delete(col_id, key)
        enqueue("collection_vars", col_id, "upsert")
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500
```
Add this new route immediately after it (still before the `export_collection` route):
```python
@bp.route("/api/collections/<col_id>/vars/<path:key>/reveal", methods=["GET"])
def reveal_collection_var(col_id, key):
    """Return the decrypted plaintext for a single secret collection var."""
    try:
        pid = _project_id()
        if not CollectionRepo().get(col_id, pid):
            return jsonify({"ok": False, "error": "Not found"}), 404
        value = CollectionVarsRepo().reveal(col_id, key)
        if value is None:
            return jsonify({"ok": False, "error": f'Variable "{key}" not found'}), 404
        resp = jsonify({"ok": True, "key": key, "value": value})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("reveal_collection_var")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 5: Verify against the running dev server**

Start the server in one terminal: `python qaclan.py serve --port 7823`. Ensure an active project exists (`python qaclan.py project use <name>` if needed) and create a test collection first via the UI or:
```bash
curl -s -X POST http://localhost:7823/api/collections -H "Content-Type: application/json" -d '{"name":"secret-test"}'
```
Note the returned `collection.id`, then run (replace `COL_ID`):
```bash
COL_ID=<paste id here>
curl -s -X PUT "http://localhost:7823/api/collections/$COL_ID/vars/TOKEN" -H "Content-Type: application/json" -d '{"initial_value":"top-secret-value","is_secret":true}'
curl -s "http://localhost:7823/api/collections/$COL_ID/vars"
curl -s "http://localhost:7823/api/collections/$COL_ID/vars/TOKEN/reveal"
```
Expected: the `PUT` response's `var.initial_value` is ciphertext (starts with `enc:v1:`); the list `GET` shows `"initial_value": "••••••••"` for `TOKEN`; the reveal `GET` shows `"value": "top-secret-value"`.

- [ ] **Step 6: Commit**

```bash
git add web/api/routes/collections.py
git commit -m "feat(api-routes): mask/reveal secret collection vars

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Postman import mapping + shared `_apply_collection_extras`

**Files:**
- Modify: `cli/api_discovery/postman_parser.py:181-184`
- Modify: `web/api/services/discovery_service.py:43-46`

**Interfaces:**
- Produces: `parse_postman(collection)["collection_vars"]` now shaped `{key: {"value": str, "is_secret": bool}}` (was `{key: str}`).
- Consumes: Task 2's `CollectionVarsRepo.upsert(..., is_secret=...)`.
- `_apply_collection_extras` must keep accepting the old flat-string shape too, since `bruno_parser.parse_bruno_collection_settings`'s `vars` output is unchanged (`{key: str}`) — both shapes flow through the same function.

- [ ] **Step 1: Read `type: "secret"` in the Postman parser**

In `cli/api_discovery/postman_parser.py`, find:
```python
    collection_vars = {
        v.get("key"): str(v.get("value", ""))
        for v in collection.get("variable", []) if v.get("key")
    }
```
Replace with:
```python
    collection_vars = {
        v.get("key"): {"value": str(v.get("value", "")), "is_secret": v.get("type") == "secret"}
        for v in collection.get("variable", []) if v.get("key")
    }
```

- [ ] **Step 2: Handle both dict and plain-string var shapes in `_apply_collection_extras`**

In `web/api/services/discovery_service.py`, find:
```python
def _apply_collection_extras(project_id: str, collection_id: str, collection_vars: dict[str, str] | None,
                              collection_auth: tuple[str, dict] | None) -> None:
    for key, value in (collection_vars or {}).items():
        _vars_repo.upsert(collection_id, key, str(value))
```
Replace with:
```python
def _apply_collection_extras(project_id: str, collection_id: str, collection_vars: dict | None,
                              collection_auth: tuple[str, dict] | None) -> None:
    for key, v in (collection_vars or {}).items():
        if isinstance(v, dict):
            value = str(v.get("value", ""))
            is_secret = bool(v.get("is_secret"))
        else:
            value = str(v)
            is_secret = False
        _vars_repo.upsert(collection_id, key, value, is_secret=is_secret)
```
(Leave the rest of the function — the `collection_auth` handling below — untouched.)

- [ ] **Step 3: Verify parse shape + end-to-end apply**

Run:
```bash
python3 -c "
from cli.api_discovery.postman_parser import parse_postman
collection = {
    'info': {'name': 'x'},
    'item': [],
    'variable': [
        {'key': 'BASE_URL', 'value': 'https://api.example.com', 'type': 'string'},
        {'key': 'API_TOKEN', 'value': 'sk-abc123', 'type': 'secret'},
    ],
}
parsed = parse_postman(collection)
cv = parsed['collection_vars']
assert cv['BASE_URL'] == {'value': 'https://api.example.com', 'is_secret': False}, cv['BASE_URL']
assert cv['API_TOKEN'] == {'value': 'sk-abc123', 'is_secret': True}, cv['API_TOKEN']
print('parse_postman shape: OK')
"
```
Then:
```bash
python3 -c "
from cli.db import init_db
init_db()
from web.api.services.discovery_service import _apply_collection_extras
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from cli.crypto import is_encrypted

cid = 'test_col_import_verify'
collection_vars = {
    'BASE_URL': {'value': 'https://api.example.com', 'is_secret': False},
    'API_TOKEN': {'value': 'sk-abc123', 'is_secret': True},
    'LEGACY_STR': 'plain-string-shape',
}
_apply_collection_extras('proj_x', cid, collection_vars, None)
rows = {v['key']: v for v in CollectionVarsRepo().list(cid)}
assert rows['BASE_URL']['is_secret'] == 0
assert rows['API_TOKEN']['is_secret'] == 1
assert is_encrypted(rows['API_TOKEN']['initial_value'])
assert rows['LEGACY_STR']['is_secret'] == 0
assert rows['LEGACY_STR']['initial_value'] == 'plain-string-shape'
print('ALL OK')
for k in rows: CollectionVarsRepo().delete(cid, k)
"
```
Expected: `parse_postman shape: OK` then `ALL OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/postman_parser.py web/api/services/discovery_service.py
git commit -m "feat(api-import): map Postman secret-type vars to is_secret

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Export — decrypt secret collection vars to Postman JSON / Bruno .bru

**Files:**
- Modify: `cli/api_discovery/postman_exporter.py:1-10,186-201`
- Modify: `cli/api_discovery/bruno_parser.py:1-10,446-462`

**Interfaces:**
- Consumes: Task 2's `CollectionVarsRepo.list()` output (`v["initial_value"]`, `v["is_secret"]`).

- [ ] **Step 1: Decrypt in the Postman exporter**

In `cli/api_discovery/postman_exporter.py`, find the import block at the top:
```python
from __future__ import annotations
import json

from cli.api_discovery.path_vars import revert_path_vars
from cli.api_discovery.script_rewrite import qc_script_to_foreign
```
Replace with:
```python
from __future__ import annotations
import json

from cli.api_discovery.path_vars import revert_path_vars
from cli.api_discovery.script_rewrite import qc_script_to_foreign
from cli.crypto import decrypt
```

Then find:
```python
    if collection_vars:
        result["variable"] = [{"key": v["key"], "value": v["initial_value"], "type": "string"} for v in collection_vars]
```
Replace with:
```python
    if collection_vars:
        result["variable"] = []
        for v in collection_vars:
            value = v["initial_value"]
            is_secret = bool(v.get("is_secret"))
            if is_secret and value:
                value = decrypt(value)
            result["variable"].append({
                "key": v["key"],
                "value": value,
                "type": "secret" if is_secret else "string",
            })
```

- [ ] **Step 2: Decrypt in the Bruno exporter**

In `cli/api_discovery/bruno_parser.py`, find the import block at the top:
```python
from __future__ import annotations
import json
import logging
import re

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc
```
Replace with:
```python
from __future__ import annotations
import json
import logging
import re

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc
from cli.crypto import decrypt
```

Then find:
```python
def collection_bru(collection: dict, collection_vars: list[dict]) -> str:
    """Build a collection.bru file: collection-level vars + auth."""
    lines = []
    if collection_vars:
        lines.append("vars:pre-request {")
        for v in collection_vars:
            lines.append(f"  {v['key']}: {v['initial_value']}")
        lines.append("}")
        lines.append("")
```
Replace with:
```python
def collection_bru(collection: dict, collection_vars: list[dict]) -> str:
    """Build a collection.bru file: collection-level vars + auth."""
    lines = []
    if collection_vars:
        lines.append("vars:pre-request {")
        for v in collection_vars:
            value = v["initial_value"]
            if v.get("is_secret") and value:
                value = decrypt(value)
            lines.append(f"  {v['key']}: {value}")
        lines.append("}")
        lines.append("")
```

- [ ] **Step 3: Verify decrypted export**

Run:
```bash
python3 -c "
from cli.crypto import encrypt
from cli.api_discovery.postman_exporter import to_postman_collection
from cli.api_discovery.bruno_parser import collection_bru

collection_vars = [
    {'key': 'BASE_URL', 'initial_value': 'https://api.example.com', 'is_secret': 0},
    {'key': 'API_TOKEN', 'initial_value': encrypt('sk-abc123'), 'is_secret': 1},
]
col = {'name': 'x', 'auth_type': 'none', 'auth_config': {}}

pm = to_postman_collection(col, [], [], collection_vars)
by_key = {v['key']: v for v in pm['variable']}
assert by_key['API_TOKEN']['value'] == 'sk-abc123', by_key['API_TOKEN']
assert by_key['API_TOKEN']['type'] == 'secret'
assert by_key['BASE_URL']['type'] == 'string'
print('postman export decrypts: OK')

bru = collection_bru(col, collection_vars)
assert 'API_TOKEN: sk-abc123' in bru, bru
assert 'enc:v1:' not in bru
print('bruno export decrypts: OK')
"
```
Expected: `postman export decrypts: OK` then `bruno export decrypts: OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/postman_exporter.py cli/api_discovery/bruno_parser.py
git commit -m "feat(api-export): decrypt secret collection vars on Postman/Bruno export

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — stop hardcoding `is_secret: false` for collection vars

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:60`
- Modify: `web/static/api/views/collection-detail-view.js:33`

**Interfaces:**
- Consumes: Task 3's `GET /api/collections/<col_id>/vars` now returning real `is_secret` per row.
- No new interfaces produced — `var-picker.js` and `inline-var-drop.js` already mask purely on `v.is_secret` regardless of `v.group`.

- [ ] **Step 1: Fix `request-editor-view.js`**

Find:
```js
    if (_effectiveCollectionId) {
      try {
        const res = await window.api('GET', `/collections/${_effectiveCollectionId}/vars`);
        (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: false, group: 'Collection' }));
      } catch(e) { /* no collection vars */ }
    }
```
Replace with:
```js
    if (_effectiveCollectionId) {
      try {
        const res = await window.api('GET', `/collections/${_effectiveCollectionId}/vars`);
        (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: !!v.is_secret, group: 'Collection' }));
      } catch(e) { /* no collection vars */ }
    }
```

- [ ] **Step 2: Fix `collection-detail-view.js`**

Find:
```js
    try {
      const res = await window.api('GET', `/collections/${col.id}/vars`);
      (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: false, group: 'Collection' }));
    } catch(e) { /* no collection vars */ }
```
Replace with:
```js
    try {
      const res = await window.api('GET', `/collections/${col.id}/vars`);
      (res.vars || []).forEach(v => results.push({ key: v.key, value: v.initial_value || '', is_secret: !!v.is_secret, group: 'Collection' }));
    } catch(e) { /* no collection vars */ }
```

- [ ] **Step 3: Verify in the browser**

Start the server (`python qaclan.py serve --port 7823`) if not already running. Using the `secret-test` collection from Task 3 (which already has a secret var `TOKEN`), open the web UI, navigate to that collection, open the Variables tab or a request editor scoped to that collection, and open the `{{` var picker / suggestion dropdown. Confirm the `TOKEN` entry under the "Collection" group shows a masked value (`••••••••`) rather than the plaintext.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/request-editor-view.js web/static/api/views/collection-detail-view.js
git commit -m "fix(api-ui): forward real is_secret for collection var suggestions

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Frontend — secret checkbox + reveal in the collection Variables tab

**Files:**
- Modify: `web/static/api/views/collection-detail-view.js:229-323` (the `_buildVarsTab` function)

**Interfaces:**
- Consumes: Task 3's `PUT /api/collections/<col_id>/vars/<key>` (body: `initial_value`/`is_secret`/`unchanged`) and `GET /api/collections/<col_id>/vars/<key>/reveal`.

- [ ] **Step 1: Replace `_buildVarsTab`**

Find the entire `_buildVarsTab` function (from `function _buildVarsTab(wrap) {` through its closing `}` right before the next section, i.e. lines 230–323 as they exist before this task) and replace it with:

```js
  // ── Variables tab ──
  function _buildVarsTab(wrap) {
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:12px;';

    const hdr = document.createElement('div');
    hdr.style.cssText = 'font-size:12px;color:var(--text-secondary);line-height:1.5;';
    hdr.textContent = 'Seed values for {{VAR}} tokens set by post-scripts (qc.set). Pre-populated before each run. Tick Secret to encrypt a value at rest.';
    wrap.appendChild(hdr);

    const tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden;';

    const varsTableEl = document.createElement('table');
    varsTableEl.style.cssText = 'width:100%;font-size:12px;border-collapse:collapse;';
    varsTableEl.innerHTML = `<thead><tr style="background:var(--bg-elevated);">
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Variable</th>
      <th style="text-align:left;padding:7px 10px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Initial value</th>
      <th style="width:56px;text-align:center;padding:7px 4px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border-default);">Secret</th>
      <th style="width:32px;border-bottom:1px solid var(--border-default);"></th>
    </tr></thead>`;
    const varsTbody = document.createElement('tbody');
    varsTableEl.appendChild(varsTbody);
    tableWrap.appendChild(varsTableEl);
    wrap.appendChild(tableWrap);

    const addVarBtn = document.createElement('button');
    addVarBtn.type = 'button';
    addVarBtn.className = 'btn btn-xs btn-ghost';
    addVarBtn.style.cssText = 'align-self:flex-start;font-size:11px;';
    addVarBtn.textContent = '+ Add Variable';
    wrap.appendChild(addVarBtn);

    function _addVarRow(v = { key: '', initial_value: '', is_secret: 0 }, isNew = false) {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid var(--border-subtle)';
      const isSecretInitially = !!v.is_secret;
      if (isSecretInitially) tr.dataset.masked = '1';

      const keyTd = document.createElement('td');
      keyTd.style.padding = '4px 6px';
      const keyInp = document.createElement('input');
      keyInp.type = 'text'; keyInp.placeholder = 'variable_name';
      keyInp.value = v.key || '';
      keyInp.className = 'input-sm';
      keyInp.style.cssText = 'font-family:var(--font-mono);font-size:11px;width:100%;background:transparent;border-color:transparent;';
      keyInp.addEventListener('focus', () => { keyInp.style.borderColor = ''; });
      keyInp.addEventListener('blur',  () => { keyInp.style.borderColor = 'transparent'; });
      keyTd.appendChild(keyInp);

      const valTd = document.createElement('td');
      valTd.style.padding = '4px 6px';
      const valInp = document.createElement('input');
      valInp.type = isSecretInitially ? 'password' : 'text';
      valInp.placeholder = '(empty — set by post-script)';
      valInp.value = v.initial_value || '';
      valInp.className = 'input-sm';
      valInp.style.cssText = 'font-size:12px;width:100%;background:transparent;border-color:transparent;';
      valInp.addEventListener('focus', () => {
        valInp.style.borderColor = '';
        if (tr.dataset.masked === '1' && !tr.dataset.edited) valInp.value = '';
      });
      valInp.addEventListener('input', () => { tr.dataset.edited = '1'; delete tr.dataset.masked; });
      valInp.addEventListener('blur',  () => { valInp.style.borderColor = 'transparent'; });
      valTd.appendChild(valInp);

      const secretTd = document.createElement('td');
      secretTd.style.cssText = 'padding:4px 6px;text-align:center;';
      const secretCb = document.createElement('input');
      secretCb.type = 'checkbox';
      secretCb.checked = isSecretInitially;
      secretCb.title = 'Secret';
      secretTd.appendChild(secretCb);

      const delTd = document.createElement('td');
      delTd.style.cssText = 'padding:4px 6px;text-align:center;';
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.style.cssText = 'background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;padding:0 4px;line-height:1;opacity:.6;';
      delBtn.textContent = '×';
      delBtn.onmouseenter = () => { delBtn.style.color = 'var(--danger)'; delBtn.style.opacity = '1'; };
      delBtn.onmouseleave = () => { delBtn.style.color = 'var(--text-muted)'; delBtn.style.opacity = '.6'; };
      delTd.appendChild(delBtn);

      async function _saveRow() {
        const key = keyInp.value.trim();
        if (!key) return;
        const is_secret = secretCb.checked ? 1 : 0;
        if (is_secret && tr.dataset.masked === '1') {
          await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, { is_secret, unchanged: true });
        } else {
          await window.api('PUT', `/collections/${col.id}/vars/${encodeURIComponent(key)}`, { initial_value: valInp.value, is_secret });
        }
        _refreshKnownVarNames();
      }
      async function _deleteRow() {
        const key = keyInp.value.trim();
        if (key) await window.api('DELETE', `/collections/${col.id}/vars/${encodeURIComponent(key)}`);
        tr.remove();
        _refreshKnownVarNames();
      }
      async function _onSecretToggle() {
        // Un-ticking a stored-masked secret: fetch decrypted value so the user sees it,
        // but only if the row is still masked (user hasn't already typed a replacement).
        if (!secretCb.checked && tr.dataset.masked === '1') {
          const key = keyInp.value.trim();
          if (key) {
            try {
              const res = await window.api('GET', `/collections/${col.id}/vars/${encodeURIComponent(key)}/reveal`);
              if (res && res.ok) valInp.value = res.value || '';
            } catch (e) { /* reveal failed, leave placeholder as-is */ }
          }
        }
        valInp.type = secretCb.checked ? 'password' : 'text';
        delete tr.dataset.masked;
        tr.dataset.edited = '1';
        await _saveRow();
      }

      keyInp.addEventListener('blur', _saveRow);
      valInp.addEventListener('blur', _saveRow);
      secretCb.addEventListener('change', _onSecretToggle);
      delBtn.onclick = _deleteRow;

      tr.appendChild(keyTd); tr.appendChild(valTd); tr.appendChild(secretTd); tr.appendChild(delTd);
      varsTbody.appendChild(tr);
      if (isNew) keyInp.focus();
    }

    addVarBtn.onclick = () => _addVarRow({ key: '', initial_value: '', is_secret: 0 }, true);

    window.api('GET', `/collections/${col.id}/vars`).then(res => {
      (res.vars || []).forEach(v => _addVarRow(v));
    });
  }
```

- [ ] **Step 2: Verify in the browser**

With the dev server running and the `secret-test` collection open on its Variables tab:
1. Confirm the existing `TOKEN` row shows a masked (`type="password"`) value input with its Secret checkbox ticked.
2. Click "+ Add Variable", type a key `NEW_SECRET`, type a value `hunter2`, tick the Secret checkbox, then click elsewhere (blur) — confirm no errors in the browser console and the request goes through (Network tab: `PUT /api/collections/<id>/vars/NEW_SECRET` with `is_secret: 1`).
3. Reload the page, reopen the Variables tab — confirm `NEW_SECRET` shows masked.
4. Untick its Secret checkbox — confirm the input reveals `hunter2` (a `GET .../reveal` call fires in the Network tab) and switches to plain text.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/collection-detail-view.js
git commit -m "feat(api-ui): secret checkbox + reveal-on-uncheck for collection vars

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: CSS — source hue custom property

**Files:**
- Modify: `web/static/style.css:1-76` (root palette + light-theme override)

**Interfaces:**
- Produces: `--var-col` CSS custom property, consumed by Task 9's `.var-tok--col` rule.

- [ ] **Step 1: Add the dark (default) value**

In `web/static/style.css`, find:
```css
  --warning:         #f59e0b;
  --warning-bg:      rgba(245,158,11,0.10);

  --font-ui:   'Outfit', sans-serif;
```
Replace with:
```css
  --warning:         #f59e0b;
  --warning-bg:      rgba(245,158,11,0.10);
  --var-col:         #a855f7;

  --font-ui:   'Outfit', sans-serif;
```

- [ ] **Step 2: Add the light-theme override**

Find:
```css
  --danger-bg:       rgba(239,68,68,0.10);
  --danger-border:   rgba(239,68,68,0.28);
  --warning-bg:      rgba(245,158,11,0.14);

  --shadow-sm:   0 1px 2px rgba(15,23,42,0.06);
```
Replace with:
```css
  --danger-bg:       rgba(239,68,68,0.10);
  --danger-border:   rgba(239,68,68,0.28);
  --warning-bg:      rgba(245,158,11,0.14);
  --var-col:         #9333ea;

  --shadow-sm:   0 1px 2px rgba(15,23,42,0.06);
```

- [ ] **Step 3: Add the token color + badge rules**

Find:
```css
.var-token-overlay--multiline { white-space: pre-wrap; word-break: break-word; }
.var-tok--ok { color: var(--success); }
.var-tok--missing { color: var(--danger); }
```
Replace with:
```css
.var-token-overlay--multiline { white-space: pre-wrap; word-break: break-word; }
.var-tok--ok { color: var(--success); }
.var-tok--missing { color: var(--danger); }
.var-tok--env { color: var(--accent); }
.var-tok--col { color: var(--var-col); }
.var-tok[data-src]::after {
  content: attr(data-src);
  font-size: 8px;
  vertical-align: super;
  opacity: .75;
  margin-left: 1px;
}
```
(`.var-tok--env`/`.var-tok--col` must stay listed after `.var-tok--ok` in the file — a token carries both classes at once, e.g. `var-tok var-tok--ok var-tok--env`, and CSS source order breaks the tie between equal-specificity single-class selectors.)

- [ ] **Step 4: Verify no syntax errors**

Run:
```bash
python3 -c "
content = open('web/static/style.css').read()
assert content.count('{') == content.count('}'), 'unbalanced braces'
assert '--var-col:' in content
assert '.var-tok--env' in content
assert '.var-tok--col' in content
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add web/static/style.css
git commit -m "style(api-ui): add env/collection source hue custom property

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: `var-token-overlay.js` — color + badge resolved tokens by source

**Files:**
- Modify: `web/static/api/components/var-token-overlay.js:86-102` (the `_render` function)

**Interfaces:**
- Consumes: Task 8's `.var-tok--env`/`.var-tok--col`/`.var-tok[data-src]::after` CSS rules; the `group` field (`'Environment' | 'Collection'`) already present on every entry returned by `getVarsList()` (unchanged by this plan — it's been there since the original suggestion-merging code).

- [ ] **Step 1: Replace `_render`**

In `web/static/api/components/var-token-overlay.js`, find:
```js
  function _render() {
    const value = el.value;
    const list = getVarsList ? getVarsList() : null;
    let html = '';
    let last = 0;
    tokenSpansIn(value).forEach(({ name, start, end }) => {
      html += escapeHtml(value.slice(last, start));
      const known = list ? list.some(v => v.key === name) : null;
      const cls = known == null ? 'var-tok' : known ? 'var-tok var-tok--ok' : 'var-tok var-tok--missing';
      html += `<span class="${cls}">${escapeHtml(value.slice(start, end))}</span>`;
      last = end;
    });
    html += escapeHtml(value.slice(last));
    overlay.innerHTML = html;
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  }
```
Replace with:
```js
  function _render() {
    const value = el.value;
    const list = getVarsList ? getVarsList() : null;
    let html = '';
    let last = 0;
    tokenSpansIn(value).forEach(({ name, start, end }) => {
      html += escapeHtml(value.slice(last, start));
      const entry = list ? list.find(v => v.key === name) || null : null;
      const known = list ? !!entry : null;
      let cls;
      let badge = '';
      if (known == null) {
        cls = 'var-tok';
      } else if (!known) {
        cls = 'var-tok var-tok--missing';
      } else if (entry.group === 'Environment') {
        cls = 'var-tok var-tok--ok var-tok--env';
        badge = ' data-src="E"';
      } else if (entry.group === 'Collection') {
        cls = 'var-tok var-tok--ok var-tok--col';
        badge = ' data-src="C"';
      } else {
        cls = 'var-tok var-tok--ok';
      }
      html += `<span class="${cls}"${badge}>${escapeHtml(value.slice(start, end))}</span>`;
      last = end;
    });
    html += escapeHtml(value.slice(last));
    overlay.innerHTML = html;
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  }
```
(No change needed to the `mousemove` hover handler's `overlay.querySelectorAll('.var-tok--ok, .var-tok--missing')` selector — env/collection tokens still carry the `var-tok--ok` class alongside their new source modifier, so they remain hoverable and the tooltip's existing `entry.group` display keeps working unchanged.)

- [ ] **Step 2: Verify in the browser**

With the dev server running: open a request editor for a request in the `secret-test` collection, and bind that collection to an environment that has at least one var (create one via the Environments page if needed, e.g. `ENV_HOST`). In the URL or a header value field, type `{{ENV_HOST}}` and `{{TOKEN}}` (the collection var from earlier tasks) and `{{NOT_DEFINED}}`. Confirm:
- `{{ENV_HOST}}` renders in blue (`--accent`) with a small "E" badge.
- `{{TOKEN}}` renders in violet (`--var-col`) with a small "C" badge.
- `{{NOT_DEFINED}}` renders in red, no badge.
- Hovering each still shows the existing tooltip (value + group label).
Toggle the app's light/dark theme switch and confirm both hues stay legible against the background in both modes.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/var-token-overlay.js
git commit -m "feat(api-ui): color/badge resolved {{var}} tokens by source

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Docs — `docs/api-script-reference.md`

**Files:**
- Modify: `docs/api-script-reference.md:207-219`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Add a "Variable secrecy" section**

Find:
```markdown
## What writes to `state.json` / how downstream steps read it

Any `qc.set("key", value)` call (script or extractor) lands in `qaclan_vars` inside the shared run state. Downstream:
- Other API requests read it via `{{key}}` in URL/headers/params/body.
- Playwright scripts read it via `os.environ["QACLAN_STATE_key"]`.

---

## Known gaps (accurate as of this writing — update if closed)
```
Replace with:
```markdown
## What writes to `state.json` / how downstream steps read it

Any `qc.set("key", value)` call (script or extractor) lands in `qaclan_vars` inside the shared run state. Downstream:
- Other API requests read it via `{{key}}` in URL/headers/params/body.
- Playwright scripts read it via `os.environ["QACLAN_STATE_key"]`.

---

## Variable secrecy

Both environment variables (`env_vars.is_secret`) and collection variables (`collection_vars.is_secret`) support secret storage: Fernet-encrypted at rest (`cli/crypto.py`, key at `~/.qaclan/secret.key`), masked as `••••••••` in list/suggestion responses, and decrypted only when actually needed — at request-resolution time (`resolve_vars`, fed by `env_loader.load_env_vars` for environment vars and `CollectionVarsRepo.as_seed_dict` for collection vars) or via an explicit reveal endpoint (`GET /api/envs/<env_name>/vars/<key>/reveal`, `GET /api/collections/<col_id>/vars/<key>/reveal`), both responding with `Cache-Control: no-store`.

**Export caveat:** exporting a collection to Postman JSON or Bruno `.bru` writes secret collection vars as **decrypted plaintext** (matching the fidelity-first behavior of the rest of collection export). Treat an exported file containing secret vars with the same care as a `.env` file — avoid committing it to git or pasting it into chat.

---

## Known gaps (accurate as of this writing — update if closed)
```

- [ ] **Step 2: Update the "no 4-tier scoping" gap note**

Find:
```markdown
- No 4-tier variable scoping (global/collection/environment/local) — one flat `qaclan_vars` bucket plus the active environment's `env_vars`. Likely intentional given the local-first/single-active-environment model rather than a bug.
```
Replace with:
```markdown
- No 4-tier variable scoping (global/collection/environment/local) — one flat `qaclan_vars` bucket plus the active environment's `env_vars`. Likely intentional given the local-first/single-active-environment model rather than a bug. Both tiers support secret values (`is_secret`) — see "Variable secrecy" above.
```

- [ ] **Step 3: Verify the doc renders sensibly**

Run:
```bash
grep -n "Variable secrecy\|Known gaps" docs/api-script-reference.md
```
Expected: both headings present, "Variable secrecy" appearing before "Known gaps".

- [ ] **Step 4: Commit**

```bash
git add docs/api-script-reference.md
git commit -m "docs: document collection var secrets and export plaintext caveat

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
