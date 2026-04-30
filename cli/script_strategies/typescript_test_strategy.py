"""TypeScript @playwright/test script strategy.

Inherits everything from JavaScriptTestStrategy. Overrides only the file
extension and harness template (ES module imports instead of require).

Run command is identical — `npx playwright test` compiles TypeScript natively
via its built-in esbuild integration; no tsx needed.
"""

from __future__ import annotations

from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy


_BEGIN_MARKER = "// BEGIN ACTIONS"
_END_MARKER = "// END ACTIONS"

_HARNESS_TEMPLATE = """\
// QAClan Playwright/test harness — do not edit the scaffolding.
// Only edit the lines between the BEGIN / END action markers.
// Browser / headless / viewport / storageState are configured by the
// playwright.config.js written alongside this file.
import { test, expect } from '@playwright/test';
import * as fs from 'fs';

const _STATE      = process.env['QACLAN_STORAGE_STATE'] ?? '';
const _ARTIFACTS  = process.env['QACLAN_ARTIFACTS_PATH'] ?? '';
const _SCREENSHOT = process.env['QACLAN_SCREENSHOT_PATH'] ?? '';

const _consoleErrors: Array<{ type: string; text: string }> = [];
const _networkFailures: Array<{ url: string; method: string; failure: string | null }> = [];

test('qaclan', async ({ page, context }) => {
  page.setDefaultTimeout(30000);
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning')
      _consoleErrors.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', (err: Error) => {
    _consoleErrors.push({ type: 'pageerror', text: String(err) });
  });
  page.on('requestfailed', req => {
    _networkFailures.push({
      url: req.url(), method: req.method(),
      failure: req.failure() ? req.failure()!.errorText : null,
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


class TypeScriptTestStrategy(JavaScriptTestStrategy):
    language = "typescript_test"
    codegen_target = "playwright-test"
    file_extension = ".spec.ts"

    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
