"""Language-agnostic helpers shared across strategies."""

import re


_VAR_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')


def scan_var_keys(content: str) -> list:
    """Return the unique ``{{KEY}}`` placeholders that appear in ``content``,
    preserving first-seen order."""
    if not content:
        return []
    seen = []
    for m in _VAR_PLACEHOLDER_RE.finditer(content):
        key = m.group(1)
        if key not in seen:
            seen.append(key)
    return seen


def substitute_template_vars(source: str, var_keys, env_vars, fallback_key, fallback_value, escape_fn=None):
    """Resolve ``{{KEY}}`` placeholders in ``source`` against ``env_vars``.

    ``escape_fn`` (optional) is applied to each value before substitution so
    the resulting text is safe to splice into a string literal of the target
    language. Without an escape function, values pass through untouched — only
    use the unescaped path for URL-like values that won't contain quotes or
    backslashes.

    Raises ValueError if a required key has neither an env value nor a
    matching fallback.
    """
    warnings = []
    for key in var_keys:
        placeholder = "{{" + key + "}}"
        if key in env_vars:
            value = env_vars[key]
        elif key == fallback_key and fallback_value:
            value = fallback_value
            warnings.append(f"Variable '{key}' not in env, using recorded fallback")
        else:
            raise ValueError(
                f"Script requires variable '{key}' but it's not in the selected environment "
                f"and no fallback is available."
            )
        if escape_fn is not None:
            value = escape_fn(value)
        source = source.replace(placeholder, value)
    return source, warnings
