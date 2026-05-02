"""JavaScript @playwright/test script strategy.

Produces a self-contained harness using @playwright/test fixtures. The harness
reads configuration from QACLAN_* env vars and writes artifacts to a JSON file
via test.afterAll. Browser / context / page are managed by playwright/test
fixtures — no manual lifecycle code.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import List

from cli import runtime_setup
from cli.script_strategies.base import ScriptStrategy
from cli.script_strategies.javascript_strategy import JavaScriptStrategy


_BEGIN_MARKER = "// BEGIN ACTIONS"
_END_MARKER = "// END ACTIONS"

_HARNESS_TEMPLATE = """\
// QAClan Playwright/test harness — do not edit the scaffolding.
// Only edit the lines between the BEGIN / END action markers.
// Browser / headless / viewport / storageState are configured by the
// playwright.config.js written alongside this file.
'use strict';
const { test, expect } = require('@playwright/test');
const fs = require('fs');

const _STATE      = process.env.QACLAN_STORAGE_STATE || '';
const _ARTIFACTS  = process.env.QACLAN_ARTIFACTS_PATH || '';
const _SCREENSHOT = process.env.QACLAN_SCREENSHOT_PATH || '';

const _consoleErrors = [];
const _networkFailures = [];

test('qaclan', async ({ page, context }) => {
  page.setDefaultTimeout(30000);
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning')
      _consoleErrors.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', err => {
    _consoleErrors.push({ type: 'pageerror', text: String(err) });
  });
  page.on('requestfailed', req => {
    _networkFailures.push({
      url: req.url(), method: req.method(),
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
  }
});

test.afterAll(() => {
  if (!_ARTIFACTS) return;
  try {
    fs.writeFileSync(_ARTIFACTS, JSON.stringify({
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
    }));
  } catch (_) {}
});
"""


class JavaScriptTestStrategy(JavaScriptStrategy):
    """@playwright/test strategy for JavaScript.

    Inherits escape_for_literal, extra_env, rewrite_url_template, and
    _patch_goto_wait from JavaScriptStrategy. Everything else is overridden
    because the harness structure (fixture-based vs manual lifecycle) differs.
    """

    language = "javascript_test"
    codegen_target = "playwright-test"
    file_extension = ".spec.js"

    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        return self._render_harness(actions)

    def setup_run_dir(self, run_dir: str) -> None:
        # Drop one shared playwright.config.js for the whole run. Content is
        # identical across scripts in the run (same testDir, same _use
        # template) so writing it per-script wastes I/O. Called once per
        # unique strategy from web/routes/runs.py before the script loop.
        config_path = os.path.join(run_dir, "playwright.config.js")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(self._render_config(run_dir))

    def build_run_command(self, script_path: str) -> List[str]:
        # playwright test treats the path argument as a regex filter against
        # discovered files. It scans testDir (default: CWD) so the script
        # living in ~/.qaclan/runtime/runs/<id>/ is never found unless we point
        # testDir at its directory via a minimal config written alongside it.
        # The shared config (written once by setup_run_dir) carries
        # browserName / headless / viewport / storageState so the harness
        # does not need test.use() at module scope (which is fragile under
        # multi-instance module resolution).
        #
        # We invoke @playwright/test's cli.js directly via `node` instead of
        # `npx playwright test`. Both `playwright` and `@playwright/test`
        # provide a `playwright` bin; whichever was installed last wins the
        # symlink, and the standalone `playwright` runner loads a different
        # `playwright/lib/common/testType.js` instance than the one a spec
        # `require('@playwright/test')` resolves to (which goes through
        # @playwright/test/node_modules/playwright/). Two instances ⇒
        # `_currentSuiteImpl` is null when the spec runs ⇒ "did not expect
        # test() to be called here". Calling cli.js directly forces the
        # runner to use @playwright/test's nested playwright — same module
        # instance the spec resolves to.
        script_dir = os.path.dirname(os.path.abspath(script_path))
        config_path = os.path.join(script_dir, "playwright.config.js")
        cli_path = self._resolve_pwtest_cli()
        return ["node", cli_path, "test", script_path, "--reporter=line", "--config", config_path]

    def _resolve_pwtest_cli(self) -> str:
        # Prefer isolated runtime cli.js.
        runtime_cli = runtime_setup.resolve_pwtest_cli()
        if runtime_cli is not None:
            return str(runtime_cli)
        # Fallback: global. Warn deprecation.
        runtime_setup.emit_deprecation_warning()
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError(
                "npm is required to locate @playwright/test. Install Node.js "
                "from https://nodejs.org and ensure 'npm' is on PATH."
            )
        result = subprocess.run(
            [npm, "root", "-g"], capture_output=True, text=True, timeout=10
        )
        npm_root = (result.stdout or "").strip()
        if not npm_root:
            raise RuntimeError("Could not resolve global npm root via 'npm root -g'.")
        cli = os.path.join(npm_root, "@playwright", "test", "cli.js")
        if not os.path.exists(cli):
            raise RuntimeError(
                f"@playwright/test cli.js not found at {cli}. "
                "Run: qaclan setup --runtime-only "
                "(or install globally: npm install -g @playwright/test@1.58.0)"
            )
        return cli

    def _render_config(self, test_dir: str) -> str:
        # Config is JS, evaluated by the child node process at run time, so
        # process.env carries the QACLAN_* values set by web/routes/runs.py
        # on child_env. Reading them here (rather than in the Python parent,
        # where those vars are not yet exported) matches how the Python and
        # plain-JS harnesses pick up the same contract.
        return (
            "'use strict';\n"
            "const fs = require('fs');\n"
            "const _BROWSER  = process.env.QACLAN_BROWSER || 'chromium';\n"
            "const _HEADLESS = process.env.QACLAN_HEADLESS !== '0';\n"
            "const _VIEWPORT = process.env.QACLAN_VIEWPORT || '';\n"
            "const _STATE    = process.env.QACLAN_STORAGE_STATE || '';\n"
            "const _use = { browserName: _BROWSER, headless: _HEADLESS, channel: 'chromium' };\n"
            "if (_VIEWPORT) {\n"
            "  const _vp = _VIEWPORT.split('x');\n"
            "  if (_vp.length === 2) {\n"
            "    const w = parseInt(_vp[0], 10), h = parseInt(_vp[1], 10);\n"
            "    if (!isNaN(w) && !isNaN(h)) _use.viewport = { width: w, height: h };\n"
            "  }\n"
            "}\n"
            "if (_STATE && fs.existsSync(_STATE)) _use.storageState = _STATE;\n"
            f"module.exports = {{ testDir: {json.dumps(test_dir)}, use: _use, "
            f"timeout: 60000, expect: {{ timeout: {ScriptStrategy.expect_timeout} }} }};\n"
        )

    def validate_runtime(self) -> None:
        if not shutil.which("node"):
            raise RuntimeError(
                "Node.js is required to run playwright/test scripts. "
                "Install Node.js from https://nodejs.org and ensure 'node' is on PATH."
            )
        # node's require() does not search npm's global root by default —
        # `node -e "require('@playwright/test')"` returns non-zero even when
        # the package is correctly installed via `npm install -g`. Resolve
        # the absolute cli.js path instead (same lookup used at run time).
        self._resolve_pwtest_cli()

    # ---- internals ----

    def _extract_actions(self, raw: str) -> str:
        """Extract body from playwright-test codegen output.

        Codegen emits:
            test('test', async ({ page }) => {
              <actions>
            });

        We grab lines between the async callback opening brace and the
        closing `});`, normalising indentation.
        """
        lines = raw.splitlines()
        captured = []
        capturing = False
        base_indent = None
        for line in lines:
            stripped = line.strip()
            if not capturing and "async" in stripped and "page" in stripped and stripped.endswith("{"):
                capturing = True
                continue
            if not capturing:
                continue
            indent = len(line) - len(line.lstrip())
            # Outer `});` closes the async callback. Multi-line action calls
            # like `.click({ ... });` produce inner `});` at body indent — those
            # must not terminate capture. Only break when `});` sits OUTSIDE
            # the body (indent < base_indent), or at indent 0 before any body
            # line set base_indent.
            if stripped == "});" and (base_indent is None or indent < base_indent):
                break
            if not stripped or stripped.startswith("//"):
                continue
            if base_indent is None:
                base_indent = indent
            relative = max(0, indent - base_indent)
            captured.append(" " * relative + stripped)
        return "\n".join(captured)

    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
