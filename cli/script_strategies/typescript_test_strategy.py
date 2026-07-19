"""TypeScript @playwright/test script strategy.

Inherits everything from JavaScriptTestStrategy. Overrides only the file
extension and harness template (ES module imports instead of require).

Run command is identical — `npx playwright test` compiles TypeScript natively
via its built-in esbuild integration; no tsx needed.
"""

from __future__ import annotations

import json

from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
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

// --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
// See javascript_strategy.py for the race-safety rationale on _capturePending.
// Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1, checked once at startup.
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests: Array<{
  method: string;
  url: string;
  request_headers: Record<string, string>;
  request_body: string | null;
  status_code: number | null;
  response_headers: Record<string, string>;
  response_body: string | null;
  duration_ms: number | null;
}> = [];
const _captureStarts = new Map<any, number>();
const _capturePending: Promise<void>[] = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_ALLOWED_TYPES = new Set({CAPTURE_ALLOWED_TYPES_JSON});

function _truncateBody(text: string | null): string | null {
  if (text == null) return text;
  const buf = Buffer.from(text, 'utf-8');
  if (buf.length <= _CAPTURE_BODY_CAP_BYTES) return text;
  return buf.subarray(0, _CAPTURE_BODY_CAP_BYTES).toString('utf-8');
}

async function _captureRequest(req: any): Promise<void> {
  if (!_CAPTURE_ENABLED) return;
  if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;
  const start = _captureStarts.get(req);
  _captureStarts.delete(req);
  if (_capturedRequests.length >= _CAPTURE_CAP) return;
  try {
    const resp = await req.response();
    const entry = {
      method: req.method(),
      url: req.url(),
      request_headers: await req.allHeaders(),
      request_body: _truncateBody(req.postData()),
      status_code: resp ? resp.status() : null,
      response_headers: resp ? await resp.allHeaders() : {},
      response_body: null as string | null,
      duration_ms: start != null ? Date.now() - start : null,
    };
    if (resp) {
      try { entry.response_body = _truncateBody(await resp.text()); } catch (_) {}
    }
    _capturedRequests.push(entry);
  } catch (_) {}
}

function _trackNetwork(page: any) {
  page.on('request', (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
  const done = (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
    _capturePending.push(_captureRequest(req).catch(() => {}));
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
    await Promise.allSettled(_capturePending);
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
      captured_requests: _capturedRequests,
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
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
