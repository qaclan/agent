from __future__ import annotations
import json

from cli.api_discovery.path_vars import revert_path_vars
from cli.api_discovery.script_rewrite import qc_script_to_foreign
from cli.crypto import decrypt

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


def _as_dict(value) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value) if value else {}
        except (ValueError, TypeError):
            return {}
    return value or {}


def _as_list(value) -> list:
    if isinstance(value, str):
        try:
            return json.loads(value) if value else []
        except (ValueError, TypeError):
            return []
    return value or []


def _auth_block(auth_type: str | None, auth_config: dict | str) -> dict | None:
    if auth_type in (None, "inherit"):
        return None
    if auth_type == "none":
        return {"type": "noauth"}
    builder = _AUTH_REVERSE.get(auth_type)
    return builder(_as_dict(auth_config)) if builder else {"type": "noauth"}


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


def _assertions_to_test_script(assertions: list[dict]) -> list[str]:
    lines = []
    for a in assertions:
        a_type, op, value = a.get("type"), a.get("op"), a.get("value")
        if a_type == "status":
            cmp = {"eq": "===", "ne": "!==", "lt": "<", "gt": ">"}.get(op, "===")
            lines.append(f'pm.test("status {op} {value}", () => {{ if (!(pm.response.code {cmp} {value})) throw new Error("status assertion failed"); }});')
        elif a_type == "header":
            key = a.get("key", "")
            if op == "contains":
                lines.append(f'pm.test("header {key} contains", () => {{ const v = pm.response.headers.get({json.dumps(key)}); if (!(String(v).includes({json.dumps(value)}))) throw new Error("header assertion failed"); }});')
            elif op == "exists":
                lines.append(f'pm.test("header {key} exists", () => {{ if (pm.response.headers.get({json.dumps(key)}) == null) throw new Error("header assertion failed"); }});')
            elif op == "not_exists":
                lines.append(f'pm.test("header {key} not exists", () => {{ if (pm.response.headers.get({json.dumps(key)}) != null) throw new Error("header assertion failed"); }});')
            elif op == "matches":
                lines.append(f'pm.test("header {key} matches", () => {{ const v = pm.response.headers.get({json.dumps(key)}); if (!(new RegExp({json.dumps(value)}).test(v))) throw new Error("header assertion failed"); }});')
            else:
                cmp = "===" if op == "eq" else "!==" if op == "ne" else "==="
                lines.append(f'pm.test("header {key} {op}", () => {{ const v = pm.response.headers.get({json.dumps(key)}); if (!(v {cmp} {json.dumps(value)})) throw new Error("header assertion failed"); }});')
        elif a_type == "json_path":
            path = a.get("path", "$")
            js_path = path.replace("$.", "").replace("$", "")
            accessor = f"pm.response.json(){'.' + js_path if js_path else ''}"
            if op == "contains":
                lines.append(f'pm.test("{path} contains", () => {{ if (!(String({accessor}).includes({json.dumps(value)}))) throw new Error("assertion failed"); }});')
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
    path_param_list = req.get("path_params") or []

    item_request: dict = {
        "method": req.get("method", "GET"),
        "header": [
            {"key": h.get("key", ""), "value": h.get("value", ""), "disabled": not h.get("enabled", True)}
            for h in _as_list(req.get("headers"))
        ],
        "url": {
            "raw": url,
            "query": [
                {"key": p.get("key", ""), "value": p.get("value", ""), "disabled": not p.get("enabled", True)}
                for p in _as_list(req.get("params"))
            ],
            "variable": [
                {"key": p.get("key", ""), "value": p.get("value", "")} for p in path_param_list if p.get("key")
            ],
        },
    }
    body = _body_block(req.get("body_type"), req.get("body"))
    if body:
        item_request["body"] = body
    auth = _auth_block(req.get("auth_type", "inherit"), req.get("auth_config") or {})
    if auth:
        item_request["auth"] = auth

    events = []
    if req.get("pre_lang", "js") == "js" and req.get("pre_script"):
        pre = qc_script_to_foreign(req["pre_script"], "postman")
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": pre.splitlines()}})

    test_lines = []
    if req.get("assertions"):
        test_lines.extend(_assertions_to_test_script(_as_list(req["assertions"])))
    if req.get("post_lang", "js") == "js" and req.get("post_script"):
        post = qc_script_to_foreign(req["post_script"], "postman")
        test_lines.extend(post.splitlines())
    if test_lines:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": test_lines}})

    item: dict = {"name": req.get("name", "Request"), "request": item_request}
    if events:
        item["event"] = events
    return item


def _build_folder_tree(folders: list[dict], requests: list[dict]) -> list[dict]:
    by_parent: dict = {}
    for f in folders:
        by_parent.setdefault(f.get("parent_folder_id"), []).append(f)
    reqs_by_folder: dict = {}
    for r in requests:
        reqs_by_folder.setdefault(r.get("folder_id"), []).append(r)

    def _build(parent_id) -> list[dict]:
        items = [_request_item(r) for r in reqs_by_folder.get(parent_id, [])]
        for f in by_parent.get(parent_id, []):
            items.append({"name": f.get("name", "Folder"), "item": _build(f["id"])})
        return items

    return _build(None)


def to_postman_collection(collection: dict, requests: list[dict], folders: list[dict], collection_vars: list[dict]) -> dict:
    """Build a spec-compliant Postman Collection v2.1.0 JSON dict from a
    qaclan collection's requests/folders/collection_vars."""
    result: dict = {
        "info": {
            "name": collection.get("name", "Exported Collection"),
            "schema": "https://schema.postman.com/json/collection/v2.1.0/collection.json",
        },
        "item": _build_folder_tree(folders, requests),
    }
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
    auth = _auth_block(collection.get("auth_type", "none"), collection.get("auth_config") or {})
    if auth and auth.get("type") != "noauth":
        result["auth"] = auth
    return result
