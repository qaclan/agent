from __future__ import annotations
import json
import logging

logger = logging.getLogger("qaclan.postman_parser")


def _process_item(item: dict, collection_name: str, results: list):
    """Recursively process Postman collection items (folders and requests)."""
    # If item has sub-items, it's a folder
    if "item" in item:
        folder_name = item.get("name", collection_name)
        for sub in item["item"]:
            _process_item(sub, folder_name, results)
        return

    # It's a request
    req = item.get("request", {})
    if not req:
        return

    name = item.get("name", "Unnamed Request")

    # URL
    url_obj = req.get("url", {})
    if isinstance(url_obj, str):
        url = url_obj
        params = []
    else:
        raw = url_obj.get("raw", "")
        # Rebuild from parts if raw is empty
        if not raw:
            host = ".".join(url_obj.get("host", []))
            path = "/".join(url_obj.get("path", []))
            raw = f"https://{host}/{path}"
        url = raw.split("?")[0]
        params = []
        for q in url_obj.get("query", []):
            if not q.get("disabled", False):
                params.append({
                    "key": q.get("key", ""),
                    "value": q.get("value", ""),
                    "enabled": True,
                })

    method = req.get("method", "GET").upper()

    # Headers
    headers = []
    for h in req.get("header", []):
        if not h.get("disabled", False):
            headers.append({
                "key": h.get("key", ""),
                "value": h.get("value", ""),
                "enabled": True,
            })

    # Body
    body_type = None
    body = None
    body_obj = req.get("body", {})
    if body_obj:
        mode = body_obj.get("mode", "")
        if mode == "raw":
            body_type = "raw"
            body = body_obj.get("raw", "")
        elif mode == "urlencoded":
            body_type = "form"
            items = []
            for p in body_obj.get("urlencoded", []):
                if not p.get("disabled", False):
                    items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True})
            body = json.dumps(items)
        elif mode == "formdata":
            body_type = "multipart"
            items = []
            for p in body_obj.get("formdata", []):
                if not p.get("disabled", False):
                    items.append({"key": p.get("key", ""), "value": p.get("value", ""), "enabled": True})
            body = json.dumps(items)
        elif mode == "graphql":
            body_type = "graphql"
            gql = body_obj.get("graphql", {})
            body = json.dumps({"query": gql.get("query", ""), "variables": gql.get("variables", {})})

    # Post-script from Postman test scripts
    post_script = None
    for event in item.get("event", []):
        if event.get("listen") == "test":
            script_lines = event.get("script", {}).get("exec", [])
            post_script = "\n".join(script_lines)
            break

    results.append({
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": "none",
        "auth_config": "{}",
        "assertions": "[]",
        "post_script": post_script,
        "post_lang": "js",
        "collection_name": collection_name,
    })


def parse_postman(collection: dict) -> list[dict]:
    """Parse Postman Collection v2.1 JSON → list of request dicts."""
    # Support both v2 and v2.1 wrappers
    info = collection.get("info", {})
    collection_name = info.get("name", "Imported Collection")

    items = collection.get("item", [])
    results = []
    for item in items:
        _process_item(item, collection_name, results)

    logger.info("parse_postman: extracted %d requests", len(results))
    return results
