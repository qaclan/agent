from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger("qaclan.bruno_parser")

# Section header regex: matches "meta {", "headers {", "body:json {", etc.
_SECTION_RE = re.compile(r"^(\w[\w:.-]*)\s*\{")
_KV_RE = re.compile(r"^\s*([\w\-\.]+)\s*:\s*(.*?)\s*$")


def _parse_bru_sections(text: str) -> dict:
    """Parse .bru text into a dict of section_name → list of lines."""
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


def parse_bruno(bru_text: str) -> list[dict]:
    """Parse a single .bru file → list with one request dict."""
    sections = _parse_bru_sections(bru_text)

    # meta section: name, method, url, seq
    meta = {}
    for line in sections.get("meta", []):
        m = _KV_RE.match(line)
        if m:
            meta[m.group(1)] = m.group(2)

    name = meta.get("name", "Imported Request")
    method = meta.get("method", "GET").upper()

    # http section has the URL
    url = ""
    for line in sections.get("http", []):
        m = _KV_RE.match(line)
        if m and m.group(1) == "url":
            url = m.group(2)
            break
    # Also check get/post/put/delete/patch direct sections
    for verb in ("get", "post", "put", "patch", "delete"):
        if verb in sections:
            for line in sections[verb]:
                m = _KV_RE.match(line)
                if m and m.group(1) == "url":
                    url = m.group(2)
                    method = verb.upper()
                    break

    # headers section
    headers = []
    for line in sections.get("headers", []):
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            if not key.startswith("~"):  # ~ prefix means disabled in Bruno
                headers.append({"key": key, "value": m.group(2), "enabled": True})
            else:
                headers.append({"key": key[1:], "value": m.group(2), "enabled": False})

    # params:query section
    params = []
    for line in sections.get("params:query", []):
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            enabled = not key.startswith("~")
            params.append({"key": key.lstrip("~"), "value": m.group(2), "enabled": enabled})

    # body:json section
    body_type = None
    body = None
    if "body:json" in sections:
        body_type = "raw"
        body = "\n".join(sections["body:json"]).strip()
    elif "body:form-urlencoded" in sections:
        body_type = "form"
        items = []
        for line in sections["body:form-urlencoded"]:
            m = _KV_RE.match(line)
            if m:
                items.append({"key": m.group(1), "value": m.group(2), "enabled": True})
        body = json.dumps(items)

    # script:post-response section
    post_script = None
    if "script:post-response" in sections:
        post_script = "\n".join(sections["script:post-response"]).strip()

    # assertions section (Bruno format: assert { path op value })
    assertions = []
    for line in sections.get("assert", []):
        parts = line.strip().split(None, 2)
        if len(parts) >= 3:
            path, op, value = parts[0], parts[1], parts[2]
            # Map Bruno operators to QAClan operators
            op_map = {"==": "eq", "!=": "ne", "<": "lt", ">": "gt", "contains": "contains"}
            assertions.append({
                "type": "json_path",
                "path": path,
                "op": op_map.get(op, "eq"),
                "value": value,
            })

    result = {
        "name": name,
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "body_type": body_type,
        "body": body,
        "auth_type": "none",
        "auth_config": "{}",
        "assertions": json.dumps(assertions),
        "post_script": post_script,
        "post_lang": "js",
    }

    logger.info("parse_bruno: extracted request '%s' %s %s", name, method, url)
    return [result]


def request_to_bru(req: dict) -> str:
    """Convert a QAClan api_request dict to Bruno .bru format string."""
    import json as _json
    lines = [
        "meta {",
        f"  name: {req.get('name', 'Request')}",
        f"  method: {req.get('method', 'GET')}",
        "  seq: 1",
        "}",
        "",
        f"{req.get('method', 'GET').lower()} {{",
        f"  url: {req.get('url', '')}",
        "}",
        "",
    ]
    headers = req.get("headers", [])
    if isinstance(headers, str):
        headers = _json.loads(headers)
    if headers:
        lines.append("headers {")
        for h in headers:
            prefix = "" if h.get("enabled", True) else "~"
            lines.append(f"  {prefix}{h.get('key', '')}: {h.get('value', '')}")
        lines.append("}")
        lines.append("")
    body = req.get("body")
    body_type = req.get("body_type")
    if body and body_type == "raw":
        lines.append("body:json {")
        for line in body.splitlines():
            lines.append(f"  {line}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)
