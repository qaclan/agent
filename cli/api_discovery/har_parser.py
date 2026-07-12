from __future__ import annotations
import base64
import json
import logging
import re
from urllib.parse import parse_qsl

from cli.schema_infer import infer_schema as _infer_schema

logger = logging.getLogger("qaclan.har_parser")

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


def parse_multipart_text(mime: str, text: str) -> list[dict]:
    """Manually split a raw multipart/form-data body into fields.

    Needed because Playwright's HAR recorder always leaves postData.params
    empty for multipart requests (only urlencoded bodies get params filled
    in) — the raw text is the only place the field data survives. Also
    reused by curl_parser for --data-raw multipart bodies (no -F flags).
    """
    m = re.search(r'boundary=("?)([^;"]+)\1', mime)
    if not m or not text:
        return []
    delimiter = "--" + m.group(2)
    fields = []
    for chunk in text.split(delimiter):
        # Strip exactly one leading newline (right after the boundary marker
        # line) and one trailing newline (mandatory framing before the next
        # boundary, present even when the part body is empty — e.g. a file
        # field with no captured bytes). A blanket strip("\r\n") would eat the
        # header/body blank-line separator too and drop empty-bodied parts.
        if chunk.startswith("\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith("\n"):
            chunk = chunk[1:]
        if chunk.endswith("\r\n"):
            chunk = chunk[:-2]
        elif chunk.endswith("\n"):
            chunk = chunk[:-1]
        if not chunk or chunk.startswith("--"):
            continue
        if "\r\n\r\n" in chunk:
            header_blob, value = chunk.split("\r\n\r\n", 1)
        elif "\n\n" in chunk:
            header_blob, value = chunk.split("\n\n", 1)
        else:
            continue
        name_m = re.search(r'name="([^"]*)"', header_blob)
        if not name_m:
            continue
        name = name_m.group(1)
        value = value.rstrip("\r\n")
        filename_m = re.search(r'filename="([^"]*)"', header_blob)
        if filename_m:
            # File-part content is stored base64-encoded so it round-trips
            # identically whether it came from a capture (this path) or a
            # real file attached later in the request editor — the runner
            # decodes base64 for any field marked is_file.
            encoded = base64.b64encode(value.encode("utf-8", errors="surrogateescape")).decode("ascii")
            field = {"key": name, "value": encoded, "enabled": True, "filename": filename_m.group(1), "is_file": True}
            ct_m = re.search(r'Content-Type:\s*([^\r\n]+)', header_blob, re.IGNORECASE)
            if ct_m:
                field["content_type"] = ct_m.group(1).strip()
        else:
            field = {"key": name, "value": _redact_sensitive(name, value), "enabled": True}
        fields.append(field)
    return fields


def merge_multipart_postdata(har_json: dict, sidecar_entries: list[dict]) -> None:
    """Patch HAR entries in place with postData captured out-of-band via CDP
    Network.getRequestPostData.

    Playwright's HAR export never populates postData for multipart/form-data
    request bodies — Chrome's Network.requestWillBeSent omits it for
    multipart requests, and Playwright's HAR writer doesn't fall back to the
    CDP Network.getRequestPostData command that can actually fetch it. Our
    recording harness captures that separately into `sidecar_entries`; this
    matches each one back to its HAR entry by (method, url), in the order
    both occurred, since HAR carries no CDP requestId to correlate on.
    """
    if not sidecar_entries:
        return
    queues: dict = {}
    for item in sidecar_entries:
        if item.get("postData") is None:
            continue
        key = (item.get("method"), item.get("url"))
        queues.setdefault(key, []).append(item)

    for entry in har_json.get("log", {}).get("entries", []):
        req = entry.get("request", {})
        existing = req.get("postData") or {}
        if existing.get("text"):
            continue
        queue = queues.get((req.get("method"), req.get("url")))
        if not queue:
            continue
        item = queue.pop(0)
        req["postData"] = {"mimeType": item.get("mimeType", ""), "text": item.get("postData", ""), "params": []}


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
        skip_headers = {
            "accept-encoding", "connection", "host", ":method", ":path", ":scheme", ":authority",
            "content-length", "transfer-encoding",
        }
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
                        field = {"key": name, "value": _redact_sensitive(name, p.get("value", "")), "enabled": True}
                    params_list.append(field)
                if not params_list:
                    params_list = parse_multipart_text(mime, text)
                body = json.dumps(params_list)
            elif "form" in mime:
                body_type = "form"
                params_list = []
                for p in post_data.get("params", []):
                    k = p.get("name", "")
                    v = _redact_sensitive(k, p.get("value", ""))
                    params_list.append({"key": k, "value": v, "enabled": True})
                if not params_list and text:
                    # Playwright's HAR recorder leaves postData.params empty for
                    # urlencoded bodies too (not just multipart) — fall back to
                    # decoding the raw text, same as the multipart branch above.
                    params_list = [
                        {"key": k, "value": _redact_sensitive(k, v), "enabled": True}
                        for k, v in parse_qsl(text, keep_blank_values=True)
                    ]
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

    logger.info("parse_har: extracted %d requests from %d entries", len(results), len(entries))
    return results
