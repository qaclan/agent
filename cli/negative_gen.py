from __future__ import annotations

"""Negative API test-case generation.

Source of truth for how a happy-path request becomes a set of negative cases
(see docs/api-negative-testing-reference.md). Pure logic — no DB, no I/O, no
HTTP. The runner (cli/api_runner.py) applies each case's `mutation` and evaluates
its `expect`; this module only decides *what* cases exist.

A case is declarative data so it can be stored, edited, toggled, diffed, synced,
and rendered in the matrix UI:

    {
        "id":        "body.age::wrong-type",     # stable, target::subtype
        "category":  "input-validation" | "request-level" | "injection",
        "subtype":   "wrong-type" | "missing-required" | ...,
        "target":    "body.age" | "param.q" | "@auth" | "@method" | ...,
        "label":     "age as string",
        "enabled":   true,
        "mutation":  { "op": "set", "path": "body.age", "value": "not-a-number" },
        "expect":    { "status_value": 400, "status_min": 400, "status_max": 499,
                       "no_500": false, "no_reflect": false, "reflect_value": null }
    }

The `expect` status is a **4xx family** check by default (status_min/max), with a
representative `status_value` for display. Exact-code strictness is opt-in in the
UI (it sets status_min == status_max). This keeps the common "the API rejected
it with a client error" intent from producing Minor noise on 400-vs-422.
"""

import json

# Curated, capped injection payload pack. Each string field gets one case per
# payload — kept small on purpose so a request with many fields doesn't explode
# into hundreds of sends.
INJECTION_PAYLOADS = [
    ("sqli", "' OR '1'='1"),
    ("xss", "<script>alert(1)</script>"),
    ("path-traversal", "../../../../etc/passwd"),
    ("null-byte", "abc\x00def"),
]

_CLIENT_ERROR = {"status_min": 400, "status_max": 499}


def _expect(status_value, *, no_500=False, no_reflect=False, reflect_value=None):
    e = {"status_value": status_value, **_CLIENT_ERROR,
         "no_500": no_500, "no_reflect": no_reflect}
    if reflect_value is not None:
        e["reflect_value"] = reflect_value
    return e


def _case(target, subtype, category, label, mutation, expect, enabled=True):
    return {
        "id": f"{target}::{subtype}",
        "category": category,
        "subtype": subtype,
        "target": target,
        "label": label,
        "enabled": enabled,
        "mutation": mutation,
        "expect": expect,
    }


def _parse_body(request_row):
    """Return the request's raw JSON body as a Python object, or None."""
    if request_row.get("body_type") != "raw":
        return None
    body = request_row.get("body")
    if not body or not isinstance(body, str):
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


def _walk_fields(obj, prefix=""):
    """Yield (dotted_path, value) for each scalar/array leaf in a JSON object,
    descending one level into nested objects. Arrays are treated as leaves."""
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _walk_fields(value, path)
        else:
            yield path, value


def _wrong_type_value(value):
    """A value of a deliberately different JSON type than `value`."""
    if isinstance(value, bool):
        return "not-a-boolean"
    if isinstance(value, (int, float)):
        return "not-a-number"
    if isinstance(value, str):
        return 123456789
    if isinstance(value, list):
        return "not-an-array"
    return "not-an-object"


def _input_validation_cases(body, constraints):
    cases = []
    if not isinstance(body, dict):
        return cases
    required = set()
    for path, cons in (constraints or {}).items():
        if isinstance(cons, dict) and cons.get("required"):
            required.add(path)

    for path, value in _walk_fields(body):
        target = f"body.{path}"
        cons = (constraints or {}).get(path, {}) if constraints else {}

        # missing-required — with constraints, only for fields marked required;
        # without, for every field (conservative default the user can prune).
        if not constraints or path in required:
            cases.append(_case(
                target, "missing-required", "input-validation",
                f"{path} missing",
                {"op": "remove", "path": target}, _expect(400)))

        # wrong-type
        cases.append(_case(
            target, "wrong-type", "input-validation",
            f"{path} wrong type",
            {"op": "set", "path": target, "value": _wrong_type_value(value)}, _expect(400)))

        # null
        cases.append(_case(
            target, "null", "input-validation",
            f"{path} null",
            {"op": "set", "path": target, "value": None}, _expect(400)))

        # empty (strings and arrays only)
        if isinstance(value, str):
            cases.append(_case(
                target, "empty", "input-validation",
                f"{path} empty",
                {"op": "set", "path": target, "value": ""}, _expect(400)))
        elif isinstance(value, list):
            cases.append(_case(
                target, "empty", "input-validation",
                f"{path} empty array",
                {"op": "set", "path": target, "value": []}, _expect(400)))

        # constraint-driven cases
        if cons:
            enum = cons.get("enum")
            if enum:
                cases.append(_case(
                    target, "enum", "input-validation",
                    f"{path} not in enum",
                    {"op": "set", "path": target, "value": "__qaclan_not_in_enum__"}, _expect(400)))
            lo, hi = cons.get("minimum"), cons.get("maximum")
            if isinstance(lo, (int, float)):
                cases.append(_case(
                    target, "boundary-min", "input-validation",
                    f"{path} below minimum",
                    {"op": "set", "path": target, "value": lo - 1}, _expect(400)))
            if isinstance(hi, (int, float)):
                cases.append(_case(
                    target, "boundary-max", "input-validation",
                    f"{path} above maximum",
                    {"op": "set", "path": target, "value": hi + 1}, _expect(400)))
            min_len = cons.get("minLength")
            max_len = cons.get("maxLength")
            if isinstance(min_len, int) and min_len > 0:
                cases.append(_case(
                    target, "boundary-minlength", "input-validation",
                    f"{path} too short",
                    {"op": "set", "path": target, "value": "x" * (min_len - 1)}, _expect(400)))
            if isinstance(max_len, int):
                cases.append(_case(
                    target, "boundary-maxlength", "input-validation",
                    f"{path} too long",
                    {"op": "set", "path": target, "value": "x" * (max_len + 1)}, _expect(400)))
            fmt = cons.get("format")
            if fmt:
                cases.append(_case(
                    target, "format", "input-validation",
                    f"{path} bad {fmt}",
                    {"op": "set", "path": target, "value": "not-a-valid-" + str(fmt)}, _expect(400)))

    # extra-unexpected-field (body-level)
    cases.append(_case(
        "body", "extra-field", "input-validation",
        "unexpected extra field",
        {"op": "set", "path": "body.__qaclan_unexpected__", "value": "x"}, _expect(400),
        enabled=False))  # off by default — many APIs legitimately ignore extras

    # oversized (body-level, string blow-up)
    cases.append(_case(
        "body", "oversized", "input-validation",
        "oversized payload",
        {"op": "set", "path": "body.__qaclan_oversized__", "value": "x" * 100000}, _expect(400),
        enabled=False))  # off by default — can stress a real backend

    return cases


def _request_level_cases(request_row):
    cases = []
    method = (request_row.get("method") or "GET").upper()
    auth_type = request_row.get("auth_type")
    headers = request_row.get("headers") or []
    has_auth_header = any(
        isinstance(h, dict) and str(h.get("key", "")).lower() == "authorization" and h.get("enabled", True)
        for h in headers)
    has_auth = (auth_type not in (None, "none")) or has_auth_header
    has_body = bool(request_row.get("body_type"))

    if has_auth:
        cases.append(_case(
            "@auth", "no-auth", "request-level", "No auth token",
            {"op": "drop_auth"}, _expect(401)))
        cases.append(_case(
            "@auth", "garbage-token", "request-level", "Garbage auth token",
            {"op": "set_auth", "value": "Bearer qaclan-invalid-token"}, _expect(401)))

    # wrong-method: for a mutating verb, GET is a safe wrong method; for GET,
    # DELETE is generated but disabled by default (it is destructive if allowed).
    if method == "GET":
        cases.append(_case(
            "@method", "wrong-method", "request-level", "Wrong method (DELETE)",
            {"op": "set_method", "value": "DELETE"}, _expect(405), enabled=False))
    else:
        cases.append(_case(
            "@method", "wrong-method", "request-level", "Wrong method (GET)",
            {"op": "set_method", "value": "GET"}, _expect(405)))

    if has_body:
        cases.append(_case(
            "@content-type", "wrong-content-type", "request-level", "Wrong Content-Type",
            {"op": "set_header", "key": "Content-Type", "value": "text/plain"}, _expect(415)))

    cases.append(_case(
        "@route", "unknown-route", "request-level", "Unknown route",
        {"op": "append_path", "value": "/__qaclan_nonexistent__"}, _expect(404)))

    if _parse_body(request_row) is not None:
        cases.append(_case(
            "@body", "malformed-json", "request-level", "Malformed JSON body",
            {"op": "set_raw_body", "value": '{"qaclan": '}, _expect(400)))

    return cases


def _injection_cases(body, request_row):
    cases = []
    targets = []  # (target, mutation-op, path)
    if isinstance(body, dict):
        for path, value in _walk_fields(body):
            if isinstance(value, str):
                targets.append((f"body.{path}", {"op": "set", "path": f"body.{path}"}))
    for p in (request_row.get("params") or []):
        if isinstance(p, dict) and p.get("enabled", True) and isinstance(p.get("value"), str) and p.get("key"):
            key = p["key"]
            targets.append((f"param.{key}", {"op": "set", "path": f"param.{key}"}))

    for target, base_mut in targets:
        for subtype, payload in INJECTION_PAYLOADS:
            mut = dict(base_mut)
            mut["value"] = payload
            cases.append(_case(
                target, subtype, "injection",
                f"{target.split('.', 1)[-1]} — {subtype}",
                mut,
                _expect(None, no_500=True, no_reflect=True, reflect_value=payload)))
    return cases


def generate_cases(request_row, field_constraints=None):
    """Generate negative cases for a request across the three v1 categories.

    request_row: a deserialized api_requests dict (method, url, headers, params,
        path_params, body_type, body, auth_type, ...).
    field_constraints: optional {dotted_field_path: {required, enum, minimum,
        maximum, minLength, maxLength, format, pattern, type}} captured from an
        OpenAPI import; when present it sharpens boundary/enum/format generation.
    """
    body = _parse_body(request_row)
    cases = []
    cases.extend(_input_validation_cases(body, field_constraints))
    cases.extend(_request_level_cases(request_row))
    cases.extend(_injection_cases(body, request_row))
    return cases


def diff_cases(old_cases, new_cases):
    """Compare a stored case list against a freshly generated one by id.

    Returns {"added": [...], "removed": [...]} so a regenerate can surface newly
    suggested and no-longer-applicable cases without discarding user edits.
    """
    old_ids = {c.get("id") for c in (old_cases or [])}
    new_ids = {c.get("id") for c in (new_cases or [])}
    added = [c for c in (new_cases or []) if c.get("id") not in old_ids]
    removed = [c for c in (old_cases or []) if c.get("id") not in new_ids]
    return {"added": added, "removed": removed}


def case_method(request_method, case):
    """The HTTP method a case will actually send — the request's method unless
    the case rewrites it. Used by the safety gate to spot mutating cases."""
    mut = case.get("mutation") or {}
    if mut.get("op") == "set_method":
        return str(mut.get("value") or request_method or "GET").upper()
    return str(request_method or "GET").upper()
