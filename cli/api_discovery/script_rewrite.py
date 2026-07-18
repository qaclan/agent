from __future__ import annotations
import re

# Direct call-name substitutions: same argument list both sides, so a
# straight prefix swap is correct. Order matters — longer/more specific
# patterns first so a generic one doesn't shadow a specific one.
_DIRECT_REWRITES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpm\.environment\.set\("), "qc.set("),
    (re.compile(r"\bpm\.variables\.set\("), "qc.set("),
    (re.compile(r"\bbru\.setEnvVar\("), "qc.set("),
    (re.compile(r"\bbru\.setVar\("), "qc.set("),
    (re.compile(r"\bpm\.test\("), "qc.test("),
    (re.compile(r"(?<![.\w])test\("), "qc.test("),
    (re.compile(r"\breq\.setHeader\("), "qc.setHeader("),
    (re.compile(r"\breq\.getHeader\("), "qc.getHeader("),
    (re.compile(r"\bpm\.request\.headers\.get\("), "qc.getHeader("),
    (re.compile(r"\bpm\.request\.url\.query\.get\("), "qc.getParam("),
    (re.compile(r"\bpm\.response\.json\("), "response.json("),
    (re.compile(r"\bpm\.response\.text\("), "response.text("),
    (re.compile(r"\bpm\.response\.headers\b"), "response.headers"),
    (re.compile(r"\bpm\.response\.(?:status|code)\b"), "response.status"),
    (re.compile(r"\bres\.headers\b"), "response.headers"),
    (re.compile(r"\bres\.status\b"), "response.status"),
    (re.compile(r"\bres\.body\b"), "response.json()"),
]

# Object-literal-argument calls: `fn({key: K, value: V})` -> `qc.x(K, V)`.
# Best-effort regex, not a JS parser — values with nested braces/commas in
# the object literal itself won't match and fall through unconverted.
_OBJECT_REWRITES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"pm\.request\.headers\.add\(\s*\{\s*key\s*:\s*(.+?)\s*,\s*value\s*:\s*(.+?)\s*\}\s*\)"),
     r"qc.setHeader(\1, \2)"),
    (re.compile(r"pm\.request\.url\.addQueryParams\(\s*\{\s*key\s*:\s*(.+?)\s*,\s*value\s*:\s*(.+?)\s*\}\s*\)"),
     r"qc.setParam(\1, \2)"),
]

# pm.expect(EXPR).to.[not.]MATCHER(ARG) / bare expect(EXPR).to....
# qc.expect(condition, message) takes a plain boolean, not a chainable —
# so the whole matched line is rewritten, not just the call name.
_EXPECT_RE = re.compile(
    r"(?:pm\.)?expect\((?P<expr>.+?)\)\.to\.(?P<neg>not\.)?"
    r"(?P<matcher>equal|eql|be\.true|be\.false|exist|include|match)"
    r"(?:\((?P<arg>.*)\))?\s*;?\s*$"
)

_UNCONVERTED_MARKERS = [
    re.compile(r"\bpm\.sendRequest\b"),
    re.compile(r"\bpm\.cookies\b"),
    re.compile(r"\bpm\.iterationData\b"),
    re.compile(r"\bbru\.runRequest\b"),
    re.compile(r"\bpm\.\w+"),
    re.compile(r"\bbru\.\w+"),
]


def _rewrite_expect_line(line: str) -> tuple[str, str] | None:
    """Returns (rewritten_line, scannable_condition) or None if no match.

    scannable_condition excludes the human-readable message string, so the
    unconverted-call scan doesn't false-flag inert label text like the
    literal "pm.expect(" this function embeds into the message for
    traceability.
    """
    m = _EXPECT_RE.search(line)
    if not m:
        return None
    expr = _apply_direct_rewrites(m.group("expr").strip())
    matcher = m.group("matcher")
    arg = _apply_direct_rewrites((m.group("arg") or "").strip())
    if matcher == "equal":
        cond = f"{expr} === {arg}"
    elif matcher == "eql":
        cond = f"JSON.stringify({expr}) === JSON.stringify({arg})"
    elif matcher == "be.true":
        cond = f"{expr} === true"
    elif matcher == "be.false":
        cond = f"{expr} === false"
    elif matcher == "exist":
        cond = f"{expr} !== undefined && {expr} !== null"
    elif matcher == "include":
        cond = f"({expr}).includes({arg})"
    elif matcher == "match":
        cond = f"{arg}.test({expr})"
    else:
        return None
    if m.group("neg"):
        cond = f"!({cond})"
    # Message is a human-readable label only (embeds the literal original
    # line, including "pm.expect(" text) — never itself scanned for
    # unconverted calls, see foreign_script_to_qc.
    message = line.strip().replace('"', "'")
    indent = line[: len(line) - len(line.lstrip())]
    return f'{indent}qc.expect({cond}, "{message}");', cond


def _apply_direct_rewrites(line: str) -> str:
    for pattern, replacement in _DIRECT_REWRITES:
        line = pattern.sub(replacement, line)
    for pattern, replacement in _OBJECT_REWRITES:
        line = pattern.sub(replacement, line)
    return line


def foreign_script_to_qc(script: str | None) -> tuple[str | None, list[str]]:
    """Rewrite Postman/Bruno pre/post script JS into native qc.* JS.

    Returns (rewritten_script, warnings). Anything not recognized is left
    as-is in the output and reported in warnings, never silently dropped.
    """
    if not script:
        return script, []

    out_lines = []
    scan_parts = []
    for line in script.splitlines():
        result = _rewrite_expect_line(line)
        if result is not None:
            rewritten_line, scannable = result
            out_lines.append(rewritten_line)
            scan_parts.append(scannable)
        else:
            direct = _apply_direct_rewrites(line)
            out_lines.append(direct)
            scan_parts.append(direct)
    text = "\n".join(out_lines)
    scan_text = "\n".join(scan_parts)

    warnings: list[str] = []
    seen = set()
    for pattern in _UNCONVERTED_MARKERS:
        for match in pattern.finditer(scan_text):
            token = match.group(0)
            if token not in seen:
                seen.add(token)
                warnings.append(f"unconverted script call: {token}")
    return text, warnings
