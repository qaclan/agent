from __future__ import annotations


def infer_schema(value, _depth=0):
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
        return [infer_schema(value[0], _depth + 1)] if value else ["?"]
    if isinstance(value, dict):
        return {k: infer_schema(v, _depth + 1) for k, v in value.items()}
    return "unknown"
