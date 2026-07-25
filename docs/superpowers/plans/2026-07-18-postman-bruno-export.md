# Postman/Bruno Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a qaclan collection to a spec-compliant Postman v2.1 collection or a Bruno `.bru` collection, reversing the same conversion tables the import-fidelity work established, so DB-stored `qc.*` scripts, structured assertions, folders, auth, and collection vars all survive the trip out.

**Architecture:** A reverse-direction script/path-var rewrite added to the existing `script_rewrite.py`/`path_vars.py` modules (Task 1). A new `cli/api_discovery/postman_exporter.py` builds the whole-collection JSON tree. `bruno_parser.py`'s existing (partial) `request_to_bru` is extended in place, plus a new `collection_bru()` writer and folder-tree zip logic. Both wired into the existing `POST /api/collections/<id>/export` route and `qaclan api export` CLI command via a `?format=` switch.

**Tech Stack:** Python 3, stdlib `re`/`json`/`zipfile` only.

## Global Constraints

- No automated test suite in this repo — every verification step is a runnable manual script, not pytest.
- Depends on `docs/superpowers/plans/2026-07-18-postman-bruno-import-fidelity.md` being implemented first (already done) — this plan reuses `FolderRepo`, `CollectionVarsRepo`, and the qc.* rewrite table it established.
- Full mapping tables live in `docs/superpowers/specs/2026-07-18-postman-bruno-export-design.md` — this plan implements that spec; consult it for anything not reproduced here.
- Known, spec-documented lossy spots (not bugs to "fix" in this plan): multipart file bytes (path placeholder only), `matchMode: any/all` on Bruno export (first-match only), Python pre/post scripts (omitted, not translated), auth types outside qaclan's 4 supported ones.

---

### Task 1: Reverse rewrite helpers (path vars + qc.* scripts)

**Files:**
- Modify: `cli/api_discovery/path_vars.py` (add function)
- Modify: `cli/api_discovery/script_rewrite.py` (add function)

**Interfaces:**
- Produces: `revert_path_vars(url: str, path_params: list[dict]) -> str` — replaces `{key}` with `:key` for every known path param.
- Produces: `qc_script_to_foreign(script: str | None, target: str) -> str | None` — `target` is `"postman"` or `"bruno"`. Used by Task 2 (Postman exporter) and Task 3 (Bruno exporter extension).

- [x] **Step 1: Add `revert_path_vars` to `path_vars.py`**

Append to `cli/api_discovery/path_vars.py`:

```python
def revert_path_vars(url: str, path_params: list[dict] | None) -> str:
    """Reverse of convert_path_vars: qaclan's {key} -> Postman/Bruno's :key."""
    for p in (path_params or []):
        key = p.get("key")
        if key:
            url = url.replace("{" + key + "}", ":" + key)
    return url
```

- [x] **Step 2: Add a bracket/quote-aware top-level argument splitter and the reverse script rewriter to `script_rewrite.py`**

Append to `cli/api_discovery/script_rewrite.py`:

```python
def _split_top_level_args(s: str) -> list[str]:
    """Split a JS call's argument text on top-level commas, respecting
    (), [], {}, and both quote types. Not a full JS parser — good enough
    for the single-line calls this module generates and typically sees."""
    parts: list[str] = []
    depth = 0
    quote = None
    current = []
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            current.append(c)
            if c == "\\" and i + 1 < len(s):
                i += 1
                current.append(s[i])
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            current.append(c)
        elif c in "([{":
            depth += 1
            current.append(c)
        elif c in ")]}":
            depth -= 1
            current.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


# Reverse of _DIRECT_REWRITES — qc.* -> foreign, keyed by target.
_REVERSE_DIRECT: dict[str, list[tuple[re.Pattern, str]]] = {
    "postman": [
        (re.compile(r"\bqc\.set\("), "pm.environment.set("),
        (re.compile(r"\bqc\.test\("), "pm.test("),
        (re.compile(r"\bqc\.getHeader\("), "pm.request.headers.get("),
        (re.compile(r"\bqc\.getParam\("), "pm.request.url.query.get("),
        (re.compile(r"\bresponse\.json\("), "pm.response.json("),
        (re.compile(r"\bresponse\.text\("), "pm.response.text("),
        (re.compile(r"\bresponse\.headers\b"), "pm.response.headers"),
        (re.compile(r"\bresponse\.status\b"), "pm.response.code"),
    ],
    "bruno": [
        (re.compile(r"\bqc\.set\("), "bru.setVar("),
        (re.compile(r"\bqc\.test\("), "test("),
        (re.compile(r"\bqc\.setHeader\("), "req.setHeader("),
        (re.compile(r"\bqc\.getHeader\("), "req.getHeader("),
        (re.compile(r"\bqc\.setParam\("), "req.setQueryParam("),
        (re.compile(r"\bqc\.getParam\("), "req.getQueryParam("),
        (re.compile(r"\bresponse\.json\(\)"), "res.body"),
        (re.compile(r"\bresponse\.headers\b"), "res.headers"),
        (re.compile(r"\bresponse\.status\b"), "res.status"),
    ],
}

_QC_SET_HEADER_RE = re.compile(r"qc\.setHeader\((.*)\)\s*;?\s*$")
_QC_SET_PARAM_RE = re.compile(r"qc\.setParam\((.*)\)\s*;?\s*$")
_QC_EXPECT_RE = re.compile(r"qc\.expect\((.*)\)\s*;?\s*$")


def _rewrite_qc_expect_line(line: str, target: str) -> str | None:
    m = _QC_EXPECT_RE.search(line)
    if not m:
        return None
    args = _split_top_level_args(m.group(1))
    if len(args) < 2:
        return None
    cond, message = args[0], ",".join(args[1:])
    indent = line[: len(line) - len(line.lstrip())]
    body = f"if (!({cond})) throw new Error({message});"
    if target == "postman":
        return f"{indent}pm.test({message}, () => {{ {body} }});"
    return f"{indent}test({message}, () => {{ {body} }});"


def qc_script_to_foreign(script: str | None, target: str) -> str | None:
    """Reverse of foreign_script_to_qc — regenerate Postman/Bruno-flavored
    JS from qaclan's native qc.* script text. target: "postman" | "bruno".
    """
    if not script:
        return script
    out_lines = []
    for line in script.splitlines():
        expect_rewrite = _rewrite_qc_expect_line(line, target)
        if expect_rewrite is not None:
            out_lines.append(expect_rewrite)
            continue

        if target == "postman":
            m = _QC_SET_HEADER_RE.search(line)
            if m:
                args = _split_top_level_args(m.group(1))
                if len(args) == 2:
                    indent = line[: len(line) - len(line.lstrip())]
                    out_lines.append(f"{indent}pm.request.headers.add({{key: {args[0]}, value: {args[1]}}});")
                    continue
            m = _QC_SET_PARAM_RE.search(line)
            if m:
                args = _split_top_level_args(m.group(1))
                if len(args) == 2:
                    indent = line[: len(line) - len(line.lstrip())]
                    out_lines.append(f"{indent}pm.request.url.addQueryParams({{key: {args[0]}, value: {args[1]}}});")
                    continue

        rewritten = line
        for pattern, replacement in _REVERSE_DIRECT[target]:
            rewritten = pattern.sub(replacement, rewritten)
        out_lines.append(rewritten)
    return "\n".join(out_lines)
```

- [x] **Step 3: Verify with a manual smoke script**

```bash
python3 -c "
from cli.api_discovery.script_rewrite import qc_script_to_foreign
from cli.api_discovery.path_vars import revert_path_vars

script = '''
qc.set(\"token\", response.json().token);
qc.test(\"status is 200\", () => { qc.expect(response.status === 200, \"status ok\"); });
qc.expect(response.json().id === 42, \"id matches\");
qc.setHeader(\"X-Trace\", response.headers[\"x-request-id\"]);
'''
print('--- postman ---')
print(qc_script_to_foreign(script, 'postman'))
print('--- bruno ---')
print(qc_script_to_foreign(script, 'bruno'))
print('--- path vars ---')
print(revert_path_vars('https://api.example.com/users/{id}/posts/{postId}', [{'key': 'id'}, {'key': 'postId'}]))
"
```

Expected: postman output uses `pm.environment.set(`, `pm.test(`, and the inner
`qc.expect(...)` inside the `pm.test` callback becomes a nested
`pm.test(..., () => { if (!(...)) throw new Error(...); })` (nesting is
harmless — the outer test still runs, matches don't need to be exclusive
here); the top-level `qc.expect` line becomes a standalone `pm.test(...)`
call; `qc.setHeader(...)` becomes `pm.request.headers.add({key: ..., value:
...})`. Bruno output uses `bru.setVar(`, bare `test(`, `res.body`/`res.status`.
Path var output: `https://api.example.com/users/:id/posts/:postId`.

- [x] **Step 4: Commit**

```bash
git add cli/api_discovery/path_vars.py cli/api_discovery/script_rewrite.py
git commit -m "feat(api-discovery): add reverse (qc.* -> foreign) script and path-var rewriters for export"
```

---

### Task 2: Postman exporter

**Files:**
- Create: `cli/api_discovery/postman_exporter.py`

**Interfaces:**
- Consumes: `revert_path_vars`, `qc_script_to_foreign` (Task 1).
- Produces: `to_postman_collection(collection: dict, requests: list[dict], folders: list[dict], collection_vars: list[dict]) -> dict` — returns the full Postman v2.1 JSON as a Python dict, ready for `json.dumps`. `collection` is an `api_collections` row (has `name`, `auth_type`, `auth_config`), `requests`/`folders` are `RequestRepo.list()`/`FolderRepo.list_for_collection()` output, `collection_vars` is `CollectionVarsRepo.list()` output.

- [x] **Step 1: Write the exporter**

```python
# cli/api_discovery/postman_exporter.py
from __future__ import annotations
import json

from cli.api_discovery.path_vars import revert_path_vars
from cli.api_discovery.script_rewrite import qc_script_to_foreign

_AUTH_REVERSE = {
    "bearer": lambda c: {"type": "bearer", "bearer": [{"key": "token", "value": c.get("token", ""), "type": "string"}]},
    "basic": lambda c: {"type": "basic", "basic": [
        {"key": "username", "value": c.get("username", ""), "type": "string"},
        {"key": "password", "value": c.get("password", ""), "type": "string"},
    ]},
    "api_key": lambda c: {"type": "apikey", "apikey": [
        {"key": "key", "value": c.get("key", ""), "type": "string"},
        {"key": "value", "value": c.get("value", ""), "type": "string"},
        {"key": "in", "value": c.get("in", "header"), "type": "string"},
    ]},
    "oauth2": lambda c: {"type": "oauth2", "oauth2": [
        {"key": "grant_type", "value": "client_credentials", "type": "string"},
        {"key": "accessTokenUrl", "value": c.get("token_url", ""), "type": "string"},
        {"key": "clientId", "value": c.get("client_id", ""), "type": "string"},
        {"key": "clientSecret", "value": c.get("client_secret", ""), "type": "string"},
    ]},
}


def _auth_block(auth_type: str, auth_config: dict | str) -> dict | None:
    if auth_type in (None, "none", "inherit"):
        return {"type": "noauth"} if auth_type == "none" else None
    if isinstance(auth_config, str):
        try:
            auth_config = json.loads(auth_config)
        except (ValueError, TypeError):
            auth_config = {}
    builder = _AUTH_REVERSE.get(auth_type)
    return builder(auth_config) if builder else {"type": "noauth"}


def _body_block(body_type: str | None, body: str | None) -> dict | None:
    if not body_type or body is None:
        return None
    if body_type == "raw":
        return {"mode": "raw", "raw": body}
    if body_type == "graphql":
        try:
            gql = json.loads(body)
        except (ValueError, TypeError):
            gql = {"query": "", "variables": {}}
        return {"mode": "graphql", "graphql": {"query": gql.get("query", ""), "variables": gql.get("variables", {})}}
    try:
        items = json.loads(body)
    except (ValueError, TypeError):
        items = []
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


def _assertions_to_test_script(assertions: list[dict]) -> list[str]:
    lines = []
    for a in assertions:
        a_type, op, value = a.get("type"), a.get("op"), a.get("value")
        if a_type == "status":
            lines.append(f'pm.test("status {op} {value}", () => {{ if (!(pm.response.code {"===" if op == "eq" else "!==" if op == "ne" else op} {value})) throw new Error("status assertion failed"); }});')
        elif a_type == "header":
            key = a.get("key", "")
            lines.append(f'pm.test("header {key}", () => {{ const v = pm.response.headers.get("{key}"); if (!(String(v).includes("{value}") )) throw new Error("header assertion failed"); }});' if op == "contains"
                          else f'pm.test("header {key}", () => {{ const v = pm.response.headers.get("{key}"); if (!(v === "{value}")) throw new Error("header assertion failed"); }});')
        elif a_type == "json_path":
            path = a.get("path", "$")
            js_path = path.replace("$.", "").replace("$", "")
            accessor = f"pm.response.json(){'.' + js_path if js_path else ''}"
            if op == "contains":
                lines.append(f'pm.test("{path} contains", () => {{ if (!(String({accessor}).includes("{value}"))) throw new Error("assertion failed"); }});')
            elif op == "exists":
                lines.append(f'pm.test("{path} exists", () => {{ if ({accessor} === undefined || {accessor} === null) throw new Error("assertion failed"); }});')
            elif op == "not_exists":
                lines.append(f'pm.test("{path} not exists", () => {{ if (!({accessor} === undefined || {accessor} === null)) throw new Error("assertion failed"); }});')
            elif op == "matches":
                lines.append(f'pm.test("{path} matches", () => {{ if (!(new RegExp({json.dumps(value)}).test({accessor}))) throw new Error("assertion failed"); }});')
            else:
                cmp = {"eq": "===", "ne": "!==", "lt": "<", "gt": ">"}.get(op, "===")
                lines.append(f'pm.test("{path} {op}", () => {{ if (!({accessor} {cmp} {json.dumps(value)})) throw new Error("assertion failed"); }});')
        elif a_type == "response_time":
            cmp = {"eq": "===", "lt": "<", "gt": ">"}.get(op, "<")
            lines.append(f'pm.test("response time {op} {value}", () => {{ if (!(pm.response.responseTime {cmp} {value})) throw new Error("assertion failed"); }});')
        elif a_type == "body_text":
            lines.append(f'pm.test("body contains", () => {{ if (!(pm.response.text().includes({json.dumps(value)}))) throw new Error("assertion failed"); }});')
    return lines


def _request_item(req: dict) -> dict:
    url = revert_path_vars(req.get("url", ""), req.get("path_params"))
    path_var_names = [p.get("key") for p in (req.get("path_params") or []) if p.get("key")]

    item_request: dict = {
        "method": req.get("method", "GET"),
        "header": [
            {"key": h.get("key", ""), "value": h.get("value", ""), "disabled": not h.get("enabled", True)}
            for h in (req.get("headers") or [])
        ],
        "url": {
            "raw": url,
            "query": [
                {"key": p.get("key", ""), "value": p.get("value", ""), "disabled": not p.get("enabled", True)}
                for p in (req.get("params") or [])
            ],
            "variable": [{"key": k, "value": next((p.get("value", "") for p in (req.get("path_params") or []) if p.get("key") == k), "")} for k in path_var_names],
        },
    }
    body = _body_block(req.get("body_type"), req.get("body"))
    if body:
        item_request["body"] = body
    auth = _auth_block(req.get("auth_type", "inherit"), req.get("auth_config") or {})
    if auth:
        item_request["auth"] = auth

    events = []
    pre = qc_script_to_foreign(req.get("pre_script"), "postman") if req.get("pre_lang", "js") == "js" else None
    if pre:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": pre.splitlines()}})
    test_lines = []
    if req.get("assertions"):
        test_lines.extend(_assertions_to_test_script(req["assertions"]))
    post = qc_script_to_foreign(req.get("post_script"), "postman") if req.get("post_lang", "js") == "js" else None
    if post:
        test_lines.extend(post.splitlines())
    if test_lines:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": test_lines}})

    item: dict = {"name": req.get("name", "Request"), "request": item_request}
    if events:
        item["event"] = events
    return item


def _build_folder_tree(folders: list[dict], requests: list[dict]) -> list[dict]:
    by_parent: dict[str | None, list[dict]] = {}
    for f in folders:
        by_parent.setdefault(f.get("parent_folder_id"), []).append(f)
    reqs_by_folder: dict[str | None, list[dict]] = {}
    for r in requests:
        reqs_by_folder.setdefault(r.get("folder_id"), []).append(r)

    def _build(parent_id: str | None) -> list[dict]:
        items = [_request_item(r) for r in reqs_by_folder.get(parent_id, [])]
        for f in by_parent.get(parent_id, []):
            items.append({"name": f.get("name", "Folder"), "item": _build(f["id"])})
        return items

    return _build(None)


def to_postman_collection(collection: dict, requests: list[dict], folders: list[dict], collection_vars: list[dict]) -> dict:
    result: dict = {
        "info": {
            "name": collection.get("name", "Exported Collection"),
            "schema": "https://schema.postman.com/json/collection/v2.1.0/collection.json",
        },
        "item": _build_folder_tree(folders, requests),
    }
    if collection_vars:
        result["variable"] = [{"key": v["key"], "value": v["initial_value"], "type": "string"} for v in collection_vars]
    auth = _auth_block(collection.get("auth_type", "none"), collection.get("auth_config") or {})
    if auth and auth.get("type") != "noauth":
        result["auth"] = auth
    return result
```

- [x] **Step 2: Verify with a manual round-trip against a real collection**

```bash
python3 -c "
import json
from cli.db import init_db
from cli.config import get_active_project_id
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.request_repo import RequestRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from cli.api_discovery.postman_exporter import to_postman_collection
from cli.api_discovery.postman_parser import parse_postman

init_db()
pid = get_active_project_id()

# Build a fixture collection directly via repos (bypassing import, to test export in isolation)
col = CollectionRepo().create(pid, 'Export Test', auth_type='bearer', auth_config=json.dumps({'token': '{{tok}}'}))
folder = FolderRepo().create(pid, col['id'], 'Auth')
CollectionVarsRepo().upsert(col['id'], 'baseUrl', 'https://api.example.com')
req = RequestRepo().create(pid, {
    'collection_id': col['id'], 'folder_id': folder['id'], 'name': 'Get User',
    'method': 'GET', 'url': '{{baseUrl}}/users/{id}',
    'path_params': [{'key': 'id', 'value': '42', 'enabled': True}],
    'auth_type': 'bearer', 'auth_config': {'token': '{{tok}}'},
    'assertions': [{'type': 'status', 'op': 'eq', 'value': '200'}],
    'post_script': 'qc.set(\"userId\", response.json().id);',
})

requests = RequestRepo().list(pid, col['id'])
folders = FolderRepo().list_for_collection(col['id'])
cvars = CollectionVarsRepo().list(col['id'])
exported = to_postman_collection(col, requests, folders, cvars)
print(json.dumps(exported, indent=2))

# Round-trip: reimport the export, confirm it comes back out recognizable
reimported = parse_postman(exported)
print('--- reimported ---')
print(json.dumps(reimported, indent=2))

# cleanup
from cli.db import get_conn
conn = get_conn()
for table, col_key in (('api_requests', 'collection_id'), ('api_folders', 'collection_id'), ('collection_vars', 'collection_id')):
    conn.execute(f'DELETE FROM {table} WHERE {col_key} = ?', (col['id'],))
conn.execute('DELETE FROM api_collections WHERE id = ?', (col['id'],))
conn.commit()
"
```

Expected: exported JSON has `item: [{"name": "Auth", "item": [{"name": "Get User", "request": {...}}]}]`,
`url.raw` ending in `/users/:id`, `url.variable: [{"key": "id", "value": "42"}]`,
`auth: {"type": "bearer", ...}` on the request, a `test` event containing a
generated `pm.test("status eq 200", ...)` line and a `qc.set` line rewritten
to `pm.environment.set("userId", pm.response.json().id);`, and top-level
`variable: [{"key": "baseUrl", ...}]`. The reimport pass should recover a
request named "Get User" inside `folder_path: ["Auth"]` with `path_params`
containing `id`.

- [x] **Step 3: Commit**

```bash
git add cli/api_discovery/postman_exporter.py
git commit -m "feat(api-discovery): add Postman v2.1 collection exporter"
```

---

### Task 3: Extend Bruno exporter (folders, auth, all body modes, scripts, assertions, collection.bru)

**Files:**
- Modify: `cli/api_discovery/bruno_parser.py` (extend `request_to_bru`, add `collection_bru()` and `export_bruno_tree()`)

**Interfaces:**
- Consumes: `revert_path_vars`, `qc_script_to_foreign` (Task 1).
- Produces: `request_to_bru(req: dict) -> str` (extended, same name/signature as today — now includes params:path, params:query, auth, all body modes, both scripts, assert block). `collection_bru(collection: dict, collection_vars: list[dict]) -> str` (new). `export_bruno_tree(collection: dict, requests: list[dict], folders: list[dict], collection_vars: list[dict]) -> dict[str, str]` (new) — returns `{relative_file_path: file_content}` for the whole collection, used by Task 4's zip writer.

- [x] **Step 1: Replace `request_to_bru` and add the new functions**

Replace the existing `request_to_bru` function (bottom of `cli/api_discovery/bruno_parser.py`) with:

```python
def request_to_bru(req: dict) -> str:
    """Convert a qaclan api_request dict to Bruno .bru format string."""
    import json as _json
    from cli.api_discovery.path_vars import revert_path_vars
    from cli.api_discovery.script_rewrite import qc_script_to_foreign

    url = revert_path_vars(req.get("url", ""), req.get("path_params"))
    method = req.get("method", "GET").lower()
    auth_type = req.get("auth_type", "inherit")

    lines = [
        "meta {",
        f"  name: {req.get('name', 'Request')}",
        "  type: http",
        "  seq: 1",
        "}",
        "",
        f"{method} {{",
        f"  url: {url}",
        f"  body: {_bru_body_mode(req.get('body_type'))}",
        f"  auth: {auth_type if auth_type in ('bearer', 'basic', 'apikey', 'oauth2', 'inherit') else 'none'}",
        "}",
        "",
    ]

    path_params = req.get("path_params") or []
    if path_params:
        lines.append("params:path {")
        for p in path_params:
            lines.append(f"  {p.get('key', '')}: {p.get('value', '')}")
        lines.append("}")
        lines.append("")

    params = req.get("params") or []
    if isinstance(params, str):
        params = _json.loads(params or "[]")
    if params:
        lines.append("params:query {")
        for p in params:
            prefix = "" if p.get("enabled", True) else "~"
            lines.append(f"  {prefix}{p.get('key', '')}: {p.get('value', '')}")
        lines.append("}")
        lines.append("")

    headers = req.get("headers", [])
    if isinstance(headers, str):
        headers = _json.loads(headers or "[]")
    if headers:
        lines.append("headers {")
        for h in headers:
            prefix = "" if h.get("enabled", True) else "~"
            lines.append(f"  {prefix}{h.get('key', '')}: {h.get('value', '')}")
        lines.append("}")
        lines.append("")

    if auth_type not in ("inherit", "none", None):
        auth_lines = _bru_auth_block(auth_type, req.get("auth_config") or {})
        if auth_lines:
            lines.extend(auth_lines)
            lines.append("")

    body_lines = _bru_body_block(req.get("body_type"), req.get("body"))
    if body_lines:
        lines.extend(body_lines)
        lines.append("")

    if req.get("pre_lang", "js") == "js" and req.get("pre_script"):
        lines.append("script:pre-request {")
        for line in qc_script_to_foreign(req["pre_script"], "bruno").splitlines():
            lines.append(f"  {line}")
        lines.append("}")
        lines.append("")

    if req.get("post_lang", "js") == "js" and req.get("post_script"):
        lines.append("script:post-response {")
        for line in qc_script_to_foreign(req["post_script"], "bruno").splitlines():
            lines.append(f"  {line}")
        lines.append("}")
        lines.append("")

    assertions = req.get("assertions") or []
    if isinstance(assertions, str):
        assertions = _json.loads(assertions or "[]")
    assert_lines = _bru_assert_lines(assertions)
    if assert_lines:
        lines.append("assert {")
        lines.extend(f"  {l}" for l in assert_lines)
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _bru_body_mode(body_type: str | None) -> str:
    return {"raw": "json", "form": "form-urlencoded", "multipart": "multipart-form", "graphql": "graphql"}.get(body_type, "none")


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


def _bru_auth_block(auth_type: str, auth_config: dict | str) -> list[str]:
    import json as _json
    if isinstance(auth_config, str):
        try:
            auth_config = _json.loads(auth_config)
        except (ValueError, TypeError):
            auth_config = {}
    if auth_type == "bearer":
        return [f"auth:bearer {{", f"  token: {auth_config.get('token', '')}", "}"]
    if auth_type == "basic":
        return ["auth:basic {", f"  username: {auth_config.get('username', '')}", f"  password: {auth_config.get('password', '')}", "}"]
    if auth_type == "api_key":
        return ["auth:apikey {", f"  key: {auth_config.get('key', '')}", f"  value: {auth_config.get('value', '')}", f"  placement: {auth_config.get('in', 'header')}", "}"]
    if auth_type == "oauth2":
        return ["auth:oauth2 {", "  grant_type: client_credentials",
                f"  accessTokenUrl: {auth_config.get('token_url', '')}",
                f"  clientId: {auth_config.get('client_id', '')}",
                f"  clientSecret: {auth_config.get('client_secret', '')}", "}"]
    return []


def _bru_assert_lines(assertions: list[dict]) -> list[str]:
    op_reverse = {"eq": "eq", "ne": "neq", "gt": "gt", "lt": "lt", "contains": "contains", "matches": "matches"}
    out = []
    for a in assertions:
        a_type, op, value = a.get("type"), a.get("op"), a.get("value")
        qc_op = op_reverse.get(op, "eq")
        if a_type == "status":
            out.append(f"res.status: {qc_op} {value}")
        elif a_type == "header":
            out.append(f"res.headers.{a.get('key', '')}: {qc_op} {value}")
        elif a_type == "response_time":
            out.append(f"res.responseTime: {qc_op} {value}")
        elif a_type == "json_path":
            path = (a.get("path") or "$").replace("$.", "").replace("$", "")
            out.append(f"res.body{'.' + path if path else ''}: {qc_op} {value}")
    return out


def collection_bru(collection: dict, collection_vars: list[dict]) -> str:
    """Build a collection.bru file: collection-level vars + auth."""
    lines = []
    if collection_vars:
        lines.append("vars:pre-request {")
        for v in collection_vars:
            lines.append(f"  {v['key']}: {v['initial_value']}")
        lines.append("}")
        lines.append("")
    auth_type = collection.get("auth_type", "none")
    if auth_type not in ("none", None, "inherit"):
        lines.append("auth {")
        lines.append(f"  mode: {auth_type}")
        lines.append("}")
        lines.append("")
        lines.extend(_bru_auth_block(auth_type, collection.get("auth_config") or {}))
    return "\n".join(lines)


def export_bruno_tree(collection: dict, requests: list[dict], folders: list[dict], collection_vars: list[dict]) -> dict[str, str]:
    """Build the whole collection as {relative_path: file_content}."""
    by_id = {f["id"]: f for f in folders}

    def _dir_path(folder_id: str | None) -> str:
        if not folder_id or folder_id not in by_id:
            return ""
        f = by_id[folder_id]
        parent = _dir_path(f.get("parent_folder_id"))
        return f"{parent}/{f['name']}" if parent else f["name"]

    files: dict[str, str] = {}
    settings = collection_bru(collection, collection_vars)
    if settings.strip():
        files["collection.bru"] = settings

    for req in requests:
        dir_path = _dir_path(req.get("folder_id"))
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in req.get("name", "request"))
        rel = f"{dir_path}/{safe_name}.bru" if dir_path else f"{safe_name}.bru"
        files[rel] = request_to_bru(req)

    return files
```

- [x] **Step 2: Verify with a manual round-trip**

```bash
python3 -c "
import json
from cli.db import init_db
from cli.config import get_active_project_id
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.request_repo import RequestRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo
from cli.api_discovery.bruno_parser import export_bruno_tree, parse_bruno

init_db()
pid = get_active_project_id()
col = CollectionRepo().create(pid, 'Bruno Export Test', auth_type='bearer', auth_config=json.dumps({'token': '{{tok}}'}))
folder = FolderRepo().create(pid, col['id'], 'Auth')
CollectionVarsRepo().upsert(col['id'], 'baseUrl', 'https://api.example.com')
req = RequestRepo().create(pid, {
    'collection_id': col['id'], 'folder_id': folder['id'], 'name': 'Get User',
    'method': 'GET', 'url': '{{baseUrl}}/users/{id}',
    'path_params': [{'key': 'id', 'value': '42', 'enabled': True}],
    'auth_type': 'bearer', 'auth_config': {'token': '{{tok}}'},
    'assertions': [{'type': 'status', 'op': 'eq', 'value': '200'}],
    'post_script': 'qc.set(\"userId\", response.json().id);',
})
requests = RequestRepo().list(pid, col['id'])
folders = FolderRepo().list_for_collection(col['id'])
cvars = CollectionVarsRepo().list(col['id'])
tree = export_bruno_tree(col, requests, folders, cvars)
for path, content in tree.items():
    print(f'=== {path} ===')
    print(content)
    print()

reimported = parse_bruno(tree['Auth/Get User.bru'])
print('--- reimported ---')
print(json.dumps(reimported, indent=2))

from cli.db import get_conn
conn = get_conn()
for table, col_key in (('api_requests', 'collection_id'), ('api_folders', 'collection_id'), ('collection_vars', 'collection_id')):
    conn.execute(f'DELETE FROM {table} WHERE {col_key} = ?', (col['id'],))
conn.execute('DELETE FROM api_collections WHERE id = ?', (col['id'],))
conn.commit()
"
```

Expected: `tree` contains `collection.bru` (with `vars:pre-request { baseUrl: ... }`
and `auth { mode: bearer }` + `auth:bearer { token: {{tok}} }`) and
`Auth/Get User.bru` (with `url: {{baseUrl}}/users/:id`, `params:path { id:
42 }`, `auth: bearer`, `auth:bearer { token: {{tok}} }`, an `assert { res.status:
eq 200 }` block, and `script:post-response { bru.setVar("userId", res.body.id); }`).
Reimport recovers `auth_type: bearer`, `path_params` with `id`, one assertion.

- [x] **Step 3: Commit**

```bash
git add cli/api_discovery/bruno_parser.py
git commit -m "feat(api-discovery): extend Bruno exporter (folders, auth, all body modes, scripts, assertions)"
```

---

### Task 4: Wire export routes + CLI command

**Files:**
- Modify: `web/api/routes/collections.py:188-214` (`export_collection`)
- Modify: `cli/commands/api_cmd.py` (find the `api export` command via `grep -n "def api_export\|\"export\"" cli/commands/api_cmd.py`)

**Interfaces:**
- Consumes: `to_postman_collection` (Task 2), `export_bruno_tree` (Task 3).

- [x] **Step 1: Extend the export route**

Replace `export_collection` in `web/api/routes/collections.py` with:

```python
@bp.route("/api/collections/<col_id>/export", methods=["POST"])
def export_collection(col_id):
    """Export collection to Bruno .bru files (zip) or a Postman v2.1 JSON file.
    Query param: ?format=bruno|postman (default bruno)."""
    try:
        fmt = request.args.get("format", "bruno")
        pid = _project_id()
        col = _svc.get(col_id, pid)
        requests = col.get("requests", [])

        from web.api.repositories.folder_repo import FolderRepo
        from web.api.repositories.collection_vars_repo import CollectionVarsRepo
        folders = FolderRepo().list_for_collection(col_id)
        collection_vars = CollectionVarsRepo().list(col_id)

        if fmt == "postman":
            from cli.api_discovery.postman_exporter import to_postman_collection
            exported = to_postman_collection(col, requests, folders, collection_vars)
            buf = io.BytesIO(json.dumps(exported, indent=2).encode("utf-8"))
            buf.seek(0)
            return send_file(
                buf, mimetype="application/json", as_attachment=True,
                download_name=f"{col['name']}.postman_collection.json",
            )

        from cli.api_discovery.bruno_parser import export_bruno_tree
        tree = export_bruno_tree(col, requests, folders, collection_vars)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, content in tree.items():
                zf.writestr(f"{col['name']}/{rel_path}", content)
        buf.seek(0)
        return send_file(
            buf, mimetype="application/zip", as_attachment=True,
            download_name=f"{col['name']}.zip",
        )
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("export_collection")
        return jsonify({"ok": False, "error": str(e)}), 500
```

Confirm `json` is already imported at the top of `web/api/routes/collections.py`
(`grep -n "^import json" web/api/routes/collections.py`); add it if missing.

- [x] **Step 2: Extend the CLI command**

Run `grep -n "def api_export\|@click.option\|api export" cli/commands/api_cmd.py`
to find the exact command definition, read it in full, and add a
`--format` option (`type=click.Choice(["bruno", "postman"])`, default
`"bruno"`) that branches the same way as the route above — write the
actual code once you've read the real function; this plan cannot show an
exact diff without knowing the current option list around it (unlike
Tasks 1–3, whose target functions were read in full during spec research).

- [x] **Step 3: Verify with a manual HTTP round-trip**

```bash
python3 -c "
import json
from cli.db import init_db
from cli.config import get_active_project_id
from web.server import create_app
from web.api.repositories.collection_repo import CollectionRepo
from web.api.repositories.request_repo import RequestRepo

init_db()
pid = get_active_project_id()
col = CollectionRepo().create(pid, 'Route Export Test')
RequestRepo().create(pid, {'collection_id': col['id'], 'name': 'Ping', 'method': 'GET', 'url': 'https://example.com/ping'})

app = create_app()
client = app.test_client()
resp = client.post(f'/api/collections/{col[\"id\"]}/export?format=postman')
print('postman status:', resp.status_code, resp.content_type)
data = json.loads(resp.data)
print(json.dumps(data, indent=2)[:500])

resp2 = client.post(f'/api/collections/{col[\"id\"]}/export?format=bruno')
print('bruno status:', resp2.status_code, resp2.content_type, len(resp2.data), 'bytes')

from cli.db import get_conn
conn = get_conn()
conn.execute('DELETE FROM api_requests WHERE collection_id = ?', (col['id'],))
conn.execute('DELETE FROM api_collections WHERE id = ?', (col['id'],))
conn.commit()
"
```

Expected: both requests return 200; the Postman one has `content_type:
application/json` and valid collection JSON; the Bruno one has
`content_type: application/zip` and a non-zero byte count.

- [x] **Step 4: Commit**

```bash
git add web/api/routes/collections.py cli/commands/api_cmd.py
git commit -m "feat(api): wire Postman/Bruno export format switch into export route and CLI command"
```

---

### Task 5: Export UI in collections-view.js

**Files:**
- Modify: `web/static/api/views/collections-view.js`

**Interfaces:**
- Consumes: `POST /api/collections/<id>/export?format=postman|bruno` (Task 4, already live).
- No backend changes — this task only adds a client trigger for the existing route.

**Design reference:** see "## UI" section in
`docs/superpowers/specs/2026-07-18-postman-bruno-export-design.md`.

- [ ] **Step 1: Add two dropdown items**

In `_renderCollectionSection`, extend the `menuDropdown.innerHTML` template
(around the existing `+ New Request` / `+ New Folder` items, before the
divider) to add:

```html
<div class="project-dropdown-item" data-action="export-postman">Export as Postman</div>
<div class="project-dropdown-item" data-action="export-bruno">Export as Bruno</div>
```

Extend the existing `menuDropdown.onclick` action switch with:

```js
else if (action === 'export-postman') await _exportCollection(col.id, col.name, 'postman');
else if (action === 'export-bruno') await _exportCollection(col.id, col.name, 'bruno');
```

- [ ] **Step 2: Add the `_exportCollection` helper**

Add near the other collection-level action functions (`_deleteCollection`,
`_createCollection`):

```js
async function _exportCollection(colId, colName, fmt) {
  const res = await fetch(`/api/collections/${encodeURIComponent(colId)}/export?format=${fmt}`, { method: 'POST' });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch (_) {}
    await window._alertDialog('Export failed: ' + msg);
    return;
  }
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match ? match[1] : `${colName}.${fmt === 'postman' ? 'postman_collection.json' : 'zip'}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

Confirm `send_file(..., as_attachment=True, download_name=...)` in
`web/api/routes/collections.py`'s `export_collection` actually sets a
`Content-Disposition` header with `filename=` (Flask does this by
default) — if the header comes back empty in Step 3's manual check, keep
the `filename` fallback above as the only source of the name.

- [ ] **Step 3: Verify manually in the browser**

Start the dev server (`python qaclan.py serve --port 7823`), open the API
tab, click a collection's `⋯` menu, click "Export as Postman" — confirm a
`.json` file downloads and its `info.schema` is the v2.1.0 URL. Click
"Export as Bruno" — confirm a `.zip` downloads and contains `.bru` files.
Trigger a failure case (e.g. stop the server mid-request or export a
just-deleted collection id) and confirm the alert dialog shows an error
instead of downloading a broken file.

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/collections-view.js
git commit -m "feat(api): add Postman/Bruno export menu items to collections view"
```

---

## Self-Review Notes

- **Spec coverage**: §A path vars (Task 1), §B folders (Task 2/3 folder-tree
  builders), §C collection vars (Task 2 `variable[]` / Task 3
  `collection.bru`), §D environments — **not implemented in this plan**,
  flagged explicitly (see below), §E auth (Task 2/3 `_auth_block`/
  `_bru_auth_block`), §F body modes (Task 2/3, file-field limitation
  documented inline as a comment-free but spec-acknowledged gap — export
  writes a path placeholder via `filename`, not bytes), §G scripts (Task 1
  reverse rewrite), §H assertions (Task 2 codegen, Task 3 native assert
  block), §J format targets (v2.1.0 schema URL literal in Task 2, `.bru`
  text format throughout Task 3), §L wiring (Task 4).
- **Known scope cut**: spec §D (environment export as separate
  `*.environment.json`/`environments/*.bru` files) is deliberately left out
  of this plan — it's the one section with no dependency from any other
  task, and the spec itself frames it as an additive UI checkbox on top of
  the core collection export. Implementing it is a follow-up, not a gap in
  this plan's own internal consistency; flagging here rather than silently
  dropping it so it doesn't get lost.
- **Type consistency**: `to_postman_collection`/`export_bruno_tree` both
  take the same four arguments in the same order
  (`collection, requests, folders, collection_vars`) for symmetry between
  the two exporters — checked against Task 4's route code, which fetches
  all four the same way before branching on `fmt`.
- **Task 5 addendum (2026-07-21)**: Tasks 1–4 were already implemented
  (verified directly in the codebase) but had no UI trigger — the export
  route was reachable only via raw HTTP or the CLI. Task 5 closes that
  gap with two dropdown items in `collections-view.js`. Still no
  environment picker (see "Known scope cut" above) since environment
  export remains unimplemented backend-side.
