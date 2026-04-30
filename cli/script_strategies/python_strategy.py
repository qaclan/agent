"""Python Playwright script strategy.

Produces a self-contained harness file from Playwright codegen output. The
harness reads configuration from QACLAN_* env vars and writes artifacts
(console errors, network failures) to a JSON file at exit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import List

from cli.runtime import is_frozen_binary
from cli.script_strategies.base import ScriptStrategy


_BEGIN_MARKER = "# BEGIN ACTIONS"
_END_MARKER = "# END ACTIONS"


_HARNESS_TEMPLATE = '''\
# QAClan Playwright harness — do not edit the scaffolding.
# Only edit the lines between the BEGIN / END action markers.
import json
import os
import sys
import traceback

from playwright.sync_api import sync_playwright, expect

_BROWSER = os.environ.get("QACLAN_BROWSER", "chromium")
_HEADLESS = os.environ.get("QACLAN_HEADLESS", "1") == "1"
_VIEWPORT = os.environ.get("QACLAN_VIEWPORT", "")
_STATE = os.environ.get("QACLAN_STORAGE_STATE")
_ARTIFACTS = os.environ.get("QACLAN_ARTIFACTS_PATH")
_SCREENSHOT = os.environ.get("QACLAN_SCREENSHOT_PATH")

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


def _write_artifacts():
    if not _ARTIFACTS:
        return
    try:
        with open(_ARTIFACTS, "w") as f:
            json.dump({
                "console_errors": _console_errors,
                "network_failures": _network_failures,
            }, f)
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


def run():
    with sync_playwright() as playwright:
        browser = getattr(playwright, _BROWSER).launch(headless=_HEADLESS)
        context = browser.new_context(**_context_opts())
        page = context.new_page()
        page.set_default_timeout(30000)
        expect.set_options(timeout={expect_timeout})
        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)
        page.on("requestfailed", _on_requestfailed)
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
                try:
                    context.storage_state(path=_STATE)
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
    try:
        run()
    except Exception:
        traceback.print_exc()
        exit_code = 1
    finally:
        _write_artifacts()
    sys.exit(exit_code)
'''.replace(
    "{expect_timeout}",
    str(ScriptStrategy.expect_timeout)
)

class PythonStrategy(ScriptStrategy):
    language = "python"
    codegen_target = "python"
    file_extension = ".py"

    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        return self._render_harness(actions)

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
        if is_frozen_binary():
            result = subprocess.run(
                [py, "-c", "import playwright"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "The 'playwright' Python package is not installed for the system Python. "
                    "Install it: pip install playwright==1.58.0\n"
                    "Then install browser binaries: playwright install"
                )

    # ---- internals ----

    def _resolve_python_executable(self) -> str:
        if is_frozen_binary():
            py = shutil.which("python3") or shutil.which("python") or shutil.which("py")
            if not py:
                raise RuntimeError(
                    "Python 3 is required to run Python scripts in binary mode. "
                    "Install Python 3 and ensure it's on PATH."
                )
            return py
        return sys.executable

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

    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            # Harness still needs a body — emit a `pass` so the file is valid.
            body = "            pass"
        else:
            body = "\n".join("            " + line if line else "" for line in actions.splitlines())
        body = f"{' ' * 12}{_BEGIN_MARKER}\n{body}\n{' ' * 12}{_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
