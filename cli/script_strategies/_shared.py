"""Language-agnostic helpers shared across strategies."""

import re
from dataclasses import dataclass, asdict
from typing import Optional


_VAR_PLACEHOLDER_RE = re.compile(r'\{\{(\w+)\}\}')

# Markers emitted by every strategy's harness. Detection is lax on the trailing
# comment so future template tweaks don't break re-import.
_BEGIN_MARKER_RE = re.compile(r'^[ \t]*(?:#|//)\s*BEGIN ACTIONS', re.MULTILINE)
_END_MARKER_RE = re.compile(r'^[ \t]*(?:#|//)\s*END ACTIONS', re.MULTILINE)


@dataclass
class ImportWarning:
    severity: str
    code: str
    message: str
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


def detect_qaclan_harness(content: str) -> bool:
    """True iff content has both BEGIN/END ACTIONS markers, in order."""
    if not content:
        return False
    begin = _BEGIN_MARKER_RE.search(content)
    if not begin:
        return False
    end = _END_MARKER_RE.search(content, pos=begin.end())
    return end is not None


def extract_between_harness_markers(content: str) -> Optional[str]:
    """Return the action body between BEGIN/END ACTIONS, dedented to the
    smallest common indent so it can be re-rendered through ``_render_harness``.
    Returns None if markers missing/out-of-order, "" if empty body."""
    if not detect_qaclan_harness(content):
        return None
    begin = _BEGIN_MARKER_RE.search(content)
    end = _END_MARKER_RE.search(content, pos=begin.end())
    body = content[begin.end():end.start()].lstrip("\n").rstrip()
    if not body:
        return ""
    lines = body.splitlines()
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    base = min(indents) if indents else 0
    return "\n".join(l[base:] if len(l) >= base else l for l in lines)


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
