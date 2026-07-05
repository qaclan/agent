# {{var}} Exists/Missing Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Color `{{var}}` tokens in headers/params/path-vars/auth fields green when every referenced variable exists (in the active environment or bound collection) and red when any doesn't, replacing the current single-color "contains a var ref" tint on those surfaces only.

**Architecture:** A new pure-function helper module (`var-style.js`) extracts `{{name}}` tokens from an input's value and toggles one of two CSS classes based on a `Set` of known variable names. `key-value-table.js` gains an optional constructor option that switches a table's value inputs onto this new helper (default: unchanged legacy behavior). `request-editor-view.js` builds one `Set` of known variable names per editor load (from the same data already used for autocomplete), passes it to the three in-scope tables, and applies the same helper directly to auth `<input>`s.

**Tech Stack:** Vanilla JS (ES modules), plain CSS custom properties. No build step, no test framework — verification is done with `node --check` for syntax and small throwaway `node` scripts (ESM, using `assert`) for the pure-function logic, then a manual browser check for the full wiring.

## Global Constraints

- Scope is exactly: headers table, query-params table, path-vars table, auth fields (bearer token, basic auth user/pass, API key value, OAuth2 token_url/client_id/client_secret). Form-urlencoded and multipart body tables, the raw/JSON body editor, and pre/post script textareas must NOT change behavior.
- Existence = variable name appears in the `Set` built from `getAllVars()` (env vars + bound collection vars) — the same list already used for autocomplete. Runtime-only variables set by a pre-script (`qc.set(...)`) are not included and will show as "missing"; this is accepted, not fixed here.
- Mixed tokens (some resolve, some don't) → whole field is "missing" (red). No third "mixed" color.
- No tokens present, or the known-vars `Set` hasn't loaded yet (`null`) → neutral, no color class. Never flash red before the first fetch resolves.
- `key-value-table.js`'s new option must be optional and backward-compatible: call sites that don't pass it (`formBodyTable`, `multipartBodyTable`) keep exactly their current `kv-value--var-ref` single-color behavior, untouched.
- New CSS classes use the existing `--success-bg`/`--success-border`/`--danger-bg`/`--danger-border` custom properties already defined in `web/static/style.css` (lines 21-26, redefined per-theme at 65-68) — do not invent new color values.

---

### Task 1: CSS classes for the two new states

**Files:**
- Modify: `web/static/style.css:1722-1731` (existing `.kv-value--var-ref` / `.kv-value--file` block)

**Interfaces:**
- Produces: CSS classes `kv-value--var-ok` and `kv-value--var-missing`, consumed by Task 2's `applyVarStyle()`.

- [ ] **Step 1: Add the two new rules**

Current content at `web/static/style.css:1722-1731`:

```css
.kv-value--var-ref {
  background: color-mix(in srgb, var(--primary, #5C6BC0) 8%, transparent) !important;
  border-color: var(--primary, #5C6BC0) !important;
  font-family: var(--font-mono);
}
.kv-value--file {
  background: color-mix(in srgb, var(--text-muted, #888) 10%, transparent) !important;
  font-style: italic;
  color: var(--text-muted);
}
```

Insert two new rules directly after the `.kv-value--var-ref` block (before `.kv-value--file`), leaving `.kv-value--var-ref` itself untouched:

```css
.kv-value--var-ref {
  background: color-mix(in srgb, var(--primary, #5C6BC0) 8%, transparent) !important;
  border-color: var(--primary, #5C6BC0) !important;
  font-family: var(--font-mono);
}
.kv-value--var-ok {
  background: var(--success-bg) !important;
  border-color: var(--success-border) !important;
  font-family: var(--font-mono);
}
.kv-value--var-missing {
  background: var(--danger-bg) !important;
  border-color: var(--danger-border) !important;
  font-family: var(--font-mono);
}
.kv-value--file {
  background: color-mix(in srgb, var(--text-muted, #888) 10%, transparent) !important;
  font-style: italic;
  color: var(--text-muted);
}
```

- [ ] **Step 2: Verify the file still parses as CSS**

Run: `node -e "require('fs').readFileSync('web/static/style.css','utf8')" && echo READABLE`
Expected: `READABLE` (this repo has no CSS linter configured; this just confirms the file is intact/readable — visually confirm brace-matching by eye since there's no linter to catch a stray brace).

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "feat: add kv-value--var-ok/--var-missing CSS classes"
```

---

### Task 2: `var-style.js` shared helper

**Files:**
- Create: `web/static/api/components/var-style.js`

**Interfaces:**
- Produces:
  - `varTokensIn(value: string): string[]` — trimmed `{{name}}` token names found in `value`, in order, duplicates included.
  - `applyVarStyle(inp: HTMLInputElement, knownNames: Set<string>|null): void` — sets/clears `kv-value--var-ok` / `kv-value--var-missing` on `inp` based on `inp.value` and `knownNames`.
- Consumed by: Task 3 (`key-value-table.js`) and Task 4 (`request-editor-view.js`, auth fields).

- [ ] **Step 1: Write the module**

Create `web/static/api/components/var-style.js`:

```js
/**
 * Shared {{var}} token extraction + exists/missing CSS styling for plain
 * <input> value fields. Used by key-value-table.js (headers/params/path-vars)
 * and request-editor-view.js (auth fields) — NOT by the body editor or
 * script textareas.
 */

const _VAR_TOKEN_RE = /\{\{([^}]+)\}\}/g;

export function varTokensIn(value) {
  if (!value) return [];
  return [...value.matchAll(_VAR_TOKEN_RE)].map(m => m[1].trim());
}

export function applyVarStyle(inp, knownNames) {
  const tokens = varTokensIn(inp.value);
  inp.classList.remove('kv-value--var-ok', 'kv-value--var-missing');
  if (!tokens.length || knownNames == null) return;
  const allKnown = tokens.every(name => knownNames.has(name));
  inp.classList.add(allKnown ? 'kv-value--var-ok' : 'kv-value--var-missing');
}
```

- [ ] **Step 2: Verify syntax**

Run: `node --check web/static/api/components/var-style.js`
Expected: no output (exit code 0).

- [ ] **Step 3: Write a throwaway verification script and run it**

Create `/tmp/verify-var-style.mjs` (adjust the import path's `..` count if your shell's cwd differs from the repo root — it must resolve to `web/static/api/components/var-style.js`):

```js
import assert from 'node:assert/strict';
import { varTokensIn, applyVarStyle } from '/mnt/ext-drive/qaclan/agent/web/static/api/components/var-style.js';

// varTokensIn
assert.deepEqual(varTokensIn(''), []);
assert.deepEqual(varTokensIn('no vars here'), []);
assert.deepEqual(varTokensIn('{{token}}'), ['token']);
assert.deepEqual(varTokensIn('Bearer {{ token }} / {{other}}'), ['token', 'other']);

// applyVarStyle — fake input with a real Set-backed classList stub
function fakeInput(value) {
  const classes = new Set();
  return {
    value,
    classList: {
      remove: (...names) => names.forEach(n => classes.delete(n)),
      add: (...names) => names.forEach(n => classes.add(n)),
      contains: (n) => classes.has(n),
    },
    _classes: classes,
  };
}

// no tokens -> neutral
let inp = fakeInput('plain text');
applyVarStyle(inp, new Set(['token']));
assert.equal(inp._classes.size, 0);

// knownNames null (not loaded yet) -> neutral even with tokens
inp = fakeInput('{{token}}');
applyVarStyle(inp, null);
assert.equal(inp._classes.size, 0);

// single known token -> ok
inp = fakeInput('{{token}}');
applyVarStyle(inp, new Set(['token']));
assert.ok(inp._classes.has('kv-value--var-ok'));
assert.ok(!inp._classes.has('kv-value--var-missing'));

// single unknown token -> missing
inp = fakeInput('{{missing}}');
applyVarStyle(inp, new Set(['token']));
assert.ok(inp._classes.has('kv-value--var-missing'));
assert.ok(!inp._classes.has('kv-value--var-ok'));

// mixed known+unknown -> missing (no third state)
inp = fakeInput('Bearer {{token}} / {{missing}}');
applyVarStyle(inp, new Set(['token']));
assert.ok(inp._classes.has('kv-value--var-missing'));
assert.ok(!inp._classes.has('kv-value--var-ok'));

// re-applying clears the previous state (toggle, not just add)
inp = fakeInput('{{token}}');
applyVarStyle(inp, new Set(['token'])); // -> ok
inp.value = '{{missing}}';
applyVarStyle(inp, new Set(['token'])); // -> missing, ok must be gone
assert.ok(inp._classes.has('kv-value--var-missing'));
assert.ok(!inp._classes.has('kv-value--var-ok'));

console.log('ALL PASS');
```

Run: `node /tmp/verify-var-style.mjs`
Expected: `ALL PASS`

- [ ] **Step 4: Delete the throwaway script**

Run: `rm /tmp/verify-var-style.mjs`

(This repo has no test suite configured — see `CLAUDE.md` — so this script is a one-off verification aid, not committed.)

- [ ] **Step 5: Commit**

```bash
git add web/static/api/components/var-style.js
git commit -m "feat: add var-style.js helper for {{var}} exists/missing coloring"
```

---

### Task 3: `key-value-table.js` — optional `getKnownVarNames` wiring

**Files:**
- Modify: `web/static/api/components/key-value-table.js:1-21` (imports + options destructuring)
- Modify: `web/static/api/components/key-value-table.js:68-72` (`_isVarRef`/`_applyVarStyle`, left as-is, used as the fallback path)
- Modify: `web/static/api/components/key-value-table.js:111-125` (value input creation)
- Modify: `web/static/api/components/key-value-table.js:238-244` (`setRows` / return statement)

**Interfaces:**
- Consumes: `applyVarStyle` from `web/static/api/components/var-style.js` (Task 2).
- Produces: `createKeyValueTable(options)` gains optional `options.getKnownVarNames: () => Set<string>|null`; the returned object gains `restyleAll(): void`. Existing `{ el, getRows, setRows }` return shape and all other options are unchanged.

- [ ] **Step 1: Import the helper**

At the top of `web/static/api/components/key-value-table.js`, current lines 1-2:

```js
import { createVarPicker } from './var-picker.js';
import { createInlineVarDrop } from './inline-var-drop.js';
```

Change to:

```js
import { createVarPicker } from './var-picker.js';
import { createInlineVarDrop } from './inline-var-drop.js';
import { applyVarStyle } from './var-style.js';
```

- [ ] **Step 2: Add the new option**

Current `createKeyValueTable` options destructuring (lines 15-21):

```js
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
    fileFieldsEnabled = false,
  } = options;
```

Change to:

```js
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
    fileFieldsEnabled = false,
    getKnownVarNames = null,
  } = options;
```

- [ ] **Step 3: Add a shared styling function that dispatches to the new or legacy path**

Immediately after the existing `_applyVarStyle` function (current lines 70-72):

```js
  function _isVarRef(v) { return /\{\{[^}]+\}\}/.test(v || ''); }

  function _applyVarStyle(inp) {
    inp.classList.toggle('kv-value--var-ref', _isVarRef(inp.value));
  }
```

Add a new function right after it:

```js
  function _styleValueInput(inp) {
    if (getKnownVarNames) applyVarStyle(inp, getKnownVarNames());
    else _applyVarStyle(inp);
  }
```

- [ ] **Step 4: Use `_styleValueInput` instead of `_applyVarStyle` at the two call sites in `_addRow`**

Current lines 111-125:

```js
    const valTd = document.createElement('td');
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'kv-value input-sm';
    valInput.placeholder = placeholder.value;
    valInput.value = data.value || '';
    valInput.readOnly = readOnly;
    _applyVarStyle(valInput);
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => _applyVarStyle(valInput));
      if (varPickerEnabled) _inlineDrop.watchInput(valInput);
    }
```

Change the two `_applyVarStyle(valInput)` calls to `_styleValueInput(valInput)`:

```js
    const valTd = document.createElement('td');
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'kv-value input-sm';
    valInput.placeholder = placeholder.value;
    valInput.value = data.value || '';
    valInput.readOnly = readOnly;
    _styleValueInput(valInput);
    valTd.appendChild(valInput);
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => _styleValueInput(valInput));
      if (varPickerEnabled) _inlineDrop.watchInput(valInput);
    }
```

(The `pickerBtn.onclick` handler further down already calls `valInput.dispatchEvent(new Event('input'))` after inserting a variable token, which will now route through `_styleValueInput` via the listener — no change needed there.)

- [ ] **Step 5: Add `restyleAll()` and return it**

Current `setRows`/return (lines 238-244):

```js
  function setRows(rows = []) {
    tbody.innerHTML = '';
    rows.forEach(r => _addRow(r));
  }

  return { el: wrapper, getRows, setRows };
}
```

Change to:

```js
  function setRows(rows = []) {
    tbody.innerHTML = '';
    rows.forEach(r => _addRow(r));
  }

  function restyleAll() {
    tbody.querySelectorAll('.kv-value').forEach(_styleValueInput);
  }

  return { el: wrapper, getRows, setRows, restyleAll };
}
```

- [ ] **Step 6: Verify syntax**

Run: `node --check web/static/api/components/key-value-table.js`
Expected: no output (exit code 0).

- [ ] **Step 7: Commit**

```bash
git add web/static/api/components/key-value-table.js
git commit -m "feat: key-value-table gains optional getKnownVarNames + restyleAll"
```

---

### Task 4: Wire `request-editor-view.js` — known-vars cache, the 3 in-scope tables, and auth fields

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:1-7` (imports)
- Modify: `web/static/api/views/request-editor-view.js:170` (`paramsTable`)
- Modify: `web/static/api/views/request-editor-view.js:173` (`headersTable`)
- Modify: `web/static/api/views/request-editor-view.js:185` (`pathVarsTable`)
- Modify: `web/static/api/views/request-editor-view.js:521-538` (`_authInlineDrop`, `_makeField`)
- Modify: `web/static/api/views/request-editor-view.js:540-542` (`_renderAuthFields` start)
- Modify: `web/static/api/views/request-editor-view.js:602-603` (initial auth render)

**Interfaces:**
- Consumes: `applyVarStyle` from `var-style.js` (Task 2); `restyleAll()` from `key-value-table.js` instances (Task 3); existing `getAllVars()` (already defined at line 32, unchanged).
- Produces: nothing consumed by later tasks — this is the last wiring task. `formBodyTable`/`multipartBodyTable` (lines 436-437) are explicitly NOT touched in this task.

- [ ] **Step 1: Import `applyVarStyle`**

Current top imports (lines 1-7):

```js
import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';
import { createVarPicker } from '../components/var-picker.js';
import { createInlineVarDrop } from '../components/inline-var-drop.js';
import { createJsonEditor } from '../components/json-editor.js';
import { buildCurlCommand } from '../curl-builder.js';
```

Add one line:

```js
import { createKeyValueTable } from '../components/key-value-table.js';
import { createAssertionBuilder } from '../components/assertion-builder.js';
import { createResponsePanel } from '../components/response-panel.js';
import { createVarPicker } from '../components/var-picker.js';
import { createInlineVarDrop } from '../components/inline-var-drop.js';
import { createJsonEditor } from '../components/json-editor.js';
import { buildCurlCommand } from '../curl-builder.js';
import { applyVarStyle } from '../components/var-style.js';
```

- [ ] **Step 2: Declare the known-vars cache and refresh function, and an auth-inputs tracking array**

`getAllVars()` is defined at line 32-48. Immediately after its closing brace (after line 48, before the blank line / `container.innerHTML = '';` at line 50), add:

```js
  let _knownVarNames = null;
  let _authFieldInputs = [];

  async function _refreshKnownVarNames() {
    const vars = await getAllVars();
    _knownVarNames = new Set(vars.map(v => v.key));
    paramsTable.restyleAll();
    headersTable.restyleAll();
    pathVarsTable.restyleAll();
    _authFieldInputs.forEach(inp => applyVarStyle(inp, _knownVarNames));
  }
```

(This references `paramsTable`/`headersTable`/`pathVarsTable`, which are declared further down with `const` — that's fine, since `_refreshKnownVarNames` is only ever *called* later, after those tables exist; JS function bodies don't evaluate free variables until the function runs.)

- [ ] **Step 3: Pass `getKnownVarNames` to the 3 in-scope tables only**

Current lines 170, 173, 185:

```js
  const paramsTable = createKeyValueTable({ placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars });
```
```js
  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars });
```
```js
  const pathVarsTable = createKeyValueTable({ placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars });
```

Change each to add `getKnownVarNames: () => _knownVarNames`:

```js
  const paramsTable = createKeyValueTable({ placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames });
```
```js
  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames });
```
```js
  const pathVarsTable = createKeyValueTable({ placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames });
```

Do **not** touch lines 436-437 (`formBodyTable`, `multipartBodyTable`) — they must keep calling `createKeyValueTable` without `getKnownVarNames`, preserving the legacy `kv-value--var-ref` behavior.

- [ ] **Step 4: Style auth-field inputs and track them**

Current `_makeField` (lines 523-538):

```js
  function _makeField(labelText, placeholder, getValue, setValue) {
    const wrap = document.createElement('div');
    wrap.className = 'req-auth-field';
    const lbl = document.createElement('label');
    lbl.textContent = labelText;
    const inp = document.createElement('input');
    inp.type = /password|secret/i.test(labelText) ? 'password' : 'text';
    inp.className = 'input-sm';
    inp.placeholder = placeholder;
    inp.value = getValue() || '';
    inp.oninput = () => setValue(inp.value);
    _authInlineDrop.watchInput(inp);
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    return wrap;
  }
```

Change to style the field on input and on creation, and track it:

```js
  function _makeField(labelText, placeholder, getValue, setValue) {
    const wrap = document.createElement('div');
    wrap.className = 'req-auth-field';
    const lbl = document.createElement('label');
    lbl.textContent = labelText;
    const inp = document.createElement('input');
    inp.type = /password|secret/i.test(labelText) ? 'password' : 'text';
    inp.className = 'input-sm';
    inp.placeholder = placeholder;
    inp.value = getValue() || '';
    inp.oninput = () => { setValue(inp.value); applyVarStyle(inp, _knownVarNames); };
    applyVarStyle(inp, _knownVarNames);
    _authInlineDrop.watchInput(inp);
    _authFieldInputs.push(inp);
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    return wrap;
  }
```

- [ ] **Step 5: Reset the tracked-inputs array each time auth fields are rebuilt**

Current `_renderAuthFields` start (lines 540-542):

```js
  function _renderAuthFields(type) {
    _authInlineDrop.close();
    authFieldsDiv.innerHTML = '';
```

Change to:

```js
  function _renderAuthFields(type) {
    _authInlineDrop.close();
    authFieldsDiv.innerHTML = '';
    _authFieldInputs = [];
```

(`_makeField`, called during this same `_renderAuthFields` invocation for whichever auth type is selected, repopulates the array — see Step 4.)

- [ ] **Step 6: Trigger the first load**

Current lines 602-603:

```js
  authTypeSelect.onchange = () => { _renderAuthFields(authTypeSelect.value); _updateAuthBanner(); };
  _renderAuthFields(authTypeSelect.value);
```

Change to:

```js
  authTypeSelect.onchange = () => { _renderAuthFields(authTypeSelect.value); _updateAuthBanner(); };
  _renderAuthFields(authTypeSelect.value);
  _refreshKnownVarNames();
```

(Deliberately not `await`ed — `renderRequestEditor` is `async`, but blocking initial render on this network fetch would add visible latency. `_refreshKnownVarNames` re-styles the already-rendered rows/fields once it resolves.)

- [ ] **Step 7: Verify syntax**

Run: `node --check web/static/api/views/request-editor-view.js`
Expected: no output (exit code 0).

- [ ] **Step 8: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: color {{var}} tokens by exists/missing in headers/params/path-vars/auth"
```

---

### Task 5: Manual browser verification

**Files:** none (verification only)

**Interfaces:** none — end-to-end check of Tasks 1-4 together.

- [ ] **Step 1: Start the dev server**

Run: `python qaclan.py serve --port 7823` (background/separate terminal)

- [ ] **Step 2: Open the request editor for any existing API request (or create one) in a browser at `http://localhost:7823`**

- [ ] **Step 3: Confirm env/collection var setup**

Make sure the active environment (or the request's bound collection) has at least one variable defined, e.g. `token`. If none exists, add one via the Environments UI first.

- [ ] **Step 4: Check the Headers table**

Add a header with value `{{token}}` (using the exact name of a variable that exists). Expected: the value input turns green (`kv-value--var-ok` — uses `--success-bg`/`--success-border`).

Change the value to `{{doesnotexist}}`. Expected: the input turns red (`kv-value--var-missing` — uses `--danger-bg`/`--danger-border`).

Change the value to `Bearer {{token}} {{doesnotexist}}`. Expected: red (mixed = missing, per spec).

Clear the value to plain text with no `{{}}`. Expected: no tint (neutral).

- [ ] **Step 5: Repeat the same check for the Params table and the Path Vars table** (add a `{param}` placeholder to the URL to make the Path Vars section appear, then set its value to a `{{var}}` reference).

- [ ] **Step 6: Check Auth fields**

Set Auth type to "Bearer Token", enter `{{token}}` in the token field. Expected: green. Change to `{{doesnotexist}}`. Expected: red.

- [ ] **Step 7: Confirm out-of-scope surfaces are unchanged**

Add a Form (x-www-form-urlencoded) or Multipart body field with value `{{token}}`. Expected: existing blue `kv-value--var-ref` tint only — no green/red, confirming Task 4 did not touch `formBodyTable`/`multipartBodyTable`.

Type `{{token}}` into the raw JSON body editor and into a pre/post script textarea. Expected: no coloring change there either (out of scope, unaffected by this feature).

- [ ] **Step 8: Report result to the user**

Summarize pass/fail for each check above.
