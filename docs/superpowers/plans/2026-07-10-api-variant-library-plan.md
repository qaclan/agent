# API Variant Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user choose "Save as Library" at Discovery save-time, see captured requests auto-grouped by endpoint with duplicates collapsed and variants surfaced, decide per group to keep variants separate or merge them into one `{{var}}`-templated request backed by saved examples, and replay any saved example from the request editor.

**Architecture:** Two-modal frontend flow (existing flat review modal → new grouping/comparison modal) backed by a stateless two-call backend contract (`/discover/group-requests` preview, `/discover/save-library` commit). A new pure Python module (`variant_grouper.py`) owns all grouping/diffing/naming logic so it's usable from both the preview and commit calls without duplicating logic. A new `api_request_examples` table stores non-default variants; the request editor gains an `Examples` dropdown that reuses the existing response panel with a "captured, not live" banner rather than a new UI surface.

**Tech Stack:** Flask (routes/services/repos, existing 3-layer pattern), raw `sqlite3` via `cli/db.py`, vanilla JS ES modules (no build step, no framework) for the frontend.

**Spec:** `docs/superpowers/specs/2026-07-05-api-variant-library-design.md`

## Global Constraints

- No automated test framework exists in this repo (`CLAUDE.md` states this; verified — no pytest/jest config or test files anywhere outside `venv/`/`node_modules/`). Every task's verification step below uses `python3 -c` inline assertions (backend) or `node --check` + a manual browser checklist (frontend) instead of a test runner — this matches, not deviates from, existing repo convention.
- Python targets 3.10+ typing style (`str | None`, `list[dict]`) — matches `web/api/repositories/request_repo.py` and friends.
- Follow the existing 3-layer backend pattern: routes parse request/response and handle errors (`{"ok": false, "error": ...}` + status code), services hold business rules, repos own SQL. Routes never touch a repo directly.
- New SQL changes are a new `_migrate_xxx(conn)` function in `cli/db.py`, appended to the end of the call chain inside `init_db()` — never reorder or remove existing `_migrate_*` calls.
- Reuse `generate_id(prefix)` from `cli.db` for every new row ID. Prefix for the new table is `"apiex"`.
- The header ignore-list (`authorization, cookie, set-cookie, x-request-id, x-correlation-id, traceparent, user-agent, date, content-length, x-csrf-token`) is defined in exactly one place — `cli/api_discovery/variant_grouper.py` — and imported everywhere else it's needed.
- Frontend files are loaded directly as ES modules (no bundler). Verify syntax with `node --check <file>`; there is no jsdom/jest, so DOM-touching logic is verified by manually running the app (`python qaclan.py serve --port 7823`) and clicking through the flow — call this out explicitly in each frontend task's verification step, don't skip it.
- `window.api()` never throws — it returns `{ok: false, error}` on failure. Always check `res.ok === false`, matching every existing call site.
- Collection runs always execute a merged request's stored defaults; there is deliberately no task here that touches `RunnerService`/collection-run execution — the spec flags "run once per saved example" as an explicit fast-follow, not part of this plan.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `cli/db.py` | Modify | New `_migrate_api_request_examples` migration, appended to `init_db()`'s chain |
| `cli/api_discovery/har_parser.py` | Modify | Capture `response_status`/`response_headers`/`response_body`/`duration_ms` per parsed request (HAR import + Record APIs mode both go through `parse_har`) |
| `cli/api_discovery/variant_grouper.py` | Create | Pure grouping/diffing/naming/templatizing logic — no I/O, no Flask, no DB |
| `web/api/repositories/request_example_repo.py` | Create | `RequestExampleRepo` — CRUD for `api_request_examples`, mirrors `request_repo.py`'s shape |
| `web/api/services/discovery_service.py` | Modify | `group_requests()` and `save_library()` orchestration functions |
| `web/api/routes/discovery.py` | Modify | `POST /api/discover/group-requests`, `POST /api/discover/save-library` |
| `web/api/services/request_service.py` | Modify | `list_examples()` |
| `web/api/routes/requests.py` | Modify | `GET /api/api-requests/<req_id>/examples` |
| `web/static/api/views/request-review-modal.js` | Modify | Flow/Library radio, button relabel, hand-off into Modal 2 |
| `web/static/api/views/variant-comparison-modal.js` | Create | Modal 2 — grouped comparison UI, per-group separate/merge, per-field `{{var}}` checkboxes |
| `web/static/api/components/response-panel.js` | Modify | `show(result, meta)` gains an optional "captured, not live" banner mode |
| `web/static/api/views/request-editor-view.js` | Modify | Fetch examples, render `[Examples ▾]`, wire selection into params/body + response panel |

---

## Task 1: `api_request_examples` table

**Files:**
- Modify: `cli/db.py`

**Interfaces:**
- Produces: table `api_request_examples(id, api_request_id, label, params, body, response_status, response_headers, response_body, created_at)` — every later task's repo/service code depends on this exact column list.

- [ ] **Step 1: Add the migration function**

Add this function to `cli/db.py`, directly after the `_migrate_collection_run_progress` function body (after its closing `conn.commit()` at what is currently line 168, before `def _migrate_var_picker`):

```python
def _migrate_api_request_examples(conn):
    """Create api_request_examples — non-default variants preserved when a Save-as-Library
    merge collapses several captured requests into one {{var}}-templated api_requests row.
    See docs/superpowers/specs/2026-07-05-api-variant-library-design.md Section 4."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_request_examples (
            id              TEXT PRIMARY KEY,
            api_request_id  TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
            label           TEXT NOT NULL,
            params          TEXT NOT NULL DEFAULT '[]',
            body            TEXT DEFAULT NULL,
            response_status INTEGER,
            response_headers TEXT,
            response_body   TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    conn.commit()
```

- [ ] **Step 2: Wire it into the migration chain**

In `cli/db.py`, change the end of `init_db()` from:

```python
    _migrate_pre_extractor(conn)
    _migrate_collection_run_progress(conn)
```

to:

```python
    _migrate_pre_extractor(conn)
    _migrate_collection_run_progress(conn)
    _migrate_api_request_examples(conn)
```

- [ ] **Step 3: Verify manually**

Run:

```bash
python3 -c "
from cli.db import get_conn, init_db
init_db()
conn = get_conn()
cols = {r['name'] for r in conn.execute(\"PRAGMA table_info('api_request_examples')\").fetchall()}
expected = {'id','api_request_id','label','params','body','response_status','response_headers','response_body','created_at'}
assert cols == expected, f'column mismatch: {cols}'
print('PASS: api_request_examples has expected columns')
"
```

Expected output: `PASS: api_request_examples has expected columns`

- [ ] **Step 4: Commit**

```bash
git add cli/db.py
git commit -m "feat(db): add api_request_examples table for variant library"
```

---

## Task 2: Capture response snapshot in `parse_har`

**Files:**
- Modify: `cli/api_discovery/har_parser.py`

**Interfaces:**
- Consumes: nothing new (same HAR entry dict already in scope).
- Produces: every dict `parse_har()` returns now additionally has `response_status: int|None`, `response_headers: dict`, `response_body: str|None`, `duration_ms: int`. Task 3 (`variant_grouper.py`) and Task 5 (`save_library`) both read these fields.

- [ ] **Step 1: Replace the response-handling block**

In `cli/api_discovery/har_parser.py`, replace this block (currently lines 284–318):

```python
        # Infer response schema from response body
        response_schema = None
        resp = entry.get("response", {})
        resp_content = resp.get("content", {})
        # mimeType may be in content or fall back to response headers
        resp_mime = resp_content.get("mimeType", "")
        if not resp_mime:
            for h in resp.get("headers", []):
                if h.get("name", "").lower() == "content-type":
                    resp_mime = h.get("value", "")
                    break
        if "json" in resp_mime:
            resp_text = resp_content.get("text", "")
            if resp_text:
                try:
                    if resp_content.get("encoding") == "base64":
                        resp_text = base64.b64decode(resp_text).decode("utf-8", errors="replace")
                    response_schema = _infer_schema(json.loads(resp_text))
                except Exception:
                    logger.debug("parse_har: could not infer response schema for %s", url)

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
            "request_schema": request_schema,
            "response_schema": response_schema,
        })
```

with:

```python
        # Response snapshot — status/headers/body/duration are only meaningful for
        # HAR-based paths (HAR import + Record APIs mode, which also produces a HAR
        # under the hood and reuses this same parser). Spec-derived imports
        # (OpenAPI/Postman/Bruno/cURL) have no live traffic, so these stay None there.
        resp = entry.get("response", {})
        resp_content = resp.get("content", {})
        resp_mime = resp_content.get("mimeType", "")
        if not resp_mime:
            for h in resp.get("headers", []):
                if h.get("name", "").lower() == "content-type":
                    resp_mime = h.get("value", "")
                    break

        resp_text = resp_content.get("text", "")
        if resp_text and resp_content.get("encoding") == "base64":
            try:
                resp_text = base64.b64decode(resp_text).decode("utf-8", errors="replace")
            except Exception:
                resp_text = ""

        response_schema = None
        if "json" in resp_mime and resp_text:
            try:
                response_schema = _infer_schema(json.loads(resp_text))
            except Exception:
                logger.debug("parse_har: could not infer response schema for %s", url)

        response_status = resp.get("status") or None
        response_headers = {}
        for h in resp.get("headers", []):
            rh_name = h.get("name", "")
            if rh_name.lower() in skip_headers or rh_name.startswith(":"):
                continue
            response_headers[rh_name] = h.get("value", "")
        duration_ms = int(entry.get("time", 0) or 0)

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
            "request_schema": request_schema,
            "response_schema": response_schema,
            "response_status": response_status,
            "response_headers": response_headers,
            "response_body": resp_text or None,
            "duration_ms": duration_ms,
        })
```

Note: `skip_headers` is already in scope from earlier in the same loop iteration (used for request headers) — reused here as-is, no new variable needed.

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.api_discovery.har_parser import parse_har
har = {
  'log': {
    'entries': [{
      'time': 94,
      'request': {'method': 'GET', 'url': 'https://api.example.com/cart?sort=date', 'headers': [], 'queryString': [{'name': 'sort', 'value': 'date'}]},
      'response': {
        'status': 200,
        'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
        'content': {'mimeType': 'application/json', 'text': '{\"items\": []}'}
      }
    }]
  }
}
reqs = parse_har(har)
assert len(reqs) == 1
r = reqs[0]
assert r['response_status'] == 200, r['response_status']
assert r['duration_ms'] == 94, r['duration_ms']
assert r['response_body'] == '{\"items\": []}', r['response_body']
assert r['response_headers'].get('Content-Type') == 'application/json', r['response_headers']
print('PASS: parse_har captures response snapshot')
"
```

Expected output: `PASS: parse_har captures response snapshot`

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/har_parser.py
git commit -m "feat(discovery): capture response status/headers/body/duration in parse_har"
```

---

## Task 3: `variant_grouper.py` — grouping, diffing, naming, templatizing

**Files:**
- Create: `cli/api_discovery/variant_grouper.py`

**Interfaces:**
- Consumes: request dicts shaped like `parse_har()`'s output (`method, url, headers, params, body_type, body, request_schema, response_schema, response_status, response_headers, response_body, duration_ms`), plus any of the other Discovery parsers' output (same shape, response fields simply absent/`None`).
- Produces (used by Task 5 `discovery_service.py` and Task 6 routes):
  - `HEADER_IGNORE_LIST: set[str]`
  - `strip_ignored_headers(headers: list[dict]) -> dict[str, str]`
  - `group_requests(requests: list[dict]) -> list[dict]` — each group: `{method, path_key, endpoint_label, needs_decision, exact_dups_collapsed, variants, diff_fields, default_action}`; each variant: `{index, request, dup_count, label_suggestion}`; each diff field: `{key, kind, field_name, values, checked_default}`.
  - `compute_diff_fields(variant_requests: list[dict]) -> list[dict]` — same diff-field shape, recomputable from any subset of variant requests (used again in Task 5 after the user drops rows).
  - `suggest_label(request: dict, diff_fields: list[dict], variant_index: int) -> str`
  - `templatize_request(request: dict, checked_field_keys: set[str]) -> dict`

- [ ] **Step 1: Write the module**

```python
from __future__ import annotations
import json
from cli.api_discovery.url_normalizer import normalize_url

HEADER_IGNORE_LIST = {
    "authorization", "cookie", "set-cookie", "x-request-id", "x-correlation-id",
    "traceparent", "user-agent", "date", "content-length", "x-csrf-token",
}


def strip_ignored_headers(headers: list[dict]) -> dict:
    """headers: list of {key/name, value, enabled}. Returns {lowercased_key: value},
    dropping disabled rows and anything in HEADER_IGNORE_LIST."""
    out = {}
    for h in headers or []:
        if h.get("enabled") is False:
            continue
        key = (h.get("key") or h.get("name") or "").strip()
        if not key or key.lower() in HEADER_IGNORE_LIST:
            continue
        out[key.lower()] = h.get("value", "")
    return out


def _params_signature(params: list[dict]) -> tuple:
    pairs = sorted(
        (p.get("key") or p.get("name") or "", p.get("value", ""))
        for p in (params or []) if p.get("enabled") is not False
    )
    return tuple(pairs)


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


def _signature(req: dict) -> tuple:
    """Exact-duplicate equality: (method, normalized path, stripped headers, params, body)."""
    return (
        req.get("method", "GET").upper(),
        normalize_url(req.get("url", "")),
        tuple(sorted(strip_ignored_headers(req.get("headers", [])).items())),
        _params_signature(req.get("params", [])),
        _body_signature(req.get("body_type"), req.get("body")),
    )


def _endpoint_key(req: dict) -> tuple:
    return (req.get("method", "GET").upper(), normalize_url(req.get("url", "")))


def _diffable_fields(req: dict) -> dict:
    """Flat {field_key: value} view of a request's headers + params + body, used to
    diff variants within a group. field_key is 'header:<name>', 'param:<name>', or
    'body:<name>' — or 'body:__raw__' when the body isn't a flat JSON object (array,
    plain text, or unparsable), since there's no clean per-field diff in that case."""
    fields = {}
    for key, value in strip_ignored_headers(req.get("headers", [])).items():
        fields[f"header:{key}"] = value

    for p in req.get("params", []) or []:
        if p.get("enabled") is False:
            continue
        key = p.get("key") or p.get("name") or ""
        if key:
            fields[f"param:{key}"] = p.get("value", "")

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


def compute_diff_fields(variant_requests: list[dict]) -> list[dict]:
    """Given 2+ request dicts already known to be distinct variants of the same
    endpoint, return the fields that differ across them."""
    per_variant_fields = [_diffable_fields(r) for r in variant_requests]
    all_keys = sorted({k for fields in per_variant_fields for k in fields})
    _ABSENT = " __absent__"
    diff_fields = []
    for key in all_keys:
        values = [fields.get(key, _ABSENT) for fields in per_variant_fields]
        if len(set(values)) > 1:
            kind = "param" if key.startswith("param:") else "header" if key.startswith("header:") else "body"
            diff_fields.append({
                "key": key,
                "kind": kind,
                "field_name": key.split(":", 1)[1],
                "values": [fields.get(key) for fields in per_variant_fields],
                "checked_default": key != "body:__raw__",
            })
    return diff_fields


def suggest_label(request: dict, diff_fields: list[dict], variant_index: int) -> str:
    """Human-readable variant label, e.g. 'sort=date' or 'role=viewer, dept=eng'.
    Falls back to 'variant N' when a diff field is 'body:__raw__' (the body isn't a
    flat JSON object, so there's no clean per-field diff) — see spec Section 3."""
    if any(f["key"] == "body:__raw__" for f in diff_fields):
        return f"variant {variant_index + 1}"

    fields = _diffable_fields(request)
    parts = [f"{f['field_name']}={fields[f['key']]}" for f in diff_fields if f["key"] in fields]
    if not parts:
        return f"variant {variant_index + 1}"
    return ", ".join(parts)


def templatize_request(request: dict, checked_field_keys: set) -> dict:
    """Return a copy of request with each checked diff-field's value replaced by a
    {{var}} placeholder named after the field. Only top-level fields are templated —
    matches the top-level-only diffing in _diffable_fields."""
    out = dict(request)
    out["headers"] = [dict(h) for h in (request.get("headers") or [])]
    out["params"] = [dict(p) for p in (request.get("params") or [])]

    for field_key in checked_field_keys:
        kind, _, name = field_key.partition(":")
        var = "{{" + name + "}}"
        if kind == "param":
            for p in out["params"]:
                if (p.get("key") or p.get("name")) == name:
                    p["value"] = var
        elif kind == "header":
            for h in out["headers"]:
                if (h.get("key") or h.get("name") or "").lower() == name:
                    h["value"] = var
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


def group_requests(requests: list[dict]) -> list[dict]:
    """Group captured requests by endpoint, collapse exact duplicates, and surface
    remaining variants for the Save-as-Library comparison UI. See
    docs/superpowers/specs/2026-07-05-api-variant-library-design.md Section 2."""
    endpoint_order: list[tuple] = []
    endpoints: dict[tuple, list[dict]] = {}
    for req in requests:
        ek = _endpoint_key(req)
        if ek not in endpoints:
            endpoint_order.append(ek)
            endpoints[ek] = []
        endpoints[ek].append(req)

    groups = []
    for ek in endpoint_order:
        method, path_key = ek
        bucket = endpoints[ek]

        sig_order: list[tuple] = []
        clusters: dict[tuple, list[dict]] = {}
        for req in bucket:
            sig = _signature(req)
            if sig not in clusters:
                sig_order.append(sig)
                clusters[sig] = []
            clusters[sig].append(req)

        variants = [
            {"index": i, "request": clusters[sig][0], "dup_count": len(clusters[sig])}
            for i, sig in enumerate(sig_order)
        ]
        exact_dups_collapsed = sum(v["dup_count"] - 1 for v in variants)
        needs_decision = len(variants) >= 2

        diff_fields = []
        if needs_decision:
            diff_fields = compute_diff_fields([v["request"] for v in variants])
            for i, v in enumerate(variants):
                v["label_suggestion"] = suggest_label(v["request"], diff_fields, i)

        groups.append({
            "method": method,
            "path_key": path_key,
            "endpoint_label": f"{method} {path_key}",
            "needs_decision": needs_decision,
            "exact_dups_collapsed": exact_dups_collapsed,
            "variants": variants,
            "diff_fields": diff_fields,
            "default_action": "merge" if needs_decision else "keep_single",
        })

    return groups
```

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.api_discovery.variant_grouper import group_requests, templatize_request

reqs = [
  {'method': 'GET', 'url': 'https://api.example.com/cart?sort=price', 'headers': [], 'params': [{'key': 'sort', 'value': 'price'}], 'body_type': None, 'body': None},
  {'method': 'GET', 'url': 'https://api.example.com/cart?sort=date', 'headers': [], 'params': [{'key': 'sort', 'value': 'date'}], 'body_type': None, 'body': None},
  {'method': 'GET', 'url': 'https://api.example.com/cart?sort=date', 'headers': [], 'params': [{'key': 'sort', 'value': 'date'}], 'body_type': None, 'body': None},
]
groups = group_requests(reqs)
assert len(groups) == 1, groups
g = groups[0]
assert g['endpoint_label'] == 'GET /cart', g
assert g['needs_decision'] is True
assert g['exact_dups_collapsed'] == 1, g['exact_dups_collapsed']
assert len(g['variants']) == 2, g['variants']
assert g['variants'][0]['label_suggestion'] == 'sort=price', g['variants'][0]
assert g['variants'][1]['label_suggestion'] == 'sort=date', g['variants'][1]
assert g['variants'][1]['dup_count'] == 2

merged = templatize_request(g['variants'][0]['request'], {'param:sort'})
assert merged['params'][0]['value'] == '{{sort}}', merged['params']
print('PASS: variant_grouper groups, collapses dups, names, and templatizes')
"
```

Expected output: `PASS: variant_grouper groups, collapses dups, names, and templatizes`

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/variant_grouper.py
git commit -m "feat(discovery): add variant_grouper for Save-as-Library grouping/diffing"
```

---

## Task 4: `RequestExampleRepo`

**Files:**
- Create: `web/api/repositories/request_example_repo.py`

**Interfaces:**
- Consumes: `api_request_examples` table (Task 1).
- Produces: `RequestExampleRepo` with `create(api_request_id: str, data: dict) -> dict` and `list_for_request(api_request_id: str) -> list[dict]` — used by Task 5 (`save_library`) and Task 7 (`RequestService.list_examples`).

- [ ] **Step 1: Write the repo**

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from cli.db import get_conn, generate_id

logger = logging.getLogger("qaclan.request_example_repo")


class RequestExampleRepo:
    def create(self, api_request_id: str, data: dict) -> dict:
        conn = get_conn()
        eid = generate_id("apiex")
        now = datetime.now(timezone.utc).isoformat()
        params = data.get("params", [])
        headers = data.get("response_headers")
        conn.execute(
            "INSERT INTO api_request_examples "
            "(id, api_request_id, label, params, body, response_status, response_headers, response_body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eid, api_request_id, data.get("label", "variant"),
                json.dumps(params) if not isinstance(params, str) else params,
                data.get("body"),
                data.get("response_status"),
                json.dumps(headers) if headers is not None and not isinstance(headers, str) else headers,
                data.get("response_body"),
                now,
            ),
        )
        conn.commit()
        logger.info("RequestExampleRepo.create: %s for request %s", data.get("label"), api_request_id)
        return self.get(eid)

    def get(self, id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute("SELECT * FROM api_request_examples WHERE id = ?", (id,)).fetchone()
        return self._deserialize(dict(row)) if row else None

    def list_for_request(self, api_request_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM api_request_examples WHERE api_request_id = ? ORDER BY created_at",
            (api_request_id,),
        ).fetchall()
        return [self._deserialize(dict(r)) for r in rows]

    @staticmethod
    def _deserialize(row: dict) -> dict:
        out = dict(row)
        for key in ("params", "response_headers"):
            if isinstance(out.get(key), str):
                try:
                    out[key] = json.loads(out[key])
                except (ValueError, TypeError):
                    out[key] = [] if key == "params" else {}
        return out
```

- [ ] **Step 2: Verify manually**

```bash
python3 -c "
from cli.db import init_db, get_conn, generate_id
from datetime import datetime, timezone
from web.api.repositories.request_example_repo import RequestExampleRepo

init_db()
conn = get_conn()
pid = generate_id('proj')
conn.execute('INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)', (pid, 'tmp', datetime.now(timezone.utc).isoformat()))
rid = generate_id('apireq')
conn.execute(
    \"INSERT INTO api_requests (id, project_id, name, method, url, created_at) VALUES (?, ?, ?, ?, ?, ?)\",
    (rid, pid, 'Test', 'GET', 'https://x/y', datetime.now(timezone.utc).isoformat()),
)
conn.commit()

repo = RequestExampleRepo()
ex = repo.create(rid, {'label': 'role=viewer', 'params': [{'key': 'role', 'value': 'viewer'}], 'body': None, 'response_status': 201, 'response_headers': {'Content-Type': 'application/json'}, 'response_body': '{}'})
assert ex['label'] == 'role=viewer'
assert ex['params'] == [{'key': 'role', 'value': 'viewer'}]
assert ex['response_headers'] == {'Content-Type': 'application/json'}

listed = repo.list_for_request(rid)
assert len(listed) == 1 and listed[0]['id'] == ex['id']
print('PASS: RequestExampleRepo create + list_for_request round-trip')
"
```

Expected output: `PASS: RequestExampleRepo create + list_for_request round-trip`

- [ ] **Step 3: Commit**

```bash
git add web/api/repositories/request_example_repo.py
git commit -m "feat(api): add RequestExampleRepo for saved variant examples"
```

---

## Task 5: `discovery_service.group_requests()` and `save_library()`

**Files:**
- Modify: `web/api/services/discovery_service.py`

**Interfaces:**
- Consumes: `variant_grouper.group_requests/compute_diff_fields/suggest_label/templatize_request` (Task 3), `schema_merger.merge_schemas` (existing), `RequestExampleRepo` (Task 4), `_save_requests`/`_req_repo`/`_col_repo` (existing module-level names in this same file).
- Produces: `group_requests(requests: list[dict]) -> list[dict]` and `save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1) -> dict` (`{"imported": int, "collection_id": str}`) — consumed by Task 6's routes.

- [ ] **Step 1: Add the two functions**

Add to `web/api/services/discovery_service.py` (after `_save_requests`, using the existing module-level `_col_repo`/`_req_repo` instances already defined in this file):

```python
def group_requests(requests: list[dict]) -> list[dict]:
    """Preview grouping for Save-as-Library. Pure computation — nothing persisted."""
    from cli.api_discovery.variant_grouper import group_requests as _group
    return _group(requests)


def save_library(project_id: str, groups: list[dict], collection_name: str, include_in_docs: int = 1) -> dict:
    """Persist the user's resolved per-group choices from the Save-as-Library
    comparison UI. See docs/superpowers/specs/2026-07-05-api-variant-library-design.md
    Sections 2, 4, 5.

    groups: [{action: "separate"|"merge", checked_fields: [field_key, ...],
              variants: [{request: {...}, included: bool, name_override: str|None}, ...]}]
    """
    from cli.api_discovery.schema_merger import merge_schemas
    from cli.api_discovery.variant_grouper import compute_diff_fields, suggest_label, templatize_request
    from web.api.repositories.request_example_repo import RequestExampleRepo
    from web.api.services.doc_service import sync_doc_entry

    col = _col_repo.create(project_id, collection_name)
    example_repo = RequestExampleRepo()
    saved = 0

    for group in groups:
        included = [v for v in group.get("variants", []) if v.get("included", True)]
        if not included:
            continue

        if group.get("action") == "merge" and len(included) > 1:
            checked_keys = set(group.get("checked_fields", []))
            default_req = dict(included[0]["request"])
            merged_req = templatize_request(default_req, checked_keys)
            merged_req["collection_id"] = col["id"]
            merged_req["include_in_docs"] = include_in_docs
            for k in ("response_status", "response_headers", "response_body", "duration_ms"):
                merged_req.pop(k, None)

            req_schema = None
            resp_schema = None
            for v in included:
                req_schema = merge_schemas(req_schema, v["request"].get("request_schema"))
                resp_schema = merge_schemas(resp_schema, v["request"].get("response_schema"))
            merged_req["request_schema"] = req_schema
            merged_req["response_schema"] = resp_schema

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
        else:
            reqs = []
            for v in included:
                r = dict(v["request"])
                if v.get("name_override"):
                    r["name"] = v["name_override"]
                r["include_in_docs"] = include_in_docs
                reqs.append(r)
            saved += _save_requests(project_id, reqs, collection_id=col["id"])

    return {"imported": saved, "collection_id": col["id"]}
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
conn.commit()

from web.api.services.discovery_service import group_requests, save_library

reqs = [
  {'name': 'POST /users', 'method': 'POST', 'url': 'https://api.example.com/users', 'headers': [], 'params': [], 'body_type': 'raw', 'body': '{\"role\": \"admin\"}', 'request_schema': {'role': 'string'}, 'response_schema': {'id': 'number'}},
  {'name': 'POST /users', 'method': 'POST', 'url': 'https://api.example.com/users', 'headers': [], 'params': [], 'body_type': 'raw', 'body': '{\"role\": \"viewer\"}', 'request_schema': {'role': 'string'}, 'response_schema': {'id': 'number'}},
]
groups = group_requests(reqs)
assert len(groups) == 1 and groups[0]['needs_decision']
g = groups[0]
payload = [{
    'action': 'merge',
    'checked_fields': [f['key'] for f in g['diff_fields']],
    'variants': [{'request': v['request'], 'included': True} for v in g['variants']],
}]
result = save_library(pid, payload, 'Test Library')
assert result['imported'] == 1, result

from web.api.repositories.request_repo import RequestRepo
rows = RequestRepo().list(pid, collection_id=result['collection_id'])
assert len(rows) == 1
assert '{{role}}' in rows[0]['body'], rows[0]['body']

from web.api.repositories.request_example_repo import RequestExampleRepo
examples = RequestExampleRepo().list_for_request(rows[0]['id'])
assert len(examples) == 1, examples
assert examples[0]['label'] == 'role=viewer', examples[0]
print('PASS: save_library merges variants and stores one example')
"
```

Expected output: `PASS: save_library merges variants and stores one example`

- [ ] **Step 3: Commit**

```bash
git add web/api/services/discovery_service.py
git commit -m "feat(discovery): add group_requests/save_library service functions"
```

---

## Task 6: Routes — `/discover/group-requests` and `/discover/save-library`

**Files:**
- Modify: `web/api/routes/discovery.py`

**Interfaces:**
- Consumes: `discovery_service.group_requests`/`save_library` (Task 5), the file's existing `_project_id()` helper.
- Produces: `POST /api/discover/group-requests` (body `{requests}` → `{ok, groups}`), `POST /api/discover/save-library` (body `{groups, collection_name, include_in_docs}` → `{ok, imported, collection_id}`) — consumed by Task 8/9 frontend.

- [ ] **Step 1: Add the two routes**

Add to `web/api/routes/discovery.py`, near the existing `/api/discover/save-requests` route, following its exact try/except shape:

```python
@bp.route("/api/discover/group-requests", methods=["POST"])
def group_requests_route():
    """Preview grouping for Save-as-Library. Body: {requests}. Saves nothing."""
    try:
        data = request.get_json(force=True) or {}
        requests_list = data.get("requests", [])
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        from web.api.services.discovery_service import group_requests
        groups = group_requests(requests_list)
        return jsonify({"ok": True, "groups": groups})
    except Exception as e:
        logger.exception("group_requests_route")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/discover/save-library", methods=["POST"])
def save_library_route():
    """Commit the user's resolved per-group choices from the grouping preview.
    Body: {groups, collection_name, include_in_docs}."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        groups = data.get("groups", [])
        collection_name = data.get("collection_name", "Recorded APIs")
        include_in_docs = int(data.get("include_in_docs", 1))
        if not groups:
            return jsonify({"ok": False, "error": "No groups provided"}), 400
        from web.api.services.discovery_service import save_library
        result = save_library(pid, groups, collection_name, include_in_docs=include_in_docs)
        logger.info("save_library_route: saved %d to collection %s", result["imported"], result["collection_id"])
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("save_library_route")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 2: Verify manually**

Start the server, set an active project, and exercise both routes with curl:

```bash
python qaclan.py serve --port 7823 &
sleep 2
curl -s -X POST http://localhost:7823/api/discover/group-requests \
  -H 'Content-Type: application/json' \
  -d '{"requests":[{"method":"GET","url":"https://api.example.com/cart?sort=price","headers":[],"params":[{"key":"sort","value":"price"}]},{"method":"GET","url":"https://api.example.com/cart?sort=date","headers":[],"params":[{"key":"sort","value":"date"}]}]}'
```

Expected: JSON with `"ok":true` and one group for `GET /cart` with `"needs_decision":true` and two variants. Then kill the server (`kill %1`).

- [ ] **Step 3: Commit**

```bash
git add web/api/routes/discovery.py
git commit -m "feat(discovery): add group-requests and save-library routes"
```

---

## Task 7: `GET /api/api-requests/<req_id>/examples`

**Files:**
- Modify: `web/api/services/request_service.py`
- Modify: `web/api/routes/requests.py`

**Interfaces:**
- Consumes: `RequestExampleRepo.list_for_request` (Task 4), existing `_repo`/`_svc` module-level instances in these two files.
- Produces: `RequestService.list_examples(request_id, project_id) -> list[dict]`; route `GET /api/api-requests/<req_id>/examples` → `{ok, examples}` — consumed by Task 11 (request editor).

- [ ] **Step 1: Add the service method**

Add to `web/api/services/request_service.py`, inside `RequestService`:

```python
    def list_examples(self, request_id: str, project_id: str) -> list[dict]:
        existing = _repo.get(request_id, project_id)
        if existing is None:
            raise LookupError(f"Request {request_id} not found")
        from web.api.repositories.request_example_repo import RequestExampleRepo
        return RequestExampleRepo().list_for_request(request_id)
```

- [ ] **Step 2: Add the route**

Add to `web/api/routes/requests.py`, after `send_request`:

```python
@bp.route("/api/api-requests/<req_id>/examples", methods=["GET"])
def list_request_examples(req_id):
    try:
        return jsonify({"ok": True, "examples": _svc.list_examples(req_id, _project_id())})
    except LookupError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("list_request_examples")
        return jsonify({"ok": False, "error": str(e)}), 500
```

- [ ] **Step 3: Verify manually**

```bash
python qaclan.py serve --port 7823 &
sleep 2
# Substitute a real request id from your local DB (e.g. one saved in Task 5's manual test, or via the UI)
curl -s http://localhost:7823/api/api-requests/apireq_XXXXXXXX/examples
kill %1
```

Expected: `{"ok":true,"examples":[...]}` (empty list is fine if the request has no saved examples).

- [ ] **Step 4: Commit**

```bash
git add web/api/services/request_service.py web/api/routes/requests.py
git commit -m "feat(api): add GET /api-requests/<id>/examples endpoint"
```

---

## Task 8: Flow/Library choice in the existing review modal

**Files:**
- Modify: `web/static/api/views/request-review-modal.js`

**Interfaces:**
- Consumes: `/discover/group-requests` (Task 6), `showVariantComparisonModal` (Task 9 — imported here).
- Produces: nothing new consumed elsewhere; this is the entry point users click through.

- [ ] **Step 1: Add the import**

At the top of `web/static/api/views/request-review-modal.js`:

```js
import { showVariantComparisonModal } from './variant-comparison-modal.js';
```

- [ ] **Step 2: Add the radio to `modalBody`**

In the `modalBody` template literal, right after the `Include in API Documentation` checkbox line, add:

```js
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border-subtle);">
      <label style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;cursor:pointer;">
        <input type="radio" name="rev-save-mode" value="flow" checked style="margin-top:3px;">
        <span><strong>Save as Flow</strong><br><span style="font-size:11px;color:var(--text-muted)">preserve exact order + repeats — for replaying this real flow</span></span>
      </label>
      <label style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;cursor:pointer;">
        <input type="radio" name="rev-save-mode" value="library" style="margin-top:3px;">
        <span><strong>Save as Library</strong><br><span style="font-size:11px;color:var(--text-muted)">group by endpoint, show variants — for building reusable requests</span></span>
      </label>
    </div>`;
```

(This replaces the closing `` `; `` of the template literal — keep everything before it unchanged.)

- [ ] **Step 3: Branch the Save button's action on the selected mode**

Replace the `'Save Selected'` button's `action` (currently the whole body of that button) with:

```js
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
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
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${colName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
```

- [ ] **Step 4: Toggle the button label when the radio changes**

In the `requestAnimationFrame(() => { ... })` block at the bottom of `showRequestReviewModal`, after the existing `rev-hide-3p` listener, add:

```js
    const saveBtn = document.querySelector('[data-btn-idx="1"]');
    document.querySelectorAll('input[name="rev-save-mode"]').forEach(r => {
      r.addEventListener('change', () => {
        const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value;
        if (saveBtn) saveBtn.textContent = mode === 'library' ? 'Next →' : 'Save Selected';
      });
    });
```

- [ ] **Step 5: Verify manually**

```bash
node --check web/static/api/views/request-review-modal.js
```

Expected: no output (exit code 0). Then run `python qaclan.py serve --port 7823`, open the web UI, run a Record APIs session (or import a HAR with a repeated endpoint), and confirm: the review modal shows the new radio, the Save button reads "Save Selected" by default and switches to "Next →" when "Save as Library" is selected, and clicking it while "Save as Library" is selected opens a (still-placeholder-empty, until Task 9) new modal instead of saving immediately.

- [ ] **Step 6: Commit**

```bash
git add web/static/api/views/request-review-modal.js
git commit -m "feat(discovery): add Save as Flow/Library choice to review modal"
```

---

## Task 9: Variant comparison modal (Modal 2)

**Files:**
- Create: `web/static/api/views/variant-comparison-modal.js`

**Interfaces:**
- Consumes: the `groups` array shape produced by `/discover/group-requests` (Task 6 / `variant_grouper.group_requests`, Task 3).
- Produces: `showVariantComparisonModal(groups, collectionName, includeInDocs)`, imported by Task 8.

- [ ] **Step 1: Write the module**

```js
function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

export function showVariantComparisonModal(groups, collectionName, includeInDocs) {
  if (!groups?.length) {
    window._alertDialog('Nothing to group — no requests were provided.');
    return;
  }

  const state = groups.map((g, gi) => ({
    ...g,
    _gi: gi,
    action: g.default_action === 'keep_single' ? 'separate' : 'merge',
    included: g.variants.map(() => true),
    checkedFields: new Set(g.diff_fields.filter(f => f.checked_default).map(f => f.key)),
  }));

  function _groupHTML(g) {
    const rows = g.variants.map((v, vi) => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;border-bottom:1px solid var(--border-subtle);font-size:12px;">
        <input type="checkbox" data-gi="${g._gi}" data-vi="${vi}" class="vcm-row-check" ${state[g._gi].included[vi] ? 'checked' : ''}>
        <span style="flex:1;font-family:var(--font-mono,monospace);color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${_esc(v.label_suggestion || v.request.name || `variant ${vi + 1}`)}
        </span>
        ${v.request.response_status ? `<span style="color:var(--text-muted);font-size:11px;">${_esc(String(v.request.response_status))}${v.request.duration_ms ? ` · ${v.request.duration_ms}ms` : ''}</span>` : ''}
        ${v.dup_count > 1 ? `<span class="badge badge-neutral" style="font-size:10px;">${v.dup_count - 1} dup${v.dup_count - 1 !== 1 ? 's' : ''} collapsed</span>` : ''}
      </div>`).join('');

    const fieldsHTML = g.needs_decision ? g.diff_fields.map(f => `
      <label style="display:flex;align-items:center;gap:6px;padding:3px 0 3px 24px;font-size:12px;cursor:pointer;">
        <input type="checkbox" data-gi="${g._gi}" data-field="${_esc(f.key)}" class="vcm-field-check" ${state[g._gi].checkedFields.has(f.key) ? 'checked' : ''}>
        <code style="font-family:var(--font-mono,monospace);color:var(--accent);">${_esc(f.field_name)}</code>
        <span style="color:var(--text-muted);">(${f.values.map(fv => _esc(String(fv ?? '—'))).join(' / ')}) &rarr; <code>{{${_esc(f.field_name)}}}</code></span>
      </label>`).join('') : '';

    const radioHTML = g.needs_decision ? `
      <div style="display:flex;gap:16px;padding:6px 8px;font-size:12px;">
        <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
          <input type="radio" name="vcm-action-${g._gi}" value="separate" class="vcm-action-radio" data-gi="${g._gi}" ${state[g._gi].action === 'separate' ? 'checked' : ''}>
          Keep as separate named requests
        </label>
        <label style="display:flex;align-items:center;gap:5px;cursor:pointer;">
          <input type="radio" name="vcm-action-${g._gi}" value="merge" class="vcm-action-radio" data-gi="${g._gi}" ${state[g._gi].action === 'merge' ? 'checked' : ''}>
          Merge into one parameterized request
        </label>
      </div>
      <div class="vcm-fields-${g._gi}" style="display:${state[g._gi].action === 'merge' ? '' : 'none'};">${fieldsHTML}</div>` : '';

    return `
      <div style="margin-bottom:14px;border:1px solid var(--border);border-radius:6px;overflow:hidden;">
        <div style="padding:6px 8px;background:var(--surface-2);font-size:12px;font-weight:600;">
          ${_esc(g.endpoint_label)} — ${g.variants.length} variant${g.variants.length !== 1 ? 's' : ''}${g.exact_dups_collapsed ? ` (${g.exact_dups_collapsed} exact dup${g.exact_dups_collapsed !== 1 ? 's' : ''} collapsed)` : ''}
        </div>
        <div>${rows}</div>
        ${radioHTML}
      </div>`;
  }

  function _render() {
    const listEl = document.getElementById('vcm-list');
    if (!listEl) return;
    listEl.innerHTML = state.map(_groupHTML).join('');

    listEl.querySelectorAll('.vcm-row-check').forEach(cb => cb.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi), vi = Number(e.target.dataset.vi);
      state[gi].included[vi] = e.target.checked;
    }));
    listEl.querySelectorAll('.vcm-action-radio').forEach(r => r.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi);
      state[gi].action = e.target.value;
      const fieldsEl = listEl.querySelector(`.vcm-fields-${gi}`);
      if (fieldsEl) fieldsEl.style.display = e.target.value === 'merge' ? '' : 'none';
    }));
    listEl.querySelectorAll('.vcm-field-check').forEach(cb => cb.addEventListener('change', e => {
      const gi = Number(e.target.dataset.gi), field = e.target.dataset.field;
      if (e.target.checked) state[gi].checkedFields.add(field);
      else state[gi].checkedFields.delete(field);
    }));
  }

  const modalBody = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px;">
      ${groups.length} endpoint group${groups.length !== 1 ? 's' : ''}. Resolve each group, then save.
    </p>
    <div id="vcm-list" style="max-height:480px;overflow-y:auto;"></div>`;

  window.showModal('Review Variants', modalBody, [
    { label: 'Cancel', cls: 'btn-ghost', action: window.closeModal },
    { label: 'Save', cls: 'btn-primary', action: async () => {
      const payloadGroups = state.map(g => ({
        endpoint_label: g.endpoint_label,
        action: g.action,
        checked_fields: Array.from(g.checkedFields),
        variants: g.variants.map((v, vi) => ({ request: v.request, included: g.included[vi] })),
      }));
      const data = await window.api('POST', '/discover/save-library', {
        groups: payloadGroups,
        collection_name: collectionName,
        include_in_docs: includeInDocs,
      });
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${collectionName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
  ], null, 'lg');

  requestAnimationFrame(_render);
}
```

- [ ] **Step 2: Verify manually**

```bash
node --check web/static/api/views/variant-comparison-modal.js
```

Expected: no output (exit code 0). Then, continuing from Task 8's manual check, confirm Modal 2 renders one card per endpoint group, the merge/separate radio toggles the field-checkbox list visibility, unchecking a variant row removes it from what gets saved, and clicking Save calls `/discover/save-library` and closes both modals with a success toast.

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/variant-comparison-modal.js
git commit -m "feat(discovery): add variant comparison modal (Save-as-Library Modal 2)"
```

---

## Task 10: "Captured, not live" banner mode in the response panel

**Files:**
- Modify: `web/static/api/components/response-panel.js`

**Interfaces:**
- Consumes: nothing new.
- Produces: `show(result, meta = null)` — `meta: {captured: true, label: string} | null`. Existing call sites (`responsePanel.show(res.result)`) are unaffected since `meta` defaults to `null`. Consumed by Task 11.

- [ ] **Step 1: Update `show()`**

Replace:

```js
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
    const _varCount = Object.keys(result.state_updates || {}).length;
    if (_varCount) tabBar.appendChild(_renderTab(`Variables (${_varCount})`, 'vars', false));

    _renderContent('body');
  }
```

with:

```js
  function show(result, meta = null) {
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
    if (meta?.captured) {
      statusSpan.className = 'response-status response-status-warn';
      statusSpan.textContent = `⚠ Captured example · not live${meta.label ? ' · ' + meta.label : ''}`;
      statusSpan.title = statusCode ? `${statusCode} · ${duration}ms at capture time` : 'No status captured';
    } else {
      statusSpan.className = `response-status ${statusClass}`;
      statusSpan.textContent = statusCode ? `${statusCode} · ${duration}ms` : `ERROR · ${duration}ms`;
    }
    tabBar.appendChild(statusSpan);

    tabBar.appendChild(_renderTab('Body', 'body', true));
    tabBar.appendChild(_renderTab('Headers', 'headers', false));
    tabBar.appendChild(_renderTab(`Assertions (${assertPass}/${assertCount})`, 'assertions', false));
    const _varCount = Object.keys(result.state_updates || {}).length;
    if (_varCount) tabBar.appendChild(_renderTab(`Variables (${_varCount})`, 'vars', false));

    _renderContent('body');
  }
```

- [ ] **Step 2: Verify manually**

```bash
node --check web/static/api/components/response-panel.js
```

Expected: no output (exit code 0). Full behavioral check happens in Task 11 (there's nothing to click yet without the Examples dropdown).

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/response-panel.js
git commit -m "feat(api-ui): add captured-example banner mode to response panel"
```

---

## Task 11: Examples dropdown in the request editor

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: `GET /api-requests/<id>/examples` (Task 7), `responsePanel.show(result, meta)` (Task 10).
- Produces: nothing consumed elsewhere — this is the final UI surface in the spec.

- [ ] **Step 1: Fetch examples alongside the existing request load**

Replace:

```js
  let existing = null;
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
  }
```

with:

```js
  let existing = null;
  let examples = [];
  if (requestId) {
    const res = await window.api('GET', `/api-requests/${requestId}`);
    if (res.ok === false) {
      container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">${res.error}</p></div>`;
      return;
    }
    existing = res.request;
    const exRes = await window.api('GET', `/api-requests/${requestId}/examples`);
    if (exRes.ok !== false) examples = exRes.examples || [];
  }
```

- [ ] **Step 2: Render the dropdown next to Send**

After the existing `urlBar.appendChild(sendBtn);` line, add:

```js
  let examplesSelect = null;
  if (examples.length) {
    examplesSelect = document.createElement('select');
    examplesSelect.className = 'req-examples-select';
    examplesSelect.style.cssText = 'font-size:12px;max-width:160px;';
    examplesSelect.title = 'Load a previously captured example';

    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = 'Default values';
    examplesSelect.appendChild(defaultOpt);

    examples.forEach(ex => {
      const opt = document.createElement('option');
      opt.value = ex.id;
      opt.textContent = ex.label;
      examplesSelect.appendChild(opt);
    });
    urlBar.appendChild(examplesSelect);

    // paramsTable, responsePanel, and _setBodyValue are declared further down in this
    // function; this listener only ever runs after the user interacts with the
    // dropdown, by which point the whole function body (and those consts) has run.
    examplesSelect.onchange = () => {
      const chosen = examples.find(ex => ex.id === examplesSelect.value);
      if (!chosen) {
        paramsTable.setRows(r.params || []);
        _setBodyValue(r.body || '');
        responsePanel.el.style.display = 'none';
        return;
      }
      paramsTable.setRows(chosen.params || []);
      _setBodyValue(chosen.body || '');
      responsePanel.show({
        status_code: chosen.response_status,
        duration_ms: null,
        response_body: chosen.response_body,
        response_headers: chosen.response_headers || {},
        assertion_results: [],
        state_updates: {},
      }, { captured: true, label: chosen.label });
    };
  }
```

- [ ] **Step 3: Verify manually**

```bash
node --check web/static/api/views/request-editor-view.js
```

Expected: no output (exit code 0). Then, using a request saved via the Task 8/9 manual flow (one that went through a "Merge" group and therefore has saved examples), open it in the request editor and confirm: the `[Examples ▾]` dropdown appears next to Send with "Default values" plus one entry per saved example; selecting an example fills Params/Body with its captured values and shows the response panel with the `⚠ Captured example · not live` banner and that example's stored status/body; selecting "Default values" reverts the fields and hides the panel; clicking Send fires a live request and the banner is replaced by a normal live result (since the existing Send handler already calls `responsePanel.show(res.result)` with no second argument, `meta` defaults to `null`).

- [ ] **Step 4: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat(api-ui): add Examples dropdown to request editor"
```

---

## Task 12: End-to-end manual verification

**Files:** none (verification only).

- [ ] **Step 1: Full flow through a real recording**

1. `python qaclan.py serve --port 7823`, open the web UI, set an active project.
2. Start "Record APIs" mode against any site, trigger the same endpoint 2-3 times with different query params or POST bodies (e.g. a search box with different query values, or a form submitted with different field values), stop recording.
3. In the review modal, confirm the new Flow/Library radio appears (Flow selected by default) and the Save button reads "Save Selected".
4. Select "Save as Library" — confirm the button changes to "Next →".
5. Click "Next →" — confirm Modal 2 opens showing one group per distinct endpoint, with variant rows, status/duration where available, and a dup-collapsed count if any repeats were byte-identical.
6. For one group with 2+ variants, leave "Merge" selected and confirm the diff-field checkboxes list the fields that actually differ.
7. For another group (if present), switch to "Keep as separate".
8. Click Save — confirm a success toast and that the collection now contains the expected rows (one merged `{{var}}`-templated request, or several separately-named requests).
9. Open the merged request in the request editor — confirm the `[Examples ▾]` dropdown lists the non-default captured variants, selecting one updates Params/Body and shows the "Captured example · not live" banner with the right stored response, and clicking Send replaces it with a fresh live result.

- [ ] **Step 2: Confirm the Flow path is unaffected**

Repeat steps 1-2 above, but choose "Save as Flow" in the review modal. Confirm the Save button stays "Save Selected", clicking it saves immediately (no Modal 2), and every captured request — including exact duplicates — lands as its own row in the resulting collection, in capture order. This confirms the existing behavior is untouched.
