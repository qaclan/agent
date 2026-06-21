from __future__ import annotations
import base64
import json
import logging
import re

logger = logging.getLogger("qaclan.har_parser")


def _infer_schema(value, _depth=0):
    """Recursively replace JSON values with their type names. Max depth 4."""
    if _depth > 4:
        return "..."
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return [_infer_schema(value[0], _depth + 1)] if value else ["?"]
    if isinstance(value, dict):
        return {k: _infer_schema(v, _depth + 1) for k, v in value.items()}
    return "unknown"

_STATIC_EXT_RE = re.compile(r"\.(css|js|png|jpg|jpeg|gif|ico|woff|woff2|ttf|svg|webp|map)$", re.IGNORECASE)
_STATIC_PATH_RE = re.compile(r"/static/|/assets/|/_next/|/favicon")
_BEACON_PATH_RE = re.compile(r"/cdn-cgi/|/__utm|/beacon/?$|/collect/?$|/pixel/?$", re.IGNORECASE)
_SENSITIVE_RE = re.compile(r"(password|secret|token|authorization|api.?key|auth)", re.IGNORECASE)
_STATIC_CONTENT_TYPES = {
    "text/css", "text/javascript", "application/javascript",
    "image/png", "image/jpeg", "image/gif", "image/svg+xml",
    "image/x-icon", "font/woff", "font/woff2",
}


_API_RESOURCE_TYPES = {"xhr", "fetch"}
_ALL_RESOURCE_TYPES = {
    "xhr", "fetch", "document", "stylesheet", "image", "font",
    "script", "manifest", "media", "websocket", "other",
}


def _is_static(entry: dict) -> bool:
    url = entry.get("request", {}).get("url", "")
    content_type = ""
    for h in entry.get("response", {}).get("headers", []):
        if h.get("name", "").lower() == "content-type":
            content_type = h.get("value", "").split(";")[0].strip().lower()
            break
    if _STATIC_EXT_RE.search(url):
        return True
    if _STATIC_PATH_RE.search(url):
        return True
    if _BEACON_PATH_RE.search(url):
        return True
    if content_type in _STATIC_CONTENT_TYPES:
        return True
    return False


def _should_skip(entry: dict) -> bool:
    """Return True if this HAR entry should be excluded from API results.

    When _resourceType is present (Chrome/Playwright HAR extension), it is
    authoritative — keep only xhr and fetch. Fall back to heuristics for
    third-party HAR files that omit the field.
    """
    resource_type = entry.get("_resourceType", "").lower()
    if resource_type in _ALL_RESOURCE_TYPES:
        return resource_type not in _API_RESOURCE_TYPES
    # No _resourceType — check response content type before static heuristics.
    # text/html means a page navigation (not an API); skip it.
    for h in entry.get("response", {}).get("headers", []):
        if h.get("name", "").lower() == "content-type":
            ct = h.get("value", "").split(";")[0].strip().lower()
            if ct == "text/html":
                return True
            break
    return _is_static(entry)


def _redact_sensitive(key: str, value: str) -> str:
    if _SENSITIVE_RE.search(key):
        safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", key).upper()
        return "{{" + safe_key + "}}"
    return value


def parse_har(har_json: dict) -> list[dict]:
    """Parse HAR JSON → list of api_request dicts."""
    entries = har_json.get("log", {}).get("entries", [])
    results = []

    for entry in entries:
        if _should_skip(entry):
            continue

        req = entry.get("request", {})
        method = req.get("method", "GET").upper()
        url = req.get("url", "")
        if not url:
            continue

        # Strip query string from URL — put params in params list
        qs_idx = url.find("?")
        base_url = url[:qs_idx] if qs_idx >= 0 else url

        # Params from queryString array
        params = []
        for qs in req.get("queryString", []):
            k = qs.get("name", "")
            v = _redact_sensitive(k, qs.get("value", ""))
            params.append({"key": k, "value": v, "enabled": True})

        # Headers — skip pseudo-headers and common browser headers
        skip_headers = {"accept-encoding", "connection", "host", ":method", ":path", ":scheme", ":authority"}
        headers = []
        for h in req.get("headers", []):
            name = h.get("name", "")
            if name.lower() in skip_headers or name.startswith(":"):
                continue
            v = _redact_sensitive(name, h.get("value", ""))
            headers.append({"key": name, "value": v, "enabled": True})

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
            elif "form" in mime:
                body_type = "form"
                params_list = []
                for p in post_data.get("params", []):
                    k = p.get("name", "")
                    v = _redact_sensitive(k, p.get("value", ""))
                    params_list.append({"key": k, "value": v, "enabled": True})
                body = json.dumps(params_list)
            else:
                body_type = "raw"
                body = text

        # Generate a name from method + path
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        path = parsed.path or "/"
        name = f"{method} {path}"

        # Infer request schema from JSON body
        request_schema = None
        if post_data and body_type == "raw" and body:
            try:
                request_schema = _infer_schema(json.loads(body))
            except (ValueError, TypeError):
                pass

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

    logger.info("parse_har: extracted %d requests from %d entries", len(results), len(entries))
    return results
