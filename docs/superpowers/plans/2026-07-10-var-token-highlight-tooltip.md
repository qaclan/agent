# {{var}} Per-Token Text Coloring + Value Tooltip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Color the `{{name}}` substring itself (not the whole field) green/red by exists/missing, show a hover tooltip with the variable's current value, and extend this — plus the existing whole-field tint — to every `{{var}}`-capable surface in the request editor: headers/params/path-vars/auth (already tinted), the URL bar, assertions, pre/post scripts, and the request body (both the CodeMirror editor and its plain-textarea fallback).

**Architecture:** A DOM overlay technique for all plain `<input>`/`<textarea>` surfaces — the real field stays the fully-functional source of truth (value, caret, paste, existing `{{` autocomplete) with its text made transparent, while a synced, non-interactive sibling `<div>` renders the same text with colored `<span>`s per token and drives a shared floating tooltip via mouse-position hit-testing. For the CodeMirror 6 body editor, real inline decorations + CM6's native `hoverTooltip` extension are added, gated on a one-time rebuild of the vendored `cm6.js` bundle (using the scaffold already documented in `REBUILD.md`) to expose `Decoration`/`ViewPlugin`/`RangeSetBuilder`/`StateEffect`/`hoverTooltip`.

**Tech Stack:** Vanilla JS (ES modules), plain CSS custom properties, CodeMirror 6 (vendored, `window.CM6`). No build step for app code (only the one-time CM6 vendor bundle rebuild uses npm/esbuild, in a throwaway directory). No test framework — verification is `node --check` for syntax, throwaway `node` scripts (ESM, `assert`) for pure-function logic, and manual browser checks for DOM/CM6 wiring.

## Global Constraints

- Existing whole-field bg/border tint (`kv-value--var-ok`/`kv-value--var-missing`, from the already-shipped `2026-07-05` feature) is **unchanged** — still only on headers/params/path-vars/auth, still computed by `var-style.js`'s existing `applyVarStyle`/`varTokensIn`. Do not modify those two functions' existing behavior.
- New per-token text coloring uses the solid `--success` (`#10b981`) / `--danger` (`#ef4444`) CSS custom properties as `color`, never `--success-border`/`--danger-border` (those are low-alpha, meant for backgrounds/borders, illegible as text).
- URL bar gets token coloring + tooltip only — no whole-field bg tint, no `{{` autocomplete/var-picker wiring (explicit non-goals, see spec).
- Tooltip always shows the plain variable value — no secret masking (explicit choice, differs from the masking in `var-picker.js`/`inline-var-drop.js` dropdown previews; do not change those).
- Form-urlencoded/multipart body tables, and the `_updateAuthBanner` computed read-only header row, are explicitly out of scope — do not touch.
- Every new DOM-wiring change must preserve existing behavior for `readOnly`/disabled paths and for callers that don't opt into the new `getVarsList` option (backward-compatible, matching how `getKnownVarNames` was added previously).
- Full spec: `docs/superpowers/specs/2026-07-10-var-token-highlight-tooltip-design.md`.

---

### Task 1: CSS — token colors, overlay layout, tooltip

**Files:**
- Modify: `web/static/style.css:1741` (insert after the existing `.kv-value--file` block, before `/* Response panel */`)

**Interfaces:**
- Produces: CSS classes `var-token-overlay-wrap`, `var-token-overlay`, `var-token-overlay--multiline`, `var-tok`, `var-tok--ok`, `var-tok--missing`, `var-tooltip`, `var-tooltip-value`, `var-tooltip-group`, `var-tooltip-missing` — consumed by Task 3 (`var-token-overlay.js`) and Task 8 (CM6 decorations/hover tooltip, which reuses `var-tok--ok`/`var-tok--missing`/`var-tooltip*`).

- [ ] **Step 1: Insert the new CSS block**

Current content at `web/static/style.css:1737-1742`:

```css
.kv-value--file {
  background: color-mix(in srgb, var(--text-muted, #888) 10%, transparent) !important;
  font-style: italic;
  color: var(--text-muted);
}

/* Response panel */
```

Insert a new block between the closing `}` of `.kv-value--file` and the `/* Response panel */` comment:

```css
.kv-value--file {
  background: color-mix(in srgb, var(--text-muted, #888) 10%, transparent) !important;
  font-style: italic;
  color: var(--text-muted);
}

/* Per-token {{var}} text coloring overlay (headers/params/path-vars/auth/
   URL bar/assertions/scripts/body-fallback inputs) — real field's text is
   made transparent; this div renders the same text with colored spans. */
.var-token-overlay-wrap { position: relative; }
.var-token-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  white-space: pre;
  color: var(--text-primary);
  box-sizing: border-box;
  border-style: solid;
  border-color: transparent;
  background: transparent;
}
.var-token-overlay--multiline { white-space: pre-wrap; word-break: break-word; }
.var-tok--ok { color: var(--success); }
.var-tok--missing { color: var(--danger); }

/* Hover tooltip showing a {{var}}'s current value or "not defined" */
.var-tooltip {
  position: fixed;
  z-index: 1003;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  box-shadow: 0 4px 18px rgba(0,0,0,.28);
  padding: 6px 10px;
  font-size: 12px;
  max-width: 320px;
  pointer-events: none;
}
.var-tooltip strong { font-family: var(--font-mono); color: var(--text-primary); }
.var-tooltip-value {
  font-family: var(--font-mono);
  color: var(--text-secondary);
  margin-top: 3px;
  word-break: break-all;
}
.var-tooltip-group {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .05em;
  margin-top: 3px;
}
.var-tooltip-missing { color: var(--danger); margin-top: 3px; }

/* Response panel */
```

- [ ] **Step 2: Verify the file still parses as CSS**

Run: `node -e "require('fs').readFileSync('web/static/style.css','utf8')" && echo READABLE`
Expected: `READABLE` (no CSS linter in this repo — this just confirms the file is intact; visually confirm brace-matching by eye).

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "feat: add CSS for per-token {{var}} coloring overlay + tooltip"
```

---

### Task 2: `var-style.js` — add `tokenSpansIn` + `escapeHtml`

**Files:**
- Modify: `web/static/api/components/var-style.js` (additive only — `varTokensIn`/`applyVarStyle` unchanged)

**Interfaces:**
- Produces:
  - `tokenSpansIn(value: string): Array<{name: string, start: number, end: number}>` — offset-aware sibling of `varTokensIn`; `start`/`end` are indices into `value`, `end` exclusive, covering the full `{{...}}` span.
  - `escapeHtml(s: string): string` — HTML-escapes `&`, `<`, `>`, `"`.
- Consumed by: Task 3 (`var-token-overlay.js`), Task 8 (`json-editor.js`).

- [ ] **Step 1: Add the two exports**

Current full file content:

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

Replace with:

```js
/**
 * Shared {{var}} token extraction + exists/missing CSS styling for plain
 * <input> value fields. Used by key-value-table.js (headers/params/path-vars),
 * request-editor-view.js (auth fields, URL bar, scripts, body fallback),
 * assertion-builder.js, var-token-overlay.js, and json-editor.js.
 */

const _VAR_TOKEN_RE = /\{\{([^}]+)\}\}/g;

export function varTokensIn(value) {
  if (!value) return [];
  return [...value.matchAll(_VAR_TOKEN_RE)].map(m => m[1].trim());
}

export function tokenSpansIn(value) {
  if (!value) return [];
  const spans = [];
  _VAR_TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = _VAR_TOKEN_RE.exec(value)) !== null) {
    spans.push({ name: m[1].trim(), start: m.index, end: m.index + m[0].length });
  }
  return spans;
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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

Create `/tmp/verify-token-spans.mjs`:

```js
import assert from 'node:assert/strict';
import { tokenSpansIn, escapeHtml, varTokensIn } from '/mnt/ext-drive/qaclan/agent/web/static/api/components/var-style.js';

// tokenSpansIn — empty/no-token cases
assert.deepEqual(tokenSpansIn(''), []);
assert.deepEqual(tokenSpansIn('no vars here'), []);

// single token, offsets correct
let spans = tokenSpansIn('{{token}}');
assert.deepEqual(spans, [{ name: 'token', start: 0, end: 9 }]);

// multiple tokens with surrounding text, offsets correct
spans = tokenSpansIn('Bearer {{token}} / {{other}}');
assert.equal(spans.length, 2);
assert.equal(spans[0].name, 'token');
assert.equal('Bearer {{token}} / {{other}}'.slice(spans[0].start, spans[0].end), '{{token}}');
assert.equal(spans[1].name, 'other');
assert.equal('Bearer {{token}} / {{other}}'.slice(spans[1].start, spans[1].end), '{{other}}');

// trimmed name, but offsets cover the raw {{ }} span including whitespace
spans = tokenSpansIn('{{ padded }}');
assert.equal(spans[0].name, 'padded');
assert.equal('{{ padded }}'.slice(spans[0].start, spans[0].end), '{{ padded }}');

// repeated calls don't leak regex lastIndex state (shared module-level regex)
assert.equal(tokenSpansIn('{{a}}').length, 1);
assert.equal(tokenSpansIn('{{a}} {{b}}').length, 2);
assert.equal(tokenSpansIn('{{a}}').length, 1);

// varTokensIn still works unchanged (regression check — shares the same regex object)
assert.deepEqual(varTokensIn('{{token}}'), ['token']);
assert.deepEqual(varTokensIn('Bearer {{token}} / {{other}}'), ['token', 'other']);

// escapeHtml
assert.equal(escapeHtml('<script>'), '&lt;script&gt;');
assert.equal(escapeHtml('a & b'), 'a &amp; b');
assert.equal(escapeHtml('"quoted"'), '&quot;quoted&quot;');
assert.equal(escapeHtml('plain'), 'plain');

console.log('ALL PASS');
```

Run: `node /tmp/verify-token-spans.mjs`
Expected: `ALL PASS`

- [ ] **Step 4: Delete the throwaway script**

Run: `rm /tmp/verify-token-spans.mjs`

- [ ] **Step 5: Commit**

```bash
git add web/static/api/components/var-style.js
git commit -m "feat: add tokenSpansIn + escapeHtml to var-style.js"
```

---

### Task 3: `var-token-overlay.js` — overlay component (input + textarea) with hover tooltip

**Files:**
- Create: `web/static/api/components/var-token-overlay.js`

**Interfaces:**
- Consumes: `tokenSpansIn`, `escapeHtml` from `./var-style.js` (Task 2).
- Produces: `attachTokenOverlay(el: HTMLInputElement|HTMLTextAreaElement, getVarsList: () => Array<{key, value, group?}>|null): { refresh(): void, el: HTMLDivElement }`. `el.parentNode` (if any) gets `wrap` inserted in its place and `el` moved inside `wrap`; callers must append/use the returned `.el` (the wrap) wherever they were going to place the original element.
- Consumed by: Task 4 (`key-value-table.js`), Task 5 (`assertion-builder.js`), Task 6 (`request-editor-view.js` — auth fields, URL bar, scripts, body fallback).

- [ ] **Step 1: Write the module**

Create `web/static/api/components/var-token-overlay.js`:

```js
/**
 * attachTokenOverlay(el, getVarsList) → { refresh(), el: wrap }
 *
 * Colors {{name}} tokens inside a plain <input> or <textarea> green/red by
 * whether the name is in the list getVarsList() returns, and shows a hover
 * tooltip with the variable's current value (or "not defined").
 *
 * Technique: the real element stays the source of truth for editing (value,
 * caret, selection, paste, any existing `{{` autocomplete wiring) — only its
 * text color is made transparent. A synced, pointer-events:none sibling <div>
 * (the "overlay") renders the same text with colored <span>s on top. Because
 * the overlay ignores pointer events, all clicks/typing still reach the real
 * element underneath; hover detection is done via mousemove rect-testing
 * against the overlay's own (visually on-top, but non-interactive) spans.
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

let _tooltipEl = null;
function _getTooltipEl() {
  if (_tooltipEl) return _tooltipEl;
  _tooltipEl = document.createElement('div');
  _tooltipEl.className = 'var-tooltip';
  _tooltipEl.style.display = 'none';
  document.body.appendChild(_tooltipEl);
  return _tooltipEl;
}

function _showTooltip(rect, name, entry) {
  const tip = _getTooltipEl();
  tip.innerHTML = entry
    ? `<strong>{{${escapeHtml(name)}}}</strong>` +
      `<div class="var-tooltip-value">${escapeHtml(String(entry.value ?? ''))}</div>` +
      (entry.group ? `<div class="var-tooltip-group">${escapeHtml(entry.group)}</div>` : '')
    : `<strong>{{${escapeHtml(name)}}}</strong>` +
      `<div class="var-tooltip-missing">Not defined in environment or collection</div>`;
  tip.style.display = 'block';
  const tipRect = tip.getBoundingClientRect();
  const below = window.innerHeight - rect.bottom;
  const top = below >= tipRect.height + 8 ? rect.bottom + 6 : rect.top - tipRect.height - 6;
  const left = Math.min(rect.left, window.innerWidth - tipRect.width - 8);
  tip.style.top = Math.max(4, top) + 'px';
  tip.style.left = Math.max(4, left) + 'px';
}

function _hideTooltip() {
  if (_tooltipEl) _tooltipEl.style.display = 'none';
}

export function attachTokenOverlay(el, getVarsList) {
  const isTextarea = el.tagName === 'TEXTAREA';

  const wrap = document.createElement('div');
  wrap.className = 'var-token-overlay-wrap';
  if (el.parentNode) el.parentNode.insertBefore(wrap, el);
  wrap.appendChild(el);

  const overlay = document.createElement('div');
  overlay.className = 'var-token-overlay' + (isTextarea ? ' var-token-overlay--multiline' : '');
  wrap.appendChild(overlay); // appended AFTER el so it paints on top; pointer-events:none lets clicks fall through

  const cs = getComputedStyle(el);
  const originalCaretColor = cs.color;
  [
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'fontFamily', 'fontSize', 'fontWeight', 'letterSpacing', 'lineHeight',
  ].forEach(prop => { overlay.style[prop] = cs[prop]; });

  el.style.color = 'transparent';
  el.style.caretColor = originalCaretColor;

  function _render() {
    const value = el.value;
    const list = getVarsList ? getVarsList() : null;
    let html = '';
    let last = 0;
    tokenSpansIn(value).forEach(({ name, start, end }) => {
      html += escapeHtml(value.slice(last, start));
      const known = list ? list.some(v => v.key === name) : null;
      const cls = known == null ? 'var-tok' : known ? 'var-tok var-tok--ok' : 'var-tok var-tok--missing';
      html += `<span class="${cls}">${escapeHtml(value.slice(start, end))}</span>`;
      last = end;
    });
    html += escapeHtml(value.slice(last));
    overlay.innerHTML = html;
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  }

  el.addEventListener('input', _render);
  el.addEventListener('scroll', () => {
    overlay.scrollLeft = el.scrollLeft;
    if (isTextarea) overlay.scrollTop = el.scrollTop;
  });

  el.addEventListener('mousemove', (e) => {
    const spans = overlay.querySelectorAll('.var-tok--ok, .var-tok--missing');
    for (const span of spans) {
      const r = span.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        const name = span.textContent.replace(/^\{\{|\}\}$/g, '').trim();
        const list = getVarsList ? getVarsList() : null;
        const entry = list ? list.find(v => v.key === name) || null : null;
        _showTooltip(r, name, entry);
        return;
      }
    }
    _hideTooltip();
  });
  el.addEventListener('mouseleave', _hideTooltip);

  _render();

  return { refresh: _render, el: wrap };
}
```

- [ ] **Step 2: Verify syntax**

Run: `node --check web/static/api/components/var-token-overlay.js`
Expected: no output (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/var-token-overlay.js
git commit -m "feat: add var-token-overlay.js for per-token {{var}} coloring + tooltip"
```

(No throwaway `node` verification script here, unlike Task 2 — this module is entirely DOM-driven (`document.createElement`, `getComputedStyle`, `getBoundingClientRect`), so a Node-only script can't meaningfully exercise it. It's covered by Task 10's manual browser check instead.)

---

### Task 4: `key-value-table.js` — wire `attachTokenOverlay` for value inputs

**Files:**
- Modify: `web/static/api/components/key-value-table.js`

**Interfaces:**
- Consumes: `attachTokenOverlay` from `./var-token-overlay.js` (Task 3).
- Produces: `createKeyValueTable(options)` gains optional `options.getVarsList: () => Array<{key,value,group?}>|null` (independent of, and alongside, the existing `getKnownVarNames` option — `getKnownVarNames` still drives the unchanged whole-field bg tint; `getVarsList` drives the new per-token overlay). `restyleAll()` additionally refreshes all attached overlays.

**Note:** in this codebase, `getVarsList` is only ever passed for tables without `fileFieldsEnabled` (params/headers/path-vars — see Task 6; form/multipart body tables pass neither option). `_setFileState`'s programmatic `valInput.value = '📎 ...'` assignment doesn't dispatch an `'input'` event, so if `getVarsList` were ever combined with `fileFieldsEnabled` on the same table, the overlay could show stale content after a file attach — not an issue today given the current call sites, but worth knowing if that combination is ever introduced later.

- [ ] **Step 1: Import the helper and add a per-table overlay-tracking array**

Current lines 1-3, 44-45:

```js
import { createVarPicker } from './var-picker.js';
import { createInlineVarDrop } from './inline-var-drop.js';
import { applyVarStyle } from './var-style.js';
```

```js
  const _picker = varPickerEnabled ? createVarPicker({ getVars }) : null;
  const _inlineDrop = varPickerEnabled ? createInlineVarDrop(getVars) : null;
```

Change to:

```js
import { createVarPicker } from './var-picker.js';
import { createInlineVarDrop } from './inline-var-drop.js';
import { applyVarStyle } from './var-style.js';
import { attachTokenOverlay } from './var-token-overlay.js';
```

```js
  const _picker = varPickerEnabled ? createVarPicker({ getVars }) : null;
  const _inlineDrop = varPickerEnabled ? createInlineVarDrop(getVars) : null;
  const _overlays = [];
```

- [ ] **Step 2: Add the new option**

Current lines 19-27:

```js
  const {
    placeholder = { key: 'Key', value: 'Value' },
    readOnly = false,
    varPickerEnabled = false,
    getVars = async () => [],
    fileFieldsEnabled = false,
    getKnownVarNames = null,
    onChange = null,
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
    getVarsList = null,
    onChange = null,
  } = options;
```

- [ ] **Step 3: Attach the overlay when creating each row's value input**

Current lines 124-139:

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
      if (onChange) valInput.addEventListener('input', onChange);
      if (varPickerEnabled) _inlineDrop.watchInput(valInput);
    }
```

Change to:

```js
    const valTd = document.createElement('td');
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'kv-value input-sm';
    valInput.placeholder = placeholder.value;
    valInput.value = data.value || '';
    valInput.readOnly = readOnly;
    _styleValueInput(valInput);
    if (getVarsList) {
      const overlay = attachTokenOverlay(valInput, getVarsList);
      _overlays.push(overlay);
      valTd.appendChild(overlay.el);
    } else {
      valTd.appendChild(valInput);
    }
    tr.appendChild(valTd);

    if (!readOnly) {
      valInput.addEventListener('input', () => _styleValueInput(valInput));
      if (onChange) valInput.addEventListener('input', onChange);
      if (varPickerEnabled) _inlineDrop.watchInput(valInput);
    }
```

(`tr.querySelector('.kv-value')`/`.kv-key'` used elsewhere in `getRows()`/`_setFileState`/`restyleAll` still find `valInput` correctly — `querySelector`/`querySelectorAll` search the full subtree, so the extra `.var-token-overlay-wrap` nesting level doesn't break them.)

- [ ] **Step 4: Reset the overlay array in `setRows`, refresh overlays in `restyleAll`**

Current lines 252-262:

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

Change to:

```js
  function setRows(rows = []) {
    tbody.innerHTML = '';
    _overlays.length = 0;
    rows.forEach(r => _addRow(r));
  }

  function restyleAll() {
    tbody.querySelectorAll('.kv-value').forEach(_styleValueInput);
    _overlays.forEach(o => o.refresh());
  }

  return { el: wrapper, getRows, setRows, restyleAll };
}
```

- [ ] **Step 5: Verify syntax**

Run: `node --check web/static/api/components/key-value-table.js`
Expected: no output (exit code 0).

- [ ] **Step 6: Commit**

```bash
git add web/static/api/components/key-value-table.js
git commit -m "feat: key-value-table gains optional getVarsList token overlay"
```

---

### Task 5: `assertion-builder.js` — `getVarsList` option + overlay wiring

**Files:**
- Modify: `web/static/api/components/assertion-builder.js`

**Interfaces:**
- Consumes: `attachTokenOverlay` from `./var-token-overlay.js` (Task 3), `applyVarStyle` from `./var-style.js` (already shipped, unchanged signature).
- Produces: `createAssertionBuilder(options?)` — new signature, `options.getVarsList?: () => Array<{key,value,group?}>|null`. Returned object gains `restyleAll(): void` alongside existing `{ el, getAssertions, setAssertions }`.

- [ ] **Step 1: Add imports and the options parameter**

Current lines 1-5:

```js
/**
 * createAssertionBuilder() → { el, getAssertions, setAssertions }
 * Assertion shape: {type, path?, key?, op, value}
 */
export function createAssertionBuilder() {
  const wrapper = document.createElement('div');
```

Change to:

```js
/**
 * createAssertionBuilder(options?) → { el, getAssertions, setAssertions, restyleAll }
 * options.getVarsList?: () => Array<{key, value, group?}>|null — when provided,
 * the path/expected-value inputs get per-token {{var}} coloring + hover
 * tooltip, and the expected-value input additionally gets the whole-field
 * kv-value--var-ok/--missing bg tint.
 * Assertion shape: {type, path?, key?, op, value}
 */
import { attachTokenOverlay } from './var-token-overlay.js';
import { applyVarStyle } from './var-style.js';

export function createAssertionBuilder(options = {}) {
  const { getVarsList = null } = options;
  const _overlays = [];
  const wrapper = document.createElement('div');
```

- [ ] **Step 2: Wire the overlay + bg tint into `_addRow`**

Current lines 34-109 (full `_addRow`):

```js
  function _addRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'assertion-row';

    // Type select
    const typeSelect = document.createElement('select');
    typeSelect.className = 'assertion-type input-sm';
    ['status', 'json_path', 'header', 'response_time', 'body_text'].forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = data.type || 'status';
    row.appendChild(typeSelect);

    // Dynamic path/key field (shown for json_path and header)
    const extraInput = document.createElement('input');
    extraInput.type = 'text';
    extraInput.className = 'assertion-extra input-sm';
    extraInput.placeholder = '$.path or header-key';
    extraInput.value = data.path || data.key || '';
    row.appendChild(extraInput);

    // Operator select
    const opSelect = document.createElement('select');
    opSelect.className = 'assertion-op input-sm';
    row.appendChild(opSelect);

    // Value input
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'assertion-value input-sm';
    valInput.placeholder = 'expected value';
    valInput.value = data.value !== undefined ? String(data.value) : '';
    row.appendChild(valInput);

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
    delBtn.textContent = '×';
    delBtn.onclick = () => row.remove();
    row.appendChild(delBtn);

    function _updateUI() {
      const t = typeSelect.value;
      const ops = TYPE_OPS[t] || ['eq'];

      // Rebuild op options
      opSelect.innerHTML = '';
      ops.forEach(op => {
        const opt = document.createElement('option');
        opt.value = op;
        opt.textContent = OP_LABELS[op] || op;
        opSelect.appendChild(opt);
      });
      if (data.op && ops.includes(data.op)) opSelect.value = data.op;

      // Show/hide extra input
      const needsExtra = (t === 'json_path' || t === 'header');
      extraInput.style.display = needsExtra ? '' : 'none';
      extraInput.placeholder = t === 'json_path' ? '$.path' : 'Header-Name';

      // Show/hide value (exists/not_exists don't need it)
      const op = opSelect.value;
      valInput.style.display = (op === 'exists' || op === 'not_exists') ? 'none' : '';
    }

    typeSelect.onchange = _updateUI;
    opSelect.onchange = _updateUI;
    _updateUI();

    list.appendChild(row);
    return row;
  }
```

Replace with:

```js
  function _addRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'assertion-row';

    // Type select
    const typeSelect = document.createElement('select');
    typeSelect.className = 'assertion-type input-sm';
    ['status', 'json_path', 'header', 'response_time', 'body_text'].forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = data.type || 'status';
    row.appendChild(typeSelect);

    // Dynamic path/key field (shown for json_path and header)
    const extraInput = document.createElement('input');
    extraInput.type = 'text';
    extraInput.className = 'assertion-extra input-sm';
    extraInput.placeholder = '$.path or header-key';
    extraInput.value = data.path || data.key || '';
    let extraOverlay = null;
    if (getVarsList) {
      extraOverlay = attachTokenOverlay(extraInput, getVarsList);
      _overlays.push(extraOverlay);
      row.appendChild(extraOverlay.el);
    } else {
      row.appendChild(extraInput);
    }

    // Operator select
    const opSelect = document.createElement('select');
    opSelect.className = 'assertion-op input-sm';
    row.appendChild(opSelect);

    // Value input
    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'assertion-value input-sm';
    valInput.placeholder = 'expected value';
    valInput.value = data.value !== undefined ? String(data.value) : '';
    function _styleValInput() {
      if (getVarsList) applyVarStyle(valInput, new Set((getVarsList() || []).map(v => v.key)));
    }
    _styleValInput();
    let valOverlay = null;
    if (getVarsList) {
      valInput.addEventListener('input', _styleValInput);
      valOverlay = attachTokenOverlay(valInput, getVarsList);
      _overlays.push(valOverlay);
      row.appendChild(valOverlay.el);
    } else {
      row.appendChild(valInput);
    }

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-xs btn-ghost btn-icon-danger';
    delBtn.textContent = '×';
    delBtn.onclick = () => row.remove();
    row.appendChild(delBtn);

    function _updateUI() {
      const t = typeSelect.value;
      const ops = TYPE_OPS[t] || ['eq'];

      // Rebuild op options
      opSelect.innerHTML = '';
      ops.forEach(op => {
        const opt = document.createElement('option');
        opt.value = op;
        opt.textContent = OP_LABELS[op] || op;
        opSelect.appendChild(opt);
      });
      if (data.op && ops.includes(data.op)) opSelect.value = data.op;

      // Show/hide extra input (toggle the overlay wrap when present, not the
      // inner input directly — the sibling overlay div isn't hidden by the
      // input's own display:none, so it must be the thing that's toggled)
      const needsExtra = (t === 'json_path' || t === 'header');
      (extraOverlay ? extraOverlay.el : extraInput).style.display = needsExtra ? '' : 'none';
      extraInput.placeholder = t === 'json_path' ? '$.path' : 'Header-Name';

      // Show/hide value (exists/not_exists don't need it)
      const op = opSelect.value;
      (valOverlay ? valOverlay.el : valInput).style.display = (op === 'exists' || op === 'not_exists') ? 'none' : '';
    }

    typeSelect.onchange = _updateUI;
    opSelect.onchange = _updateUI;
    _updateUI();

    list.appendChild(row);
    return row;
  }
```

- [ ] **Step 3: Reset overlays in `setAssertions`, add `restyleAll`, return it**

Current lines 130-136:

```js
  function setAssertions(assertions = []) {
    list.innerHTML = '';
    assertions.forEach(a => _addRow(a));
  }

  return { el: wrapper, getAssertions, setAssertions };
}
```

Change to:

```js
  function setAssertions(assertions = []) {
    list.innerHTML = '';
    _overlays.length = 0;
    assertions.forEach(a => _addRow(a));
  }

  function restyleAll() {
    _overlays.forEach(o => o.refresh());
    if (getVarsList) {
      const known = new Set((getVarsList() || []).map(v => v.key));
      list.querySelectorAll('.assertion-value').forEach(inp => applyVarStyle(inp, known));
    }
  }

  return { el: wrapper, getAssertions, setAssertions, restyleAll };
}
```

- [ ] **Step 4: Verify syntax**

Run: `node --check web/static/api/components/assertion-builder.js`
Expected: no output (exit code 0).

- [ ] **Step 5: Commit**

```bash
git add web/static/api/components/assertion-builder.js
git commit -m "feat: assertion-builder gains optional getVarsList token overlay + bg tint"
```

---

### Task 6: `request-editor-view.js` — wire URL bar, auth fields, scripts, body fallback, assertions, and refresh

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: `attachTokenOverlay` (Task 3), `getVarsList`/`restyleAll` from `key-value-table.js` (Task 4), `getVarsList`/`restyleAll` from `assertion-builder.js` (Task 5).
- Produces: nothing consumed by a later task in this file except Task 9, which extends `_refreshKnownVarNames`'s already-written body (this task adds the `_cmEditor?.refresh?.()` call defensively now, guarded with optional chaining, so Task 9 doesn't need to touch this function again).
- **Depends on Tasks 3, 4, 5 being complete** (imports/options this task uses).

- [ ] **Step 1: Import `attachTokenOverlay`**

Current line 8:

```js
import { applyVarStyle } from '../components/var-style.js';
```

Change to:

```js
import { applyVarStyle } from '../components/var-style.js';
import { attachTokenOverlay } from '../components/var-token-overlay.js';
```

- [ ] **Step 2: Add overlay-tracking state and the full new `_refreshKnownVarNames`**

Current lines 51-61:

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

Change to:

```js
  let _knownVarNames = null;
  let _allVarsList = null;
  let _authFieldInputs = [];
  let _authFieldOverlays = [];
  let _urlOverlay = null;
  let _scriptTextareaOverlays = [];
  let _bodyFallbackOverlay = null;

  async function _refreshKnownVarNames() {
    const vars = await getAllVars();
    _knownVarNames = new Set(vars.map(v => v.key));
    _allVarsList = vars;
    paramsTable.restyleAll();
    headersTable.restyleAll();
    pathVarsTable.restyleAll();
    _authFieldInputs.forEach(inp => applyVarStyle(inp, _knownVarNames));
    _authFieldOverlays.forEach(o => o.refresh());
    _urlOverlay?.refresh();
    _scriptTextareaOverlays.forEach(o => o.refresh());
    _bodyFallbackOverlay?.refresh();
    assertionBuilder.restyleAll();
    _cmEditor?.refresh?.();
  }
```

(`assertionBuilder` and `_cmEditor` are declared later in the file — line 325 and line 395 respectively, both before line 706 where `_refreshKnownVarNames()` is actually *called* — same "declared-before-call, not before-definition" pattern this function already relied on for `paramsTable`/`headersTable`/`pathVarsTable`. `_cmEditor?.refresh?.()` uses double optional chaining because Task 9 — which adds a real `.refresh()` method to CM editor objects — hasn't run yet at the point this step lands; the guard makes this line safe both before and after Task 9.)

- [ ] **Step 3: Add `getVarsList` to the three in-scope `createKeyValueTable` calls**

Current lines 223-226:

```js
  const paramsTable = createKeyValueTable({
    placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    onChange: () => _syncUrlFromQueryParams(),
  });
```

Change to:

```js
  const paramsTable = createKeyValueTable({
    placeholder: { key: 'Parameter', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    getVarsList: () => _allVarsList,
    onChange: () => _syncUrlFromQueryParams(),
  });
```

Current line 240:

```js
  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames });
```

Change to:

```js
  const headersTable = createKeyValueTable({ placeholder: { key: 'Header', value: 'Value' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList });
```

Current lines 252-255:

```js
  const pathVarsTable = createKeyValueTable({
    placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    onChange: () => _syncUrlFromPathVars(),
  });
```

Change to:

```js
  const pathVarsTable = createKeyValueTable({
    placeholder: { key: 'param', value: 'value or {{VAR}}' }, varPickerEnabled: true, getVars: getAllVars, getKnownVarNames: () => _knownVarNames,
    getVarsList: () => _allVarsList,
    onChange: () => _syncUrlFromPathVars(),
  });
```

- [ ] **Step 4: Wire the URL bar overlay**

Current lines 103-108:

```js
  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'req-url-input';
  urlInput.placeholder = 'https://api.example.com/endpoint';
  urlInput.value = r.url || '';
  urlBar.appendChild(urlInput);
```

Change to:

```js
  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'req-url-input';
  urlInput.placeholder = 'https://api.example.com/endpoint';
  urlInput.value = r.url || '';
  _urlOverlay = attachTokenOverlay(urlInput, () => _allVarsList);
  urlBar.appendChild(_urlOverlay.el);
```

(No whole-field bg tint and no `{{` autocomplete for the URL bar — per spec, explicit non-goals. Everything else referencing `urlInput` elsewhere in the file — `.value`, `.addEventListener('input'/'paste', ...)`, `_syncPathVars()`, etc. — is unaffected, since `urlInput` keeps its identity; only where it's appended to the DOM changes.)

- [ ] **Step 5: Wire the auth-field overlay**

Current lines 622-639 (`_makeField`):

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

Change to:

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
    const overlay = attachTokenOverlay(inp, () => _allVarsList);
    _authFieldOverlays.push(overlay);
    wrap.appendChild(lbl);
    wrap.appendChild(overlay.el);
    return wrap;
  }
```

(Works uniformly for `type="password"` fields too — the browser's masking dots are drawn in `currentColor`, so `el.style.color = 'transparent'` inside `attachTokenOverlay` hides them the same way it hides normal text, letting the overlay's colored spans show through.)

- [ ] **Step 6: Wire the script-textarea overlay**

Current lines 921-931 (inside `makeScriptSection`):

```js
    const textarea = document.createElement('textarea');
    textarea.className = 'input-sm';
    textarea.style.cssText = 'width:100%;min-height:110px;font-family:var(--font-mono);font-size:12px;';
    const _ph = (l) => l === 'python'
      ? 'qc.set("token", response.json()["access_token"])'
      : 'qc.set("token", response.json().access_token)';
    textarea.placeholder = _ph(lang || 'js');
    langSelect.onchange = () => { textarea.placeholder = _ph(langSelect.value); };
    textarea.value = code || '';
    div.appendChild(textarea);
    _scriptInlineDrop.watchInput(textarea);
```

Change to:

```js
    const textarea = document.createElement('textarea');
    textarea.className = 'input-sm';
    textarea.style.cssText = 'width:100%;min-height:110px;font-family:var(--font-mono);font-size:12px;';
    const _ph = (l) => l === 'python'
      ? 'qc.set("token", response.json()["access_token"])'
      : 'qc.set("token", response.json().access_token)';
    textarea.placeholder = _ph(lang || 'js');
    langSelect.onchange = () => { textarea.placeholder = _ph(langSelect.value); };
    textarea.value = code || '';
    const scriptOverlay = attachTokenOverlay(textarea, () => _allVarsList);
    _scriptTextareaOverlays.push(scriptOverlay);
    div.appendChild(scriptOverlay.el);
    _scriptInlineDrop.watchInput(textarea);
```

(`makeScriptSection` runs twice — once each for `makePreScriptSection`/`makePostScriptSection` — so `_scriptTextareaOverlays` ends up with 2 entries, matching the 2 script fields.)

- [ ] **Step 7: Wire the body-fallback overlay**

Current lines 387-390:

```js
  const bodyFallback = document.createElement('textarea');
  bodyFallback.className = 'input-sm body-json-editor';
  bodyFallback.style.cssText = 'width:100%;min-height:180px;font-family:var(--font-mono);font-size:12px;line-height:1.6;margin-top:4px;resize:vertical;tab-size:2;display:none;';
  bodyFallback.spellcheck = false;
```

Change to (note `display:none;` moved out of `bodyFallback`'s own inline style — visibility for this field is now owned entirely by the overlay wrap, since a hidden inner `<textarea>` would leave its sibling overlay `<div>` still visibly showing colored text with no field around it):

```js
  const bodyFallback = document.createElement('textarea');
  bodyFallback.className = 'input-sm body-json-editor';
  bodyFallback.style.cssText = 'width:100%;min-height:180px;font-family:var(--font-mono);font-size:12px;line-height:1.6;margin-top:4px;resize:vertical;tab-size:2;';
  bodyFallback.spellcheck = false;
  _bodyFallbackOverlay = attachTokenOverlay(bodyFallback, () => _allVarsList);
  _bodyFallbackOverlay.el.style.display = 'none';
```

Current lines 514-520 (inside `_activateCmEditor`):

```js
    if (!_cmEditor) {
      // CM unavailable — show fallback textarea instead
      cmWrap.style.display = 'none';
      bodyFallback.value = val;
      bodyFallback.style.display = '';
      jsonErrorEl.style.display = 'none';
    }
```

Change to:

```js
    if (!_cmEditor) {
      // CM unavailable — show fallback textarea instead
      cmWrap.style.display = 'none';
      bodyFallback.value = val;
      _bodyFallbackOverlay.el.style.display = '';
      jsonErrorEl.style.display = 'none';
    }
```

Current lines 553-561 (inside `_setBodyType`, leaving text mode):

```js
    if (!isText && _cmEditor) {
      // Leaving text mode — read current value before destroying
      bodyTextarea.value = _cmEditor.getValue();
      _cmEditor.destroy();
      _cmEditor = null;
      cmWrap.style.display = 'none';
      bodyFallback.style.display = 'none';
      _cmActive = false;
    }
```

Change to:

```js
    if (!isText && _cmEditor) {
      // Leaving text mode — read current value before destroying
      bodyTextarea.value = _cmEditor.getValue();
      _cmEditor.destroy();
      _cmEditor = null;
      cmWrap.style.display = 'none';
      _bodyFallbackOverlay.el.style.display = 'none';
      _cmActive = false;
    }
```

Current lines 572-579 (inside `_setBodyType`, entering text mode):

```js
    if (isText) {
      _cmActive = true;
      cmWrap.style.display = '';
      bodyFallback.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      if (type === 'graphql') bodyFallback.placeholder = '{ "query": "{ users { id name } }" }';
      else bodyFallback.placeholder = '{\n  "key": "value"\n}';
    }
```

Change to:

```js
    if (isText) {
      _cmActive = true;
      cmWrap.style.display = '';
      _bodyFallbackOverlay.el.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      if (type === 'graphql') bodyFallback.placeholder = '{ "query": "{ users { id name } }" }';
      else bodyFallback.placeholder = '{\n  "key": "value"\n}';
    }
```

Current line 587:

```js
  bodySection.appendChild(bodyFallback);
```

Change to:

```js
  bodySection.appendChild(_bodyFallbackOverlay.el);
```

- [ ] **Step 8: Pass `getVarsList` into `createAssertionBuilder`**

Current line 325:

```js
  const assertionBuilder = createAssertionBuilder();
```

Change to:

```js
  const assertionBuilder = createAssertionBuilder({ getVarsList: () => _allVarsList });
```

- [ ] **Step 9: Verify syntax**

Run: `node --check web/static/api/views/request-editor-view.js`
Expected: no output (exit code 0).

- [ ] **Step 10: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: wire per-token {{var}} overlay into URL bar, auth, scripts, body fallback, assertions"
```

---

### Task 7: Rebuild vendored CM6 bundle with decoration + hover-tooltip primitives

**Files:**
- Modify: `web/static/vendor/codemirror/REBUILD.md` (consolidate the two illustrative `entry.js` snippets into one accurate, complete one)
- Modify: `web/static/vendor/codemirror/cm6.js` (regenerated bundle)

**Interfaces:**
- Produces: `window.CM6` gains `Decoration`, `ViewPlugin`, `ViewUpdate`, `RangeSetBuilder`, `StateEffect`, `hoverTooltip` alongside its existing exports (`EditorState, EditorView, Compartment, basicSetup, oneDark, indentUnit, python, javascript, json, jsonParseLinter, linter, lintGutter`). Consumed by Task 8 (`json-editor.js`).
- **Soft dependency:** if this task can't complete (e.g. no npm registry access in the build environment), Task 8's feature-detection guard means the CM6 body editor simply keeps working exactly as it does today, without token coloring — every other task in this plan ships independently either way.

- [ ] **Step 1: Update `REBUILD.md`'s documented `entry.js` to the final, accurate version**

Current `web/static/vendor/codemirror/REBUILD.md` has two illustrative snippets under `## entry.js` (lines 59-107) and `## entry.js with scafolding` (lines 109-168). Replace both sections (from the `## entry.js` heading on line 59 through the end of the second code block, just before `## Notes` on line 170) with a single, complete, accurate section:

```markdown
## entry.js

This is the actual entry point used to produce the committed `cm6.js` —
keep it in sync with reality (json language + lint support, plus the
decoration/hover-tooltip primitives used for {{var}} highlighting) so a
future rebuild doesn't silently drop functionality.

```js
import { EditorState, Compartment, RangeSetBuilder, StateEffect } from "@codemirror/state"
import {
  EditorView, keymap, lineNumbers, highlightActiveLine,
  highlightActiveLineGutter, drawSelection,
  Decoration, ViewPlugin, ViewUpdate, hoverTooltip,
} from "@codemirror/view"
import {
  defaultKeymap, indentWithTab, history, historyKeymap,
} from "@codemirror/commands"
import {
  indentOnInput, bracketMatching, syntaxHighlighting,
  defaultHighlightStyle, foldGutter, foldKeymap, indentUnit,
} from "@codemirror/language"
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search"
import { python } from "@codemirror/lang-python"
import { javascript } from "@codemirror/lang-javascript"
import { json, jsonParseLinter } from "@codemirror/lang-json"
import { linter, lintGutter } from "@codemirror/lint"
import { oneDark } from "@codemirror/theme-one-dark"

function basicSetup() {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightActiveLine(),
    foldGutter(),
    drawSelection(),
    history(),
    indentUnit.of("    "),  // 4-space indent (Python convention)
    indentOnInput(),
    bracketMatching(),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    highlightSelectionMatches(),
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      ...foldKeymap,
      ...searchKeymap,
      indentWithTab,
    ]),
  ]
}

window.CM6 = {
  EditorState, Compartment, RangeSetBuilder, StateEffect,
  EditorView, Decoration, ViewPlugin, ViewUpdate, hoverTooltip,
  basicSetup, oneDark, indentUnit,
  python, javascript, json, jsonParseLinter, linter, lintGutter,
}
```
```

- [ ] **Step 2: Run the rebuild**

```bash
mkdir -p /tmp/cm6-bundle && cd /tmp/cm6-bundle

cat > package.json << 'EOF'
{ "name": "cm6-bundle", "version": "1.0.0", "private": true }
EOF

npm install --silent --no-audit --no-fund \
  @codemirror/state@6 \
  @codemirror/view@6 \
  @codemirror/commands@6 \
  @codemirror/language@6 \
  @codemirror/search@6 \
  @codemirror/lang-python@6 \
  @codemirror/lang-javascript@6 \
  @codemirror/lang-json@6 \
  @codemirror/lint@6 \
  @codemirror/theme-one-dark@6 \
  esbuild@0.24
```

Then write `entry.js` in `/tmp/cm6-bundle/` with the exact content from Step 1's updated `REBUILD.md` (the `window.CM6 = {...}` version, not a partial one), and bundle it:

```bash
./node_modules/.bin/esbuild entry.js \
  --bundle --format=iife --minify --target=es2019 \
  --outfile=cm6.js

cp cm6.js /mnt/ext-drive/qaclan/agent/web/static/vendor/codemirror/cm6.js

cd && rm -rf /tmp/cm6-bundle
```

- [ ] **Step 3: Verify the new bundle**

Run: `node --check web/static/vendor/codemirror/cm6.js`
Expected: no output (exit code 0) — confirms the minified IIFE is syntactically valid JS.

Run: `grep -o 'window\.CM6=[^;]*' web/static/vendor/codemirror/cm6.js | grep -o 'Decoration\|ViewPlugin\|RangeSetBuilder\|StateEffect\|hoverTooltip\|ViewUpdate' | sort -u`
Expected output (order may vary):
```
Decoration
RangeSetBuilder
StateEffect
ViewPlugin
ViewUpdate
hoverTooltip
```
(esbuild's minifier renames internal variable identifiers but never renames object-literal property keys, so these names survive as literal strings in the final `window.CM6 = {...}` assignment even though the bundle is otherwise minified.)

- [ ] **Step 4: Commit**

```bash
git add web/static/vendor/codemirror/cm6.js web/static/vendor/codemirror/REBUILD.md
git commit -m "chore: rebuild CM6 vendor bundle with decoration + hoverTooltip primitives"
```

If Step 2 can't complete (no npm registry access in this environment), stop here, leave `cm6.js`/`REBUILD.md` unmodified, and skip directly to Task 10 noting Task 7/8/9 as blocked — Tasks 1-6 are already fully shipped and independent of this one.

---

### Task 8: `json-editor.js` — CM6 decorations + hover tooltip for the body editor

**Files:**
- Modify: `web/static/api/components/json-editor.js`

**Interfaces:**
- Consumes: `tokenSpansIn`, `escapeHtml` from `../components/var-style.js` (Task 2); `Decoration`/`ViewPlugin`/`RangeSetBuilder`/`StateEffect`/`hoverTooltip` from `window.CM6` (Task 7).
- Produces: `createJsonEditor({parent, value, isDark, onChange, getVarsList})` — new `getVarsList` option. Returned editor object gains `refresh(): void` (no-op if the vendor bundle lacks the decoration primitives or `getVarsList` wasn't passed).
- **Depends on Task 2** for the import. Works standalone even before Task 7 lands — `hasTokenSupport` feature-detects and no-ops gracefully, matching the existing `createJsonEditor` → `null` fallback pattern already in this codebase.

- [ ] **Step 1: Replace the file content**

Current full file content (`web/static/api/components/json-editor.js`, 84 lines):

```js
/**
 * createJsonEditor({ parent, value, isDark, onChange }) → Promise<editor|null>
 * Uses the bundled CM6 from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 unavailable.
 * editor: { getValue(), setValue(str), focus(), destroy() }
 */

export async function createJsonEditor({ parent, value = '', isDark = true, onChange }) {
  try {
    const CM = window.CM6;
    if (!CM) throw new Error('CM6 vendor bundle not loaded');

    const { EditorView, EditorState, basicSetup, json, jsonParseLinter, linter, lintGutter, oneDark } = CM;

    // Custom linter that understands {{VAR}} template syntax
    const varAwareLinter = linter((view) => {
      const text = view.state.doc.toString().trim();
      if (!text) return [];
      const subbed = text.replace(/\{\{[^}]+\}\}/g, '"__QCVAR__"');
      try { JSON.parse(subbed); return []; }
      catch (e) {
        const m = /at position (\d+)/i.exec(e.message) || /position (\d+)/i.exec(e.message);
        const pos = m ? Math.min(+m[1], text.length - 1) : 0;
        return [{ from: pos, to: Math.min(pos + 1, text.length), severity: 'error', message: e.message }];
      }
    });

    const baseTheme = EditorView.theme({
      '&': {
        fontSize: '12px',
        border: '1px solid var(--border-default)',
        borderRadius: '6px',
        overflow: 'hidden',
        marginTop: '4px',
      },
      '.cm-scroller': {
        fontFamily: 'var(--font-mono, monospace)',
        lineHeight: '1.6',
        minHeight: '180px',
        maxHeight: '500px',
        overflow: 'auto',
      },
      '.cm-content': { padding: '8px 0', caretColor: 'var(--text-primary)' },
      '.cm-line': { padding: '0 12px' },
      '.cm-gutters': {
        border: 'none',
        borderRight: '1px solid var(--border-default)',
        paddingRight: '4px',
        background: 'var(--bg-panel)',
        color: 'var(--text-muted)',
      },
      '.cm-activeLineGutter': { background: 'transparent' },
      '.cm-activeLine': { background: 'rgba(255,255,255,0.03)' },
      '.cm-selectionBackground, ::selection': { background: 'rgba(92,107,192,.35) !important' },
    });

    const extensions = [basicSetup(), json(), lintGutter(), varAwareLinter, baseTheme];
    if (isDark) extensions.push(oneDark);

    if (onChange) {
      extensions.push(EditorView.updateListener.of(u => {
        if (u.docChanged) onChange(u.state.doc.toString());
      }));
    }

    const view = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent,
    });

    return {
      getValue: () => view.state.doc.toString(),
      setValue: (val) => {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: val } });
      },
      focus: () => view.focus(),
      destroy: () => view.destroy(),
    };
  } catch (e) {
    console.warn('JSON editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
```

Replace the entire file with:

```js
/**
 * createJsonEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>
 * Uses the bundled CM6 from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 unavailable.
 * getVarsList?: () => Array<{key, value, group?}>|null — when provided AND
 * the vendor bundle exposes Decoration/ViewPlugin/RangeSetBuilder/
 * StateEffect/hoverTooltip, {{name}} tokens in the doc get colored
 * (var-tok--ok/--missing) and a hover tooltip shows the current value or
 * "not defined". Silently skipped on older bundles (see REBUILD.md).
 * editor: { getValue(), setValue(str), refresh(), focus(), destroy() }
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

export async function createJsonEditor({ parent, value = '', isDark = true, onChange, getVarsList }) {
  try {
    const CM = window.CM6;
    if (!CM) throw new Error('CM6 vendor bundle not loaded');

    const { EditorView, EditorState, basicSetup, json, jsonParseLinter, linter, lintGutter, oneDark } = CM;
    const { Decoration, ViewPlugin, RangeSetBuilder, StateEffect, hoverTooltip } = CM;

    // Custom linter that understands {{VAR}} template syntax
    const varAwareLinter = linter((view) => {
      const text = view.state.doc.toString().trim();
      if (!text) return [];
      const subbed = text.replace(/\{\{[^}]+\}\}/g, '"__QCVAR__"');
      try { JSON.parse(subbed); return []; }
      catch (e) {
        const m = /at position (\d+)/i.exec(e.message) || /position (\d+)/i.exec(e.message);
        const pos = m ? Math.min(+m[1], text.length - 1) : 0;
        return [{ from: pos, to: Math.min(pos + 1, text.length), severity: 'error', message: e.message }];
      }
    });

    const baseTheme = EditorView.theme({
      '&': {
        fontSize: '12px',
        border: '1px solid var(--border-default)',
        borderRadius: '6px',
        overflow: 'hidden',
        marginTop: '4px',
      },
      '.cm-scroller': {
        fontFamily: 'var(--font-mono, monospace)',
        lineHeight: '1.6',
        minHeight: '180px',
        maxHeight: '500px',
        overflow: 'auto',
      },
      '.cm-content': { padding: '8px 0', caretColor: 'var(--text-primary)' },
      '.cm-line': { padding: '0 12px' },
      '.cm-gutters': {
        border: 'none',
        borderRight: '1px solid var(--border-default)',
        paddingRight: '4px',
        background: 'var(--bg-panel)',
        color: 'var(--text-muted)',
      },
      '.cm-activeLineGutter': { background: 'transparent' },
      '.cm-activeLine': { background: 'rgba(255,255,255,0.03)' },
      '.cm-selectionBackground, ::selection': { background: 'rgba(92,107,192,.35) !important' },
    });

    const extensions = [basicSetup(), json(), lintGutter(), varAwareLinter, baseTheme];
    if (isDark) extensions.push(oneDark);

    let forceRedecorate = null;
    const hasTokenSupport = !!(Decoration && ViewPlugin && RangeSetBuilder && StateEffect && hoverTooltip && getVarsList);

    if (hasTokenSupport) {
      forceRedecorate = StateEffect.define();

      function buildDecorations(view) {
        const builder = new RangeSetBuilder();
        const list = getVarsList();
        if (list) {
          tokenSpansIn(view.state.doc.toString()).forEach(({ name, start, end }) => {
            const known = list.some(v => v.key === name);
            builder.add(start, end, Decoration.mark({ class: known ? 'var-tok--ok' : 'var-tok--missing' }));
          });
        }
        return builder.finish();
      }

      const tokenDecorationPlugin = ViewPlugin.fromClass(class {
        constructor(view) { this.decorations = buildDecorations(view); }
        update(u) {
          const forced = u.transactions.some(tr => tr.effects.some(e => e.is(forceRedecorate)));
          if (u.docChanged || forced) this.decorations = buildDecorations(u.view);
        }
      }, { decorations: v => v.decorations });

      const tokenHoverTooltip = hoverTooltip((view, pos) => {
        const hit = tokenSpansIn(view.state.doc.toString()).find(s => pos >= s.start && pos < s.end);
        if (!hit) return null;
        const list = getVarsList() || [];
        const entry = list.find(v => v.key === hit.name);
        return {
          pos: hit.start,
          end: hit.end,
          above: true,
          create() {
            const dom = document.createElement('div');
            dom.className = 'var-tooltip';
            dom.innerHTML = entry
              ? `<strong>{{${escapeHtml(hit.name)}}}</strong><div class="var-tooltip-value">${escapeHtml(String(entry.value ?? ''))}</div>` +
                (entry.group ? `<div class="var-tooltip-group">${escapeHtml(entry.group)}</div>` : '')
              : `<strong>{{${escapeHtml(hit.name)}}}</strong><div class="var-tooltip-missing">Not defined in environment or collection</div>`;
            return { dom };
          },
        };
      });

      extensions.push(tokenDecorationPlugin, tokenHoverTooltip);
    }

    if (onChange) {
      extensions.push(EditorView.updateListener.of(u => {
        if (u.docChanged) onChange(u.state.doc.toString());
      }));
    }

    const view = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent,
    });

    return {
      getValue: () => view.state.doc.toString(),
      setValue: (val) => {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: val } });
      },
      refresh: () => { if (forceRedecorate) view.dispatch({ effects: forceRedecorate.of(null) }); },
      focus: () => view.focus(),
      destroy: () => view.destroy(),
    };
  } catch (e) {
    console.warn('JSON editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
```

- [ ] **Step 2: Verify syntax**

Run: `node --check web/static/api/components/json-editor.js`
Expected: no output (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add web/static/api/components/json-editor.js
git commit -m "feat: json-editor gains CM6 decoration + hoverTooltip for {{var}} highlighting"
```

---

### Task 9: `request-editor-view.js` — pass `getVarsList` into the body's CM6 editor

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:508-513` (`_activateCmEditor`)

**Interfaces:**
- Consumes: `createJsonEditor`'s new `getVarsList` option (Task 8).
- **Depends on Task 6** (`_allVarsList` must already exist) **and Task 8**.

- [ ] **Step 1: Add `getVarsList` to the `createJsonEditor` call**

Current lines 505-513:

```js
  async function _activateCmEditor(val) {
    cmWrap.innerHTML = '';
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') !== 'light';
    _cmEditor = await createJsonEditor({
      parent: cmWrap,
      value: val,
      isDark,
      onChange: (v) => { bodyTextarea.value = v; }, // keep hidden textarea in sync
    });
```

Change to:

```js
  async function _activateCmEditor(val) {
    cmWrap.innerHTML = '';
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') !== 'light';
    _cmEditor = await createJsonEditor({
      parent: cmWrap,
      value: val,
      isDark,
      onChange: (v) => { bodyTextarea.value = v; }, // keep hidden textarea in sync
      getVarsList: () => _allVarsList,
    });
```

(`_refreshKnownVarNames`'s `_cmEditor?.refresh?.()` call, already added in Task 6 Step 2, now hits a real `.refresh()` method once this editor is active.)

- [ ] **Step 2: Verify syntax**

Run: `node --check web/static/api/views/request-editor-view.js`
Expected: no output (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "feat: wire getVarsList into the body CM6 editor"
```

---

### Task 10: Manual browser verification

**Files:** none (verification only)

**Interfaces:** none — end-to-end check of Tasks 1-9 together.

- [ ] **Step 1: Start the dev server**

Run: `python qaclan.py serve --port 7823` (background/separate terminal)

- [ ] **Step 2: Open the request editor for any existing API request (or create one) in a browser at `http://localhost:7823`**

- [ ] **Step 3: Confirm env/collection var setup**

Make sure the active environment (or the request's bound collection) has at least one variable defined, e.g. `token`. Add one via the Environments UI if none exists.

- [ ] **Step 4: Headers/Params/Path-Vars — per-token coloring alongside the existing field tint**

In the Headers table, set a value to `Bearer {{token}} {{doesnotexist}}` (using a real var name for `token`). Expected: the whole field still shows the existing red `kv-value--var-missing` bg tint (mixed → missing, unchanged behavior), AND now `{{token}}` renders in green text while `{{doesnotexist}}` renders in red text within that same field. Hover each token: a tooltip appears showing the variable's value (for `{{token}}`) or "Not defined in environment or collection" (for `{{doesnotexist}}`). Repeat briefly for Params and Path Vars.

- [ ] **Step 5: Auth fields**

Set Auth type to "Bearer Token", enter `{{token}} {{doesnotexist}}`. Expected: same per-token coloring + tooltip behavior as Step 4. Switch to Basic Auth and check the Password field specifically — confirm the `{{token}}` text renders colored (not hidden/garbled) despite the field being `type="password"`.

- [ ] **Step 6: URL bar**

Set the URL to `http://demo.com/api/users/{{user_id}}?query_pm={{qm}}` where `user_id` exists as a variable but `qm` doesn't. Expected: `{{user_id}}` renders green, `{{qm}}` renders red, hovering each shows the correct tooltip. Confirm the URL bar's own background does NOT get a whole-field green/red tint (per the explicit non-goal) and that typing `{{` does NOT open an autocomplete dropdown there (explicit non-goal).

- [ ] **Step 7: Assertions**

Go to the Assertions tab, add an assertion of type `json_path`, set the path to `$.{{token}}` and expected value to `{{token}} {{doesnotexist}}`. Expected: per-token coloring + tooltip on both fields; the expected-value field additionally shows the existing whole-field bg tint (mixed → red).

- [ ] **Step 8: Pre-Script / Post-Script**

In the Pre-Script tab's Script pane, type `qc.set("x", "{{token}} {{doesnotexist}}")`. Expected: per-token coloring + tooltip inside the textarea, text wraps normally (multi-line), scrolling the textarea (if content exceeds visible height) keeps the overlay in sync — no visual drift between the real (invisible) text and the colored overlay text. Repeat briefly for Post-Script.

- [ ] **Step 9: Body — CM6 active path**

Set Body type to "raw" (JSON). In the CodeMirror editor, type `{"token": "{{token}}", "bad": "{{doesnotexist}}"}`. Expected (only if Task 7's vendor rebuild completed): `{{token}}` renders green, `{{doesnotexist}}` renders red, hovering shows the tooltip using CM6's own tooltip chrome. If Task 7 was skipped/blocked, expected instead: the editor works exactly as before (JSON linting, formatting, etc.) with no token coloring — not broken, just unchanged.

- [ ] **Step 10: Body — fallback textarea path**

Temporarily rename/move `web/static/vendor/codemirror/cm6.js` (e.g. `mv web/static/vendor/codemirror/cm6.js /tmp/cm6.js.bak`) and hard-refresh the page to force the fallback path. Repeat Step 9's body text in the plain fallback textarea. Expected: same per-token coloring + tooltip as the script textareas (Step 8) — multi-line overlay technique, not CM6. Restore the file afterward: `mv /tmp/cm6.js.bak web/static/vendor/codemirror/cm6.js`.

- [ ] **Step 11: Async refresh — rows/fields rendered before the known-vars fetch resolves**

With browser devtools network throttling set to "Slow 3G" (or similar), reload the request editor. Immediately (before the vars fetch would normally resolve) add a header with value `{{token}}`. Expected: initially neutral (no color) since the known-vars list hasn't loaded yet; once it resolves, the token retroactively turns green without needing to re-type or refocus the field.

- [ ] **Step 12: Confirm out-of-scope surfaces are unchanged**

Add a Form (x-www-form-urlencoded) or Multipart body field with value `{{token}}`. Expected: existing blue `kv-value--var-ref` tint only — no per-token coloring, no tooltip (Task 4/6 deliberately didn't pass `getVarsList` to `formBodyTable`/`multipartBodyTable`).

- [ ] **Step 13: Report result to the user**

Summarize pass/fail for each check above, and explicitly note whether Task 7 (CM6 rebuild) completed or was skipped.
