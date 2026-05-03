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
// QAClan Playwright/test harness - do not edit the scaffolding.
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


# Match ANY async callback shape after `test(...,`:
#   `async ()`, `async (page)`, `async ({page})`, `async ({page, context})`
#   `async function()`, `async function named()`
_TEST_CALLBACK_RE = re.compile(
    r'\btest\s*\('                               # test(
    r'[^)]*?,\s*'                                # name argument up to comma
    r'async\s*'                                  # async
    r'(?:function(?:\s+[A-Za-z_$][\w$]*)?\s*)?'  # optional `function` or `function name`
    r'\([^)]*\)'                                 # arg list (...)
    r'(?:\s*=>)?'                                # optional => (functions don't use it)
    r'\s*\{',                                    # opening brace
    re.DOTALL,
)


def _dedent_block_simple(body: str) -> str:
    body = body.strip("\n").rstrip()
    lines = body.splitlines()
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    base = min(indents) if indents else 0
    return "\n".join(l[base:] if len(l) >= base else l for l in lines)


def _slice_test_callback_body(text: str):
    """Return ``(body, warnings)`` — body is the first test() callback body,
    or ``None`` if no test() found. Body is the raw text between the callback
    `{` and matching `}` — caller handles dedent.
    """
    from cli.script_strategies._shared import ImportWarning
    warnings = []

    m = _TEST_CALLBACK_RE.search(text)
    if not m:
        return None, warnings

    # Extract destructure if any to surface unsupported_fixture warning.
    # Look at the matched chunk for `{...}` inside parens.
    destruct = re.search(r'\(\s*\{([^}]*)\}\s*\)', m.group(0))
    if destruct:
        fixtures = {p.strip().split(':')[0].strip() for p in destruct.group(1).split(',') if p.strip()}
        unsupported = fixtures - {"page", "context"}
        if unsupported:
            warnings.append(ImportWarning(
                severity="warn", code="unsupported_fixture",
                message=f"Test uses fixtures the harness does not provide: {sorted(unsupported)}.",
            ))

    # Walk braces from the matched opening `{` (last char of m.group(0)).
    open_pos = m.end() - 1  # the `{`
    depth = 0
    close_pos = None
    i = open_pos
    n = len(text)
    in_str = None  # quote char if inside string literal
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = text[i]
        nxt = text[i+1] if i + 1 < n else ''
        if in_line_comment:
            if ch == '\n':
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == '*' and nxt == '/':
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            if ch == '\\':
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        # Not in string/comment.
        if ch == '/' and nxt == '/':
            in_line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'", '`'):
            in_str = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                close_pos = i
                break
        i += 1

    if close_pos is None:
        warnings.append(ImportWarning(
            severity="error", code="extraction_failed",
            message="Could not find matching `}` for the test() callback.",
        ))
        return None, warnings

    body = text[open_pos + 1:close_pos]
    return body, warnings


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
        # Pass basename, not full path. Playwright treats the positional arg
        # as a regex filter against discovered file paths. Windows absolute
        # paths contain `\` and `:` (regex meta) -> regex compiles to nothing
        # matchable -> "No tests found". Discovery itself uses config.testDir
        # (set to script_dir), so a basename like `srun_xxx.spec.js` is
        # enough to substring-match the discovered absolute path on every OS.
        script_filter = os.path.basename(script_path)
        return ["node", cli_path, "test", script_filter, "--reporter=line", "--config", config_path]

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

    def extract_actions_freeform(self, raw: str):
        """Pull action body out of a user-written ``@playwright/test`` spec.

        Steps:
          1. report sibling-construct warnings (multiple tests, hooks,
             test.use, test.extend);
          2. locate the FIRST ``test(...)`` callback — accept any callback
             shape: ``async ({page})``, ``async (arg)``, ``async ()``,
             ``async function()``, ``async function name()``;
          3. slice the callback body via brace-depth counting;
          4. peel manual ``newPage()``/``close()`` lifecycle out of the body
             (some users launch their own browser inside the test) by
             delegating to the plain-JS lifecycle peeler;
          5. report body-shape warnings.
        """
        from cli.script_strategies._shared import ImportWarning
        from cli.script_strategies.javascript_strategy import (
            _peel_js_lifecycle, _js_body_warnings,
        )
        warnings = []

        text = raw.expandtabs(2)
        lines = text.splitlines()

        test_count = sum(1 for l in lines if re.match(r'^\s*test\s*\(', l))
        if test_count > 1:
            warnings.append(ImportWarning(
                severity="warn", code="multiple_tests_dropped",
                message=f"{test_count} test() blocks found; only the first is kept.",
            ))
        for code, pattern, msg in (
            ("test_use_dropped", r'^\s*test\.use\s*\(',
             "test.use({...}) removed — harness owns config."),
            ("hook_dropped", r'^\s*test\.(beforeAll|beforeEach|afterAll|afterEach)\s*\(',
             "test hooks (beforeAll/beforeEach/afterAll/afterEach) removed."),
            ("fixture_definition_dropped", r'^\s*test\.extend\s*\(',
             "test.extend({...}) fixture definitions removed."),
        ):
            if any(re.match(pattern, l) for l in lines):
                warnings.append(ImportWarning(severity="warn", code=code, message=msg))

        body, slice_warnings = _slice_test_callback_body(text)
        warnings.extend(slice_warnings)
        if body is None:
            return "", warnings + [ImportWarning(
                severity="error", code="extraction_failed",
                message="No `test('name', <async callback>)` block found.",
            )]
        if not body.strip():
            return "", warnings + [ImportWarning(
                severity="error", code="extraction_failed",
                message="test() callback body is empty.",
            )]

        # Some users hand-roll lifecycle inside the test() body. Strip it.
        peeled, peel_warnings = _peel_js_lifecycle(body)
        if peeled.strip() and peeled != body.strip():
            warnings.append(ImportWarning(
                severity="info", code="manual_lifecycle_in_test",
                message="Detected manual browser/context/page lifecycle in test body — stripped.",
            ))
            actions = peeled
        else:
            # No internal lifecycle: keep callback body as-is. Filter the
            # 'no_lifecycle_found' info warning since fixture-style tests
            # don't have a lifecycle by design.
            actions = _dedent_block_simple(body)
            peel_warnings = [w for w in peel_warnings if w.code != "no_lifecycle_found"]
        warnings.extend(peel_warnings)

        warnings.extend(_js_body_warnings(actions))
        return actions, warnings

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
