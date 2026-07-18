from __future__ import annotations
import json
import logging
import re

from cli.api_discovery.path_vars import convert_path_vars
from cli.api_discovery.script_rewrite import foreign_script_to_qc

logger = logging.getLogger("qaclan.bruno_parser")

# Section header regex: matches "meta {", "headers {", "body:json {", etc.
_SECTION_RE = re.compile(r"^(\w[\w:.-]*)\s*\{")
_KV_RE = re.compile(r"^\s*([\w\-\.~]+)\s*:\s*(.*?)\s*$")

_BRUNO_OP_MAP = {
    "eq": "eq", "neq": "ne", "gt": "gt", "lt": "lt", "contains": "contains", "matches": "matches",
}
# Ops with no qaclan equivalent — approximated with an adjusted boundary value.
_BRUNO_APPROX_OPS = {"gte": ("gt", -1), "lte": ("lt", 1)}
_BRUNO_UNSUPPORTED_OPS = {"isJson", "isString", "isNumber", "isBoolean", "isArray"}


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


def _find_verb_sections(sections: dict) -> list[str]:
    lines: list[str] = list(sections.get("http", []))
    for verb in ("get", "post", "put", "patch", "delete"):
        lines.extend(sections.get(verb, []))
    return lines


def _convert_auth(sections: dict, warnings: list[str], context: str) -> tuple[str, dict]:
    mode = None
    for line in _find_verb_sections(sections):
        m = _KV_RE.match(line)
        if m and m.group(1) == "auth":
            mode = m.group(2).strip()
            break
    if mode is None:
        # collection.bru/folder.bru use a standalone `auth { mode: ... }`
        # block instead of an inline `auth:` key in a verb block.
        for line in sections.get("auth", []):
            m = _KV_RE.match(line)
            if m and m.group(1) == "mode":
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

        if raw_path == "res.status":
            a_type, key = "status", None
        elif raw_path.startswith("res.headers."):
            a_type, key = "header", raw_path[len("res.headers."):]
        elif raw_path == "res.responseTime":
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

    path_seed = {kv["key"]: kv["value"] for kv in _parse_kv_block(sections.get("params:path", []))}
    url, path_params = convert_path_vars(url, path_seed)

    headers = _parse_kv_block(sections.get("headers", []))
    params = _parse_kv_block(sections.get("params:query", []))

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
            try:
                gql_vars = json.loads("\n".join(sections["body:graphql:vars"]).strip() or "{}")
            except json.JSONDecodeError:
                gql_vars = {}
        body_type = "graphql"
        body = json.dumps({"query": "\n".join(sections["body:graphql"]).strip(), "variables": gql_vars})

    # script:pre-request / script:post-response sections
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
    """Parse a collection.bru / folder.bru file.

    Returns {"vars": {key: value}, "auth": (auth_type, auth_config) | None}.
    """
    warnings: list[str] = []
    sections = _parse_bru_sections(bru_text)
    var_kv = _parse_kv_block(sections.get("vars:pre-request", []))
    variables = {kv["key"]: kv["value"] for kv in var_kv if kv["enabled"]}
    auth_type, auth_config = _convert_auth(sections, warnings, "collection")
    auth = (auth_type, auth_config) if auth_type != "inherit" else None
    return {"vars": variables, "auth": auth}


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
