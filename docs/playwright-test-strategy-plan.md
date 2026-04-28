# Playwright/test Strategy Plan

## Context

Existing `javascript` and `typescript` strategies use the plain `playwright` CommonJS package —
`require('playwright')`, manual browser/context/page lifecycle, run via `node script.js`.

Modern best practice is `@playwright/test` (`import { test, expect } from '@playwright/test'`),
which manages browser/context/page as fixtures, has richer assertions, and is the default
scaffolding Playwright's own tooling now generates.

Goal: add two new language keys (`javascript_test`, `typescript_test`) backed by new strategies
that use `@playwright/test`, keeping the existing CommonJS strategies untouched.

---

## New Language Keys

| DB / API key        | Display label                   |
|---------------------|---------------------------------|
| `javascript_test`   | `JavaScript (playwright/test)`  |
| `typescript_test`   | `TypeScript (playwright/test)`  |

These sit alongside `python`, `javascript`, `typescript` in `SUPPORTED_LANGUAGES`.

---

## Playwright/test Locator & Action Reference

These are the locator and action combinations used most frequently in `@playwright/test` codegen
output and manual scripts.

### Locator strategies (element selection)

```javascript
// Semantic — preferred, most readable
page.getByRole('textbox', { name: 'Password' })       // ARIA role + name
page.getByRole('button', { name: 'Sign in' })
page.getByRole('checkbox', { name: 'Remember me' })
page.getByRole('link', { name: 'Home' })
page.getByRole('combobox', { name: 'Country' })

page.getByLabel('Password')                            // <label> text
page.getByPlaceholder('Enter Password')                // placeholder attr
page.getByText('Forgot password?')                     // visible text (partial match)
page.getByText('Forgot password?', { exact: true })    // exact match
page.getByTestId('login-btn')                          // data-testid attr

// CSS / XPath (still fully supported)
page.locator('input[placeholder="Enter Password"]')
page.locator('button[type="submit"]')
page.locator('#username')
page.locator('.login-form input')
page.locator('xpath=//input[@placeholder="Enter Password"]')

// Chaining / scoping
page.locator('.modal').getByRole('button', { name: 'Close' })
page.locator('tr').filter({ hasText: 'John' }).getByRole('button', { name: 'Edit' })

// nth match
page.getByRole('row').nth(1)
page.locator('li').first()
page.locator('li').last()
```

### Actions (what you do with a locator)

```javascript
// Fill / input
await loc.fill('value')                   // clear + set value (most common)
await loc.clear()                         // clear only
await loc.pressSequentially('value')      // simulate key-by-key typing (for masked inputs)
await loc.press('Enter')                  // single key
await loc.press('Tab')
await loc.press('Control+a')

// Click variants
await loc.click()
await loc.click({ button: 'right' })      // right-click
await loc.dblclick()
await loc.tap()                           // mobile / touch
await loc.hover()

// Form controls
await loc.check()                         // checkbox / radio on
await loc.uncheck()                       // checkbox off
await loc.setChecked(true)
await loc.selectOption('value')           // <select> by value
await loc.selectOption({ label: 'USA' }) // <select> by label
await loc.selectOption(['a', 'b'])        // multi-select

// Focus / blur
await loc.focus()
await loc.blur()

// Scroll
await loc.scrollIntoViewIfNeeded()

// File upload
await loc.setInputFiles('/path/to/file.pdf')

// Drag
await loc.dragTo(page.locator('#target'))

// Wait
await loc.waitFor()                       // wait for attached + visible
await loc.waitFor({ state: 'hidden' })
await loc.waitFor({ state: 'detached' })

// Navigation (page-level)
await page.goto('https://example.com')
await page.goto('https://example.com', { waitUntil: 'domcontentloaded' })
await page.goBack()
await page.reload()
await page.waitForURL('**/dashboard')

// Keyboard (global)
await page.keyboard.press('Escape')
await page.keyboard.type('hello')
```

### Assertions (expect)

```javascript
// Element state
await expect(loc).toBeVisible()
await expect(loc).toBeHidden()
await expect(loc).toBeEnabled()
await expect(loc).toBeDisabled()
await expect(loc).toBeChecked()
await expect(loc).toBeEmpty()
await expect(loc).toBeFocused()

// Content
await expect(loc).toHaveText('Expected text')
await expect(loc).toHaveText(/regex/)
await expect(loc).toContainText('partial')
await expect(loc).toHaveValue('input value')
await expect(loc).toHaveAttribute('href', '/home')
await expect(loc).toHaveClass('active')
await expect(loc).toHaveCount(3)

// Page-level
await expect(page).toHaveURL('https://example.com/dashboard')
await expect(page).toHaveURL(/dashboard/)
await expect(page).toHaveTitle('My App')
```

---

## Strategy Design

### Class hierarchy

```
ScriptStrategy (ABC)
├── PythonStrategy            (existing)
├── JavaScriptStrategy        (existing — plain playwright CommonJS)
│   └── TypeScriptStrategy    (existing — tsx runner)
└── JavaScriptTestStrategy    (NEW — @playwright/test CommonJS harness)
    └── TypeScriptTestStrategy (NEW — @playwright/test ESM harness, npx playwright test)
```

`JavaScriptTestStrategy` inherits from `ScriptStrategy` directly (not from `JavaScriptStrategy`)
because the harness structure is fundamentally different — fixture injection replaces manual
browser lifecycle.

`TypeScriptTestStrategy` inherits from `JavaScriptTestStrategy`, overriding only:
- `language = "typescript_test"`
- `file_extension = ".ts"`
- `_HARNESS_TEMPLATE` — uses `import` syntax instead of `require`
  (optional: could share one template with a flag; prefer separate for clarity)

### Key attributes

| Attribute          | `javascript_test`          | `typescript_test`             |
|--------------------|----------------------------|-------------------------------|
| `language`         | `"javascript_test"`        | `"typescript_test"`           |
| `codegen_target`   | `"playwright-test"`        | `"playwright-test"`           |
| `file_extension`   | `".js"`                    | `".ts"`                       |
| `build_run_command`| `npx playwright test <f> --reporter=line` | same |
| `validate_runtime` | node + `@playwright/test`  | inherits (pw/test handles TS) |

---

## Harness Template — JavaScript (playwright/test)

```javascript
// QAClan Playwright/test harness — do not edit the scaffolding.
// Only edit the lines between the BEGIN / END action markers.
'use strict';
const { test, expect } = require('@playwright/test');
const fs = require('fs');

const _BROWSER = process.env.QACLAN_BROWSER || 'chromium';
const _HEADLESS = process.env.QACLAN_HEADLESS !== '0';
const _VIEWPORT  = process.env.QACLAN_VIEWPORT  || '';
const _STATE     = process.env.QACLAN_STORAGE_STATE || '';
const _ARTIFACTS = process.env.QACLAN_ARTIFACTS_PATH || '';
const _SCREENSHOT= process.env.QACLAN_SCREENSHOT_PATH || '';

const _consoleErrors = [];
const _networkFailures = [];

// Configure fixtures via test.use() — evaluated at load time
const _useConfig = { browserName: _BROWSER, headless: _HEADLESS };
if (_STATE && fs.existsSync(_STATE)) _useConfig.storageState = _STATE;
if (_VIEWPORT) {
  const [w, h] = _VIEWPORT.split('x').map(Number);
  if (!isNaN(w) && !isNaN(h)) _useConfig.viewport = { width: w, height: h };
}
test.use(_useConfig);

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
    _networkFailures.push({ url: req.url(), method: req.method(),
      failure: req.failure() ? req.failure().errorText : null });
  });

  try {
{ACTIONS}
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
```

### TypeScript variant differences

Only the imports line changes:
```typescript
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
```
Rest of harness identical. `npx playwright test` compiles TypeScript natively via esbuild.

---

## `_extract_actions` for playwright-test codegen output

Codegen `--target playwright-test` emits:
```javascript
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('https://example.com');
  await page.getByRole('textbox', { name: 'Email' }).fill('user@example.com');
  // ...
});
```

Extraction logic:
- **Start marker:** line containing `async ({ page` (signals entry to test body)
- **End marker:** line equal to `});` at column 0 (closes the test block)
- Normalise indentation same as existing JS strategy

---

## `validate_runtime`

```python
def validate_runtime(self) -> None:
    if not shutil.which("node"):
        raise RuntimeError("Node.js required. Install from https://nodejs.org")
    result = subprocess.run(
        ["node", "-e", "require('@playwright/test')"],
        capture_output=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "'@playwright/test' not installed. Run: npm install -g @playwright/test\n"
            "Then: npx playwright install"
        )
```

`TypeScriptTestStrategy.validate_runtime` calls `super().validate_runtime()` — no extra check
needed since `npx playwright test` handles TypeScript compilation internally.

---

## `build_run_command`

```python
def build_run_command(self, script_path: str) -> List[str]:
    return ["npx", "playwright", "test", script_path, "--reporter=line"]
```

Note: `npx playwright test <file>` runs the specific file directly.
`--reporter=line` keeps output compact for the run log.

---

## `extra_env`

Inherit `JavaScriptStrategy.extra_env` (sets `NODE_PATH` to global npm root so
`require('@playwright/test')` resolves when the package is installed globally).

---

## File Checklist

### New files
- `cli/script_strategies/javascript_test_strategy.py`
- `cli/script_strategies/typescript_test_strategy.py`

### Modified files

**`cli/script_strategies/__init__.py`**
- Add imports for `JavaScriptTestStrategy`, `TypeScriptTestStrategy`
- Add `"javascript_test"`, `"typescript_test"` to `_STRATEGIES`

**`web/static/app.js`**
Three places have language `<option>` lists and one has the `langLabel` map:

1. **Record modal** (line ~994): add two new `<option>` entries
2. **New Script modal** (line ~1597): add two new `<option>` entries
3. **`langLabel` map** (line 1719): add `javascript_test` and `typescript_test` keys

```javascript
// langLabel update
const langLabel = {
  python: 'Python',
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  javascript_test: 'JavaScript (playwright/test)',
  typescript_test: 'TypeScript (playwright/test)',
}[lang] || lang
```

4. **`_createScriptEditor` language hint** (if it maps language to CodeMirror mode): map both
   `javascript_test` → `javascript` and `typescript_test` → `typescript` for syntax highlighting.

---

## Edge Cases

- **Codegen target `playwright-test`**: if the installed Playwright version doesn't support this
  target flag, `record` will fail with a clear error from codegen itself. No harness to handle.
- **`test.use()` at load time**: `_STATE`/`_VIEWPORT` are read when the file is `require()`'d.
  If storage state file doesn't exist at load time, `fs.existsSync` returns false — safe.
- **Screenshot on failure**: `@playwright/test` has built-in screenshot-on-failure. Our harness
  doesn't duplicate it. `_SCREENSHOT` env var goes unused for test strategies (acceptable).
- **`context` fixture**: added to test signature alongside `page` for `context.storageState()`.
  playwright/test provides both automatically.
- **Escape rules**: same as `JavaScriptStrategy.escape_for_literal` — single/double/backtick/`\r`.

---

## Acceptance Criteria

- Record a script with `javascript_test` → `.js` harness using `require('@playwright/test')` 
- Record a script with `typescript_test` → `.ts` harness using `import { test, expect }` 
- Run succeeds and artifacts JSON is written
- Missing `@playwright/test` → clear pre-flight error, not a subprocess crash
- Existing `python`/`javascript`/`typescript` strategies unaffected
- UI dropdowns show four language options with correct labels

---

## Session Notes

_Claude: append short dated notes here when finishing tasks._

- 2026-04-27: Plan written. Awaiting user approval before implementation.
- 2026-04-27: Implementation complete. `javascript_test_strategy.py` + `typescript_test_strategy.py` added. `__init__.py` registered both. `app.js` updated in 4 spots (CodeMirror map, record modal, new script modal, langLabel). All smoke tests pass.
