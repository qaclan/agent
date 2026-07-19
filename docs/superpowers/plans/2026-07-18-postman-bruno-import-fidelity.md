# Postman/Bruno Import Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Postman/Bruno import produce requests that actually run — correct path vars, real folder trees, auth, collection vars, and a script/assertion conversion that keeps qaclan's DB as the single point of truth (`qc.*` JS, not foreign `pm.*`/`bru.*` calls).

**Architecture:** Two new small shared modules (`script_rewrite.py`, `path_vars.py`) used by both parsers. Both parsers rewritten to emit `folder_path`, `path_params`, mapped auth, and rewritten scripts/assertions. `discovery_service.py` gains folder-tree resolution and collection-var writing on the save path, plus a `warnings` list threaded back to the caller.

**Tech Stack:** Python 3, stdlib `re`/`json` only — no new dependencies.

## Global Constraints

- No automated test suite in this repo (per CLAUDE.md) — every task's verification step is a runnable manual script (`python -c` / a small fixture script run via the venv), not pytest.
- qaclan URL syntax: `{param}` for path params, `{{VAR}}` for env/state vars (`cli/api_runner.py::_PATH_PARAM_RE`).
- qaclan auth types: exactly `bearer`, `basic`, `api_key`, `oauth2` (client_credentials only), `inherit`, `none` — see `cli/api_runner.py::_apply_auth`.
- qaclan assertion ops: exactly `eq, ne, lt, gt, contains, exists, not_exists, matches` — no `gte`/`lte`.
- `RequestRepo._serialize`/`_deserialize` (`web/api/repositories/request_repo.py:34-60`) already JSON-encode/decode `headers, params, path_params, assertions, pre_extractor, post_extractor, auth_config` automatically on `create()` — parsers should emit native Python lists/dicts for these fields, not pre-serialized JSON strings.
- Full mapping tables live in `docs/superpowers/specs/2026-07-18-postman-bruno-import-fidelity-design.md` — this plan implements that spec exactly; consult it for anything not reproduced here.

---

### Task 1: Shared script rewrite module

**Files:**
- Create: `cli/api_discovery/script_rewrite.py`

**Interfaces:**
- Produces: `foreign_script_to_qc(script: str) -> tuple[str, list[str]]` — returns `(rewritten_script, warnings)`. Used by Task 3 (Postman) and Task 4 (Bruno) for both `pre_script`/`post_script`.

- [ ] **Step 1: Write the module**

```python
# cli/api_discovery/script_rewrite.py
from __future__ import annotations
import re

# Direct call-name substitutions: same argument list both sides, so a
# straight prefix swap is correct. Order matters — longer/more specific
# patterns first so a generic one doesn't shadow a specific one.
_DIRECT_REWRITES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpm\.environment\.set\("), "qc.set("),
    (re.compile(r"\bpm\.variables\.set\("), "qc.set("),
    (re.compile(r"\bbru\.setEnvVar\("), "qc.set("),
    (re.compile(r"\bbru\.setVar\("), "qc.set("),
    (re.compile(r"\bpm\.test\("), "qc.test("),
    (re.compile(r"(?<![.\w])test\("), "qc.test("),
    (re.compile(r"\breq\.setHeader\("), "qc.setHeader("),
    (re.compile(r"\breq\.getHeader\("), "qc.getHeader("),
    (re.compile(r"\bpm\.request\.headers\.get\("), "qc.getHeader("),
    (re.compile(r"\bpm\.request\.url\.query\.get\("), "qc.getParam("),
    (re.compile(r"\bpm\.response\.json\("), "response.json("),
    (re.compile(r"\bpm\.response\.text\("), "response.text("),
    (re.compile(r"\bpm\.response\.headers\b"), "response.headers"),
    (re.compile(r"\bpm\.response\.(?:status|code)\b"), "response.status"),
    (re.compile(r"\bres\.headers\b"), "response.headers"),
    (re.compile(r"\bres\.status\b"), "response.status"),
    (re.compile(r"\bres\.body\b"), "response.json()"),
]

# Object-literal-argument calls: `fn({key: K, value: V})` -> `qc.x(K, V)`.
# Best-effort regex, not a JS parser — values with nested braces/commas in
# the object literal itself won't match and fall through unconverted.
_OBJECT_REWRITES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"pm\.request\.headers\.add\(\s*\{\s*key\s*:\s*(.+?)\s*,\s*value\s*:\s*(.+?)\s*\}\s*\)"),
     r"qc.setHeader(\1, \2)"),
    (re.compile(r"pm\.request\.url\.addQueryParams\(\s*\{\s*key\s*:\s*(.+?)\s*,\s*value\s*:\s*(.+?)\s*\}\s*\)"),
     r"qc.setParam(\1, \2)"),
]

# pm.expect(EXPR).to.[not.]MATCHER(ARG) / bare expect(EXPR).to....
# qc.expect(condition, message) takes a plain boolean, not a chainable —
# so the whole matched line is rewritten, not just the call name.
_EXPECT_RE = re.compile(
    r"(?:pm\.)?expect\((?P<expr>.+?)\)\.to\.(?P<neg>not\.)?"
    r"(?P<matcher>equal|eql|be\.true|be\.false|exist|include|match)"
    r"(?:\((?P<arg>.*)\))?\s*;?\s*$"
)

_UNCONVERTED_MARKERS = [
    re.compile(r"\bpm\.sendRequest\b"),
    re.compile(r"\bpm\.cookies\b"),
    re.compile(r"\bpm\.iterationData\b"),
    re.compile(r"\bbru\.runRequest\b"),
    re.compile(r"\bpm\.\w+"),
    re.compile(r"\bbru\.\w+"),
]


def _rewrite_expect_line(line: str) -> str | None:
    m = _EXPECT_RE.search(line)
    if not m:
        return None
    expr = m.group("expr").strip()
    matcher = m.group("matcher")
    arg = (m.group("arg") or "").strip()
    if matcher == "equal":
        cond = f"{expr} === {arg}"
    elif matcher == "eql":
        cond = f"JSON.stringify({expr}) === JSON.stringify({arg})"
    elif matcher == "be.true":
        cond = f"{expr} === true"
    elif matcher == "be.false":
        cond = f"{expr} === false"
    elif matcher == "exist":
        cond = f"{expr} !== undefined && {expr} !== null"
    elif matcher == "include":
        cond = f"({expr}).includes({arg})"
    elif matcher == "match":
        cond = f"{arg}.test({expr})"
    else:
        return None
    if m.group("neg"):
        cond = f"!({cond})"
    message = line.strip().replace('"', "'")
    indent = line[: len(line) - len(line.lstrip())]
    return f'{indent}qc.expect({cond}, "{message}");'


def _apply_direct_rewrites(line: str) -> str:
    for pattern, replacement in _DIRECT_REWRITES:
        line = pattern.sub(replacement, line)
    for pattern, replacement in _OBJECT_REWRITES:
        line = pattern.sub(replacement, line)
    return line


def foreign_script_to_qc(script: str | None) -> tuple[str | None, list[str]]:
    """Rewrite Postman/Bruno pre/post script JS into native qc.* JS.

    Returns (rewritten_script, warnings). Anything not recognized is left
    as-is in the output and reported in warnings, never silently dropped.
    """
    if not script:
        return script, []

    out_lines = []
    for line in script.splitlines():
        rewritten = _rewrite_expect_line(line)
        out_lines.append(rewritten if rewritten is not None else _apply_direct_rewrites(line))
    text = "\n".join(out_lines)

    warnings: list[str] = []
    seen = set()
    for pattern in _UNCONVERTED_MARKERS:
        for match in pattern.finditer(text):
            token = match.group(0)
            if token not in seen:
                seen.add(token)
                warnings.append(f"unconverted script call: {token}")
    return text, warnings
```

- [ ] **Step 2: Verify with a manual smoke script**

Run:
```bash
python -c "
from cli.api_discovery.script_rewrite import foreign_script_to_qc

script = '''
pm.environment.set(\"token\", pm.response.json().token);
pm.test(\"status is 200\", () => pm.response.to.have.status(200));
pm.expect(pm.response.json().id).to.equal(42);
pm.expect(pm.response.json().name).to.not.exist;
pm.sendRequest(\"http://x\", () => {});
'''
text, warnings = foreign_script_to_qc(script)
print(text)
print('WARNINGS:', warnings)
"
```

Expected output: `qc.set(` / `qc.test(` lines present, the `.to.equal(42)` line
rewritten to `qc.expect(pm.response.json().id === 42, ...)`, the
`.to.not.exist` line rewritten to a `!== undefined && !== null` condition,
and `WARNINGS: ['unconverted script call: pm.sendRequest']` (the `.to.have.status(200)` chain inside the `pm.test` callback is intentionally NOT
rewritten by this pass — it's an argument to `pm.test(`, not a top-level
`.expect()` chain; it's covered separately in Task 3/4 since
`pm.response.to.have.status` isn't in the `_EXPECT_RE` matcher set. Confirm
it appears verbatim in the output, unconverted).

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/script_rewrite.py
git commit -m "feat(api-discovery): add Postman/Bruno script-to-qc rewrite module"
```

---

### Task 2: Path-variable conversion helper

**Files:**
- Create: `cli/api_discovery/path_vars.py`

**Interfaces:**
- Produces: `convert_path_vars(url: str, seed_values: dict[str, str] | None = None) -> tuple[str, list[dict]]` — returns `(url_with_braces, path_params)` where `path_params` is `[{"key": ..., "value": ..., "enabled": True}, ...]`. Used by Task 3 and Task 4.

- [ ] **Step 1: Write the module**

```python
# cli/api_discovery/path_vars.py
from __future__ import annotations
import re

# Matches a Postman/Bruno path variable segment, e.g. :id or :userId.
# Deliberately does NOT match {{var}} (qaclan/Postman's own env-var syntax,
# already compatible with qaclan and left untouched).
_COLON_VAR_RE = re.compile(r":([A-Za-z_]\w*)")


def convert_path_vars(url: str, seed_values: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Convert Postman/Bruno `:var` path segments to qaclan's `{var}` syntax.

    seed_values: known values for path vars (e.g. from Postman's
    url.variable[] or Bruno's params:path block), keyed by var name.
    """
    seed_values = seed_values or {}
    path_params: list[dict] = []
    seen: set[str] = set()

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            path_params.append({
                "key": key,
                "value": seed_values.get(key, ""),
                "enabled": True,
            })
        return "{" + key + "}"

    # Only rewrite the path portion, not the query string, so a stray
    # ":" inside a query value (unusual, but possible) is left alone.
    if "?" in url:
        path_part, _, query_part = url.partition("?")
        new_path = _COLON_VAR_RE.sub(_replace, path_part)
        new_url = f"{new_path}?{query_part}"
    else:
        new_url = _COLON_VAR_RE.sub(_replace, url)

    return new_url, path_params
```

- [ ] **Step 2: Verify with a manual smoke script**

Run:
```bash
python -c "
from cli.api_discovery.path_vars import convert_path_vars
url, params = convert_path_vars('https://api.example.com/users/:userId/posts/:postId?sort=desc', {'userId': '123'})
print(url)
print(params)
"
```

Expected output:
```
https://api.example.com/users/{userId}/posts/{postId}?sort=desc
[{'key': 'userId', 'value': '123', 'enabled': True}, {'key': 'postId', 'value': '', 'enabled': True}]
```

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/path_vars.py
git commit -m "feat(api-discovery): add :var to {var} path conversion helper"
```

---

### Task 3: Rewrite `postman_parser.py`

**Files:**
- Modify: `cli/api_discovery/postman_parser.py` (full rewrite, 124 → ~230 lines)

**Interfaces:**
- Consumes: `foreign_script_to_qc` (Task 1), `convert_path_vars` (Task 2).
- Produces: `parse_postman(collection: dict) -> dict` — **signature change** from
  `list[dict]` to `{"requests": [...], "folders": [...], "collection_vars": {...}, "collection_auth": {...} | None, "warnings": [...]}`.
  Each request dict gains `folder_path: list[str]`, `path_params: list[dict]`,
  populated `auth_type`/`auth_config`, `pre_script`/`pre_lang`. Task 5 (service
  layer) consumes this new dict shape.

- [ ] **Step 1: Write the rewritten parser**

```python
# cli/api_discovery/postman_parser.py
from __future__ import annotations
import json
import logging

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc

logger = logging.getLogger("qaclan.postman_parser")

_AUTH_TYPE_MAP = {"bearer", "basic", "apikey", "oauth2"}


def _convert_auth(auth_obj: dict | None, warnings: list[str], context: str) -> tuple[str, dict]:
    """Map a Postman auth block to (qaclan auth_type, auth_config)."""
    if not auth_obj:
        return "inherit", {}
    ptype = auth_obj.get("type", "noauth")
    if ptype == "noauth":
        return "inherit", {}

    def _attrs(key: str) -> dict:
        return {a.get("key"): a.get("value") for a in auth_obj.get(key, []) if a.get("key")}

    if ptype == "bearer":
        a = _attrs("bearer")
        return "bearer", {"token": a.get("token", "")}
    if ptype == "basic":
        a = _attrs("basic")
        return "basic", {"username": a.get("username", ""), "password": a.get("password", "")}
    if ptype == "apikey":
        a = _attrs("apikey")
        return "api_key", {"key": a.get("key", "X-API-Key"), "value": a.get("value", ""), "in": a.get("in", "header")}
    if ptype == "oauth2":
        a = _attrs("oauth2")
        if a.get("grant_type", "client_credentials") == "client_credentials":
            return "oauth2", {
                "token_url": a.get("accessTokenUrl", ""),
                "client_id": a.get("clientId", ""),
                "client_secret": a.get("clientSecret", ""),
            }
        warnings.append(f"{context}: oauth2 grant '{a.get('grant_type')}' not supported, auth set to none")
        return "none", {}

    warnings.append(f"{context}: auth type '{ptype}' not supported, auth set to none")
    return "none", {}


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


def _convert_events(item: dict) -> tuple[str | None, str | None, list[str]]:
    pre_script = None
    post_script = None
    for event in item.get("event", []):
        listen = event.get("listen")
        lines = event.get("script", {}).get("exec", [])
        text = "\n".join(lines)
        if listen == "prerequest":
            pre_script = text
        elif listen == "test":
            post_script = text
    warnings: list[str] = []
    if pre_script:
        pre_script, w = foreign_script_to_qc(pre_script)
        warnings.extend(w)
    if post_script:
        post_script, w = foreign_script_to_qc(post_script)
        warnings.extend(w)
    return pre_script, post_script, warnings


def _process_item(item: dict, folder_path: list[str], results: list, warnings: list[str]):
    if "item" in item:
        sub_path = folder_path + [item.get("name", "Folder")] if item.get("name") else folder_path
        for sub in item["item"]:
            _process_item(sub, sub_path, results, warnings)
        return

    req = item.get("request", {})
    if not req:
        return
    name = item.get("name", "Unnamed Request")
    context = f"'{name}'"

    url_obj = req.get("url", {})
    if isinstance(url_obj, str):
        raw, query_params = url_obj, []
    else:
        raw = url_obj.get("raw", "")
        if not raw:
            host = ".".join(url_obj.get("host", []))
            path = "/".join(url_obj.get("path", []))
            raw = f"https://{host}/{path}"
        raw = raw.split("?")[0]
        query_params = [
            {"key": q.get("key", ""), "value": q.get("value", ""), "enabled": True}
            for q in url_obj.get("query", []) if not q.get("disabled", False)
        ]
        var_seed = {v.get("key"): v.get("value", "") for v in url_obj.get("variable", []) if v.get("key")}

    if isinstance(url_obj, str):
        var_seed = {}
    url, path_params = convert_path_vars(raw, var_seed)

    method = req.get("method", "GET").upper()
    headers = [
        {"key": h.get("key", ""), "value": h.get("value", ""), "enabled": True}
        for h in req.get("header", []) if not h.get("disabled", False)
    ]
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
        "auth_config": auth_config,
        "assertions": [],
        "pre_script": pre_script,
        "pre_lang": "js",
        "post_script": post_script,
        "post_lang": "js",
        "folder_path": folder_path,
    })


def parse_postman(collection: dict) -> dict:
    """Parse Postman Collection v2.1 JSON.

    Returns {"requests": [...], "collection_vars": {...},
             "collection_auth": (auth_type, auth_config) | None,
             "warnings": [...]}.
    """
    warnings: list[str] = []
    results: list[dict] = []

    items = collection.get("item", [])
    for item in items:
        _process_item(item, [], results, warnings)

    collection_vars = {
        v.get("key"): str(v.get("value", ""))
        for v in collection.get("variable", []) if v.get("key")
    }

    collection_auth = None
    if collection.get("auth"):
        auth_type, auth_config = _convert_auth(collection.get("auth"), warnings, "collection")
        if auth_type != "inherit":
            collection_auth = (auth_type, auth_config)

    logger.info("parse_postman: extracted %d requests, %d warnings", len(results), len(warnings))
    return {
        "requests": results,
        "collection_vars": collection_vars,
        "collection_auth": collection_auth,
        "warnings": warnings,
    }
```

- [ ] **Step 2: Verify with a manual fixture**

```bash
mkdir -p /tmp/qaclan_import_test
cat > /tmp/qaclan_import_test/postman_fixture.json <<'EOF'
{
  "info": {"name": "Test Collection"},
  "variable": [{"key": "baseUrl", "value": "https://api.example.com"}],
  "item": [
    {
      "name": "Auth",
      "item": [
        {
          "name": "Get User",
          "request": {
            "method": "GET",
            "url": {"raw": "{{baseUrl}}/users/:id", "path": ["users", ":id"], "variable": [{"key": "id", "value": "42"}]},
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{authToken}}"}]},
            "event": [
              {"listen": "test", "script": {"exec": ["pm.test(\"status is 200\", () => pm.response.to.have.status(200));", "pm.expect(pm.response.json().id).to.equal(42);"]}}
            ]
          }
        }
      ]
    }
  ]
}
EOF
python -c "
import json
from cli.api_discovery.postman_parser import parse_postman
data = json.load(open('/tmp/qaclan_import_test/postman_fixture.json'))
result = parse_postman(data)
print(json.dumps(result, indent=2))
"
```

Expected: one request with `url` containing `{id}`, `path_params: [{"key": "id", "value": "42", ...}]`, `auth_type: "bearer"`, `folder_path: ["Auth"]`, `collection_vars: {"baseUrl": "https://api.example.com"}`, and `post_script` containing `qc.test(` + a `qc.expect(` line generated from `.to.equal(42)` (the `.to.have.status(200)` chain inside the `pm.test` callback stays as literal `pm.response.to.have.status(200)` text — not rewritten, since it's nested inside an arrow-function argument, not a top-level `.expect()` chain; this is expected and matches Task 1's documented behavior).

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/postman_parser.py
git commit -m "feat(api-discovery): full-fidelity Postman import (folders, auth, path vars, scripts)"
```

---

### Task 4: Rewrite `bruno_parser.py` import side

**Files:**
- Modify: `cli/api_discovery/bruno_parser.py:1-139` (import side only — `request_to_bru` at the bottom is untouched by this task, revisited in the export plan)

**Interfaces:**
- Consumes: `foreign_script_to_qc` (Task 1), `convert_path_vars` (Task 2).
- Produces: `parse_bruno(bru_text: str) -> dict` — **signature change** from
  `list[dict]` to `{"requests": [...], "warnings": [...]}` (one request per
  call, same as before, but wrapped). `pre_script`/`pre_lang` now present.
  Also produces `parse_bruno_collection_settings(bru_text: str) -> dict` for
  reading `collection.bru`/`folder.bru` — returns
  `{"vars": {...}, "auth": (auth_type, auth_config) | None}`.

- [ ] **Step 1: Write the rewritten import side**

Replace lines 1–139 of `cli/api_discovery/bruno_parser.py` (everything above
`def request_to_bru`) with:

```python
from __future__ import annotations
import json
import logging
import re

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc

logger = logging.getLogger("qaclan.bruno_parser")

_SECTION_RE = re.compile(r"^(\w[\w:.-]*)\s*\{")
_KV_RE = re.compile(r"^\s*([\w\-\.~]+)\s*:\s*(.*?)\s*$")

_BRUNO_OP_MAP = {
    "eq": "eq", "neq": "ne", "gt": "gt", "lt": "lt", "contains": "contains", "matches": "matches",
}
# Ops with no qaclan equivalent — approximated with an adjusted boundary value.
_BRUNO_APPROX_OPS = {"gte": ("gt", -1), "lte": ("lt", 1)}
_BRUNO_UNSUPPORTED_OPS = {"isJson", "isString", "isNumber", "isBoolean", "isArray"}


def _parse_bru_sections(text: str) -> dict:
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


def _parse_kv_block(lines: list[str]) -> list[dict]:
    """Parse a `key: value` block into [{key, value, enabled}], ~ prefix = disabled."""
    out = []
    for line in lines:
        m = _KV_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        enabled = not key.startswith("~")
        out.append({"key": key.lstrip("~"), "value": m.group(2), "enabled": enabled})
    return out


def _convert_auth(sections: dict, warnings: list[str], context: str) -> tuple[str, dict]:
    mode = None
    for line in sections.get("http", []) + sum((sections.get(v, []) for v in ("get", "post", "put", "patch", "delete")), []):
        m = _KV_RE.match(line)
        if m and m.group(1) == "auth":
            mode = m.group(2).strip()
            break
    if not mode or mode in ("none", "inherit"):
        return "inherit", {}

    attrs = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections.get(f"auth:{mode}", []))}
    if mode == "bearer":
        return "bearer", {"token": attrs.get("token", "")}
    if mode == "basic":
        return "basic", {"username": attrs.get("username", ""), "password": attrs.get("password", "")}
    if mode == "apikey":
        return "api_key", {"key": attrs.get("key", "X-API-Key"), "value": attrs.get("value", ""), "in": attrs.get("placement", "header")}
    if mode == "oauth2" and attrs.get("grant_type", "client_credentials") == "client_credentials":
        return "oauth2", {"token_url": attrs.get("accessTokenUrl", ""), "client_id": attrs.get("clientId", ""), "client_secret": attrs.get("clientSecret", "")}

    warnings.append(f"{context}: auth mode '{mode}' not supported, auth set to none")
    return "none", {}


def _convert_assertions(sections: dict, warnings: list[str], context: str) -> list[dict]:
    assertions = []
    for line in sections.get("assert", []):
        m = _KV_RE.match(line)
        if not m:
            continue
        raw_path, rest = m.group(1), m.group(2)
        parts = rest.split(None, 1)
        if len(parts) != 2:
            continue
        op, value = parts[0], parts[1]

        if raw_path in ("res.status",):
            a_type, key = "status", None
        elif raw_path.startswith("res.headers."):
            a_type, key = "header", raw_path[len("res.headers."):]
        elif raw_path in ("res.responseTime",):
            a_type, key = "response_time", None
        else:
            a_type, key = "json_path", None

        path = None
        if a_type == "json_path":
            rest_path = raw_path
            for prefix in ("res.body.", "res.body"):
                if rest_path.startswith(prefix):
                    rest_path = rest_path[len(prefix):]
                    break
            path = "$." + rest_path if rest_path else "$"

        if op in _BRUNO_OP_MAP:
            qc_op, adj_value = _BRUNO_OP_MAP[op], value
        elif op in _BRUNO_APPROX_OPS:
            qc_op, delta = _BRUNO_APPROX_OPS[op]
            try:
                adj_value = str(float(value) + delta) if "." in value else str(int(value) + delta)
            except ValueError:
                adj_value = value
            warnings.append(f"{context}: assert op '{op}' approximated as '{qc_op}' (adjusted value)")
        elif op in _BRUNO_UNSUPPORTED_OPS:
            warnings.append(f"{context}: assert op '{op}' not supported, skipped")
            continue
        else:
            qc_op, adj_value = "eq", value

        assertion = {"type": a_type, "op": qc_op, "value": adj_value}
        if key is not None:
            assertion["key"] = key
        if path is not None:
            assertion["path"] = path
        assertions.append(assertion)
    return assertions


def parse_bruno(bru_text: str) -> dict:
    """Parse a single .bru file. Returns {"requests": [...], "warnings": [...]}."""
    warnings: list[str] = []
    sections = _parse_bru_sections(bru_text)

    meta = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections.get("meta", []))}
    name = meta.get("name", "Imported Request")
    method = meta.get("method", "GET").upper()
    context = f"'{name}'"

    url = ""
    for line in sections.get("http", []):
        m = _KV_RE.match(line)
        if m and m.group(1) == "url":
            url = m.group(2)
            break
    for verb in ("get", "post", "put", "patch", "delete"):
        if verb in sections:
            for line in sections[verb]:
                m = _KV_RE.match(line)
                if m and m.group(1) == "url":
                    url, method = m.group(2), verb.upper()
                    break

    path_seed = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections.get("params:path", []))}
    url, path_params = convert_path_vars(url, path_seed)

    headers = _parse_kv_block(sections.get("headers", []))
    params = _parse_kv_block(sections.get("params:query", []))

    body_type, body = None, None
    if "body:json" in sections:
        body_type, body = "raw", "\n".join(sections["body:json"]).strip()
    elif "body:text" in sections or "body:xml" in sections or "body:sparql" in sections:
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
            try:
                gql_vars = json.loads("\n".join(sections["body:graphql:vars"]).strip() or "{}")
            except json.JSONDecodeError:
                gql_vars = {}
        body_type = "graphql"
        body = json.dumps({"query": "\n".join(sections["body:graphql"]).strip(), "variables": gql_vars})

    pre_script = None
    if "script:pre-request" in sections:
        pre_script, w = foreign_script_to_qc("\n".join(sections["script:pre-request"]).strip())
        warnings.extend(f"{context}: {x}" for x in w)

    post_script = None
    if "script:post-response" in sections:
        post_script, w = foreign_script_to_qc("\n".join(sections["script:post-response"]).strip())
        warnings.extend(f"{context}: {x}" for x in w)

    auth_type, auth_config = _convert_auth(sections, warnings, context)
    assertions = _convert_assertions(sections, warnings, context)

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
        "auth_config": auth_config,
        "assertions": assertions,
        "pre_script": pre_script,
        "pre_lang": "js",
        "post_script": post_script,
        "post_lang": "js",
    }
    logger.info("parse_bruno: extracted request '%s' %s %s, %d warnings", name, method, url, len(warnings))
    return {"requests": [result], "warnings": warnings}


def parse_bruno_collection_settings(bru_text: str) -> dict:
    """Parse a collection.bru / folder.bru file. Returns {"vars": {...}, "auth": (type, config) | None}."""
    warnings: list[str] = []
    sections = _parse_bru_sections(bru_text)
    var_kv = _parse_kv_block(sections.get("vars:pre-request", []))
    variables = {kv["key"]: kv["value"] for kv in var_kv if kv["enabled"]}
    auth_type, auth_config = _convert_auth(sections, warnings, "collection")
    auth = (auth_type, auth_config) if auth_type != "inherit" else None
    return {"vars": variables, "auth": auth}
```

- [ ] **Step 2: Verify with a manual fixture**

```bash
python -c "
from cli.api_discovery.bruno_parser import parse_bruno

bru = '''
meta {
  name: Get User
  type: http
  seq: 1
}

get {
  url: https://api.example.com/users/:id
  auth: bearer
}

params:path {
  id: 42
}

auth:bearer {
  token: {{authToken}}
}

script:post-response {
  bru.setVar(\"userId\", res.body.id);
}

assert {
  res.status: eq 200
  res.body.id: gte 1
}
'''
result = parse_bruno(bru)
import json
print(json.dumps(result, indent=2))
"
```

Expected: `url` = `https://api.example.com/users/{id}`, `path_params` seeded
with `id: 42`, `auth_type: bearer`, `post_script` containing `qc.set(`,
`assertions` with one `status/eq/200` entry and one `json_path` entry whose
`op` is `gt` and `value` is `0` (the `gte 1` approximation), plus a warning
about the `gte` approximation.

- [ ] **Step 3: Commit**

```bash
git add cli/api_discovery/bruno_parser.py
git commit -m "feat(api-discovery): full-fidelity Bruno import (path vars, auth, assertions, scripts)"
```

---

### Task 5: Wire folders, collection vars, auth, and warnings into `discovery_service.py`

**Files:**
- Modify: `web/api/services/discovery_service.py:74-113` (`_save_requests`), `:248-288` (`import_postman`, `import_bruno`)

**Interfaces:**
- Consumes: `parse_postman` / `parse_bruno` new dict return shape (Task 3, 4), `FolderRepo.create`/`get_or_create_root` (existing, `web/api/repositories/folder_repo.py:26-60`), `CollectionVarsRepo.upsert` (existing, `web/api/repositories/collection_vars_repo.py:19`).
- Produces: `import_postman`/`import_bruno` now return `{"imported": N, "warnings": [...]}` instead of `{"imported": N}`.

- [ ] **Step 1: Add folder resolution + update `_save_requests`**

In `web/api/services/discovery_service.py`, add near the top (after the
existing `_col_repo`/`_req_repo` module-level instances):

```python
from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.collection_vars_repo import CollectionVarsRepo

_folder_repo = FolderRepo()
_vars_repo = CollectionVarsRepo()


def _resolve_folders(project_id: str, collection_id: str, requests: list[dict]) -> dict[tuple, str]:
    """Ensure api_folders rows exist for every folder_path seen; return
    {tuple(path): folder_id}, top-down, memoized so repeated paths reuse
    the same folder."""
    cache: dict[tuple, str] = {}
    for req in requests:
        path = tuple(req.get("folder_path") or ())
        if not path or path in cache:
            continue
        parent_id = None
        built: tuple = ()
        for name in path:
            built = built + (name,)
            if built in cache:
                parent_id = cache[built]
                continue
            if parent_id is None:
                folder = _folder_repo.get_or_create_root(project_id, collection_id, name)
            else:
                folder = _folder_repo.create(project_id, collection_id, name, parent_folder_id=parent_id)
            cache[built] = folder["id"]
            parent_id = folder["id"]
    return cache
```

Replace `_save_requests` (lines 74–112) with:

```python
def _save_requests(project_id: str, requests: list[dict], collection_id: str | None = None) -> int:
    """Save a list of parsed request dicts to the DB. Returns count saved."""
    from web.api.services.doc_service import sync_doc_entry

    folder_cache = _resolve_folders(project_id, collection_id, requests) if collection_id else {}

    saved = 0
    for req in requests:
        data = dict(req)
        data.pop("collection_name", None)  # not a DB column
        folder_path = tuple(data.pop("folder_path", None) or ())
        if collection_id:
            data["collection_id"] = collection_id
            if folder_path:
                data["folder_id"] = folder_cache.get(folder_path)
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
        enqueue("api_request", saved_req["id"], "upsert")

        try:
            sync_doc_entry(project_id, {**data, 'id': saved_req['id']})
        except Exception as e:
            logger.warning("sync_doc_entry failed for %s: %s", data.get('url'), e)

        saved += 1
    return saved


def _apply_collection_extras(project_id: str, collection_id: str, collection_vars: dict[str, str] | None,
                              collection_auth: tuple[str, dict] | None) -> None:
    for key, value in (collection_vars or {}).items():
        _vars_repo.upsert(collection_id, key, str(value))
    if collection_auth:
        auth_type, auth_config = collection_auth
        _col_repo.update(collection_id, {"auth_type": auth_type, "auth_config": json.dumps(auth_config)})
```

- [ ] **Step 2: Verify `CollectionRepo.update` supports `auth_type`/`auth_config`**

```bash
grep -n "def update" -A 15 web/api/repositories/collection_repo.py
```

If `auth_type`/`auth_config` aren't in that method's field allowlist, add
them there before proceeding (read the file first — this plan assumes the
allowlist pattern matches `RequestRepo.update`'s `fields = [...]` style seen
in Task-adjacent code; extend it the same way if needed).

- [ ] **Step 3: Update `import_postman` and `import_bruno`**

Replace `import_postman` (old lines 248–270) with:

```python
    def import_postman(self, project_id: str, collection_json: dict, collection_name: str | None = None) -> dict:
        from cli.api_discovery.postman_parser import parse_postman
        parsed = parse_postman(collection_json)
        requests = parsed["requests"]
        name = collection_name or collection_json.get("info", {}).get("name", "Imported Collection")

        col = _col_repo.create(project_id, name)
        total = _save_requests(project_id, requests, collection_id=col["id"])
        _apply_collection_extras(project_id, col["id"], parsed.get("collection_vars"), parsed.get("collection_auth"))

        logger.info("import_postman: saved %d requests to collection '%s', %d warnings",
                    total, name, len(parsed["warnings"]))
        return {"imported": total, "collection_id": col["id"], "warnings": parsed["warnings"]}
```

Replace `import_bruno` (old lines 272–288) with:

```python
    def import_bruno(self, project_id: str, bru_files: list[dict], collection_name: str | None = None) -> dict:
        """bru_files: list of {name: str, content: str}. `name` may include
        `/`-separated folder path components (e.g. 'Auth/Login.bru')."""
        from cli.api_discovery.bruno_parser import parse_bruno, parse_bruno_collection_settings
        col = _col_repo.create(project_id, collection_name or "Imported Collection")
        col_id = col["id"]

        all_warnings: list[str] = []
        total = 0
        for f in bru_files:
            rel_name = f.get("name", "Request.bru")
            base = rel_name.rsplit("/", 1)[-1]
            if base in ("collection.bru", "folder.bru"):
                settings = parse_bruno_collection_settings(f.get("content", ""))
                _apply_collection_extras(project_id, col_id, settings.get("vars"), settings.get("auth"))
                continue

            parsed = parse_bruno(f.get("content", ""))
            all_warnings.extend(parsed["warnings"])
            folder_path = rel_name.split("/")[:-1]
            for req in parsed["requests"]:
                if req.get("name") in ("Imported Request", "", None):
                    req["name"] = base.replace(".bru", "")
                req["folder_path"] = folder_path
            total += _save_requests(project_id, parsed["requests"], collection_id=col_id)

        logger.info("import_bruno: saved %d requests from %d files, %d warnings",
                    total, len(bru_files), len(all_warnings))
        return {"imported": total, "collection_id": col_id, "warnings": all_warnings}
```

- [ ] **Step 4: Update callers of `import_postman`/`import_bruno` for the new return shape**

```bash
grep -rn "import_postman\|import_bruno" web/api/routes/
```

Read each route hit and confirm it forwards the full dict (including the
new `warnings` key) in its JSON response rather than destructuring only
`imported`/`collection_id` — adjust any route that does the latter so
`warnings` reaches the client. Show the actual route code you find and the
exact diff in your implementation — do not skip this step even if it looks
like a one-line change.

- [ ] **Step 5: Verify with a manual end-to-end run**

```bash
python -c "
import json
from cli.db import init_db
from web.api.services.discovery_service import DiscoveryService
from cli.config import get_active_project

init_db()
project_id = get_active_project()
assert project_id, 'set an active project first: qaclan project use <name>'

data = json.load(open('/tmp/qaclan_import_test/postman_fixture.json'))
result = DiscoveryService().import_postman(project_id, data)
print(json.dumps(result, indent=2))

from web.api.repositories.folder_repo import FolderRepo
from web.api.repositories.request_repo import RequestRepo
folders = FolderRepo().list_for_collection(result['collection_id'])
reqs = RequestRepo().list(project_id, result['collection_id'])
print('folders:', [(f['name'], f['parent_folder_id']) for f in folders])
print('requests:', [(r['name'], r['folder_id'], r['url'], r['auth_type']) for r in reqs])
"
```

Expected: one folder named "Auth" with `parent_folder_id: None`, one
request with `folder_id` matching that folder's id, `url` containing
`{id}`, `auth_type: "bearer"`.

- [ ] **Step 6: Commit**

```bash
git add web/api/services/discovery_service.py
git commit -m "feat(discovery): reconstruct folders, collection vars, auth on Postman/Bruno import"
```

---

### Task 6: Import-preview UI surfaces warnings

**Files:**
- Modify: whichever file renders the import-preview modal for Postman/Bruno
  imports (per `docs/superpowers/plans/2026-06-25-import-preview-flow.md`,
  this is `web/static/api/components/request-review-modal.js` or the
  discovery view that calls `import_postman`/`import_bruno` — confirm with
  `grep -rn "import_postman\|/discover/import" web/static/api/` before
  editing, file may differ from this guess).

**Interfaces:**
- Consumes: `warnings: string[]` field now present on the `import_postman`/
  `import_bruno` JSON response (Task 5).

- [ ] **Step 1: Locate the exact frontend call site**

```bash
grep -rn "postman\|bruno" web/static/api/ --include=*.js -il
```

- [ ] **Step 2: Read the matched file(s) in full**, find where the import
  response is handled (likely a `.then(res => ...)` or `await window.api(...)`
  call), and add a warnings banner: if `res.warnings?.length`, render a
  dismissible list of the warning strings above the imported-requests list
  (reuse whatever toast/banner pattern the file already uses elsewhere —
  do not invent new CSS; if none exists, a plain `<ul>` inside a `div`
  styled with existing `.text-warning`/similar utility class from
  `web/static/style.css` is sufficient). Write the actual diff here once
  the file is read — this step cannot be fully specified without reading
  the real file first, unlike Tasks 1–5.

- [ ] **Step 3: Verify in browser**

Start the dev server (`python qaclan.py serve --port 7823`), import the
Postman fixture from Task 3 via the web UI, confirm the warnings banner
renders (this fixture has no warnings by default — temporarily add an
unsupported auth type or a `pm.sendRequest` call to the fixture to force at
least one warning, confirm it displays, then revert the fixture).

- [ ] **Step 4: Commit**

```bash
git add web/static/api/
git commit -m "feat(api-ui): surface Postman/Bruno import warnings in preview modal"
```

---

## Self-Review Notes

- **Spec coverage**: §A (Task 2), §B (Task 5), §C (Task 5), §D (Task 3/4
  auth conversion + Task 5 `_apply_collection_extras`), §E (Task 3/4 body
  modes), §F (Task 1 rewrite table + Task 3/4 wiring), §G (Task 4 assertion
  conversion), §H (Task 5/6 warnings threading) — all covered.
- **Known gap carried forward, not silently dropped**: Task 6's exact diff
  is left for implementation time because the frontend file wasn't
  confirmed during planning — this is flagged explicitly, not glossed over,
  and Step 1 of that task is dedicated to resolving it before any code is
  written.
- **Type consistency**: `parse_postman`/`parse_bruno` both return a dict
  with a `"requests"` key (not a bare list) consistently across Tasks 3–5;
  `_save_requests` signature (`project_id, requests, collection_id`) is
  unchanged from today, so no other caller of `_save_requests` breaks.
