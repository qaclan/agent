from __future__ import annotations
import re

# Matches a Postman/Bruno path variable segment, e.g. :id or :userId.
# Deliberately does NOT match {{var}} (Postman/qaclan's own env-var syntax,
# already compatible with qaclan and left untouched).
_COLON_VAR_RE = re.compile(r":([A-Za-z_]\w*)")


def convert_path_vars(url: str, seed_values: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Convert Postman/Bruno `:var` path segments to qaclan's `{var}` syntax.

    seed_values: known values for path vars (e.g. from Postman's
    url.variable[] or Bruno's params:path block), keyed by var name.
    """
    seed_values = seed_values or {}
    path_params: list[dict] = []
    seen: set[str] = set()

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            path_params.append({
                "key": key,
                "value": seed_values.get(key, ""),
                "enabled": True,
            })
        return "{" + key + "}"

    # Only rewrite the path portion, not the query string, so a stray
    # ":" inside a query value (unusual, but possible) is left alone.
    if "?" in url:
        path_part, _, query_part = url.partition("?")
        new_path = _COLON_VAR_RE.sub(_replace, path_part)
        new_url = f"{new_path}?{query_part}"
    else:
        new_url = _COLON_VAR_RE.sub(_replace, url)

    return new_url, path_params
