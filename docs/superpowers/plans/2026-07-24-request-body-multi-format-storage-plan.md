# Request Body Multi-Format Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `api_requests` body storage from one shared `body_type`+`body` slot into `body_type` (pure mode-selector, unchanged) plus 4 dedicated content columns (`body` raw-only, new `body_form`/`body_multipart`/`body_graphql`), so switching body-format tabs or picking "none" in the request editor never discards another format's saved content, and discovery/import never leaks one format's content into another's tab.

**Architecture:** Every layer that reads/writes `body`/`body_type` — SQLite schema, the request repo, the runner, 5 discovery parsers, 2 exporters, the variant grouper, 2 frontend views, and the cloud sync push/pull pair — gets the same one-line-per-type change: route content into the field matching its format instead of the single shared `body` column. No new abstraction; this mirrors the exact pattern already used for every other per-request field in this codebase (plain TEXT columns, JSON-stringified by the producer, read back the same way).

**Tech Stack:** Python 3, Flask, SQLite (`cli/db.py`), vanilla JS frontend (`web/static/api/`), httpx (`cli/api_runner.py`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-24-request-body-multi-format-storage-design.md`.
- Task 16 spec: `docs/superpowers/specs/2026-07-25-body-format-active-indicator-design.md` — depends on Tasks 11-13 (frontend already reading the correct per-type column).
- Companion server-repo plan: `qaclan-server/docs/superpowers/plans/2026-07-24-request-body-multi-format-storage-plan.md` — **must be deployed to production before this plan's Task 11 (cloud sync push) ships to users**, per the spec's rollout-ordering requirement. Every other task in this plan (1-10, 12-13, 15) has no cross-repo dependency and can proceed regardless of server deploy status.
- No automated test suite exists in this repo (confirmed in `CLAUDE.md`: "There are no automated tests or linting configured"). Every "test" step below is a real runnable command — `sqlite3` queries, `python3 -c` snippets, `curl` against the local Flask dev server (`python qaclan.py serve --port 7823`), or a manual browser check — not a persisted pytest file.
- Column naming/types must exactly match the server repo's Postgres columns: `body_form TEXT DEFAULT NULL`, `body_multipart TEXT DEFAULT NULL`, `body_graphql TEXT DEFAULT NULL`.
- `api_request_examples` is explicitly out of scope (per spec) — it has no `body_type` discriminator and is an immutable snapshot, not a tabbed editing surface. Do not touch it in any task below.
- Task order matters: Tasks 1-3 (schema → repo → runner) must land before any parser/frontend task, since those tasks' verification steps depend on the new columns existing and being persistable. Tasks 4-10 (parsers/exporters/grouper) and 11-14 (frontend/sync) can be done in any order relative to each other once 1-3 are done, but are listed in a sensible dependency order below.

---

### Task 1: DB schema migration (`cli/db.py`)

**Files:**
- Modify: `cli/db.py:134-156` (migration call list), add new `_migrate_request_body_columns` function near the other `_migrate_*` functions, `cli/db.py:358-383` (`CREATE TABLE IF NOT EXISTS api_requests` — for brand-new DBs only)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `api_requests.body_form`, `.body_multipart`, `.body_graphql` columns, available to every later task.

- [ ] **Step 1: Add the new migration function**

Add this function anywhere among the other `_migrate_*` functions in `cli/db.py` (e.g. right after `_migrate_collection_var_secret`, whichever is currently last):

```python
def _migrate_request_body_columns(conn):
    """Split api_requests.body into per-mode columns — body stays raw-only,
    body_form/body_multipart/body_graphql hold the other 3 modes. body_type
    stays a pure mode-selector. Backfill only runs once, on the transition
    that first adds these columns — it must never re-run on a DB that
    already has them, since a legitimately-saved row can have non-null
    body alongside a non-raw body_type once every save writes all 4
    fields (see docs/superpowers/specs/2026-07-24-request-body-multi-format-storage-design.md)."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(api_requests)").fetchall()}
    needs_backfill = "body_form" not in existing_cols
    # ALTER + backfill commit as one transaction — otherwise a crash between
    # the ALTERs and the UPDATEs leaves the columns present but the backfill
    # permanently skipped (needs_backfill is derived from column presence).
    conn.execute("BEGIN")
    try:
        for col in ("body_form", "body_multipart", "body_graphql"):
            try:
                conn.execute(f"ALTER TABLE api_requests ADD COLUMN {col} TEXT DEFAULT NULL")
            except Exception:
                pass
        if needs_backfill:
            conn.execute("UPDATE api_requests SET body_form = body, body = NULL WHERE body_type = 'form' AND body IS NOT NULL")
            conn.execute("UPDATE api_requests SET body_multipart = body, body = NULL WHERE body_type = 'multipart' AND body IS NOT NULL")
            conn.execute("UPDATE api_requests SET body_graphql = body, body = NULL WHERE body_type = 'graphql' AND body IS NOT NULL")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

- [ ] **Step 2: Register it in the migration call list**

In `cli/db.py`, change the end of the call list (currently ending at `_migrate_collection_var_secret(conn)`):
```python
    _migrate_collection_var_secret(conn)
```
to:
```python
    _migrate_collection_var_secret(conn)
    _migrate_request_body_columns(conn)
```

- [ ] **Step 3: Add the 3 columns to the `CREATE TABLE` block (new-DB path)**

In `cli/db.py`, inside `_migrate_api_tables`, change:
```python
            body_type TEXT DEFAULT NULL,
            body TEXT DEFAULT NULL,
```
to:
```python
            body_type TEXT DEFAULT NULL,
            body TEXT DEFAULT NULL,
            body_form TEXT DEFAULT NULL,
            body_multipart TEXT DEFAULT NULL,
            body_graphql TEXT DEFAULT NULL,
```

- [ ] **Step 4: Run the migration against your local DB**

Run: `python qaclan.py status` (any CLI invocation triggers `init_db()` per this repo's convention — `status` is a cheap read-only one)
Expected: no traceback.

- [ ] **Step 5: Verify the columns exist**

Run: `sqlite3 ~/.qaclan/qaclan.db ".schema api_requests"`
Expected: output includes `body_form TEXT DEFAULT NULL`, `body_multipart TEXT DEFAULT NULL`, `body_graphql TEXT DEFAULT NULL`.

- [ ] **Step 6: Verify the backfill against a seeded row**

```bash
sqlite3 ~/.qaclan/qaclan.db <<'EOF'
INSERT INTO api_requests (id, project_id, name, method, url, headers, params, path_params, body_type, body, auth_type, auth_config, assertions, created_at)
SELECT 'apireq_backfilltest', id, 'Backfill test', 'POST', 'https://example.test', '[]', '[]', '[]', 'multipart', '[{"key":"file","value":"x","enabled":true}]', 'inherit', '{}', '[]', datetime('now')
FROM projects LIMIT 1;
EOF
python qaclan.py status
sqlite3 ~/.qaclan/qaclan.db "SELECT body_type, body, body_multipart FROM api_requests WHERE id = 'apireq_backfilltest';"
```
Expected: since the row was inserted *after* the migration already ran once, this row won't retroactively backfill on its own — the migration function only fires at `init_db()` time and its UPDATEs are safe to rerun (idempotent, gated on `body IS NOT NULL`). To actually see the backfill fire, insert the row and manually re-run just the UPDATE statements from Step 1 directly via `sqlite3`, then confirm `body_multipart` now holds the JSON array and `body` is `NULL`. This confirms the UPDATE logic itself works correctly; the migration-registration (Step 2) is what makes it fire automatically for any row that existed before a user upgrades.

Clean up: `sqlite3 ~/.qaclan/qaclan.db "DELETE FROM api_requests WHERE id = 'apireq_backfilltest';"`

- [ ] **Step 7: Commit**

```bash
git add cli/db.py
git commit -m "$(cat <<'EOF'
feat(db): add body_form/body_multipart/body_graphql columns

Splits api_requests body storage into per-mode columns with a
backfill for existing form/multipart/graphql rows, so body_type no
longer implies a single shared body column that different formats
silently overwrite.
EOF
)"
```

---

### Task 2: Repo layer (`web/api/repositories/request_repo.py`)

**Files:**
- Modify: `web/api/repositories/request_repo.py:9-31` (`_DEFAULTS`), `:109-126` (`create()`), `:131-146` (`update()`)

**Interfaces:**
- Consumes: columns from Task 1.
- Produces: `RequestRepo.create()`/`.update()` now persist `body_form`/`body_multipart`/`body_graphql` when present in the input dict — consumed by every parser/frontend task below.

- [ ] **Step 1: Add defaults**

Change:
```python
    "body_type": None,
    "body": None,
```
to:
```python
    "body_type": None,
    "body": None,
    "body_form": None,
    "body_multipart": None,
    "body_graphql": None,
```

- [ ] **Step 2: Extend the `create()` INSERT**

Change:
```python
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
```
to:
```python
        conn.execute(
            "INSERT INTO api_requests (id, project_id, feature_id, collection_id, folder_id, order_index, name, method, url, "
            "headers, params, path_params, body_type, body, body_form, body_multipart, body_graphql, auth_type, auth_config, pre_script, pre_lang, pre_extractor, "
            "post_script, post_lang, post_extractor, request_schema, response_schema, "
            "assertions, follow_redirects, timeout_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, project_id,
             merged.get("feature_id"), collection_id, folder_id, order_index,
             merged.get("name", "Unnamed"), merged["method"], merged["url"],
             merged["headers"], merged["params"], merged["path_params"],
             merged["body_type"], merged["body"], merged["body_form"], merged["body_multipart"], merged["body_graphql"],
             merged["auth_type"], merged["auth_config"],
             merged["pre_script"], merged["pre_lang"], merged["pre_extractor"],
             merged["post_script"], merged["post_lang"], merged["post_extractor"],
             merged.get("request_schema"), merged.get("response_schema"),
             merged["assertions"], merged["follow_redirects"], merged["timeout_ms"],
             now),
        )
```

- [ ] **Step 3: Extend the `update()` field list**

Change:
```python
        fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "pre_extractor", "post_script",
                  "post_lang", "post_extractor", "request_schema", "response_schema",
                  "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id", "folder_id"]
```
to:
```python
        fields = ["name", "method", "url", "headers", "params", "path_params", "body_type", "body",
                  "body_form", "body_multipart", "body_graphql",
                  "auth_type", "auth_config", "pre_script", "pre_lang", "pre_extractor", "post_script",
                  "post_lang", "post_extractor", "request_schema", "response_schema",
                  "assertions", "follow_redirects", "timeout_ms",
                  "feature_id", "collection_id", "folder_id"]
```

- [ ] **Step 4: Verify with a Python one-liner**

Run:
```bash
python3 -c "
from cli.db import init_db
init_db()
from web.api.repositories.request_repo import RequestRepo
from cli.config import get_active_project_id
repo = RequestRepo()
pid = get_active_project_id()
assert pid, 'run `qaclan project use <name>` first to set an active project'
r = repo.create(pid, {
    'name': 'repo layer test', 'method': 'POST', 'url': 'https://example.test',
    'body_type': 'multipart', 'body_multipart': '[{\"key\":\"f\",\"value\":\"x\",\"enabled\":true}]',
})
assert r['body_type'] == 'multipart'
assert r['body_multipart'] == '[{\"key\":\"f\",\"value\":\"x\",\"enabled\":true}]'
assert r['body'] is None
print('create OK:', r['id'])
ok = repo.update(r['id'], {'body_type': 'graphql', 'body_graphql': '{\"query\":\"{a}\",\"variables\":{}}'})
assert ok
fetched = repo.get(r['id'], pid)
assert fetched['body_graphql'] == '{\"query\":\"{a}\",\"variables\":{}}'
assert fetched['body_multipart'] == '[{\"key\":\"f\",\"value\":\"x\",\"enabled\":true}]', 'update must not clear other modes'
print('update OK — body_multipart survived a body_type switch to graphql')
"
```
Expected: prints both OK lines, no `AssertionError`/traceback. The last assertion is the actual bug-fix behavior — updating `body_type`/`body_graphql` alone must not touch `body_multipart`, since `update()`'s dynamic `SET` clause only includes keys present in the input dict.

Clean up: `sqlite3 ~/.qaclan/qaclan.db "DELETE FROM api_requests WHERE name = 'repo layer test';"`

- [ ] **Step 5: Commit**

```bash
git add web/api/repositories/request_repo.py
git commit -m "$(cat <<'EOF'
feat(api): persist body_form/body_multipart/body_graphql in RequestRepo
EOF
)"
```

---

### Task 3: Runner dispatch (`cli/api_runner.py`)

**Files:**
- Modify: `cli/api_runner.py:544-546`

**Interfaces:**
- Consumes: columns from Task 1, values from Task 2's `RequestRepo.get()` (called upstream of this function to build `req`).
- Produces: correct body content sent over the wire regardless of which column the active mode's content lives in.

- [ ] **Step 1: Change the body-column lookup**

Change:
```python
        # 4. Build request body
        body_type = req.get("body_type")
        body_raw = req.get("body")
```
to:
```python
        # 4. Build request body
        body_type = req.get("body_type")
        _body_column = {"raw": "body", "form": "body_form", "multipart": "body_multipart", "graphql": "body_graphql"}.get(body_type)
        body_raw = req.get(_body_column) if _body_column else None
```

Nothing else in this function changes — every branch below (`if body_type == "raw" and body_raw:` etc., lines 551-614) already keys off `body_type`/`body_raw` exactly as before; only where `body_raw` comes from moves.

- [ ] **Step 2: Verify multipart execution still works end-to-end**

Create a request with a multipart body via the repo (reusing the pattern from Task 2 Step 4), then run it:
```bash
python3 -c "
from cli.db import init_db
init_db()
from web.api.repositories.request_repo import RequestRepo
from cli.config import get_active_project_id
from web.api.services.runner_service import RunnerService
repo = RequestRepo()
pid = get_active_project_id()
r = repo.create(pid, {
    'name': 'runner dispatch test', 'method': 'POST', 'url': 'https://httpbin.org/post',
    'body_type': 'multipart', 'body_multipart': '[{\"key\":\"field1\",\"value\":\"hello\",\"enabled\":true}]',
})
result = RunnerService().run_request(r['id'], pid)
print('status:', result.get('status_code'))
import json
body = json.loads(result.get('response_body') or '{}')
assert body.get('form', {}).get('field1') == 'hello', body
print('multipart body correctly sent:', body.get('form'))
"
```
(Requires network access to httpbin.org; if unavailable in your environment, substitute any local echo endpoint, or inspect the constructed `files`/`data` via a debugger breakpoint instead of a live call — the point is confirming `body_raw` is correctly sourced from `body_multipart`, not that httpbin itself is reachable.)
Expected: prints `multipart body correctly sent: {'field1': 'hello'}`.

Clean up: `sqlite3 ~/.qaclan/qaclan.db "DELETE FROM api_requests WHERE name = 'runner dispatch test';"`

- [ ] **Step 3: Commit**

```bash
git add cli/api_runner.py
git commit -m "$(cat <<'EOF'
fix(runner): read body from the column matching body_type

body_raw previously always came from the single body column; now
form/multipart/graphql each read their own dedicated column.
EOF
)"
```

---

### Task 4: HAR parser (`cli/api_discovery/har_parser.py`)

**Files:**
- Modify: `cli/api_discovery/har_parser.py:282-332` (body_type detection), `:384-400` (results dict)

**Interfaces:**
- Consumes: nothing new (pure function, no DB access).
- Produces: parsed-request dicts carrying `body_form`/`body_multipart`/`body_graphql` keys instead of collapsing everything into `body` — consumed by `web/api/services/discovery_service.py`'s `_save_requests`/`save_library` (no code change needed there, per Task 9 note below — it does `data = dict(req)`, a generic passthrough).

- [ ] **Step 1: Route multipart/form content to dedicated variables**

Change:
```python
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
            elif "multipart" in mime:
                body_type = "multipart"
                params_list = []
                for p in post_data.get("params", []):
                    name = p.get("name", "")
                    file_name = p.get("fileName")
                    if file_name:
                        raw_value = p.get("value", "")
                        encoded = base64.b64encode(raw_value.encode("utf-8", errors="surrogateescape")).decode("ascii")
                        field = {"key": name, "value": encoded, "enabled": True, "filename": file_name, "is_file": True}
                        if p.get("contentType"):
                            field["content_type"] = p.get("contentType")
                    else:
                        field = {"key": name, "value": p.get("value", ""), "enabled": True}
                    params_list.append(field)
                if not params_list:
                    raw_bytes = post_data.get("_raw_bytes")
                    if raw_bytes is not None:
                        params_list = parse_multipart_bytes(mime, raw_bytes)
                    else:
                        params_list = parse_multipart_text(mime, text)
                body = json.dumps(params_list)
            elif "form" in mime:
                body_type = "form"
                params_list = []
                for p in post_data.get("params", []):
                    k = p.get("name", "")
                    v = p.get("value", "")
                    params_list.append({"key": k, "value": v, "enabled": True})
                if not params_list and text:
                    # Playwright's HAR recorder leaves postData.params empty for
                    # urlencoded bodies too (not just multipart) — fall back to
                    # decoding the raw text, same as the multipart branch above.
                    params_list = [
                        {"key": k, "value": v, "enabled": True}
                        for k, v in parse_qsl(text, keep_blank_values=True)
                    ]
                body = json.dumps(params_list)
            else:
                body_type = "raw"
                body = text
```
to:
```python
        # Body
        body_type = None
        body = None
        body_form = None
        body_multipart = None
        post_data = req.get("postData", {})
        if post_data:
            mime = post_data.get("mimeType", "")
            text = post_data.get("text", "")
            if "json" in mime:
                body_type = "raw"
                body = text
            elif "multipart" in mime:
                body_type = "multipart"
                params_list = []
                for p in post_data.get("params", []):
                    name = p.get("name", "")
                    file_name = p.get("fileName")
                    if file_name:
                        raw_value = p.get("value", "")
                        encoded = base64.b64encode(raw_value.encode("utf-8", errors="surrogateescape")).decode("ascii")
                        field = {"key": name, "value": encoded, "enabled": True, "filename": file_name, "is_file": True}
                        if p.get("contentType"):
                            field["content_type"] = p.get("contentType")
                    else:
                        field = {"key": name, "value": p.get("value", ""), "enabled": True}
                    params_list.append(field)
                if not params_list:
                    raw_bytes = post_data.get("_raw_bytes")
                    if raw_bytes is not None:
                        params_list = parse_multipart_bytes(mime, raw_bytes)
                    else:
                        params_list = parse_multipart_text(mime, text)
                body_multipart = json.dumps(params_list)
            elif "form" in mime:
                body_type = "form"
                params_list = []
                for p in post_data.get("params", []):
                    k = p.get("name", "")
                    v = p.get("value", "")
                    params_list.append({"key": k, "value": v, "enabled": True})
                if not params_list and text:
                    # Playwright's HAR recorder leaves postData.params empty for
                    # urlencoded bodies too (not just multipart) — fall back to
                    # decoding the raw text, same as the multipart branch above.
                    params_list = [
                        {"key": k, "value": v, "enabled": True}
                        for k, v in parse_qsl(text, keep_blank_values=True)
                    ]
                body_form = json.dumps(params_list)
            else:
                body_type = "raw"
                body = text
```

- [ ] **Step 2: Add the 2 new keys to the results dict**

Change:
```python
        results.append({
            "name": name,
            "method": method,
            "url": base_url,
            "headers": headers,
            "params": params,
            "body_type": body_type,
            "body": body,
            "auth_type": "none",
```
to:
```python
        results.append({
            "name": name,
            "method": method,
            "url": base_url,
            "headers": headers,
            "params": params,
            "body_type": body_type,
            "body": body,
            "body_form": body_form,
            "body_multipart": body_multipart,
            "auth_type": "none",
```

(No `body_graphql` here — HAR capture never produces a GraphQL body_type, since it's parsed purely from HTTP MIME types, which have no GraphQL signal. Leave it absent from this dict; downstream consumers already treat a missing key as `None` via `.get()`.)

- [ ] **Step 3: Verify with a synthetic HAR entry**

```bash
python3 -c "
from cli.api_discovery.har_parser import parse_har
import json
har = {'log': {'entries': [{
    'request': {
        'method': 'POST', 'url': 'https://example.test/upload',
        'headers': [], 'queryString': [],
        'postData': {'mimeType': 'multipart/form-data; boundary=x', 'params': [{'name': 'field1', 'value': 'hello'}]},
    },
    'response': {'status': 200, 'content': {}, 'headers': []},
    'time': 10,
}]}}
results = parse_har(har)
r = results[0]
assert r['body_type'] == 'multipart'
assert r['body'] is None
assert json.loads(r['body_multipart']) == [{'key': 'field1', 'value': 'hello', 'enabled': True}]
print('HAR multipart routing OK')
"
```
Expected: prints `HAR multipart routing OK`, no `AssertionError`. (`parse_har(har_json: dict) -> list[dict]` — takes the parsed HAR dict directly, not a JSON string; confirmed against `cli/api_discovery/har_parser.py:243`.)

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/har_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): route HAR form/multipart bodies to dedicated fields

Previously both landed in the shared body column, which then leaked
into the Raw tab in the request editor.
EOF
)"
```

---

### Task 5: Postman import (`cli/api_discovery/postman_parser.py`)

**Files:**
- Modify: `cli/api_discovery/postman_parser.py:46-73` (`_convert_body`), `:142,147-164` (call site + results dict)

**Interfaces:**
- Consumes: nothing new.
- Produces: same shape as Task 4 — `body_form`/`body_multipart`/`body_graphql` keys instead of one shared `body`.

- [ ] **Step 1: Change `_convert_body` to return a 4-tuple**

Change:
```python
def _convert_body(body_obj: dict, warnings: list[str], context: str) -> tuple[str | None, str | None]:
    if not body_obj:
        return None, None
    mode = body_obj.get("mode", "")
    if mode == "raw":
        return "raw", body_obj.get("raw", "")
    if mode == "urlencoded":
        items = [{"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True}
                 for p in body_obj.get("urlencoded", []) if not p.get("disabled", False)]
        return "form", json.dumps(items)
    if mode == "formdata":
        items = []
        for p in body_obj.get("formdata", []):
            if p.get("disabled", False):
                continue
            if p.get("type") == "file":
                items.append({
                    "key": p.get("key", ""), "value": "", "enabled": True,
                    "is_file": True, "filename": p.get("src") or "", "content_type": p.get("contentType"),
                })
                warnings.append(f"{context}: formdata file field '{p.get('key')}' needs manual re-attach")
            else:
                items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True, "is_file": False})
        return "multipart", json.dumps(items)
    if mode == "graphql":
        gql = body_obj.get("graphql", {})
        return "graphql", json.dumps({"query": gql.get("query", ""), "variables": gql.get("variables", {})})
    return None, None
```
to:
```python
def _convert_body(body_obj: dict, warnings: list[str], context: str) -> dict:
    """Returns {'body_type', 'body', 'body_form', 'body_multipart', 'body_graphql'} —
    exactly one of the 4 body_* keys is non-None, matching body_type."""
    empty = {"body_type": None, "body": None, "body_form": None, "body_multipart": None, "body_graphql": None}
    if not body_obj:
        return empty
    mode = body_obj.get("mode", "")
    if mode == "raw":
        return {**empty, "body_type": "raw", "body": body_obj.get("raw", "")}
    if mode == "urlencoded":
        items = [{"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True}
                 for p in body_obj.get("urlencoded", []) if not p.get("disabled", False)]
        return {**empty, "body_type": "form", "body_form": json.dumps(items)}
    if mode == "formdata":
        items = []
        for p in body_obj.get("formdata", []):
            if p.get("disabled", False):
                continue
            if p.get("type") == "file":
                items.append({
                    "key": p.get("key", ""), "value": "", "enabled": True,
                    "is_file": True, "filename": p.get("src") or "", "content_type": p.get("contentType"),
                })
                warnings.append(f"{context}: formdata file field '{p.get('key')}' needs manual re-attach")
            else:
                items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True, "is_file": False})
        return {**empty, "body_type": "multipart", "body_multipart": json.dumps(items)}
    if mode == "graphql":
        gql = body_obj.get("graphql", {})
        return {**empty, "body_type": "graphql", "body_graphql": json.dumps({"query": gql.get("query", ""), "variables": gql.get("variables", {})})}
    return empty
```

- [ ] **Step 2: Update the call site**

Change:
```python
    body_type, body = _convert_body(req.get("body", {}), warnings, context)
    auth_type, auth_config = _convert_auth(req.get("auth"), warnings, context)
    pre_script, post_script, script_warnings = _convert_events(item)
    warnings.extend(f"{context}: {w}" for w in script_warnings)

    results.append({
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": query_params,
        "path_params": path_params,
        "body_type": body_type,
        "body": body,
        "auth_type": auth_type,
```
to:
```python
    body_fields = _convert_body(req.get("body", {}), warnings, context)
    auth_type, auth_config = _convert_auth(req.get("auth"), warnings, context)
    pre_script, post_script, script_warnings = _convert_events(item)
    warnings.extend(f"{context}: {w}" for w in script_warnings)

    results.append({
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": query_params,
        "path_params": path_params,
        **body_fields,
        "auth_type": auth_type,
```

- [ ] **Step 3: Verify each Postman body mode round-trips**

```bash
python3 -c "
from cli.api_discovery.postman_parser import _convert_body
import json
w = []
r = _convert_body({'mode': 'formdata', 'formdata': [{'key': 'f', 'value': 'v', 'type': 'text'}]}, w, 'ctx')
assert r['body_type'] == 'multipart'
assert json.loads(r['body_multipart']) == [{'key': 'f', 'value': 'v', 'enabled': True, 'is_file': False}]
assert r['body'] is None and r['body_form'] is None and r['body_graphql'] is None
r2 = _convert_body({'mode': 'raw', 'raw': '{\"a\":1}'}, w, 'ctx')
assert r2 == {'body_type': 'raw', 'body': '{\"a\":1}', 'body_form': None, 'body_multipart': None, 'body_graphql': None}
r3 = _convert_body({}, w, 'ctx')
assert r3 == {'body_type': None, 'body': None, 'body_form': None, 'body_multipart': None, 'body_graphql': None}
print('postman _convert_body OK')
"
```
Expected: prints `postman _convert_body OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/postman_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): route Postman import bodies to dedicated fields per mode
EOF
)"
```

---

### Task 6: cURL import (`cli/api_discovery/curl_parser.py`)

**Files:**
- Modify: `cli/api_discovery/curl_parser.py:184-211`

**Interfaces:**
- Consumes: nothing new.
- Produces: same shape — curl only ever produces `"multipart"` or `"raw"` (urlencoded `-d` data folds into `"raw"` today, unchanged by this task — see note below), so this task only needs to route the multipart branch.

- [ ] **Step 1: Route multipart to `body_multipart`**

Change:
```python
    body_type = None
    body = None
    if is_multipart:
        body_type = "multipart"
        body = json.dumps(form_rows)
    elif raw_data_parts:
        if force_query:
            for part in raw_data_parts:
                for k, v in parse_qsl(part, keep_blank_values=True):
                    params.append({"key": k, "value": v, "enabled": True})
        else:
            body_type = "raw"
            body = "&".join(raw_data_parts) if len(raw_data_parts) > 1 else raw_data_parts[0]

    if not method:
        method = "POST" if (raw_data_parts and not force_query) or is_multipart else "GET"

    return {
        "name": f"{method} {split.path or '/'}",
        "method": method,
        "url": clean_url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": auth_type,
        "auth_config": auth_config,
    }
```
to:
```python
    body_type = None
    body = None
    body_multipart = None
    if is_multipart:
        body_type = "multipart"
        body_multipart = json.dumps(form_rows)
    elif raw_data_parts:
        if force_query:
            for part in raw_data_parts:
                for k, v in parse_qsl(part, keep_blank_values=True):
                    params.append({"key": k, "value": v, "enabled": True})
        else:
            body_type = "raw"
            body = "&".join(raw_data_parts) if len(raw_data_parts) > 1 else raw_data_parts[0]

    if not method:
        method = "POST" if (raw_data_parts and not force_query) or is_multipart else "GET"

    return {
        "name": f"{method} {split.path or '/'}",
        "method": method,
        "url": clean_url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "body_multipart": body_multipart,
        "auth_type": auth_type,
        "auth_config": auth_config,
    }
```

(curl's urlencoded `-d` bodies staying folded into `"raw"` is pre-existing behavior, unchanged by this plan — it's a separate, orthogonal gap from the bug this plan fixes, since a `"raw"`-typed body never leaks into another tab. Not in scope here.)

- [ ] **Step 2: Verify with a multipart curl command**

```bash
python3 -c "
from cli.api_discovery.curl_parser import parse_curl
import json
results = parse_curl('curl -X POST https://example.test/upload -F \"field1=hello\"')
r = results[0]
assert r['body_type'] == 'multipart'
assert r['body'] is None
assert json.loads(r['body_multipart'])[0]['key'] == 'field1'
print('curl multipart routing OK')
"
```
(`parse_curl(text: str) -> list[dict]` — returns a list even for one command; confirmed against `cli/api_discovery/curl_parser.py:214`.)
Expected: prints `curl multipart routing OK`.

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/curl_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): route curl multipart bodies to body_multipart field
EOF
)"
```

---

### Task 7: OpenAPI import (`cli/api_discovery/openapi_parser.py`)

**Files:**
- Modify: `cli/api_discovery/openapi_parser.py:81-127` (OpenAPI 3.x form branch)

**Interfaces:**
- Consumes: nothing new.
- Produces: same shape — Swagger 2.0 (`_parse_swagger2`) only ever produces `"raw"`, so it needs no change (verify this in Step 2). OpenAPI 3.x produces `"raw"` or `"form"`, so only the `"form"` branch needs routing.

- [ ] **Step 1: Route the form branch to `body_form`**

Change:
```python
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
```
to:
```python
            # Request body
            body_type = None
            body = None
            body_form = None
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
                body_form = json.dumps(form_items)

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
                "body_form": body_form,
                "auth_type": "none",
                "auth_config": "{}",
                "assertions": json.dumps(assertions),
                "collection_name": collection_name,
            })
```

- [ ] **Step 2: Confirm Swagger 2.0 needs no change**

Read `cli/api_discovery/openapi_parser.py`'s `_parse_swagger2` function (~lines 131-182) and confirm its `body_type` is only ever set to `"raw"` (via the `p_in == "body"` branch) or left `None` — no `"form"`/`"multipart"`/`"graphql"` assignment exists there. If this has changed since the spec was written, apply the same routing pattern as Step 1; otherwise, no edit needed to this function.

- [ ] **Step 3: Verify with a synthetic OpenAPI 3 spec**

```bash
python3 -c "
from cli.api_discovery.openapi_parser import parse_openapi
import json
spec = {
    'openapi': '3.0.0', 'info': {'title': 't'}, 'servers': [{'url': 'https://example.test'}],
    'paths': {'/submit': {'post': {'requestBody': {'content': {
        'application/x-www-form-urlencoded': {'schema': {'type': 'object', 'properties': {'name': {'type': 'string', 'example': 'x'}}}}
    }}, 'responses': {'200': {}}}}},
}
results = parse_openapi(spec)
r = next(r for r in results if r['url'].endswith('/submit'))
assert r['body_type'] == 'form'
assert r['body'] is None
assert json.loads(r['body_form'])[0]['key'] == 'name'
print('openapi form routing OK')
"
```
(`parse_openapi(spec: dict) -> list[dict]` — takes the parsed spec dict directly, dispatches to `_parse_openapi3`/`_parse_swagger2` based on an `"openapi"`/`"swagger"` key; confirmed against `cli/api_discovery/openapi_parser.py:185`.)
Expected: prints `openapi form routing OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/openapi_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): route OpenAPI form bodies to body_form field
EOF
)"
```

---

### Task 8: Bruno import (`cli/api_discovery/bruno_parser.py` — parser side)

**Files:**
- Modify: `cli/api_discovery/bruno_parser.py:192-256`

**Interfaces:**
- Consumes: nothing new.
- Produces: same shape as prior parser tasks.

- [ ] **Step 1: Route form/multipart/graphql sections to dedicated fields**

Change:
```python
    # body section
    body_type = None
    body = None
    if "body:json" in sections:
        body_type, body = "raw", "\n".join(sections["body:json"]).strip()
    elif any(k in sections for k in ("body:text", "body:xml", "body:sparql")):
        key = next(k for k in ("body:text", "body:xml", "body:sparql") if k in sections)
        body_type, body = "raw", "\n".join(sections[key]).strip()
    elif "body:form-urlencoded" in sections:
        body_type = "form"
        body = json.dumps(_parse_kv_block(sections["body:form-urlencoded"]))
    elif "body:multipart-form" in sections:
        body_type = "multipart"
        items = []
        for kv in _parse_kv_block(sections["body:multipart-form"]):
            is_file = kv["value"].startswith("@file(")
            if is_file:
                warnings.append(f"{context}: multipart file field '{kv['key']}' needs manual re-attach")
            items.append({**kv, "is_file": is_file})
        body = json.dumps(items)
    elif "body:graphql" in sections:
        gql_vars = {}
        if "body:graphql:vars" in sections:
            raw_vars = "\n".join(sections["body:graphql:vars"]).strip()
            try:
                gql_vars = json.loads(raw_vars or "{}")
            except json.JSONDecodeError:
                # Not JSON — fall back to Bru's own key: value dict-block
                # syntax (same as params:query/headers), since it's
                # ambiguous which form a given Bruno version writes here.
                gql_vars = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections["body:graphql:vars"]) if kv["enabled"]}
        body_type = "graphql"
        body = json.dumps({"query": "\n".join(sections["body:graphql"]).strip(), "variables": gql_vars})
```
to:
```python
    # body section
    body_type = None
    body = None
    body_form = None
    body_multipart = None
    body_graphql = None
    if "body:json" in sections:
        body_type, body = "raw", "\n".join(sections["body:json"]).strip()
    elif any(k in sections for k in ("body:text", "body:xml", "body:sparql")):
        key = next(k for k in ("body:text", "body:xml", "body:sparql") if k in sections)
        body_type, body = "raw", "\n".join(sections[key]).strip()
    elif "body:form-urlencoded" in sections:
        body_type = "form"
        body_form = json.dumps(_parse_kv_block(sections["body:form-urlencoded"]))
    elif "body:multipart-form" in sections:
        body_type = "multipart"
        items = []
        for kv in _parse_kv_block(sections["body:multipart-form"]):
            is_file = kv["value"].startswith("@file(")
            if is_file:
                warnings.append(f"{context}: multipart file field '{kv['key']}' needs manual re-attach")
            items.append({**kv, "is_file": is_file})
        body_multipart = json.dumps(items)
    elif "body:graphql" in sections:
        gql_vars = {}
        if "body:graphql:vars" in sections:
            raw_vars = "\n".join(sections["body:graphql:vars"]).strip()
            try:
                gql_vars = json.loads(raw_vars or "{}")
            except json.JSONDecodeError:
                # Not JSON — fall back to Bru's own key: value dict-block
                # syntax (same as params:query/headers), since it's
                # ambiguous which form a given Bruno version writes here.
                gql_vars = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections["body:graphql:vars"]) if kv["enabled"]}
        body_type = "graphql"
        body_graphql = json.dumps({"query": "\n".join(sections["body:graphql"]).strip(), "variables": gql_vars})
```

- [ ] **Step 2: Add the 3 new keys to the result dict**

Change:
```python
    result = {
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "path_params": path_params,
        "body_type": body_type,
        "body": body,
        "auth_type": auth_type,
```
to:
```python
    result = {
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "path_params": path_params,
        "body_type": body_type,
        "body": body,
        "body_form": body_form,
        "body_multipart": body_multipart,
        "body_graphql": body_graphql,
        "auth_type": auth_type,
```

- [ ] **Step 3: Verify with a synthetic .bru file**

```bash
python3 -c "
from cli.api_discovery.bruno_parser import parse_bruno
bru = '''
meta {
  name: test
  type: http
  seq: 1
}

post {
  url: https://example.test/submit
  body: multipart-form
}

body:multipart-form {
  field1: hello
}
'''
result = parse_bruno(bru)
r = result['requests'][0]
assert r['body_type'] == 'multipart'
assert r['body'] is None
import json
assert json.loads(r['body_multipart'])[0]['key'] == 'field1'
print('bruno multipart routing OK')
"
```
(`parse_bruno(bru_text: str) -> dict` — returns `{"requests": [...], "warnings": [...]}`, not the request dict directly; confirmed against `cli/api_discovery/bruno_parser.py:159,259`.)
Expected: prints `bruno multipart routing OK`.

- [ ] **Step 4: Commit**

```bash
git add cli/api_discovery/bruno_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): route Bruno import bodies to dedicated fields per mode
EOF
)"
```

---

### Task 9: Exporters (`cli/api_discovery/postman_exporter.py`, `bruno_parser.py` — exporter side)

**Files:**
- Modify: `cli/api_discovery/postman_exporter.py:55-76,143-145`
- Modify: `cli/api_discovery/bruno_parser.py:372-405` (`_bru_body_block`, exporter call site at line 340)

**Interfaces:**
- Consumes: `body_form`/`body_multipart`/`body_graphql` fields as now persisted via Task 2 (`RequestRepo.get()`/`.list()` return them for any saved request).
- Produces: correct Postman/Bruno collection exports for form/multipart/graphql requests — previously these read from `body`, which is now `None` for those types.

- [ ] **Step 1: Fix `postman_exporter.py`'s `_body_block`**

Change:
```python
def _body_block(body_type: str | None, body: str | None) -> dict | None:
    if not body_type or body is None:
        return None
    if body_type == "raw":
        return {"mode": "raw", "raw": body}
    if body_type == "graphql":
        gql = _as_dict(body)
        return {"mode": "graphql", "graphql": {"query": gql.get("query", ""), "variables": gql.get("variables", {})}}
    items = _as_list(body)
    if body_type == "form":
        return {"mode": "urlencoded", "urlencoded": [
            {"key": i.get("key", ""), "value": i.get("value", ""), "disabled": not i.get("enabled", True)} for i in items
        ]}
    if body_type == "multipart":
        formdata = []
        for i in items:
            if i.get("is_file"):
                formdata.append({"key": i.get("key", ""), "type": "file", "src": i.get("filename") or None, "disabled": not i.get("enabled", True)})
            else:
                formdata.append({"key": i.get("key", ""), "value": i.get("value", ""), "type": "text", "disabled": not i.get("enabled", True)})
        return {"mode": "formdata", "formdata": formdata}
    return None
```
to:
```python
def _body_block(body_type: str | None, body: str | None, body_form: str | None = None,
                 body_multipart: str | None = None, body_graphql: str | None = None) -> dict | None:
    if not body_type:
        return None
    if body_type == "raw":
        if body is None:
            return None
        return {"mode": "raw", "raw": body}
    if body_type == "graphql":
        if body_graphql is None:
            return None
        gql = _as_dict(body_graphql)
        return {"mode": "graphql", "graphql": {"query": gql.get("query", ""), "variables": gql.get("variables", {})}}
    if body_type == "form":
        if body_form is None:
            return None
        items = _as_list(body_form)
        return {"mode": "urlencoded", "urlencoded": [
            {"key": i.get("key", ""), "value": i.get("value", ""), "disabled": not i.get("enabled", True)} for i in items
        ]}
    if body_type == "multipart":
        if body_multipart is None:
            return None
        items = _as_list(body_multipart)
        formdata = []
        for i in items:
            if i.get("is_file"):
                formdata.append({"key": i.get("key", ""), "type": "file", "src": i.get("filename") or None, "disabled": not i.get("enabled", True)})
            else:
                formdata.append({"key": i.get("key", ""), "value": i.get("value", ""), "type": "text", "disabled": not i.get("enabled", True)})
        return {"mode": "formdata", "formdata": formdata}
    return None
```

- [ ] **Step 2: Update the call site**

Change:
```python
    body = _body_block(req.get("body_type"), req.get("body"))
    if body:
        item_request["body"] = body
```
to:
```python
    body = _body_block(
        req.get("body_type"), req.get("body"),
        req.get("body_form"), req.get("body_multipart"), req.get("body_graphql"),
    )
    if body:
        item_request["body"] = body
```

- [ ] **Step 3: Fix `bruno_parser.py`'s `_bru_body_block`**

Change:
```python
def _bru_body_block(body_type: str | None, body: str | None) -> list[str]:
    import json as _json
    if not body_type or body is None:
        return []
    if body_type == "raw":
        return ["body:json {"] + [f"  {l}" for l in body.splitlines()] + ["}"]
    if body_type == "graphql":
        try:
            gql = _json.loads(body)
        except (ValueError, TypeError):
            gql = {"query": "", "variables": {}}
        out = ["body:graphql {"] + [f"  {l}" for l in gql.get("query", "").splitlines()] + ["}"]
        if gql.get("variables"):
            out += ["", "body:graphql:vars {"] + [f"  {l}" for l in _json.dumps(gql["variables"], indent=2).splitlines()] + ["}"]
        return out
    try:
        items = _json.loads(body)
    except (ValueError, TypeError):
        items = []
    if body_type == "form":
        return ["body:form-urlencoded {"] + [f"  {'' if i.get('enabled', True) else '~'}{i.get('key', '')}: {i.get('value', '')}" for i in items] + ["}"]
    if body_type == "multipart":
        out = ["body:multipart-form {"]
        for i in items:
            prefix = "" if i.get("enabled", True) else "~"
            value = f"@file({i.get('filename', '')})" if i.get("is_file") else i.get("value", "")
            out.append(f"  {prefix}{i.get('key', '')}: {value}")
        out.append("}")
        return out
    return []
```
to:
```python
def _bru_body_block(body_type: str | None, body: str | None, body_form: str | None = None,
                     body_multipart: str | None = None, body_graphql: str | None = None) -> list[str]:
    import json as _json
    if not body_type:
        return []
    if body_type == "raw":
        if body is None:
            return []
        return ["body:json {"] + [f"  {l}" for l in body.splitlines()] + ["}"]
    if body_type == "graphql":
        if body_graphql is None:
            return []
        try:
            gql = _json.loads(body_graphql)
        except (ValueError, TypeError):
            gql = {"query": "", "variables": {}}
        out = ["body:graphql {"] + [f"  {l}" for l in gql.get("query", "").splitlines()] + ["}"]
        if gql.get("variables"):
            out += ["", "body:graphql:vars {"] + [f"  {l}" for l in _json.dumps(gql["variables"], indent=2).splitlines()] + ["}"]
        return out
    if body_type == "form":
        if body_form is None:
            return []
        try:
            items = _json.loads(body_form)
        except (ValueError, TypeError):
            items = []
        return ["body:form-urlencoded {"] + [f"  {'' if i.get('enabled', True) else '~'}{i.get('key', '')}: {i.get('value', '')}" for i in items] + ["}"]
    if body_type == "multipart":
        if body_multipart is None:
            return []
        try:
            items = _json.loads(body_multipart)
        except (ValueError, TypeError):
            items = []
        out = ["body:multipart-form {"]
        for i in items:
            prefix = "" if i.get("enabled", True) else "~"
            value = f"@file({i.get('filename', '')})" if i.get("is_file") else i.get("value", "")
            out.append(f"  {prefix}{i.get('key', '')}: {value}")
        out.append("}")
        return out
    return []
```

- [ ] **Step 4: Update the exporter call site**

Change:
```python
    body_lines = _bru_body_block(req.get("body_type"), req.get("body"))
```
to:
```python
    body_lines = _bru_body_block(
        req.get("body_type"), req.get("body"),
        req.get("body_form"), req.get("body_multipart"), req.get("body_graphql"),
    )
```

- [ ] **Step 5: Verify both exporters**

```bash
python3 -c "
from cli.api_discovery.postman_exporter import _body_block
r = {'body_type': 'multipart', 'body': None, 'body_multipart': '[{\"key\":\"f\",\"value\":\"v\",\"enabled\":true}]'}
result = _body_block(r['body_type'], r['body'], body_multipart=r['body_multipart'])
assert result['mode'] == 'formdata'
assert result['formdata'][0]['key'] == 'f'
print('postman exporter OK')
"
python3 -c "
from cli.api_discovery.bruno_parser import _bru_body_block
lines = _bru_body_block('multipart', None, body_multipart='[{\"key\":\"f\",\"value\":\"v\",\"enabled\":true}]')
assert 'body:multipart-form {' in lines
assert any('f: v' in l for l in lines)
print('bruno exporter OK')
"
```
Expected: both print their OK lines.

- [ ] **Step 6: Commit**

```bash
git add cli/api_discovery/postman_exporter.py cli/api_discovery/bruno_parser.py
git commit -m "$(cat <<'EOF'
fix(discovery): export form/multipart/graphql bodies from their own fields

Postman and Bruno exporters previously read from the shared body
column, which is now empty for non-raw body types.
EOF
)"
```

---

### Task 10: Variant grouper (`cli/api_discovery/variant_grouper.py`)

**Files:**
- Modify: `cli/api_discovery/variant_grouper.py:33-45` (`_body_signature`), `:55` (`_signature` call), `:79-101` (`_diffable_fields`), `:162-179` (`templatize_request`)

**Interfaces:**
- Consumes: `body_form`/`body_multipart`/`body_graphql` keys now present on parser-output dicts (Tasks 4-8).
- Produces: correct duplicate-detection, per-field diffing, and `{{var}}` templating for the "Save as Library" variant-comparison flow, across all 4 body types.

- [ ] **Step 1: Fix `_body_signature`**

Change:
```python
def _body_signature(body_type, body):
    if body_type in ("form", "multipart"):
        try:
            rows = json.loads(body) if isinstance(body, str) else (body or [])
        except (ValueError, TypeError):
            rows = []
        return _params_signature(rows)
    if body_type == "raw" and body:
        try:
            return ("json", json.dumps(json.loads(body), sort_keys=True))
        except (ValueError, TypeError):
            return ("raw", body)
    return (body_type, body)
```
to:
```python
def _body_signature(body_type, body, body_form=None, body_multipart=None, body_graphql=None):
    if body_type == "form":
        try:
            rows = json.loads(body_form) if isinstance(body_form, str) else (body_form or [])
        except (ValueError, TypeError):
            rows = []
        return _params_signature(rows)
    if body_type == "multipart":
        try:
            rows = json.loads(body_multipart) if isinstance(body_multipart, str) else (body_multipart or [])
        except (ValueError, TypeError):
            rows = []
        return _params_signature(rows)
    if body_type == "graphql":
        return ("graphql", body_graphql)
    if body_type == "raw" and body:
        try:
            return ("json", json.dumps(json.loads(body), sort_keys=True))
        except (ValueError, TypeError):
            return ("raw", body)
    return (body_type, body)
```

- [ ] **Step 2: Update the `_signature` call site**

Change:
```python
def _signature(req: dict) -> tuple:
    """Exact-duplicate equality: (method, normalized path, stripped headers, params, body)."""
    return (
        req.get("method", "GET").upper(),
        normalize_url(req.get("url", "")),
        tuple(sorted(strip_ignored_headers(req.get("headers", [])).items())),
        _params_signature(req.get("params", [])),
        _body_signature(req.get("body_type"), req.get("body")),
    )
```
to:
```python
def _signature(req: dict) -> tuple:
    """Exact-duplicate equality: (method, normalized path, stripped headers, params, body)."""
    return (
        req.get("method", "GET").upper(),
        normalize_url(req.get("url", "")),
        tuple(sorted(strip_ignored_headers(req.get("headers", [])).items())),
        _params_signature(req.get("params", [])),
        _body_signature(req.get("body_type"), req.get("body"), req.get("body_form"), req.get("body_multipart"), req.get("body_graphql")),
    )
```

- [ ] **Step 3: Fix `_diffable_fields`**

Change:
```python
    body_type = req.get("body_type")
    body = req.get("body")
    if body_type in ("form", "multipart"):
        try:
            rows = json.loads(body) if isinstance(body, str) else (body or [])
        except (ValueError, TypeError):
            rows = []
        for row in rows:
            if row.get("enabled") is False:
                continue
            key = row.get("key") or row.get("name") or ""
            if key:
                fields[f"body:{key}"] = row.get("value", "")
    elif body_type == "raw" and body:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                fields[f"body:{key}"] = value
        else:
            fields["body:__raw__"] = body

    return fields
```
to:
```python
    body_type = req.get("body_type")
    body = req.get("body")
    if body_type in ("form", "multipart"):
        raw_rows = req.get("body_form") if body_type == "form" else req.get("body_multipart")
        try:
            rows = json.loads(raw_rows) if isinstance(raw_rows, str) else (raw_rows or [])
        except (ValueError, TypeError):
            rows = []
        for row in rows:
            if row.get("enabled") is False:
                continue
            key = row.get("key") or row.get("name") or ""
            if key:
                fields[f"body:{key}"] = row.get("value", "")
    elif body_type == "graphql":
        fields["body:__raw__"] = req.get("body_graphql")
    elif body_type == "raw" and body:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                fields[f"body:{key}"] = value
        else:
            fields["body:__raw__"] = body

    return fields
```

(GraphQL falls back to `body:__raw__` the same way an unparsable/non-dict raw body does today — `templatize_request`, below, only templates top-level dict keys, and a `{query, variables}` object isn't a flat field set worth diffing per-key.)

- [ ] **Step 4: Fix `templatize_request`**

Change:
```python
        elif kind == "body":
            body_type = out.get("body_type")
            if body_type in ("form", "multipart"):
                try:
                    rows = json.loads(out["body"]) if isinstance(out.get("body"), str) else (out.get("body") or [])
                except (ValueError, TypeError):
                    rows = []
                for row in rows:
                    if (row.get("key") or row.get("name")) == name:
                        row["value"] = var
                out["body"] = json.dumps(rows)
            elif body_type == "raw" and out.get("body"):
                try:
                    parsed = json.loads(out["body"])
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict) and name in parsed:
                    parsed[name] = var
                    out["body"] = json.dumps(parsed)
    return out
```
to:
```python
        elif kind == "body":
            body_type = out.get("body_type")
            if body_type in ("form", "multipart"):
                field_key = "body_form" if body_type == "form" else "body_multipart"
                try:
                    rows = json.loads(out[field_key]) if isinstance(out.get(field_key), str) else (out.get(field_key) or [])
                except (ValueError, TypeError):
                    rows = []
                for row in rows:
                    if (row.get("key") or row.get("name")) == name:
                        row["value"] = var
                out[field_key] = json.dumps(rows)
            elif body_type == "raw" and out.get("body"):
                try:
                    parsed = json.loads(out["body"])
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict) and name in parsed:
                    parsed[name] = var
                    out["body"] = json.dumps(parsed)
    return out
```

- [ ] **Step 5: Verify grouping/templating across body types**

```bash
python3 -c "
from cli.api_discovery.variant_grouper import group_requests, _diffable_fields, templatize_request
reqs = [
    {'method': 'POST', 'url': 'https://example.test/submit', 'headers': [], 'params': [],
     'body_type': 'multipart', 'body_multipart': '[{\"key\":\"role\",\"value\":\"admin\",\"enabled\":true}]'},
    {'method': 'POST', 'url': 'https://example.test/submit', 'headers': [], 'params': [],
     'body_type': 'multipart', 'body_multipart': '[{\"key\":\"role\",\"value\":\"viewer\",\"enabled\":true}]'},
]
groups = group_requests(reqs)
g = groups[0]
assert g['needs_decision'] is True, 'two distinct multipart bodies must be treated as 2 variants, not 1 dup'
assert g['diff_fields'][0]['field_name'] == 'role'
print('variant_grouper: distinct multipart bodies correctly diffed on role')

templated = templatize_request(reqs[0], {'body:role'})
import json
rows = json.loads(templated['body_multipart'])
assert rows[0]['value'] == '{{role}}'
print('templatize_request: multipart field templated correctly')
"
```
Expected: prints both OK lines.

- [ ] **Step 6: Commit**

```bash
git add cli/api_discovery/variant_grouper.py
git commit -m "$(cat <<'EOF'
fix(discovery): read form/multipart/graphql bodies from dedicated fields
in variant grouping, diffing, and templating
EOF
)"
```

---

### Task 11: Frontend — load-seed fix (`web/static/api/views/request-editor-view.js`)

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:610` (`bodyTextarea.value` initial seed), `:635` (`_rawValue` initial seed), `:783-791` (`_formRows`/`_multipartRows` load), `:811-821` (`_gqlQuery` load), `:311-314` (curl-import-into-open-editor — same bug pattern, separate leak)

**Interfaces:**
- Consumes: `body_form`/`body_multipart`/`body_graphql` now returned by `GET /api/api-requests/:id` (backed by Task 2's `RequestRepo.get()`).
- Produces: each of the 4 body-format tab drafts loads only its own content, never another type's — fixes bug #1 from the spec (Raw tab showing captured form-data).

- [ ] **Step 1: Make the raw-value seeds unconditional-but-correct**

Change:
```javascript
  bodyTextarea.value = r.body || '';
```
(this line stays exactly as-is — `r.body` is now raw-only at the data layer, so this was already correct once Tasks 1-2 land; no edit needed here, confirm by inspection.)

Change:
```javascript
  // Raw body gets its own private cache, mirroring _formRows/_multipartRows/
  // _gqlQuery — otherwise switching away to graphql (which continuously
  // overwrites the shared bodyTextarea via _syncGqlBodyTextarea) and back
  // would read back the other type's content instead of raw's own text.
  let _rawValue = r.body || '';
```
(also stays as-is, for the same reason — `r.body` can no longer hold another type's content once the backend split lands. No edit needed here either; this step exists to make explicit that these two lines are *not* bugs anymore after Tasks 1-2, purely a data-shape change, not a code change.)

- [ ] **Step 2: Make `_formRows`/`_multipartRows` load from their own columns**

Change:
```javascript
  let _formRows = [];
  let _multipartRows = [];
  try {
    const parsed = JSON.parse(r.body || '[]');
    if (Array.isArray(parsed)) {
      if (r.body_type === 'multipart') _multipartRows = parsed;
      else if (r.body_type === 'form') _formRows = parsed;
    }
  } catch(e) { /* leave both empty */ }
```
to:
```javascript
  let _formRows = [];
  let _multipartRows = [];
  try {
    const parsedForm = JSON.parse(r.body_form || '[]');
    if (Array.isArray(parsedForm)) _formRows = parsedForm;
  } catch(e) { /* leave empty */ }
  try {
    const parsedMultipart = JSON.parse(r.body_multipart || '[]');
    if (Array.isArray(parsedMultipart)) _multipartRows = parsedMultipart;
  } catch(e) { /* leave empty */ }
```

- [ ] **Step 3: Make `_gqlQuery`/`_gqlVariables` load unconditionally from `body_graphql`**

Change:
```javascript
  let _gqlQuery = '';
  let _gqlVariables = '{}';
  let _gqlLastValidVariables = {};
  try {
    if (r.body_type === 'graphql') {
      const gql = JSON.parse(r.body || '{}');
      _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
      _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
      _gqlLastValidVariables = gql.variables ?? {};
    }
  } catch (e) { /* malformed saved body — start both panes empty */ }
```
to:
```javascript
  let _gqlQuery = '';
  let _gqlVariables = '{}';
  let _gqlLastValidVariables = {};
  try {
    const gql = JSON.parse(r.body_graphql || '{}');
    _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
    _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
    _gqlLastValidVariables = gql.variables ?? {};
  } catch (e) { /* malformed saved body — start both panes empty */ }
```

- [ ] **Step 4: Fix the same leak in the curl-import-into-open-editor handler**

Change:
```javascript
    if (parsed.body_type === 'form') _formRows = JSON.parse(parsed.body || '[]');
    if (parsed.body_type === 'multipart') _multipartRows = JSON.parse(parsed.body || '[]');
    _rawValue = parsed.body || '';
    bodyTextarea.value = parsed.body || '';
    _setBodyType(parsed.body_type || 'none');
```
to:
```javascript
    _formRows = JSON.parse(parsed.body_form || '[]');
    _multipartRows = JSON.parse(parsed.body_multipart || '[]');
    _rawValue = parsed.body || '';
    bodyTextarea.value = parsed.body || '';
    try {
      const gql = JSON.parse(parsed.body_graphql || '{}');
      _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
      _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
      _gqlLastValidVariables = gql.variables ?? {};
    } catch (e) { _gqlQuery = ''; _gqlVariables = '{}'; _gqlLastValidVariables = {}; }
    _setBodyType(parsed.body_type || 'none');
```

The graphql reseed must run unconditionally (not gated on `parsed.body_type === 'graphql'`): `curl_parser.py`'s `_parse_one` never emits `body_type: "graphql"` (curl produces only `"multipart"`/`"raw"`), so a type-gated branch is dead code, and — worse — leaves a stale graphql draft from a prior import surviving into the new one and still getting persisted on save.

(This requires `curl_parser.py`'s output — from Task 6 — to include `body_form: null` and `body_graphql: null` always, since curl never produces `"form"` or `"graphql"` today; `JSON.parse(null || '[]')` / `JSON.parse(null || '{}')` safely yield `[]` / `{}`. Confirmed safe.)

- [ ] **Step 5: Manual browser verification**

Start the server (`python qaclan.py serve --port 7823`), open the API testing UI, capture a multipart request via discovery (or import a curl command with `-F`), open it in the request editor.
Expected: Raw tab is empty; Form-data/multipart tab shows the captured fields. Switch between tabs — no cross-contamination.

- [ ] **Step 6: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "$(cat <<'EOF'
fix(editor): load each body-format draft from its own column

Raw tab previously showed captured form-data/multipart content
because _rawValue was seeded from the shared body column regardless
of body_type. Each of the 4 drafts now loads from its own dedicated
field.
EOF
)"
```

---

### Task 12: Frontend — save fix (`web/static/api/views/request-editor-view.js`)

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:1682-1710` (`_buildPayload`)

**Interfaces:**
- Consumes: `_rawValue`, `_formRows`/`formBodyTable.getRows()`, `_multipartRows`/`multipartBodyTable.getRows()`, `_gqlQuery`/`_gqlLastValidVariables` — all now correctly isolated per Task 11.
- Produces: `PUT`/`POST` payload that always carries all 4 body fields, so switching tabs or picking "none" never discards another format's content (fixes bugs #2/#3 from the spec).

- [ ] **Step 1: Send all 4 body fields on every save**

Change:
```javascript
      body_type: activeBodyType !== 'none' ? activeBodyType : null,
      body: activeBodyType === 'form' ? JSON.stringify(formBodyTable.getRows())
        : activeBodyType === 'multipart' ? JSON.stringify(multipartBodyTable.getRows())
        : (activeBodyType !== 'none' ? (bodyTextarea.value || null) : null),
```
to:
```javascript
      body_type: activeBodyType !== 'none' ? activeBodyType : null,
      body: _rawValue || null,
      body_form: JSON.stringify(activeBodyType === 'form' ? formBodyTable.getRows() : _formRows),
      body_multipart: JSON.stringify(activeBodyType === 'multipart' ? multipartBodyTable.getRows() : _multipartRows),
      body_graphql: JSON.stringify({ query: _gqlQuery, variables: _gqlLastValidVariables }),
```

(`_rawValue` is reliable regardless of which tab is active — see the design spec's Section 2 for why: it's updated on every keystroke via both the CodeMirror path, line 768, `onChange: (v) => { _rawValue = v; bodyTextarea.value = v; }`, and the no-CM fallback path, lines 726/755 — and unlike `bodyTextarea.value`, it's never clobbered by the graphql tab's `_syncGqlBodyTextarea()`. `_gqlQuery`/`_gqlLastValidVariables` are already module-level and never reset on tab switch, per `_setBodyType`'s line 908 only calling `_unmountGqlEditors()` for the outgoing graphql tab, not touching the vars.)

- [ ] **Step 2: Manual verification — fill 2 tabs, save, reload**

In the request editor: switch to Form-data, add a row `key=hello`. Switch to Raw, type `{"unrelated": true}`. Save. Reload the page (or navigate away and back to this request).
Expected: Form-data tab still shows `key=hello`; Raw tab still shows `{"unrelated": true}` — both survive independently.

- [ ] **Step 3: Manual verification — "none" doesn't wipe anything**

With the same request from Step 2 still populated: switch body type to "None". Save. Refresh the browser. Switch back to "Raw".
Expected: `{"unrelated": true}` is still there — picking "none" only deactivated the mode, didn't clear the column.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "$(cat <<'EOF'
fix(editor): save always sends all 4 body drafts, not just the active one

Switching body-format tabs or selecting none previously discarded
every draft except whichever tab was active at save time.
EOF
)"
```

---

### Task 13: Review modal fix (`web/static/api/views/request-review-modal.js`)

**Files:**
- Modify: `web/static/api/views/request-review-modal.js:59-64`

**Interfaces:**
- Consumes: parser-output dicts from Tasks 4-8 (via the `/preview` routes / `group_requests` output), which now carry `body_form`/`body_multipart`/`body_graphql` instead of a shared `body`.
- Produces: correct body preview in the pre-save discovery/import review modal, for every body type — without this fix, form/multipart/graphql previews go blank once the parsers stop writing into `body` (this is a genuine gap found during research, not in the original spec — flagging why it's included here).

- [ ] **Step 1: Pick the right field per `body_type`**

Change:
```javascript
  const bodyContent = !req.body
    ? '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>'
    : (req.body_type === 'form' || req.body_type === 'multipart')
      ? _kvTable(req.body)
      : `<pre style="margin:0;padding:10px 12px;border-left:3px solid var(--accent);background:var(--bg-base);font-size:11px;font-family:var(--font-mono,monospace);white-space:pre-wrap;word-break:break-all;max-height:150px;overflow-y:auto;color:var(--text-primary);border-radius:0 4px 4px 0;">${_esc(_fmt(req.body))}</pre>`;
  const bodySection = _section('Request Body', bodyContent);
```
to:
```javascript
  const _bodyPreviewValue =
    req.body_type === 'form' ? req.body_form
    : req.body_type === 'multipart' ? req.body_multipart
    : req.body_type === 'graphql' ? req.body_graphql
    : req.body;
  const bodyContent = !_bodyPreviewValue
    ? '<span style="color:var(--text-muted);font-size:12px;font-style:italic;">—</span>'
    : (req.body_type === 'form' || req.body_type === 'multipart')
      ? _kvTable(_bodyPreviewValue)
      : `<pre style="margin:0;padding:10px 12px;border-left:3px solid var(--accent);background:var(--bg-base);font-size:11px;font-family:var(--font-mono,monospace);white-space:pre-wrap;word-break:break-all;max-height:150px;overflow-y:auto;color:var(--text-primary);border-radius:0 4px 4px 0;">${_esc(_fmt(_bodyPreviewValue))}</pre>`;
  const bodySection = _section('Request Body', bodyContent);
```

- [ ] **Step 2: Manual verification**

Capture or import a multipart request, open the pre-save review/comparison modal (before clicking final "Save").
Expected: the Request Body section shows the captured fields as a key-value table, not a blank "—".

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/request-review-modal.js
git commit -m "$(cat <<'EOF'
fix(discovery): show form/multipart/graphql body in pre-save review modal

Was always reading req.body, which is now empty for non-raw types
once the parsers stopped writing into the shared column.
EOF
)"
```

---

### Task 14: Cloud sync round-trip (`cli/sync.py` push, `cli/commands/pull.py` restore)

**Files:**
- Modify: `cli/sync.py:322-323` (SELECT), `:343-344` (payload dict)
- Modify: `cli/commands/pull.py:237-251` (`row_values`), `:255-259` (UPDATE column list), `:268-273` (INSERT column list)

**Interfaces:**
- Consumes: `body_form`/`body_multipart`/`body_graphql` columns (Task 1) and the server-side sync route's acceptance of those fields — **requires the companion server-repo plan's Task 3 to be deployed first**, per Global Constraints. The pull side additionally requires the companion plan's Task 2 (`to_dict()`).
- Produces: a full round-trip — local edits reach the cloud, and a workspace restore on a new machine brings all 4 body fields back.

- [ ] **Step 1: Extend the push SELECT + payload**

Change:
```python
    row = get_conn().execute(
        "SELECT project_id, feature_id, collection_id, folder_id, name, method, url, headers, "
        "params, path_params, body_type, body, auth_type, auth_config, pre_script, pre_lang, "
        "pre_extractor, post_script, post_lang, post_extractor, request_schema, response_schema, "
        "assertions, follow_redirects, timeout_ms, include_in_docs, order_index "
        "FROM api_requests WHERE id = ?", (request_id,)
    ).fetchone()
```
to:
```python
    row = get_conn().execute(
        "SELECT project_id, feature_id, collection_id, folder_id, name, method, url, headers, "
        "params, path_params, body_type, body, body_form, body_multipart, body_graphql, auth_type, auth_config, pre_script, pre_lang, "
        "pre_extractor, post_script, post_lang, post_extractor, request_schema, response_schema, "
        "assertions, follow_redirects, timeout_ms, include_in_docs, order_index "
        "FROM api_requests WHERE id = ?", (request_id,)
    ).fetchone()
```

Change:
```python
        "body_type": row["body_type"],
        "body": row["body"],
```
to:
```python
        "body_type": row["body_type"],
        "body": row["body"],
        "body_form": row["body_form"],
        "body_multipart": row["body_multipart"],
        "body_graphql": row["body_graphql"],
```

- [ ] **Step 2: Extend the pull `row_values`, UPDATE, and INSERT**

Change:
```python
        row_values = (
            r["name"], r.get("method", "GET"), r.get("url", ""),
            json.dumps(r.get("headers", [])), json.dumps(r.get("params", [])),
            json.dumps(r.get("path_params", [])), r.get("body_type"), r.get("body"),
            r.get("auth_type", "none"), json.dumps(r.get("auth_config", {})),
```
to:
```python
        row_values = (
            r["name"], r.get("method", "GET"), r.get("url", ""),
            json.dumps(r.get("headers", [])), json.dumps(r.get("params", [])),
            json.dumps(r.get("path_params", [])), r.get("body_type"), r.get("body"),
            r.get("body_form"), r.get("body_multipart"), r.get("body_graphql"),
            r.get("auth_type", "none"), json.dumps(r.get("auth_config", {})),
```

Change:
```python
            conn.execute(
                "UPDATE api_requests SET name=?, method=?, url=?, headers=?, params=?, path_params=?, "
                "body_type=?, body=?, auth_type=?, auth_config=?, pre_script=?, pre_lang=?, pre_extractor=?, "
                "post_script=?, post_lang=?, post_extractor=?, request_schema=?, response_schema=?, "
                "assertions=?, follow_redirects=?, timeout_ms=?, include_in_docs=?, order_index=?, "
                "feature_id=?, collection_id=?, folder_id=? WHERE id=?",
                row_values + (local_feature_id, local_collection_id, local_folder_id, existing["id"]),
            )
```
to:
```python
            conn.execute(
                "UPDATE api_requests SET name=?, method=?, url=?, headers=?, params=?, path_params=?, "
                "body_type=?, body=?, body_form=?, body_multipart=?, body_graphql=?, auth_type=?, auth_config=?, pre_script=?, pre_lang=?, pre_extractor=?, "
                "post_script=?, post_lang=?, post_extractor=?, request_schema=?, response_schema=?, "
                "assertions=?, follow_redirects=?, timeout_ms=?, include_in_docs=?, order_index=?, "
                "feature_id=?, collection_id=?, folder_id=? WHERE id=?",
                row_values + (local_feature_id, local_collection_id, local_folder_id, existing["id"]),
            )
```

Change:
```python
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
```
to:
```python
            conn.execute(
                "INSERT INTO api_requests (id, project_id, feature_id, collection_id, folder_id, name, "
                "method, url, headers, params, path_params, body_type, body, body_form, body_multipart, body_graphql, auth_type, auth_config, "
                "pre_script, pre_lang, pre_extractor, post_script, post_lang, post_extractor, "
                "request_schema, response_schema, assertions, follow_redirects, timeout_ms, "
                "include_in_docs, order_index, created_at, cloud_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (local_id, local_project_id, local_feature_id, local_collection_id, local_folder_id)
                + row_values + (now, cloud_id),
            )
```
(3 new `?` placeholders added to the `VALUES` clause, matching the 3 new columns in `row_values`.)

- [ ] **Step 3: Verify against a running local server + the (already-deployed) cloud API**

This step requires the server-repo plan's Tasks 1-3 already deployed (staging or prod, whichever your `~/.qaclan/config.json` `server_url` points at) and a valid `auth_key`.

```bash
python3 -c "
from cli.db import init_db
init_db()
from web.api.repositories.request_repo import RequestRepo
from cli.config import get_active_project_id
from cli.sync import sync_api_request_to_cloud
repo = RequestRepo()
pid = get_active_project_id()
r = repo.create(pid, {
    'name': 'sync round-trip test', 'method': 'POST', 'url': 'https://example.test',
    'body_type': 'multipart', 'body_multipart': '[{\"key\":\"f\",\"value\":\"v\",\"enabled\":true}]',
})
result = sync_api_request_to_cloud(r['id'])
assert result and result.get('id'), f'sync failed: {result}'
print('pushed OK, cloud id:', result['id'])
"
```
Expected: prints `pushed OK, cloud id: ...`, no exception (an exception here most likely means the server-repo plan isn't deployed yet — stop and deploy it first, per Global Constraints).

Then, to exercise the restore path against a clean local DB, move `~/.qaclan/qaclan.db` aside (`mv ~/.qaclan/qaclan.db ~/.qaclan/qaclan.db.bak`) so `pull` populates a fresh one:
```bash
python qaclan.py pull
sqlite3 ~/.qaclan/qaclan.db "SELECT body_type, body, body_multipart FROM api_requests WHERE name = 'sync round-trip test';"
```
(Restore your original DB afterwards: `mv ~/.qaclan/qaclan.db.bak ~/.qaclan/qaclan.db`.)
Expected: `body_type = multipart`, `body` is empty/NULL, `body_multipart` holds the JSON array — full round-trip confirmed.

Clean up test data locally and in the cloud DB once confirmed.

- [ ] **Step 4: Commit**

```bash
git add cli/sync.py cli/commands/pull.py
git commit -m "$(cat <<'EOF'
feat(sync): push and restore body_form/body_multipart/body_graphql

Completes the cloud round-trip for the new per-mode body columns —
without this, cloud sync/restore would silently drop form/multipart/
graphql bodies once body stopped double-purposing as their storage.
EOF
)"
```

---

### Task 15: End-to-end verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-14, fully applied, plus the companion server-repo plan deployed.
- Produces: confidence the fix is complete and ready to ship.

- [ ] **Step 1: Fresh-capture-to-execution walkthrough**

Start the server (`python qaclan.py serve --port 7823`). Using the browser recorder / discovery flow, capture traffic against any site that submits a multipart form (or use a local test page). Save the captured request into a collection.
Expected: opening the saved request shows the multipart fields under the Form-data/Multipart tab; Raw tab is empty.

- [ ] **Step 2: Multi-format editing walkthrough**

On that same request: switch to Raw, type an unrelated JSON body. Save. Switch to None. Save. Refresh the browser. Switch back to Multipart, then to Raw.
Expected: Multipart fields are exactly as captured; Raw content is exactly what was typed. Nothing lost at any step.

- [ ] **Step 3: Execution regression check**

Click "Send" on the multipart request (Multipart tab active, `body_type` saved as `multipart`).
Expected: request executes successfully (confirms Task 3's runner dispatch change didn't break multipart execution).

- [ ] **Step 4: Pre-migration data check**

If you have a `~/.qaclan/qaclan.db` from before this plan was applied (or a backup of one), copy it in, run `python qaclan.py status` to trigger the migration, then open a request that was captured pre-fix with a form/multipart body.
Expected: Raw tab is empty, Form-data/Multipart tab has the content — the backfill correctly relocated it.

- [ ] **Step 5: Export/import fidelity check**

Export the collection containing the multipart request to a Postman collection JSON (or Bruno folder), then re-import it as a new collection.
Expected: the re-imported request still has its multipart fields, not an empty body.

- [ ] **Step 6: Sign off**

Confirm `git log --oneline -15` shows all 14 prior commits, and that the companion server-repo plan was deployed before Task 14 was exercised against production/staging.

---

### Task 16: Body-format active indicator (editor tab bar + review modal)

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:936-939` (`_setBodyType`)
- Modify: `web/static/style.css:1788` (`.req-body-type-btn.active`)
- Modify: `web/static/api/views/request-review-modal.js` (top-of-file label map, `_detailHTML` body heading)

**Interfaces:**
- Consumes: Tasks 11-13 — both files already read the body content matching `req.body_type`/`activeBodyType` per-type; this task only adds a non-color signal of which type that is.
- Produces: a `title` tooltip + CSS checkmark on the active body-type tab in the editor, and a format suffix on the review modal's "Request Body" heading.

- [ ] **Step 1: Add the tooltip in `_setBodyType`**

Change:
```javascript
    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
```
to:
```javascript
    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      const isActive = b.dataset.type === type;
      b.classList.toggle('active', isActive);
      b.title = isActive
        ? (type === 'none' ? 'No body — nothing sent when you Run this request' : 'Active — sent when you Run this request')
        : '';
    });
```

- [ ] **Step 2: Add the checkmark in CSS**

In `web/static/style.css`, next to the existing rule:
```css
.req-body-type-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
```
add:
```css
.req-body-type-btn.active::before { content: "✓ "; }
```

- [ ] **Step 3: Add the format label to the review modal heading**

In `web/static/api/views/request-review-modal.js`, add a local label map near the top of the file (mirrors the editor's own labels, kept local per this file's existing pattern of duplicating small helpers rather than importing from the editor):
```javascript
const _BODY_TYPE_LABELS = { form: 'x-www-form-urlencoded', multipart: 'form-data/multipart', graphql: 'GraphQL' };
```

Change:
```javascript
  const bodySection = _section('Request Body', bodyContent);
```
to:
```javascript
  const _bodyTypeLabel = req.body_type && req.body_type !== 'raw' ? _BODY_TYPE_LABELS[req.body_type] || req.body_type : null;
  const bodySection = _section(_bodyTypeLabel ? `Request Body — ${_bodyTypeLabel}` : 'Request Body', bodyContent);
```
`raw` and null/undefined `body_type` both keep the plain "Request Body" heading — raw is the implicit default and doesn't need calling out.

- [ ] **Step 4: Manual verification**

Open the request editor on a request with `body_type = 'multipart'` — the form-data/multipart tab shows the checkmark and accent highlight, hovering shows the tooltip. Click through Raw → x-www-form-urlencoded → GraphQL → none without saving — checkmark follows the click on each tab immediately, and the "none" pill shows the "No body" tooltip.
Then run a HAR/Postman/cURL import that produces a mix of raw, form, multipart, and graphql requests, and open the pre-save review modal — each request's body section heading shows the correct format suffix (or plain "Request Body" for raw), matching the content rendered below it.
Expected: all of the above match, no console errors.

- [ ] **Step 5: Commit**

```bash
git add web/static/api/views/request-editor-view.js web/static/style.css web/static/api/views/request-review-modal.js
git commit -m "$(cat <<'EOF'
feat(editor): add non-color active-format indicator to body tabs + review modal

Tab highlight was color-only. Adds a title tooltip + CSS checkmark on
the active body-type tab, and a format suffix on the review modal's
Request Body heading, per docs/superpowers/specs/2026-07-25-body-format-active-indicator-design.md.
EOF
)"
```
