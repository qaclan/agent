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


def _body_signature(body_type, body, body_form=None, body_multipart=None, body_graphql=None):
    if body_type == "form":
        try:
            rows = json.loads(body_form) if isinstance(body_form, str) else (body_form or [])
        except (ValueError, TypeError):
            rows = []
        return _params_signature(rows)
    if body_type == "multipart":
        try:
            rows = json.loads(body_multipart) if isinstance(body_multipart, str) else (body_multipart or [])
        except (ValueError, TypeError):
            rows = []
        return _params_signature(rows)
    if body_type == "graphql":
        return ("graphql", body_graphql)
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
        _body_signature(req.get("body_type"), req.get("body"), req.get("body_form"), req.get("body_multipart"), req.get("body_graphql")),
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
        raw_rows = req.get("body_form") if body_type == "form" else req.get("body_multipart")
        try:
            rows = json.loads(raw_rows) if isinstance(raw_rows, str) else (raw_rows or [])
        except (ValueError, TypeError):
            rows = []
        for row in rows:
            if row.get("enabled") is False:
                continue
            key = row.get("key") or row.get("name") or ""
            if key:
                fields[f"body:{key}"] = row.get("value", "")
    elif body_type == "graphql":
        fields["body:__raw__"] = req.get("body_graphql")
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
    _ABSENT = " __absent__"
    diff_fields = []
    for key in all_keys:
        values = [fields.get(key, _ABSENT) for fields in per_variant_fields]
        hashable_values = [json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v for v in values]
        if len(set(hashable_values)) > 1:
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
                field_key = "body_form" if body_type == "form" else "body_multipart"
                try:
                    rows = json.loads(out[field_key]) if isinstance(out.get(field_key), str) else (out.get(field_key) or [])
                except (ValueError, TypeError):
                    rows = []
                for row in rows:
                    if (row.get("key") or row.get("name")) == name:
                        row["value"] = var
                out[field_key] = json.dumps(rows)
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
