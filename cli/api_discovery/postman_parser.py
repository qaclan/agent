from __future__ import annotations
import json
import logging

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc

logger = logging.getLogger("qaclan.postman_parser")


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
    """Recursively process Postman collection items (folders and requests)."""
    if "item" in item:
        folder_name = item.get("name")
        sub_path = folder_path + [folder_name] if folder_name else folder_path
        for sub in item["item"]:
            _process_item(sub, sub_path, results, warnings)
        return

    req = item.get("request", {})
    if not req:
        return

    name = item.get("name", "Unnamed Request")
    context = f"'{name}'"

    # URL
    url_obj = req.get("url", {})
    var_seed: dict[str, str] = {}
    if isinstance(url_obj, str):
        raw = url_obj
        query_params: list[dict] = []
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

    url, path_params = convert_path_vars(raw, var_seed)

    method = req.get("method", "GET").upper()

    # Headers
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
        v.get("key"): {"value": str(v.get("value", "")), "is_secret": v.get("type") == "secret"}
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
