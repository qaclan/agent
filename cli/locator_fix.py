"""Fix "selector matched multiple elements" failures without hand-editing.

Playwright's strict-mode error lists every match with its HTML and a unique
locator ("aka ...") for each. This module parses that list out of the stored
run error and rewrites the failing script. Three fixes:

  wait      (recommended) insert ``expect(<locator>).toHaveCount(1)`` before the
            failing line. Playwright does NOT retry a strict-mode error, so when
            the page is still re-rendering (e.g. a filter just changed) the
            check fires on stale rows. A retrying count wait rides that out and
            keeps the check strict. Codegen only emits locators that were unique
            at record time, so "exactly one" is the original intent.
  any       append ``.first()`` / ``.first`` -- for pages that really do show
            several matches.
  specific  swap in Playwright's own unique locator for one match.

Pure string work, no network. Used by web/routes/scripts.py.
"""

from __future__ import annotations

import re
from typing import Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# "<locator> resolved to 3 elements:" -- locator runs from after the colon.
_HEAD_RE = re.compile(
    r"strict mode violation:\s*(?P<loc>.+?)\s+resolved to (?P<n>\d+) elements?:",
    re.DOTALL,
)
_ITEM_RE = re.compile(r"^\s*(\d+)\)\s+(.*)$")
_STACK_AT_RE = re.compile(r"\.(?:spec\.)?[jt]s:(\d+):(\d+)\b|\.py:(\d+)\b")
_CODE_LINE_RE = re.compile(r"^\s*>\s*(\d+)\s*\|\s?(.*)$")
_TEXT_RE = re.compile(r">([^<]*)<")
_ATTR_RE = re.compile(r'\s([\w:-]+)="([^"]*)"')
_LABEL_ATTRS = ("aria-label", "title", "alt", "placeholder")


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _describe_match(html: str, aka: str) -> dict:
    """Plain-language label for one match: its visible text plus the first
    attribute that tells it apart from its siblings."""
    text = " ".join(" ".join(_TEXT_RE.findall(html)).replace("↵", " ").split())
    extra = ""
    for key, val in _ATTR_RE.findall(html):
        if val and (("name" in key and key != "name") or key in _LABEL_ATTRS):
            extra = val
            break
    return {"text": text, "extra": extra}


def parse_strict_violation(raw: str) -> Optional[dict]:
    """Return {locator, count, kind, line, code, matches[]} or None when ``raw``
    isn't a strict-mode violation. ``matches[i]`` has ``index`` (1-based),
    ``label`` and ``aka`` (None when Playwright gave no better locator)."""
    if not raw:
        return None
    clean = _ANSI_RE.sub("", raw)
    head = _HEAD_RE.search(clean)
    if not head:
        return None
    locator = " ".join(head.group("loc").split())
    count = int(head.group("n"))

    matches = []
    after = clean[head.end():]
    for ln in after.splitlines():
        if not ln.strip():
            if matches:
                break
            continue
        m = _ITEM_RE.match(ln)
        if not m:
            if matches:
                break
            continue
        body = m.group(2)
        html, sep, aka = body.rpartition(" aka ")
        if not sep:
            html, aka = body, ""
        matches.append({"index": int(m.group(1)), "html": html, "aka": aka.strip() or None})

    line = None
    code = None
    for ln in clean.splitlines():
        cm = _CODE_LINE_RE.match(ln)
        if cm:
            line, code = int(cm.group(1)), cm.group(2).strip()
            break
    if line is None:
        am = _STACK_AT_RE.search(clean)
        if am:
            line = int(am.group(1) or am.group(3))

    kind = "assertion" if re.search(r"\bexpect\b", clean[:head.start()][-400:]) else "action"

    described = [_describe_match(m["html"], m["aka"] or "") for m in matches]
    texts = {d["text"] for d in described}
    for m, d in zip(matches, described):
        parts = [d["text"]] if d["text"] else []
        if d["extra"]:
            parts.append(d["extra"])
        # Identical text and no distinguishing attribute -> fall back to position.
        if not d["extra"] and len(texts) <= 1:
            parts = parts[:1] + [f"{_ordinal(m['index'])} match"]
        m["label"] = " — ".join(parts) if parts else f"{_ordinal(m['index'])} match"
        del m["html"]
    return {"locator": locator, "count": count, "kind": kind,
            "line": line, "code": code, "matches": matches}


def _first_suffix(language: str) -> str:
    return ".first" if language == "python" else ".first()"


# Languages whose harness exposes ``expect`` (plain JavaScript has none).
_EXPECT_LANGUAGES = ("python", "javascript_test", "typescript_test")


def _wait_line(language: str, indent: str, prefix: str, locator: str) -> str:
    if language == "python":
        return f"{indent}expect({prefix}{locator}).to_have_count(1)"
    return f"{indent}await expect({prefix}{locator}).toHaveCount(1);"


def _locator_prefix(line: str, locator: str) -> Optional[str]:
    """``page.`` (or ``self.page.``) directly before the locator, else None."""
    pos = line.find(locator)
    m = re.search(r"((?:self\.)?page\.)$", line[:pos]) if pos > 0 else None
    return m.group(1) if m else None


def _already_waits(lines: list, idx: int, locator: str) -> bool:
    """True when the line above is already a count-wait on this locator."""
    return idx > 0 and locator in lines[idx - 1] and bool(
        re.search(r"toHaveCount\(1\)|to_have_count\(1\)", lines[idx - 1]))


def find_target_line(lines: list, locator: str, hint_line: Optional[int]) -> Optional[int]:
    """0-based index of the script line holding ``locator``. Prefer the line the
    stack trace named; otherwise accept the match only if it's unambiguous."""
    # Ignore count-waits this module inserted earlier, so re-opening the fix on
    # an old run after applying it targets the real step, not the wait line.
    hits = [i for i, ln in enumerate(lines)
            if locator in ln and not re.search(r"toHaveCount\(1\)|to_have_count\(1\)", ln)]
    if hint_line is not None and (hint_line - 1) in hits:
        return hint_line - 1
    if len(hits) == 1:
        return hits[0]
    return None


def rewrite_line(line: str, locator: str, replacement: str) -> str:
    """Replace the first occurrence of ``locator`` in ``line``."""
    return line.replace(locator, replacement, 1)


def build_options(source: str, language: str, info: dict) -> Optional[dict]:
    """Preview every available rewrite against ``source``. None when the failing
    locator can't be placed in the script (script edited since the run)."""
    lines = source.splitlines(keepends=True)
    idx = find_target_line(lines, info["locator"], info.get("line"))
    if idx is None:
        return None
    before = lines[idx].rstrip("\r\n")
    suffix = _first_suffix(language)
    already_first = (info["locator"] + suffix) in before
    any_after = before if already_first else rewrite_line(before, info["locator"], info["locator"] + suffix)
    specific = []
    for m in info["matches"]:
        aka = m.get("aka")
        specific.append({
            "index": m["index"], "label": m["label"], "aka": aka,
            "after": rewrite_line(before, info["locator"], aka).strip() if aka else None,
        })
    wait_after = None
    prefix = _locator_prefix(before, info["locator"])
    if language in _EXPECT_LANGUAGES and prefix and not _already_waits(lines, idx, info["locator"]):
        indent = before[:len(before) - len(before.lstrip())]
        wait_after = _wait_line(language, indent, prefix, info["locator"]).strip()
    return {"line_no": idx + 1, "before": before.strip(), "any_after": any_after.strip(),
            "wait_after": wait_after, "already_waits": _already_waits(lines, idx, info["locator"]),
            "specific": specific}


def apply_fix(source: str, language: str, info: dict, mode: str,
              match_index: Optional[int]) -> str:
    """Return ``source`` with the failing line rewritten. Raises ValueError."""
    lines = source.splitlines(keepends=True)
    idx = find_target_line(lines, info["locator"], info.get("line"))
    if idx is None:
        raise ValueError("The script has changed since this run, so the failing "
                         "line can't be found. Re-run it, then try again.")
    if mode == "wait":
        opts = build_options(source, language, info)
        if not opts or not opts["wait_after"]:
            raise ValueError("A wait can't be added here. Choose another option.")
        line = lines[idx]
        eol = line[len(line.rstrip("\r\n")):] or "\n"
        indent = line[:len(line) - len(line.lstrip())]
        lines.insert(idx, indent + opts["wait_after"] + eol)
        return "".join(lines)
    if mode == "any":
        replacement = info["locator"] + _first_suffix(language)
    elif mode == "specific":
        match = next((m for m in info["matches"] if m["index"] == match_index), None)
        if not match or not match.get("aka"):
            raise ValueError("That match has no unique locator. Pick another.")
        replacement = match["aka"]
    else:
        raise ValueError(f"Unknown fix mode '{mode}'")
    lines[idx] = rewrite_line(lines[idx], info["locator"], replacement)
    return "".join(lines)
