from __future__ import annotations

"""Structural diff for inferred type-tree schemas (see cli/schema_infer.py).

Source of truth for response-schema drift detection. Compares a frozen
"expected response" schema against a freshly inferred one and classifies each
difference by severity. Pure logic — no DB, no I/O. Mirrors the recursion of
cli/api_discovery/schema_merger.py but emits differences instead of a union.

Type-tree format (from infer_schema):
    - primitives: "string", "number", "boolean", "null"
    - objects:    {"key": <schema>, ...}
    - arrays:     [<item_schema>]  (single-element list) or ["?"] when empty
    - wildcards:  "?" (unknown), "..." (depth-4 cap)

Severity (fixed mapping):
    removed / type-changed / became-nullable / element-type-changed -> breaking
    added -> additive
    any wildcard on either side -> no difference emitted
"""

_WILDCARDS = ("?", "...")


def _is_wildcard(schema):
    return isinstance(schema, str) and schema in _WILDCARDS


def _category(schema):
    if isinstance(schema, dict):
        return "object"
    if isinstance(schema, list):
        return "array"
    return "primitive"


def _type_label(schema):
    if isinstance(schema, dict):
        return "object"
    if isinstance(schema, list):
        return "array"
    return schema


def _diff(path, kind, severity, expected_type, actual_type):
    return {
        "path": path,
        "kind": kind,
        "severity": severity,
        "expected_type": expected_type,
        "actual_type": actual_type,
    }


def _child_path(parent, key):
    return f"{parent}.{key}" if parent else key


def _walk(expected, current, path, diffs):
    # Wildcard on either side -> unknown shape, never claim drift.
    if _is_wildcard(expected) or _is_wildcard(current):
        return

    if isinstance(expected, dict) and isinstance(current, dict):
        for key in expected:
            cp = _child_path(path, key)
            if key not in current:
                diffs.append(_diff(cp, "removed", "breaking", _type_label(expected[key]), None))
            else:
                _walk(expected[key], current[key], cp, diffs)
        for key in current:
            if key not in expected:
                diffs.append(_diff(_child_path(path, key), "added", "additive", None, _type_label(current[key])))
        return

    if isinstance(expected, list) and isinstance(current, list):
        ex_item = expected[0] if expected else "?"
        in_item = current[0] if current else "?"
        elem_path = f"{path}[]"
        if _is_wildcard(ex_item) or _is_wildcard(in_item):
            return
        ecat, icat = _category(ex_item), _category(in_item)
        if ecat == icat and ecat in ("object", "array"):
            _walk(ex_item, in_item, elem_path, diffs)
        elif ex_item != in_item:
            if in_item == "null" and ex_item != "null":
                diffs.append(_diff(elem_path, "became-nullable", "breaking", _type_label(ex_item), "null"))
            else:
                diffs.append(_diff(elem_path, "element-type-changed", "breaking", _type_label(ex_item), _type_label(in_item)))
        return

    # Category mismatch (object vs array vs primitive) is a breaking type change.
    if _category(expected) != _category(current):
        if current == "null" and expected != "null":
            diffs.append(_diff(path, "became-nullable", "breaking", _type_label(expected), "null"))
        else:
            diffs.append(_diff(path, "type-changed", "breaking", _type_label(expected), _type_label(current)))
        return

    # Both primitives.
    if isinstance(expected, str) and isinstance(current, str):
        if expected == current:
            return
        if current == "null" and expected != "null":
            diffs.append(_diff(path, "became-nullable", "breaking", expected, "null"))
        else:
            diffs.append(_diff(path, "type-changed", "breaking", expected, current))


def diff_schemas(expected, current):
    """Return a flat list of difference records between two type-tree schemas.

    Each record: {path, kind, severity, expected_type, actual_type}.
    kind in {removed, added, type-changed, became-nullable, element-type-changed}.
    """
    if expected is None or current is None:
        return []
    diffs = []
    _walk(expected, current, "", diffs)
    return diffs


def classify_drift(differences):
    """Build the schema_drift verdict object from a difference list."""
    breaking = sum(1 for d in differences if d["severity"] == "breaking")
    additive = sum(1 for d in differences if d["severity"] == "additive")
    worst = "breaking" if breaking else ("additive" if additive else "none")
    return {
        "checked": True,
        "verdict": "fail" if breaking else "pass",
        "skipped_reason": None,
        "breaking_count": breaking,
        "additive_count": additive,
        "worst_severity": worst,
        "differences": differences,
    }


def evaluate_drift(expected, current):
    """Convenience: diff two schemas and return the classified verdict."""
    return classify_drift(diff_schemas(expected, current))


def skipped(reason):
    """Verdict object for a check that ran but produced no comparison."""
    checked = reason == "first-capture"
    return {
        "checked": checked,
        "verdict": "skipped",
        "skipped_reason": reason,
        "breaking_count": 0,
        "additive_count": 0,
        "worst_severity": "none",
        "differences": [],
    }
