"""Python Playwright script strategy.

Produces a self-contained harness file from Playwright codegen output. The
harness reads configuration from QACLAN_* env vars and writes artifacts
(console errors, network failures) to a JSON file at exit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli.runtime import is_frozen_binary
from cli import runtime_setup
from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
from cli.script_strategies.base import ScriptStrategy

logger = logging.getLogger("qaclan.script_strategies.python")

_BEGIN_MARKER = "# BEGIN ACTIONS"
_END_MARKER = "# END ACTIONS"


_HARNESS_TEMPLATE = '''\
# Ensure the correct Python encoding for all file operations, regardless of
# the user's locale settings. Playwright scripts often include non-ASCII text,
# and we want to avoid encoding issues when writing artifacts or screenshots.
# -*- coding: utf-8 -*-
# QAClan Playwright harness - do not edit the scaffolding.
# Only edit the lines between the BEGIN / END action markers.
import json
import os
import sys
import time
import traceback

from playwright.sync_api import sync_playwright, expect

_BROWSER = os.environ.get("QACLAN_BROWSER", "chromium")
_HEADLESS = os.environ.get("QACLAN_HEADLESS", "1") == "1"
_VIEWPORT = os.environ.get("QACLAN_VIEWPORT", "")
_STATE = os.environ.get("QACLAN_STORAGE_STATE")
_ARTIFACTS = os.environ.get("QACLAN_ARTIFACTS_PATH")
_SCREENSHOT = os.environ.get("QACLAN_SCREENSHOT_PATH")

try:
    _EXPECT_TIMEOUT = int(os.environ.get("QACLAN_EXPECT_TIMEOUT", "15000"))
except ValueError:
    _EXPECT_TIMEOUT = 15000

try:
    _ACTION_TIMEOUT = int(os.environ.get("QACLAN_ACTION_TIMEOUT", "30000"))
except ValueError:
    _ACTION_TIMEOUT = 30000

_console_errors = []
_network_failures = []


def _context_opts():
    opts = {}
    if _STATE and os.path.exists(_STATE):
        opts["storage_state"] = _STATE
    if _VIEWPORT:
        try:
            w, h = _VIEWPORT.split("x")
            opts["viewport"] = {"width": int(w), "height": int(h)}
        except ValueError:
            pass
    return opts


def _write_artifacts(error=None):
    if not _ARTIFACTS:
        return
    try:
        payload = {
            "console_errors": _console_errors,
            "network_failures": _network_failures,
            "captured_requests": _captured_requests,
        }
        # Structured error — raw exception fields the runner's classifier
        # keys on. See docs/error-reporting-plan.md (section 2.1).
        if error is not None:
            payload["error"] = error
        with open(_ARTIFACTS, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _on_console(msg):
    if msg.type in ("error", "warning"):
        _console_errors.append({"type": msg.type, "text": msg.text})


def _on_pageerror(err):
    _console_errors.append({"type": "pageerror", "text": str(err)})


def _on_requestfailed(req):
    _network_failures.append({
        "url": req.url,
        "method": req.method,
        "failure": str(req.failure) if req.failure else None,
    })


# --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
# Counts in-flight XHR/fetch requests so _wait_for_network_settle can block
# until a slow-loading page (table fed by an XHR) finishes.
_in_flight = 0

# --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
# Records XHR/fetch traffic as a passive side effect of the run so it can be
# saved as API requests afterward. Never fails the run — every capture step
# is wrapped in a swallowed try/except. Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1,
# checked once at startup so _capture_request() no-ops before touching anything
# when the run didn't ask for capture.
_CAPTURE_ENABLED = os.environ.get("QACLAN_CAPTURE_REQUESTS") == "1"
_captured_requests = []
_capture_starts = {}
_CAPTURE_CAP = 200
_CAPTURE_BODY_CAP_BYTES = 200_000
_CAPTURE_ALLOWED_TYPES = set({CAPTURE_ALLOWED_TYPES_JSON})


def _truncate_body(text):
    if text is None:
        return None
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= _CAPTURE_BODY_CAP_BYTES:
        return text
    return encoded[:_CAPTURE_BODY_CAP_BYTES].decode("utf-8", errors="ignore")


def _capture_request(req):
    if not _CAPTURE_ENABLED:
        return
    if req.resource_type not in _CAPTURE_ALLOWED_TYPES:
        return
    start = _capture_starts.pop(id(req), None)
    if len(_captured_requests) >= _CAPTURE_CAP:
        return
    try:
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        resp = None
        try:
            resp = req.response()
        except Exception:
            resp = None
        entry = {
            "method": req.method,
            "url": req.url,
            "request_headers": dict(req.headers),
            "request_body": _truncate_body(req.post_data),
            "status_code": resp.status if resp else None,
            "response_headers": dict(resp.headers) if resp else {},
            "response_body": None,
            "duration_ms": duration_ms,
        }
        if resp is not None:
            try:
                entry["response_body"] = _truncate_body(resp.text())
            except Exception:
                pass
        _captured_requests.append(entry)
    except Exception:
        pass


def _track_network(page):
    def _on_request(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight += 1
        if _CAPTURE_ENABLED and req.resource_type in _CAPTURE_ALLOWED_TYPES:
            _capture_starts[id(req)] = time.monotonic()

    def _on_done(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight = max(0, _in_flight - 1)
        _capture_request(req)

    page.on("request", _on_request)
    page.on("requestfinished", _on_done)
    page.on("requestfailed", _on_done)


def _wait_for_network_settle(page, grace_ms=700, quiet_ms=400, timeout_ms=15000):
    # Wait until in-flight XHR/fetch stays 0 for `quiet_ms`, capped at
    # `timeout_ms`. Two-step grace probe: fast 150ms check catches the common
    # case; a second probe at `grace_ms` (default 700ms) catches debounced
    # inputs whose XHR has not fired yet at 150ms.
    page.wait_for_timeout(150)
    if _in_flight == 0:
        extra = max(0, grace_ms - 150)
        if extra > 0:
            page.wait_for_timeout(extra)
        if _in_flight == 0:
            return
    deadline = time.monotonic() + timeout_ms / 1000.0
    quiet_since = None
    while time.monotonic() < deadline:
        if _in_flight == 0:
            if quiet_since is None:
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_ms / 1000.0:
                return
        else:
            quiet_since = None
        page.wait_for_timeout(50)
    # Soft cap: do not raise — let the next real action surface the failure.


def run():
    with sync_playwright() as playwright:
        browser = getattr(playwright, _BROWSER).launch(headless=_HEADLESS)
        context = browser.new_context(**_context_opts())
        page = context.new_page()
        page.set_default_timeout(_ACTION_TIMEOUT)
        expect.set_options(timeout=_EXPECT_TIMEOUT)
        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)
        page.on("requestfailed", _on_requestfailed)
        _track_network(page)
        try:
{ACTIONS}
        except Exception:
            if _SCREENSHOT:
                try:
                    page.screenshot(path=_SCREENSHOT)
                except Exception:
                    pass
            raise
        finally:
            if _STATE:
                # Give a trailing auth request (e.g. a cookie/token finalized
                # just after the page renders) a short window to land before
                # snapshotting, so the next script in the suite doesn't inherit
                # a partial session.
                try:
                    _wait_for_network_settle(page, grace_ms=200, quiet_ms=300, timeout_ms=3000)
                except Exception:
                    pass
                try:
                    # Merge, don't overwrite: state.json also carries qaclan_vars
                    # (API items' extracted variables within this same suite run).
                    # A plain storage_state(path=_STATE) write replaces the whole
                    # file with just cookies/origins, silently dropping those vars.
                    _new_state = context.storage_state()
                    try:
                        with open(_STATE, "r", encoding="utf-8") as _f:
                            _existing_state = json.load(_f)
                    except Exception:
                        _existing_state = {}
                    if isinstance(_existing_state, dict) and _existing_state.get("qaclan_vars"):
                        _new_state["qaclan_vars"] = _existing_state["qaclan_vars"]
                    with open(_STATE, "w", encoding="utf-8") as _f:
                        json.dump(_new_state, _f)
                except Exception:
                    pass
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    exit_code = 0
    _error = None
    try:
        run()
    except Exception as exc:
        traceback.print_exc()
        exit_code = 1
        _error = {"raw_type": type(exc).__name__, "raw_message": str(exc)}
    finally:
        _write_artifacts(_error)
    sys.exit(exit_code)
'''

class PythonStrategy(ScriptStrategy):
    language = "python"
    codegen_target = "python"
    file_extension = ".py"

    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)

    def settle_call_snippet(self) -> str:
        return "_wait_for_network_settle(page)"

    def settle_marker(self) -> str:
        return "_wait_for_network_settle"

    def typed_fill_marker(self) -> str:
        return "press_sequentially"

    def typed_fill_call_template(self) -> str:
        return ".press_sequentially({value}, delay=50)"

    def rewrite_url_template(self, content: str, base_value: str, key_name: str) -> str:
        if not base_value or not key_name:
            return content
        base = base_value.rstrip("/")
        pattern = re.compile(
            r'page\.goto\(\s*["\']' + re.escape(base) + r'(?P<path>[^"\']*)["\']'
            r'(?P<rest>\s*(?:,[^)]*)?)\)'
        )

        def _replace(m):
            path = m.group("path")
            rest = m.group("rest") or ""
            return f'page.goto("{{{{{key_name}}}}}{path}"{rest})'

        return pattern.sub(_replace, content)

    def build_run_command(self, script_path: str) -> List[str]:
        py = self._resolve_python_executable()
        return [py, script_path]

    def validate_runtime(self) -> None:
        py = self._resolve_python_executable()
        # Validate when:
        #  - frozen binary (system Python — must verify playwright importable), OR
        #  - resolved python is the runtime venv (catch broken venv early in dev too).
        # Skip only in plain dev mode where py == sys.executable — assume the
        # developer's own venv is sane.
        runtime_py = runtime_setup.resolve_venv_python()
        is_runtime_py = runtime_py is not None and str(runtime_py) == py
        if not (is_frozen_binary() or is_runtime_py):
            return
        result = subprocess.run(
            [py, "-c", "import playwright"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if is_runtime_py:
                raise RuntimeError(
                    f"Runtime venv at {py} is missing the 'playwright' package. "
                    "Re-run: qaclan setup --runtime-only --force\n"
                    f"Underlying error: {stderr}"
                )
            raise RuntimeError(
                f"The 'playwright' Python package is not importable from {py}. "
                "Run: qaclan setup --runtime-only "
                "(or install for the SAME interpreter):\n"
                "  Windows:  py -m pip install playwright==1.58.0\n"
                "  Linux:    python3 -m pip install playwright==1.58.0\n"
                f"Underlying error: {stderr}"
            )

    # ---- internals ----

    def _resolve_python_executable(self) -> str:
        # Prefer isolated runtime venv first.
        venv_py = runtime_setup.resolve_venv_python()
        if venv_py is not None:
            return str(venv_py)
        if is_frozen_binary():
            runtime_setup.emit_deprecation_warning()
            # Windows: prefer `py` launcher first. Reasons:
            #   1. Many Windows installs leave the real `python.exe` off PATH
            #      (installer's "Add to PATH" checkbox is opt-in).
            #   2. Microsoft ships a stub at
            #      %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe that IS on
            #      PATH by default. The stub redirects to the Store and has
            #      no site-packages, so `import playwright` always fails
            #      even when the user installed playwright via `py -m pip`.
            # Linux/macOS: `py` does not exist; fall through to python3/python.
            if sys.platform == "win32":
                candidates = ["py", "python3", "python"]
            else:
                candidates = ["python3", "python"]
            for name in candidates:
                resolved = shutil.which(name)
                if resolved and not self._is_windows_store_stub(resolved):
                    return resolved
            raise RuntimeError(
                "Python 3 is required to run Python scripts in binary mode. "
                "Install Python 3 (https://www.python.org/downloads/) and ensure "
                "it's on PATH, or that the `py` launcher is available on Windows."
            )
        return sys.executable

    @staticmethod
    def _is_windows_store_stub(path: str) -> bool:
        # The Microsoft Store python.exe shim lives under
        # %LOCALAPPDATA%\Microsoft\WindowsApps. It is a zero-byte
        # AppExecutionAlias that opens the Store when run from a child
        # process — never the real interpreter.
        if sys.platform != "win32":
            return False
        norm = os.path.normcase(os.path.normpath(path))
        return os.path.join("microsoft", "windowsapps") in norm

    def extract_actions_freeform(self, raw: str):
        """Pull the action body out of a hand-written Python Playwright script.

        Heuristics, in order:
          1. find ``page = ...new_page()`` (or ``page = await ... new_page()``
             — sync_playwright doesn't await but be permissive);
          2. capture lines until ``browser.close()`` / ``page.close()`` /
             ``playwright.stop()`` / end of enclosing ``with`` block;
          3. dedent + expand tabs.
        """
        from cli.script_strategies._shared import ImportWarning
        warnings = []

        text = raw.expandtabs(4)
        lines = text.splitlines()

        # Accept both sync (`page = context.new_page()`) and async
        # (`page = await context.new_page()`) wrappers.
        new_page_re = re.compile(r'^\s*page\s*=\s*(?:await\s+)?[^=].*new_page\s*\(')
        # Stop at any teardown-shaped close, including renamed variables and
        # `playwright.stop()`. Action body should not contain these.
        close_re = re.compile(
            r'^\s*(?:await\s+)?(?:[A-Za-z_][\w]*\.close\s*\(|playwright\.stop\s*\()'
        )

        start_idx = None
        for i, line in enumerate(lines):
            if new_page_re.match(line):
                start_idx = i + 1
                break
        if start_idx is None:
            return "", [ImportWarning(
                severity="error", code="extraction_failed",
                message="No `page = ...new_page()` line found. Cannot locate action body.",
            )]

        captured = []
        for j in range(start_idx, len(lines)):
            line = lines[j]
            if close_re.match(line):
                break
            captured.append(line)

        body = "\n".join(captured).rstrip()
        if not body.strip():
            return "", [ImportWarning(
                severity="error", code="extraction_failed",
                message="Action body between new_page() and close() is empty.",
            )]

        # Dedent to smallest common indent so it can be re-rendered.
        body_lines = body.splitlines()
        indents = [len(l) - len(l.lstrip()) for l in body_lines if l.strip()]
        base = min(indents) if indents else 0
        dedented = "\n".join(l[base:] if len(l) >= base else l for l in body_lines)

        # Surface QAClan scaffold-name collisions inside the action body.
        for name in (
            "_BROWSER", "_HEADLESS", "_VIEWPORT", "_STATE", "_ARTIFACTS",
            "_SCREENSHOT", "_console_errors", "_network_failures", "_context_opts",
            "_write_artifacts", "_on_console", "_on_pageerror", "_on_requestfailed",
            "_in_flight", "_captured_requests", "_capture_starts", "_capture_request",
            "_CAPTURE_ENABLED", "_CAPTURE_CAP", "_CAPTURE_BODY_CAP_BYTES",
            "_CAPTURE_ALLOWED_TYPES", "_truncate_body",
        ):
            if re.search(r'^\s*' + re.escape(name) + r'\s*=', dedented, re.MULTILINE):
                warnings.append(ImportWarning(
                    severity="error", code="qaclan_var_collision",
                    message=f"Action body redefines QAClan scaffold variable `{name}`.",
                ))

        if re.search(r'\bbrowser\.close\s*\(|\bplaywright\.stop\s*\(', dedented):
            warnings.append(ImportWarning(
                severity="warn", code="manual_browser_lifecycle",
                message="Action body calls browser.close()/playwright.stop() — harness owns lifecycle.",
            ))
        if re.search(r'storage_state\s*=', dedented):
            warnings.append(ImportWarning(
                severity="warn", code="storage_state_override",
                message="Action body sets storage_state — overrides QAClan shared state.",
            ))
        if re.search(r'\bpage\.pause\s*\(', dedented):
            warnings.append(ImportWarning(
                severity="warn", code="pause_call_present",
                message="Action body contains page.pause() — headless runs will hang.",
            ))

        return dedented, warnings

    def _extract_actions(self, raw: str) -> str:
        """Pull the action body out of Playwright codegen ougtput.

        Codegen emits a ``def run(playwright)`` with ``context.new_page()`` and
        ``page.close()`` as bookends around the recorded interactions. We grab
        the lines between them and re-indent them against the first captured
        line so they can be re-embedded under our own indentation.
        """
        lines = raw.splitlines()
        captured = []
        capturing = False
        base_indent = None
        for line in lines:
            stripped = line.strip()
            if not capturing and stripped.startswith("page = context.new_page()"):
                capturing = True
                continue
            if capturing and stripped.startswith("page.close()"):
                break
            if not capturing:
                continue
            if not stripped or stripped.startswith("# ---"):
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
            relative = max(0, indent - base_indent)
            captured.append(" " * relative + stripped)
        return "\n".join(captured)

    def _patch_goto_wait(self, actions: str) -> str:
        """Add ``wait_until="domcontentloaded"`` to bare ``page.goto(url)``
        calls. SPAs rarely reach networkidle, and codegen's default wait tends
        to stall on them."""
        return re.sub(
            r'page\.goto\(\s*(["\'][^"\']+["\'])\s*\)',
            r'page.goto(\1, wait_until="domcontentloaded")',
            actions,
        )

    _UPLOAD_CLICK_RE = re.compile(
        r'^(?P<indent>[ \t]*)(?P<loc>page\.[^\n]*?)\.click\(\)[ \t]*\n'
        r'(?:(?P=indent)_wait_for_network_settle\(page\)[ \t]*\n)?'
        r'(?=(?P=indent)(?P=loc)\.set_input_files\()',
        re.MULTILINE,
    )

    def _strip_upload_click(self, actions: str) -> str:
        """Drop a codegen-recorded ``.click()`` that immediately precedes a
        ``.set_input_files()`` call on the identical locator.

        Codegen's own recording session intercepts the native OS file-picker
        that click triggers on a real ``<input type=file>``, but that
        interception isn't part of the exported script. Replayed headed, the
        click opens a real unhandled OS dialog and hangs the page.
        ``set_input_files()`` alone sets the file via CDP — no click needed."""
        return self._UPLOAD_CLICK_RE.sub("", actions)

    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            # Harness still needs a body — emit a `pass` so the file is valid.
            body = "            pass"
        else:
            body = "\n".join("            " + line if line else "" for line in actions.splitlines())
        body = f"{' ' * 12}{_BEGIN_MARKER}\n{body}\n{' ' * 12}{_END_MARKER}"
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
