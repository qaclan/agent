from __future__ import annotations


def merge_schemas(existing, incoming):
    """Merge two inferred type-tree schemas. Union of fields; union of types on conflict.

    Both inputs use the format produced by har_parser._infer_schema():
    - primitive types: "string", "number", "boolean", "null", "?"
    - objects: {"key": <schema>, ...}
    - arrays:  [<item_schema>]  (single-element list)
    - depth sentinel: "..."
    """
    if existing is None:
        return incoming
    if incoming is None:
        return existing

    # Both primitives (type strings)
    if isinstance(existing, str) and isinstance(incoming, str):
        if existing == incoming:
            return existing
        # Prefer a real type over null/unknown
        if existing in ('null', '?', '...'):
            return incoming
        if incoming in ('null', '?', '...'):
            return existing
        return existing  # Keep first seen on true conflict

    # Both arrays
    if isinstance(existing, list) and isinstance(incoming, list):
        ex_item = existing[0] if existing else None
        in_item = incoming[0] if incoming else None
        merged = merge_schemas(ex_item, in_item)
        return [merged] if merged is not None else []

    # Both objects
    if isinstance(existing, dict) and isinstance(incoming, dict):
        result = dict(existing)
        for k, v in incoming.items():
            result[k] = merge_schemas(result.get(k), v)
        return result

    # Type mismatch (e.g. one is object, other is primitive) — keep existing
    return existing
