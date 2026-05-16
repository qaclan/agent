"""Offline structured error classifier.

Turns a raw script failure (exception type + message, or a raw stderr/stdout
blob) into a structured, human-readable error detail. Pure local pattern
matching — no network, no LLM, no external services.

See docs/error-reporting-plan.md (section 2.2).

Two callers:
  * the runner (web/routes/runs.py) for every failure path;
  * indirectly the per-language harnesses, which emit only the raw exception
    fields (raw_type / raw_message) into the artifacts JSON — the runner runs
    this classifier on those fields. Keeping ONE classifier in Python avoids
    duplicating the ordered rule list into the JS / TS harness templates.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Category table — title / plain message / suggested next step / severity.
# severity: "error" (something is wrong) | "warning" (config / setup, user can
# fix without code changes). UI colours by this.
# ---------------------------------------------------------------------------

CATEGORIES = {
    "ASSERTION_FAILED": {
        "title": "Check did not pass",
        "message": "A check did not pass: the page was not in the expected state.",
        "next_step": "Open the screenshot to see the page when the check ran.",
        "severity": "error",
    },
    "ELEMENT_NOT_FOUND": {
        "title": "Element not found",
        "message": "Could not find or interact with an element (e.g. a button or field).",
        "next_step": "The page layout may have changed — re-record the script.",
        "severity": "error",
    },
    "TIMEOUT": {
        "title": "Timed out",
        "message": "The page took too long to respond.",
        "next_step": "Check the site is reachable, or raise the wait limit and re-run.",
        "severity": "error",
    },
    "NAVIGATION_FAILED": {
        "title": "Page could not be opened",
        "message": "The page or website could not be opened.",
        "next_step": "Verify the URL in the environment is correct and reachable.",
        "severity": "error",
    },
    "NETWORK_ERROR": {
        "title": "Network request failed",
        "message": "A network request failed while loading the page.",
        "next_step": "Check the network connection or the API the page calls.",
        "severity": "error",
    },
    "BROWSER_CRASHED": {
        "title": "Browser stopped",
        "message": "The browser stopped unexpectedly during the test.",
        "next_step": "Re-run the test; if it keeps happening, report it.",
        "severity": "error",
    },
    "CONFIG_ERROR": {
        "title": "Missing setting",
        "message": "A required setting or value is missing.",
        "next_step": "Edit the environment and add the missing value.",
        "severity": "warning",
    },
    "SETUP_ERROR": {
        "title": "Test tools not installed",
        "message": "The test tools are not installed correctly.",
        "next_step": "Run: qaclan setup",
        "severity": "warning",
    },
    "SCRIPT_MISSING": {
        "title": "Script file missing",
        "message": "The test script file could not be found.",
        "next_step": "The script may have been deleted — re-create or re-record it.",
        "severity": "warning",
    },
    "SCRIPT_ERROR": {
        "title": "Script has a problem",
        "message": "The test script itself has a problem.",
        "next_step": "Re-record or edit the script to fix it.",
        "severity": "error",
    },
    "RUNTIME_ERROR": {
        "title": "Internal error",
        "message": "The test could not be run due to an internal error.",
        "next_step": "Report this — it is an internal bug.",
        "severity": "error",
    },
    "UNKNOWN": {
        "title": "Unknown failure",
        "message": "The test failed for an unknown reason.",
        "next_step": "Open the technical details below for more.",
        "severity": "error",
    },
}


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

_TIMEOUT_RES = (
    re.compile(r"Test timeout of (\d+)\s*ms"),
    re.compile(r"Timeout (\d+)\s*ms"),
    re.compile(r"timeout (?:of )?(\d+)\s*ms", re.IGNORECASE),
)

# Selector forms Playwright embeds in messages / call logs.
_SELECTOR_RES = (
    re.compile(r"waiting for (locator\(.+?\)|get_?[Bb]y[A-Za-z_]*\(.*?\))"),
    re.compile(r"(locator\(['\"`].+?['\"`]\))"),
    re.compile(r"(get[Bb]y[A-Z][A-Za-z]*\([^\n]*?\))"),
)


def extract_timeout_ms(message: str) -> Optional[int]:
    if not message:
        return None
    for re_ in _TIMEOUT_RES:
        m = re_.search(message)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def extract_selector(message: str) -> Optional[str]:
    if not message:
        return None
    for re_ in _SELECTOR_RES:
        m = re_.search(message)
        if m:
            sel = m.group(1).strip()
            # Trim a trailing "to be visible" / "to be enabled" tail from the
            # call-log "waiting for ..." line.
            sel = re.split(r"\s+to be\s+", sel)[0].strip()
            if sel:
                return sel[:300]
    return None


# --- code-snippet stripping --------------------------------------------------

# @playwright/test renders the failing source with a line-number gutter:
#   > 41 |   await page.locator('#x').click();
#     42 |   await expect(...).toBeVisible();
# Every such line matches this. Stripping them before keyword rules run stops
# the source code (e.g. a stray `expect(...)`) from fooling the classifier.
_GUTTER_RE = re.compile(r"^\s*>?\s*\d+\s*\|")


def strip_code_snippet(blob: str) -> str:
    """Drop @playwright/test rendered source-code lines (line-number gutter)
    so keyword rules match the real error text, not the script source."""
    if not blob:
        return blob
    return "\n".join(ln for ln in blob.splitlines() if not _GUTTER_RE.match(ln))


# --- richer field extraction -------------------------------------------------

# Playwright embeds an identical "<api>: <reason>" block in every language.
_ACTION_RE = re.compile(
    r"\b((?:locator|page|frame|mouse|keyboard|elementHandle|"
    r"browserContext|browser|request|response|apiRequestContext)"
    r"\.[a-zA-Z_]+)\b"
)
_ASSERT_LINE_RE = re.compile(r"(?mi)^\s*(error:\s*)?expect\(")
_MATCH_COUNT_RE = re.compile(r"resolved to (\d+) element", re.IGNORECASE)
_NET_ERROR_RE = re.compile(r"net::(ERR_[A-Z_]+)")
_URL_RES = (
    re.compile(r'navigating to "([^"]+)"'),
    re.compile(r"(https?://[^\s\"')]+)"),
)


def extract_action(message: str) -> Optional[str]:
    """The Playwright API that failed, e.g. `locator.click`, `page.goto`."""
    if not message:
        return None
    m = _ACTION_RE.search(message)
    if m:
        return m.group(1)
    if _ASSERT_LINE_RE.search(message):
        return "expect"
    return None


def extract_actionability(message: str) -> Optional[str]:
    """Why the element could not be acted on, e.g. `not visible`."""
    if not message:
        return None
    m = _ACTIONABILITY_RE.search(message.lower())
    return m.group(0) if m else None


def extract_element_state(message: str) -> Optional[str]:
    """`found-but-hidden` | `found` | `never-appeared` — or None when unknown."""
    if not message:
        return None
    low = message.lower()
    if "resolved to" in low:
        hidden = (
            bool(_ACTIONABILITY_RE.search(low))
            or "hidden" in low
            or "display: none" in low
            or "display:none" in low
        )
        return "found-but-hidden" if hidden else "found"
    if "waiting for" in low and "timeout" in low:
        return "never-appeared"
    return None


def extract_match_count(message: str) -> Optional[int]:
    """Strict-mode: how many elements the selector matched."""
    if not message:
        return None
    m = _MATCH_COUNT_RE.search(message)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def extract_url(message: str) -> Optional[str]:
    if not message:
        return None
    for re_ in _URL_RES:
        m = re_.search(message)
        if m:
            return m.group(1)[:500]
    return None


def extract_net_error(message: str) -> Optional[str]:
    if not message:
        return None
    m = _NET_ERROR_RE.search(message)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Ordered rule list — first match wins. See plan section 2.2.
# Each rule: (category, predicate(rt, msg)) where rt is the lowercased raw
# type and msg is the raw message (original case).
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")
_LOCATOR_PREFIX_RE = re.compile(
    r"\b(locator|get_by_\w+|getBy[A-Z]\w*)[.(]"
    r"|\.(click|fill|check|uncheck|hover|select_option|selectOption|"
    r"press|type|set_input_files|setInputFiles|tap|dblclick)\b"
)
_ACTIONABILITY_RE = re.compile(
    r"not visible|not enabled|not stable|not editable|not checked"
    r"|intercepts pointer events|outside of the viewport|element is not attached"
)


def _is_script_missing(rt: str, msg: str) -> bool:
    return (
        "filenotfounderror" in rt
        or "script file not found" in msg.lower()
        or "no such file" in msg.lower()
    )


def _is_setup_error(rt: str, msg: str) -> bool:
    low = msg.lower()
    return (
        "executable doesn't exist" in low
        or "playwright install" in low
        or "qaclan setup" in low
        or "runtime venv" in low
        or "is broken. re-run" in low
        or "not installed correctly" in low
        or "browsertype.launch" in low and "executable" in low
    )


def _is_config_error(rt: str, msg: str) -> bool:
    low = msg.lower()
    return (
        bool(_PLACEHOLDER_RE.search(msg))
        or "missing env var" in low
        or "var_keys" in low
        or "unresolved placeholder" in low
    )


def _is_browser_crashed(rt: str, msg: str) -> bool:
    low = msg.lower()
    return (
        "targetclosederror" in rt
        or "has been closed" in low
        or "browser has been closed" in low
        or "target page, context or browser" in low
        or "worker process" in low and "crash" in low
    )


def _is_assertion(rt: str, msg: str) -> bool:
    low = msg.lower()
    if "assertionerror" in rt:
        return True
    # Match `expect(` only at the start of a line — a real Playwright
    # assertion message ("Error: expect(locator).toBeVisible() failed").
    # A loose `"expect(" in msg` also matches rendered source code.
    if _ASSERT_LINE_RE.search(msg):
        return True
    return (
        "expected to be" in low
        or "expected pattern" in low
        or "expected string" in low
    )


def _is_navigation(rt: str, msg: str) -> bool:
    low = msg.lower()
    return (
        "page.goto" in low
        or "net::err" in low
        or "execution context was destroyed" in low
    )


def _is_element_not_found(rt: str, msg: str) -> bool:
    low = msg.lower()
    if "strict mode violation" in low:
        return True
    if _ACTIONABILITY_RE.search(low):
        return True
    # A locator-call timeout: locator prefix present AND a timeout signature.
    if _LOCATOR_PREFIX_RE.search(msg) and ("timeout" in low or "timeouterror" in rt):
        return True
    return False


def _is_timeout(rt: str, msg: str) -> bool:
    low = msg.lower()
    return (
        "timeouterror" in rt
        or "test timeout of" in low
        or "timeout" in low and "exceeded" in low
        or "timed out" in low
    )


def _is_script_error(rt: str, msg: str) -> bool:
    low = msg.lower()
    if any(t in rt for t in (
        "syntaxerror", "importerror", "modulenotfounderror",
        "indentationerror", "nameerror", "referenceerror",
    )):
        return True
    return (
        "cannot find module" in low
        or "is not defined" in low
        or "syntaxerror" in low
        or "unexpected token" in low
        or "compilation error" in low
    )


# ---------------------------------------------------------------------------
# Dynamic message builders — interpolate extracted fields into plain
# sentences. When a field is missing the builder degrades to the frozen
# CATEGORIES default. See error-reporting-plan §6.4.
# ---------------------------------------------------------------------------

# Plain-language verb for a Playwright API method.
_ACTION_VERBS = {
    "click": "click", "dblclick": "double-click", "fill": "fill in",
    "type": "type into", "press": "press a key on", "check": "check",
    "uncheck": "uncheck", "hover": "hover over", "tap": "tap",
    "focus": "focus", "selectOption": "select an option in",
    "select_option": "select an option in", "setInputFiles": "upload a file to",
    "set_input_files": "upload a file to", "goto": "open",
    "waitForSelector": "wait for", "wait_for_selector": "wait for",
}

_NET_ERROR_TEXT = {
    "ERR_NAME_NOT_RESOLVED": "the website address could not be found",
    "ERR_CONNECTION_REFUSED": "the server refused the connection",
    "ERR_CONNECTION_TIMED_OUT": "the server did not respond in time",
    "ERR_INTERNET_DISCONNECTED": "there is no internet connection",
    "ERR_CONNECTION_RESET": "the connection was reset by the server",
    "ERR_ABORTED": "the request was aborted",
    "ERR_SSL_PROTOCOL_ERROR": "the secure connection could not be established",
    "ERR_CERT_DATE_INVALID": "the site's security certificate is invalid",
}


def _humanize_action(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    method = action.split(".")[-1]
    return _ACTION_VERBS.get(method, method)


def _humanize_net_error(net: Optional[str]) -> str:
    if not net:
        return "the connection failed"
    return _NET_ERROR_TEXT.get(net, net.replace("ERR_", "").replace("_", " ").lower())


def _fmt_timeout(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    s = ms / 1000.0
    return f"{int(s)}s" if s == int(s) else f"{s:g}s"


def describe(category: str, fields: dict, meta: dict):
    """Return (title, message, next_step). Interpolate extracted fields into
    plain sentences; fall back to the frozen CATEGORIES strings when fields
    are absent. One sentence serves both audiences — plain words, exact
    selector / action / timeout inline."""
    title = meta["title"]
    message = meta["message"]
    next_step = meta["next_step"]

    sel = fields.get("selector")
    to = _fmt_timeout(fields.get("timeout_ms"))
    verb = _humanize_action(fields.get("action"))
    state = fields.get("element_state")
    count = fields.get("match_count")
    actionability = fields.get("actionability")
    url = fields.get("url")
    net = fields.get("net_error")

    if category == "ELEMENT_NOT_FOUND":
        if count and count > 1 and sel:
            title = "Selector matched multiple elements"
            message = (f"The selector {sel} matched {count} elements but the "
                       f"script needs exactly one.")
            next_step = ("Make the selector specific to a single element, "
                         "then re-record the script.")
        elif state == "found-but-hidden" and sel:
            act = verb or "interact with"
            waited = f" but gave up after {to}" if to else ""
            why = actionability or "hidden"
            title = "Element found but not usable"
            message = (f"The script tried to {act} {sel}{waited}. The element "
                       f"exists on the page but stayed {why} — so the {act} "
                       f"never happened.")
            next_step = ("A step that opens or reveals it may be missing. If "
                         "it should already be visible, the page changed — "
                         "re-record the script.")
        elif sel:
            looked = f"waited {to} for" if to else "looked for"
            message = (f"The script {looked} {sel} but it never appeared "
                       f"on the page.")

    elif category == "TIMEOUT":
        if to:
            message = (f"The script ran longer than its {to} limit and "
                       f"was stopped.")

    elif category == "NAVIGATION_FAILED":
        if net:
            where = url or "the page"
            message = f"{where} could not be opened — {_humanize_net_error(net)}."
        elif url:
            message = f"{url} could not be opened."

    elif category == "ASSERTION_FAILED":
        if sel:
            message = (f"A check on {sel} did not pass — the page was not in "
                       f"the expected state.")

    return title, message, next_step


# ---------------------------------------------------------------------------
# Main classification
# ---------------------------------------------------------------------------

def classify(
    *,
    raw_type: Optional[str] = None,
    raw_message: Optional[str] = None,
    stderr: Optional[str] = None,
    stdout: Optional[str] = None,
    kind: str = "subprocess",
    returncode: Optional[int] = None,
    has_network_failures: bool = False,
) -> dict:
    """Classify a failure into a structured detail dict.

    kind: "subprocess" (script exited non-zero) | "timeout" (300s kill) |
          "internal" (runner-side exception).

    raw_type / raw_message come from the harness `error` object when present;
    otherwise the classifier falls back to the stderr/stdout blob.

    Returns a dict: category, title, message, next_step, severity, raw_type,
    selector, timeout_ms.
    """
    rt = (raw_type or "").lower()
    # Build the message to pattern-match against: prefer the harness message,
    # else the raw blob. The blob carries @playwright/test rendered source
    # code — strip the line-number gutter so keyword rules see only the real
    # error text. See error-reporting-plan §6.2.
    msg = raw_message or ""
    if not msg:
        blob = "\n".join(p for p in (stderr or "", stdout or "") if p).strip()
        msg = strip_code_snippet(blob)

    category = None

    if kind == "internal":
        # A runner-side exception. Still let environment rules win — a
        # FileNotFoundError for the script is a SCRIPT_MISSING, not internal.
        if _is_script_missing(rt, msg):
            category = "SCRIPT_MISSING"
        elif _is_config_error(rt, msg):
            category = "CONFIG_ERROR"
        elif _is_setup_error(rt, msg):
            category = "SETUP_ERROR"
        else:
            category = "RUNTIME_ERROR"
    elif kind == "timeout":
        # The 300s PER_SCRIPT_TIMEOUT_SEC subprocess kill.
        category = "TIMEOUT"
    else:
        # Ordered rule list — first match wins.
        rules = [
            ("SCRIPT_MISSING", _is_script_missing),
            ("SETUP_ERROR", _is_setup_error),
            ("CONFIG_ERROR", _is_config_error),
            ("BROWSER_CRASHED", _is_browser_crashed),
            ("ASSERTION_FAILED", _is_assertion),
            ("NAVIGATION_FAILED", _is_navigation),
            ("ELEMENT_NOT_FOUND", _is_element_not_found),
            ("TIMEOUT", _is_timeout),
            ("SCRIPT_ERROR", _is_script_error),
        ]
        for cat, pred in rules:
            if pred(rt, msg):
                category = cat
                break
        if category is None:
            if has_network_failures and not msg.strip():
                category = "NETWORK_ERROR"
            else:
                category = "UNKNOWN"

    meta = CATEGORIES[category]
    fields = {
        "action": extract_action(msg),
        "selector": extract_selector(msg),
        "timeout_ms": extract_timeout_ms(msg),
        "actionability": extract_actionability(msg),
        "element_state": extract_element_state(msg),
        "match_count": extract_match_count(msg),
        "url": extract_url(msg),
        "net_error": extract_net_error(msg),
    }
    title, message, next_step = describe(category, fields, meta)
    return {
        "category": category,
        "title": title,
        "message": message,
        "next_step": next_step,
        "severity": meta["severity"],
        "raw_type": raw_type or None,
        "selector": fields["selector"],
        "timeout_ms": fields["timeout_ms"],
        "action": fields["action"],
        "actionability": fields["actionability"],
        "element_state": fields["element_state"],
        "match_count": fields["match_count"],
        "url": fields["url"],
        "net_error": fields["net_error"],
    }
