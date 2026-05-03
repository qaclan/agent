"""JavaScript Playwright script strategy.

Produces a self-contained harness file from Playwright codegen output. The
harness reads configuration from QACLAN_* env vars and writes artifacts
(console errors, network failures) to a JSON file at exit.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli import runtime_setup
from cli.script_strategies.base import ScriptStrategy

logger = logging.getLogger("qaclan.script_strategies.javascript")


_BEGIN_MARKER = "// BEGIN ACTIONS"
_END_MARKER = "// END ACTIONS"


_HARNESS_TEMPLATE = """\
// QAClan Playwright harness - do not edit the scaffolding.
// Only edit the lines between the BEGIN / END action markers.
'use strict';
const { chromium, firefox, webkit } = require('playwright');
const fs = require('fs');

const _BROWSER = process.env.QACLAN_BROWSER || 'chromium';
const _HEADLESS = process.env.QACLAN_HEADLESS !== '0';
const _VIEWPORT = process.env.QACLAN_VIEWPORT || '';
const _STATE = process.env.QACLAN_STORAGE_STATE || '';
const _ARTIFACTS = process.env.QACLAN_ARTIFACTS_PATH || '';
const _SCREENSHOT = process.env.QACLAN_SCREENSHOT_PATH || '';

const _consoleErrors = [];
const _networkFailures = [];

function _contextOpts() {
  const opts = {};
  if (_STATE && fs.existsSync(_STATE)) {
    opts.storageState = _STATE;
  }
  if (_VIEWPORT) {
    const parts = _VIEWPORT.split('x');
    if (parts.length === 2) {
      const w = parseInt(parts[0], 10);
      const h = parseInt(parts[1], 10);
      if (!isNaN(w) && !isNaN(h)) opts.viewport = { width: w, height: h };
    }
  }
  return opts;
}

function _writeArtifacts() {
  if (!_ARTIFACTS) return;
  try {
    fs.writeFileSync(_ARTIFACTS, JSON.stringify({
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
    }));
  } catch (_) {}
}

async function run() {
  const _browsers = { chromium, firefox, webkit };
  const _browserType = _browsers[_BROWSER] || chromium;
  const browser = await _browserType.launch({ headless: _HEADLESS });
  const context = await browser.newContext(_contextOpts());
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      _consoleErrors.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on('pageerror', err => {
    _consoleErrors.push({ type: 'pageerror', text: String(err) });
  });
  page.on('requestfailed', req => {
    _networkFailures.push({
      url: req.url(),
      method: req.method(),
      failure: req.failure() ? req.failure().errorText : null,
    });
  });
  try {
{ACTIONS}
  } catch (err) {
    if (_SCREENSHOT) {
      try { await page.screenshot({ path: _SCREENSHOT }); } catch (_) {}
    }
    throw err;
  } finally {
    if (_STATE) {
      try { await context.storageState({ path: _STATE }); } catch (_) {}
    }
    try { await page.close(); } catch (_) {}
    try { await context.close(); } catch (_) {}
    try { await browser.close(); } catch (_) {}
  }
}

run().then(() => {
  _writeArtifacts();
  process.exit(0);
}).catch(err => {
  console.error(err);
  _writeArtifacts();
  process.exit(1);
});
"""


_QACLAN_JS_NAMES = (
    "_BROWSER", "_HEADLESS", "_VIEWPORT", "_STATE", "_ARTIFACTS",
    "_SCREENSHOT", "_consoleErrors", "_networkFailures", "_contextOpts",
    "_writeArtifacts", "_browsers", "_browserType",
)


def _dedent_block(body: str) -> str:
    lines = body.splitlines()
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    base = min(indents) if indents else 0
    return "\n".join(l[base:] if len(l) >= base else l for l in lines)


def _peel_js_lifecycle(text: str):
    """Return ``(actions, warnings)`` after stripping any browser/context
    lifecycle wrapper around the action body.

    Handles three shapes:
      1. ``newPage()`` … ``await context.close()/browser.close()`` (incl. inside
         a test() callback that manually launches its own browser);
      2. async IIFE wrapper — terminates at ``})();``;
      3. no lifecycle at all — return the input unchanged with a warning.
    """
    from cli.script_strategies._shared import ImportWarning
    warnings = []
    lines = text.splitlines()

    new_page_re = re.compile(r'newPage\s*\(\s*\)')
    # Match any teardown-shaped close call regardless of variable name (users
    # name them `ctx`, `myBrowser`, etc.). Stops as soon as we see a top-level
    # `<ident>.close()` — the action body itself shouldn't have any.
    close_re = re.compile(r'^\s*(?:await\s+)?[A-Za-z_$][\w$]*\.close\s*\(')
    iife_close_re = re.compile(r'^\s*\}\s*\)\s*\(\s*\)\s*;?\s*$')

    start_idx = None
    for i, line in enumerate(lines):
        if new_page_re.search(line):
            start_idx = i + 1
            break

    if start_idx is None:
        # No lifecycle — fall back to whole text. Caller decides whether to
        # accept (e.g. test() bodies that just await page.* directly).
        warnings.append(ImportWarning(
            severity="info", code="no_lifecycle_found",
            message="No newPage()/close() pair detected; using body as-is.",
        ))
        return _dedent_block(text.rstrip()), warnings

    captured = []
    for j in range(start_idx, len(lines)):
        line = lines[j]
        if close_re.match(line):
            break
        if iife_close_re.match(line):
            break
        captured.append(line)

    body = "\n".join(captured).rstrip()
    if not body.strip():
        return "", warnings
    return _dedent_block(body), warnings


def _js_body_warnings(body: str):
    from cli.script_strategies._shared import ImportWarning
    warnings = []
    for name in _QACLAN_JS_NAMES:
        if re.search(r'^\s*(?:const|let|var)\s+' + re.escape(name) + r'\b', body, re.MULTILINE):
            warnings.append(ImportWarning(
                severity="error", code="qaclan_var_collision",
                message=f"Action body redefines QAClan scaffold variable `{name}`.",
            ))
    if re.search(r'\bbrowser\.close\s*\(|\bcontext\.close\s*\(', body):
        warnings.append(ImportWarning(
            severity="warn", code="manual_browser_lifecycle",
            message="Action body calls browser.close()/context.close() — harness owns lifecycle.",
        ))
    if re.search(r'\bstorageState\s*[:=]', body):
        warnings.append(ImportWarning(
            severity="warn", code="storage_state_override",
            message="Action body sets storageState — overrides QAClan shared state.",
        ))
    if re.search(r'\bpage\.pause\s*\(', body):
        warnings.append(ImportWarning(
            severity="warn", code="pause_call_present",
            message="Action body contains page.pause() — headless runs will hang.",
        ))
    return warnings


class JavaScriptStrategy(ScriptStrategy):
    language = "javascript"
    codegen_target = "javascript"
    file_extension = ".js"

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
        return ["node", script_path]

    def validate_runtime(self) -> None:
        if not shutil.which("node"):
            raise RuntimeError(
                "Node.js is required to run JavaScript scripts. "
                "Install Node.js from https://nodejs.org and ensure 'node' is on PATH."
            )
        # Try runtime first. cwd=RUNTIME_DIR so Node's parent-dir module walk
        # starts inside runtime/ and finds runtime/node_modules first — a
        # stray ~/node_modules with an older playwright otherwise shadows
        # the runtime install (NODE_PATH is consulted only after the walk).
        if runtime_setup.resolve_node_module("playwright") is not None:
            env = os.environ.copy()
            env["NODE_PATH"] = str(runtime_setup.NODE_MODULES)
            result = subprocess.run(
                ["node", "-e", "require('playwright')"],
                capture_output=True, timeout=10, env=env,
                cwd=str(runtime_setup.RUNTIME_DIR),
            )
            if result.returncode == 0:
                return
            # Runtime present but broken — surface the error rather than silently falling back.
            raise RuntimeError(
                f"Runtime playwright at {runtime_setup.NODE_MODULES}/playwright is broken. "
                "Re-run: qaclan setup --runtime-only --force"
            )
        # Fallback: global.
        runtime_setup.emit_deprecation_warning()
        env = os.environ.copy()
        env.update(self._global_node_path_env())
        result = subprocess.run(
            ["node", "-e", "require('playwright')"],
            capture_output=True, timeout=10, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "The 'playwright' npm package is not available. "
                "Run: qaclan setup --runtime-only "
                "(or install globally: npm install -g playwright@1.58.0)"
            )

    def extra_env(self) -> dict:
        rt_modules = runtime_setup.NODE_MODULES
        if rt_modules.exists():
            return {"NODE_PATH": str(rt_modules)}
        return self._global_node_path_env()

    def _global_node_path_env(self) -> dict:
        npm = shutil.which("npm")
        if not npm:
            return {}
        try:
            result = subprocess.run(
                [npm, "root", "-g"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            npm_root = result.stdout.strip()
            if npm_root:
                return {"NODE_PATH": npm_root}
        except Exception:
            pass
        return {}

    def escape_for_literal(self, value: str) -> str:
        return (
            value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("`", "\\`")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

    # ---- internals ----

    def extract_actions_freeform(self, raw: str):
        """Pull action body out of a hand-written plain-JS Playwright script."""
        from cli.script_strategies._shared import ImportWarning
        text = raw.expandtabs(2)
        actions, peel_warnings = _peel_js_lifecycle(text)
        warnings = list(peel_warnings)
        if not actions.strip():
            warnings.append(ImportWarning(
                severity="error", code="extraction_failed",
                message="No `newPage()`/`close()` lifecycle found and no usable body extracted.",
            ))
            return "", warnings
        warnings.extend(_js_body_warnings(actions))
        return actions, warnings

    def _extract_actions(self, raw: str) -> str:
        """Pull the action body out of Playwright JS codegen output.

        Codegen emits an async IIFE with ``context.newPage()`` as the start
        boundary and ``await context.close()`` / ``await browser.close()`` as
        the end. We grab the lines between them and normalise indentation.
        """
        lines = raw.splitlines()
        captured = []
        capturing = False
        base_indent = None
        for line in lines:
            stripped = line.strip()
            if not capturing and "context.newPage()" in stripped:
                capturing = True
                continue
            if capturing and (
                stripped.startswith("await context.close()")
                or stripped.startswith("await browser.close()")
            ):
                break
            if not capturing:
                continue
            if not stripped or stripped.startswith("//"):
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
            relative = max(0, indent - base_indent)
            captured.append(" " * relative + stripped)
        return "\n".join(captured)

    def _patch_goto_wait(self, actions: str) -> str:
        """Add ``{ waitUntil: 'domcontentloaded' }`` to bare ``page.goto(url)``
        calls. SPAs rarely reach networkidle, and codegen's default wait stalls."""
        return re.sub(
            r'page\.goto\(\s*(["\'][^"\']+["\'])\s*\)',
            r"page.goto(\1, { waitUntil: 'domcontentloaded' })",
            actions,
        )

    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
