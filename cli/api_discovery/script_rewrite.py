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


def _split_top_level_args(s: str) -> list[str]:
    """Split a JS call's argument text on top-level commas, respecting
    (), [], {}, and both quote types. Not a full JS parser — good enough
    for the single-line calls this module generates and typically sees."""
    parts: list[str] = []
    depth = 0
    quote = None
    current = []
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            current.append(c)
            if c == "\\" and i + 1 < len(s):
                i += 1
                current.append(s[i])
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            current.append(c)
        elif c in "([{":
            depth += 1
            current.append(c)
        elif c in ")]}":
            depth -= 1
            current.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


# Reverse of _DIRECT_REWRITES — qc.* -> foreign, keyed by target.
_REVERSE_DIRECT: dict[str, list[tuple[re.Pattern, str]]] = {
    "postman": [
        (re.compile(r"\bqc\.set\("), "pm.environment.set("),
        (re.compile(r"\bqc\.test\("), "pm.test("),
        (re.compile(r"\bqc\.getHeader\("), "pm.request.headers.get("),
        (re.compile(r"\bqc\.getParam\("), "pm.request.url.query.get("),
        (re.compile(r"\bresponse\.json\("), "pm.response.json("),
        (re.compile(r"\bresponse\.text\("), "pm.response.text("),
        (re.compile(r"\bresponse\.headers\b"), "pm.response.headers"),
        (re.compile(r"\bresponse\.status\b"), "pm.response.code"),
    ],
    "bruno": [
        (re.compile(r"\bqc\.set\("), "bru.setVar("),
        (re.compile(r"\bqc\.test\("), "test("),
        (re.compile(r"\bqc\.setHeader\("), "req.setHeader("),
        (re.compile(r"\bqc\.getHeader\("), "req.getHeader("),
        (re.compile(r"\bqc\.setParam\("), "req.setQueryParam("),
        (re.compile(r"\bqc\.getParam\("), "req.getQueryParam("),
        (re.compile(r"\bresponse\.json\(\)"), "res.body"),
        (re.compile(r"\bresponse\.text\(\)"), "(typeof res.body === 'string' ? res.body : JSON.stringify(res.body))"),
        (re.compile(r"\bresponse\.headers\b"), "res.headers"),
        (re.compile(r"\bresponse\.status\b"), "res.status"),
    ],
}


def _find_matching_paren(s: str, open_idx: int) -> int:
    """s[open_idx] must be '('. Returns the index of its matching ')',
    respecting nesting and quotes, or -1 if unbalanced."""
    depth = 0
    quote = None
    i = open_idx
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\" and i + 1 < len(s):
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _rewrite_calls(line: str, call_name: str, build) -> str:
    """Replace every top-level call to `call_name(...)` in line, using
    build(args: list[str]) -> str | None (None = leave this call alone).
    Uses real paren-matching (not regex) so nested calls on the same line
    (e.g. qc.expect(...) inside a qc.test(...) callback) are handled
    correctly instead of a greedy regex swallowing past the true close
    paren."""
    out = []
    i = 0
    needle = call_name + "("
    while True:
        idx = line.find(needle, i)
        if idx == -1:
            out.append(line[i:])
            break
        out.append(line[i:idx])
        open_paren = idx + len(call_name)
        close_paren = _find_matching_paren(line, open_paren)
        if close_paren == -1:
            out.append(line[idx:])
            break
        inner = line[open_paren + 1:close_paren]
        args = _split_top_level_args(inner) if inner.strip() else []
        replacement = build(args, line[:idx], line[close_paren + 1:])
        if replacement is None:
            out.append(line[idx:close_paren + 1])
        else:
            out.append(replacement)
        i = close_paren + 1
    return "".join(out)


def _build_expect_replacement(target):
    def build(args: list[str], before: str, after: str) -> str | None:
        if len(args) < 2:
            return None
        cond, message = args[0], ",".join(args[1:])
        # Whole-statement case (qc.expect(...) is the entire line, modulo
        # indentation/semicolon): wrap as a named test so Postman/Bruno's
        # test runner records it as a distinct result, matching what a
        # standalone qc.expect() does in qaclan (records its own pass/fail).
        if not before.strip() and not after.strip().rstrip(";").strip():
            # No trailing ";" here — the original line's own trailing ";"
            # (left in `after`) supplies it, avoiding a doubled ";;".
            if target == "postman":
                return f'pm.test({message}, () => {{ if (!({cond})) throw new Error({message}); }})'
            return f'test({message}, () => {{ if (!({cond})) throw new Error({message}); }})'
        # Nested case (already inside some other block, e.g. a qc.test
        # callback): in-place statement substitution, no extra wrapping —
        # qc.expect is always called for its side effect, never as a value,
        # so it's always safe to replace with an if/throw statement.
        return f"if (!({cond})) throw new Error({message})"
    return build


def _build_object_wrap(wrapper: str):
    def build(args: list[str], before: str, after: str) -> str | None:
        if len(args) != 2:
            return None
        return f"{wrapper}({{key: {args[0]}, value: {args[1]}}})"
    return build


def qc_script_to_foreign(script: str | None, target: str) -> str | None:
    """Reverse of foreign_script_to_qc — regenerate Postman/Bruno-flavored
    JS from qaclan's native qc.* script text. target: "postman" | "bruno".
    """
    if not script:
        return script
    out_lines = []
    for line in script.splitlines():
        rewritten = _rewrite_calls(line, "qc.expect", _build_expect_replacement(target))
        if target == "postman":
            rewritten = _rewrite_calls(rewritten, "qc.setHeader", _build_object_wrap("pm.request.headers.add"))
            rewritten = _rewrite_calls(rewritten, "qc.setParam", _build_object_wrap("pm.request.url.addQueryParams"))
        for pattern, replacement in _REVERSE_DIRECT[target]:
            rewritten = pattern.sub(replacement, rewritten)
        out_lines.append(rewritten if rewritten.strip() else line)
    return "\n".join(out_lines)
