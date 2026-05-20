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
// QAClan Playwright/test harness - do not edit the scaffolding.
// Only edit the lines between the BEGIN / END action markers.
// Browser / headless / viewport / storageState are configured by the
// playwright.config.js written alongside this file.
import { test, expect } from '@playwright/test';
import * as fs from 'fs';

const _STATE      = process.env['QACLAN_STORAGE_STATE'] ?? '';
const _ARTIFACTS  = process.env['QACLAN_ARTIFACTS_PATH'] ?? '';
const _SCREENSHOT = process.env['QACLAN_SCREENSHOT_PATH'] ?? '';
const _ACTION_TIMEOUT = parseInt(process.env['QACLAN_ACTION_TIMEOUT'] ?? '30000', 10) || 30000;

const _consoleErrors: Array<{ type: string; text: string }> = [];
const _networkFailures: Array<{ url: string; method: string; failure: string | null }> = [];
// Stash the thrown error before re-throwing — test.afterAll has no access to
// it otherwise. See docs/error-reporting-plan.md (section 2.1).
let _scriptError: any = null;

// --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
let _inFlight = 0;
function _trackNetwork(page: any) {
  page.on('request', (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
  });
  const done = (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
}

// Wait until in-flight XHR/fetch stays 0 for `quietMs`, capped at `timeoutMs`.
// Two-step grace probe (150ms then graceMs) catches debounced inputs whose
// XHR has not fired yet at 150ms.
async function _waitForNetworkSettle(page: any, { graceMs = 700, quietMs = 400, timeoutMs = 15000 }: { graceMs?: number; quietMs?: number; timeoutMs?: number } = {}) {
  await page.waitForTimeout(150);
  if (_inFlight === 0) {
    const extra = Math.max(0, graceMs - 150);
    if (extra > 0) await page.waitForTimeout(extra);
    if (_inFlight === 0) return;
  }
  const deadline = Date.now() + timeoutMs;
  let quietSince: number | null = null;
  while (Date.now() < deadline) {
    if (_inFlight === 0) {
      if (quietSince === null) quietSince = Date.now();
      else if (Date.now() - quietSince >= quietMs) return;
    } else {
      quietSince = null;
    }
    await page.waitForTimeout(50);
  }
  // Soft cap: do not throw.
}

test('qaclan', async ({ page, context }) => {
  page.setDefaultTimeout(_ACTION_TIMEOUT);
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
  _trackNetwork(page);
  try {
{ACTIONS}
  } catch (err) {
    if (_SCREENSHOT) {
      try { await page.screenshot({ path: _SCREENSHOT }); } catch (_) {}
    }
    _scriptError = err;
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
    const payload: any = {
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
    };
    if (_scriptError) payload.error = {
      raw_type: (_scriptError && _scriptError.name) || 'Error',
      raw_message: (_scriptError && _scriptError.message) || String(_scriptError),
    };
    fs.writeFileSync(_ARTIFACTS, JSON.stringify(payload));
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
