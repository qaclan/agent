# GraphQL Body Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the bug where switching a request's body type between `raw` and `graphql` shows/overwrites the same content, and replace the single-JSON-blob GraphQL body editor with a real split Query + Variables editor (syntax-highlighted GraphQL text, like Postman/Insomnia/GraphiQL).

**Architecture:** `raw` and `graphql` currently share one CodeMirror instance and one backing textarea in [request-editor-view.js](../../../web/static/api/views/request-editor-view.js) — that's the root cause of the content-leak bug. This plan gives `graphql` its own independent state (mirroring the existing `_formRows`/`_multipartRows` pattern already used for the `form`/`multipart` types), rendered as two CM6 editors (Query + Variables) instead of one. The wire format on disk/over-the-wire stays exactly `{"query": "...", "variables": {...}}` in the existing `body` column — `cli/api_runner.py` already parses this shape for `body_type == "graphql"`, so **no backend or database change is needed**. A new CM6 language pack (`cm6-graphql`) is added to the existing bundled vendor editor so the Query pane gets real GraphQL syntax highlighting instead of being edited as plain/JSON text.

**Tech Stack:** CodeMirror 6 (already vendored at `web/static/vendor/codemirror/cm6.js`, built via esbuild — see [REBUILD.md](../../../web/static/vendor/codemirror/REBUILD.md)), vanilla JS ES modules (no framework), Flask/Python backend (untouched by this plan).

## Global Constraints

- No backend, database, or wire-format changes. `body_type='graphql'` + `body = '{"query":...,"variables":{...}}'` stays exactly as `cli/api_runner.py:602-614` and `cli/api_discovery/postman_parser.py:81-84` already expect.
- No automated test framework exists in this repo (confirmed in CLAUDE.md: "There are no automated tests or linting configured") — every verification step in this plan is a manual browser walkthrough via the Flask dev server (`python qaclan.py serve --port 7823`), not a test-runner invocation.
- No CDN dependency — the app is local-first; all CM6 code ships pre-bundled inside `cm6.js` (committed to the repo, bundled into the Nuitka binary). Any new library goes through the same bundle-and-commit process, never a runtime fetch.
- Schema-less GraphQL editing only. No introspection, no schema-aware field/type autocomplete — that requires a loaded `GraphQLSchema`, which is explicitly out of scope (see the parked future idea at `docs/superpowers/plans/future-plan/27-graphql-auto-detection.md`).
- Auto-detection of GraphQL requests during discovery/recording is explicitly **out of scope** for this plan — parked as a future idea (see same doc above). This plan only fixes the editor for body types the user (or Postman import) has already tagged `graphql`.
- Preserve existing behavior for `none`/`raw`/`form`/`multipart` body types exactly as-is — every code path this plan touches must leave those four types' behavior unchanged.

---

## File Structure

- **Modify:** `web/static/vendor/codemirror/REBUILD.md` — document + perform the CM6 bundle rebuild that adds the `cm6-graphql` language pack.
- **Modify (regenerated binary):** `web/static/vendor/codemirror/cm6.js` — rebuilt bundle, now exposing `window.CM6.graphql`.
- **Create:** `web/static/api/components/graphql-editor.js` — `createGraphqlEditor()`, a GraphQL-flavored mirror of the existing `createJsonEditor()` in `web/static/api/components/json-editor.js`.
- **Modify:** `web/static/api/views/request-editor-view.js` — give `graphql` its own state/DOM/editors, split out of the `raw` type's shared machinery.

No new files needed on the Python/Flask side — confirmed via repo-wide grep that `body_type='graphql'` handling in `cli/api_runner.py`, `cli/api_discovery/postman_parser.py`, and `web/static/api/curl-builder.js` already works against the `{query,variables}` JSON shape this plan continues to produce.

---

### Task 1: Rebuild the CM6 vendor bundle with GraphQL language support

**Files:**
- Modify: `web/static/vendor/codemirror/REBUILD.md`
- Modify (binary): `web/static/vendor/codemirror/cm6.js`

**Interfaces:**
- Produces: `window.CM6.graphql` — a function `(schema?, opts?) => Extension[]`, callable with no arguments for schema-less mode (confirmed via the package's shipped `.d.ts`: `declare function graphql(schema?: GraphQLSchema, opts?: GqlExtensionsOptions): Extension[];`). Consumed by Task 2's `createGraphqlEditor`.

- [ ] **Step 1: Update the REBUILD.md dependency list**

Edit `web/static/vendor/codemirror/REBUILD.md`. In the `npm install` block, add three packages (`graphql`, `@lezer/highlight`, `cm6-graphql`) right before `esbuild`:

```diff
 npm install --silent --no-audit --no-fund \
   @codemirror/state@6 \
   @codemirror/view@6 \
   @codemirror/commands@6 \
   @codemirror/language@6 \
   @codemirror/search@6 \
   @codemirror/autocomplete@6 \
   @codemirror/lang-python@6 \
   @codemirror/lang-javascript@6 \
   @codemirror/lang-json@6 \
   @codemirror/lint@6 \
   @codemirror/theme-one-dark@6 \
+  @lezer/highlight@1 \
+  graphql@16 \
+  cm6-graphql@0.2 \
   esbuild@0.24
```

- [ ] **Step 2: Update the entry.js snippet in REBUILD.md**

In the same file, update the `entry.js` code fence: add the `cm6-graphql` import and export `graphql` on `window.CM6`.

```diff
 import { python } from "@codemirror/lang-python"
 import { javascript } from "@codemirror/lang-javascript"
 import { json, jsonParseLinter } from "@codemirror/lang-json"
 import { linter, lintGutter } from "@codemirror/lint"
 import { oneDark } from "@codemirror/theme-one-dark"
+import { graphql } from "cm6-graphql"
```

```diff
 window.CM6 = {
   EditorState, Compartment, RangeSetBuilder, StateEffect,
   EditorView, Decoration, ViewPlugin, ViewUpdate, hoverTooltip, keymap,
   basicSetup, oneDark, indentUnit,
   python, javascript, json, jsonParseLinter, linter, lintGutter,
   autocompletion, completionKeymap, CompletionContext,
+  graphql,
 }
```

Also update the trailing "Notes" section's comment about what the entry point covers, and the bundle size line (it currently reads "Bundle is ~530 KB minified") — leave a `<!-- updated in Step 5 with the real number -->` marker for now; Step 5 replaces it with the measured value.

```diff
 This is the actual entry point used to produce the committed `cm6.js` —
 keep it in sync with reality (json language + lint support, the
 decoration/hover-tooltip primitives used for {{var}} highlighting, and the
-autocomplete primitives used for {{var}} suggestions in the raw JSON body
-editor) so a future rebuild doesn't silently drop functionality.
+autocomplete primitives used for {{var}} suggestions in the raw JSON body
+editor, and the schema-less GraphQL language pack used by the GraphQL
+query/variables body editor) so a future rebuild doesn't silently drop
+functionality.
```

- [ ] **Step 3: Perform the rebuild**

Run these commands (Node 20 required — this environment already has `node v20.20.1`, confirmed via `node --version`):

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
  @codemirror/autocomplete@6 \
  @codemirror/lang-python@6 \
  @codemirror/lang-javascript@6 \
  @codemirror/lang-json@6 \
  @codemirror/lint@6 \
  @codemirror/theme-one-dark@6 \
  @lezer/highlight@1 \
  graphql@16 \
  cm6-graphql@0.2 \
  esbuild@0.24
```

Then write `entry.js` in `/tmp/cm6-bundle/` with the **full** updated content (this is the complete file, not a diff — copy it verbatim):

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
import { autocompletion, completionKeymap, CompletionContext } from "@codemirror/autocomplete"
import { python } from "@codemirror/lang-python"
import { javascript } from "@codemirror/lang-javascript"
import { json, jsonParseLinter } from "@codemirror/lang-json"
import { linter, lintGutter } from "@codemirror/lint"
import { oneDark } from "@codemirror/theme-one-dark"
import { graphql } from "cm6-graphql"

function basicSetup() {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightActiveLine(),
    foldGutter(),
    drawSelection(),
    history(),
    indentUnit.of("    "),
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
  EditorView, Decoration, ViewPlugin, ViewUpdate, hoverTooltip, keymap,
  basicSetup, oneDark, indentUnit,
  python, javascript, json, jsonParseLinter, linter, lintGutter,
  autocompletion, completionKeymap, CompletionContext,
  graphql,
}
```

Bundle it:

```bash
./node_modules/.bin/esbuild entry.js \
  --bundle --format=iife --minify --target=es2019 \
  --outfile=cm6.js
```

- [ ] **Step 4: Verify the bundle actually exposes `graphql`**

CM6's IIFE bundle assigns to the global `window` object. Verify it in plain Node by shimming `window` to the global object before loading:

```bash
node -e "
global.window = global;
require('/tmp/cm6-bundle/cm6.js');
console.log('graphql export:', typeof window.CM6.graphql);
console.log('existing json export still present:', typeof window.CM6.json);
"
```

Expected output:
```
graphql export: function
existing json export still present: function
```

If `graphql export` is not `function`, stop — re-check Step 2's entry.js and Step 3's install output for errors before continuing.

- [ ] **Step 5: Copy the bundle into the repo and record its size**

```bash
cp /tmp/cm6-bundle/cm6.js /mnt/ext-drive/qaclan/agent/web/static/vendor/codemirror/cm6.js
ls -la /mnt/ext-drive/qaclan/agent/web/static/vendor/codemirror/cm6.js
```

Note the byte size from `ls -la`. Edit `web/static/vendor/codemirror/REBUILD.md`'s Notes section, replacing:

```diff
-- Bundle is ~530 KB minified (includes Python + JS grammars, one-dark theme, autocomplete).
+- Bundle is ~<measured KB> minified (includes Python + JS grammars, GraphQL grammar + graphql-js, one-dark theme, autocomplete).
```

filling in the real measured kilobyte value (divide the byte count from `ls -la` by 1024, round to the nearest 10).

- [ ] **Step 6: Clean up and commit**

```bash
cd /mnt/ext-drive/qaclan/agent
rm -rf /tmp/cm6-bundle
git add web/static/vendor/codemirror/cm6.js web/static/vendor/codemirror/REBUILD.md
git commit -m "build(cm6): add GraphQL language pack to vendored CodeMirror bundle"
```

---

### Task 2: Create the `createGraphqlEditor` component

**Files:**
- Create: `web/static/api/components/graphql-editor.js`

**Interfaces:**
- Consumes: `window.CM6.graphql`, `window.CM6.EditorView`, `window.CM6.EditorState`, `window.CM6.basicSetup`, `window.CM6.oneDark`, `window.CM6.Decoration`, `window.CM6.ViewPlugin`, `window.CM6.RangeSetBuilder`, `window.CM6.StateEffect`, `window.CM6.hoverTooltip`, `window.CM6.autocompletion`, `window.CM6.completionKeymap`, `window.CM6.keymap` (all produced by Task 1). `tokenSpansIn`, `escapeHtml` from `web/static/api/components/var-style.js` (already exist, used identically by `json-editor.js`).
- Produces: `createGraphqlEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>` where `editor = { getValue(), setValue(str), refresh(), focus(), destroy() }`. Same shape as `createJsonEditor` from `web/static/api/components/json-editor.js` — Task 3 mounts this exactly like Task 3 already mounts `createJsonEditor` for the raw body and will mount it again for the new Variables pane.

- [ ] **Step 1: Write the component**

Create `web/static/api/components/graphql-editor.js`:

```js
/**
 * createGraphqlEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>
 * Uses the bundled CM6 GraphQL language pack from window.CM6 (vendor/codemirror/cm6.js).
 * Returns null if CM6 or the graphql() extension is unavailable — caller falls
 * back to a plain textarea, same pattern as createJsonEditor.
 * Schema-less: no introspection/schema wired in, so this gives syntax
 * highlighting, bracket matching, and GraphQL-grammar completion only — no
 * field/type-aware autocomplete (that needs a loaded schema, out of scope).
 * editor: { getValue(), setValue(str), refresh(), focus(), destroy() }
 */
import { tokenSpansIn, escapeHtml } from './var-style.js';

export async function createGraphqlEditor({ parent, value = '', isDark = true, onChange, getVarsList }) {
  try {
    const CM = window.CM6;
    if (!CM || !CM.graphql) throw new Error('CM6 GraphQL language pack not loaded');

    const { EditorView, EditorState, basicSetup, graphql, oneDark } = CM;
    const { Decoration, ViewPlugin, RangeSetBuilder, StateEffect, hoverTooltip } = CM;
    const { autocompletion, completionKeymap, keymap } = CM;

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
        minHeight: '140px',
        maxHeight: '400px',
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

    const extensions = [basicSetup(), graphql(), baseTheme];
    if (isDark) extensions.push(oneDark);

    // {{var}} name suggestions while typing — identical mechanism to the raw
    // JSON body editor's var autocomplete, just wired into the GraphQL doc.
    if (autocompletion && getVarsList) {
      function varCompletions(context) {
        const word = context.matchBefore(/\{\{[\w.-]*/);
        if (!word) return null;
        const list = getVarsList() || [];
        if (!list.length) return null;
        return {
          from: word.from + 2,
          options: list.map(v => ({
            label: v.key,
            type: 'variable',
            detail: v.group || undefined,
            info: () => document.createTextNode(String(v.value ?? '')),
            apply: (view, completion, from, to) => {
              const alreadyClosed = view.state.sliceDoc(to, to + 2) === '}}';
              const insert = completion.label + (alreadyClosed ? '' : '}}');
              view.dispatch({
                changes: { from, to, insert },
                selection: { anchor: from + insert.length },
              });
            },
          })),
          validFor: /^[\w.-]*$/,
        };
      }
      extensions.push(autocompletion({ override: [varCompletions] }));
      if (keymap && completionKeymap) extensions.push(keymap.of(completionKeymap));
    }

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
    console.warn('GraphQL editor (CodeMirror) unavailable:', e.message);
    return null;
  }
}
```

- [ ] **Step 2: Verify no syntax errors**

```bash
node --check /mnt/ext-drive/qaclan/agent/web/static/api/components/graphql-editor.js
```

Expected: no output (exit code 0). `--check` only parses, it doesn't run ES module `import` resolution against the browser-only `window` global, so this just confirms the file is syntactically valid JS.

- [ ] **Step 3: Commit**

```bash
cd /mnt/ext-drive/qaclan/agent
git add web/static/api/components/graphql-editor.js
git commit -m "feat(api): add GraphQL-aware CodeMirror editor component"
```

---

### Task 3: Give `graphql` its own state, DOM, and editors in the request editor

**Files:**
- Modify: `web/static/api/views/request-editor-view.js`

**Interfaces:**
- Consumes: `createGraphqlEditor` from Task 2, `createJsonEditor` from `web/static/api/components/json-editor.js` (already imported), `_allVarsList` (existing module-level closure var already populated by `_refreshKnownVarNames()`).
- Produces: no new exports — this task only changes the internal body-section state machine of `renderRequestEditor()`. External callers (`_buildPayload()`'s output shape, the save endpoint payload) are unchanged; `bodyTextarea.value` continues to hold the exact same combined `{query,variables}` JSON string for `body_type='graphql'` as it does today, so every other consumer of `bodyTextarea.value` (`_buildPayload` at line ~1518-1521, `_copyAsCurl` at line ~1077, the curl-paste dirty-check at line ~246) needs **no changes** — verified by tracing all three call sites during planning.

- [ ] **Step 1: Add the `createGraphqlEditor` import**

In `web/static/api/views/request-editor-view.js`, find the existing import block near the top:

```js
import { createJsonEditor } from '../components/json-editor.js';
```

Add immediately after it:

```js
import { createGraphqlEditor } from '../components/graphql-editor.js';
```

- [ ] **Step 2: Add GraphQL pane state and DOM, seeded from the loaded request**

Find this existing block (it sets up the `form`/`multipart` row state):

```js
  // Form / multipart bodies share the same key-value table widget, but each
  // type keeps its own row set — otherwise switching tabs would show one
  // type's fields under the other's tab.
  let _formRows = [];
  let _multipartRows = [];
  try {
    const parsed = JSON.parse(r.body || '[]');
    if (Array.isArray(parsed)) {
      if (r.body_type === 'multipart') _multipartRows = parsed;
      else if (r.body_type === 'form') _formRows = parsed;
    }
  } catch(e) { /* leave both empty */ }
  const formBodyTable = createKeyValueTable({
    placeholder: { key: 'field', value: 'value' }, varPickerEnabled: true, getVars: getAllVars,
    getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList,
  });
  const multipartBodyTable = createKeyValueTable({
    placeholder: { key: 'field', value: 'value' }, varPickerEnabled: true, getVars: getAllVars, fileFieldsEnabled: true,
    getKnownVarNames: () => _knownVarNames, getVarsList: () => _allVarsList,
  });
  formBodyTable.setRows(_formRows);
  multipartBodyTable.setRows(_multipartRows);
  formBodyTable.el.style.display = 'none';
  multipartBodyTable.el.style.display = 'none';
```

Immediately after `multipartBodyTable.el.style.display = 'none';`, add:

```js

  // GraphQL body gets its own two-pane state (query text + variables JSON),
  // independent from the raw/JSON body's _cmEditor — this is what makes
  // switching raw<->graphql stop leaking content into each other, the bug
  // this refactor fixes. Wire format is unchanged: on save/send/curl-copy
  // this still collapses to a single {"query":...,"variables":{...}} JSON
  // string in bodyTextarea.value, exactly as cli/api_runner.py expects.
  let _gqlQuery = '';
  let _gqlVariables = '{}';
  try {
    if (r.body_type === 'graphql') {
      const gql = JSON.parse(r.body || '{}');
      _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
      _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
    }
  } catch (e) { /* malformed saved body — start both panes empty */ }

  let _gqlQueryEditor = null;
  let _gqlVariablesEditor = null;
  let _gqlQueryFallback = null;
  let _gqlVariablesFallback = null;

  const gqlWrap = document.createElement('div');
  gqlWrap.style.display = 'none';

  const gqlQueryLabel = document.createElement('div');
  gqlQueryLabel.textContent = 'Query';
  gqlQueryLabel.style.cssText = 'font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);margin:8px 0 2px;';
  const gqlQueryMount = document.createElement('div');

  const gqlVariablesLabel = document.createElement('div');
  gqlVariablesLabel.textContent = 'Variables';
  gqlVariablesLabel.style.cssText = 'font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);margin:8px 0 2px;';
  const gqlVariablesMount = document.createElement('div');

  gqlWrap.append(gqlQueryLabel, gqlQueryMount, gqlVariablesLabel, gqlVariablesMount);

  function _syncGqlBodyTextarea() {
    let variables = {};
    try { variables = JSON.parse(_gqlVariables || '{}'); }
    catch (e) { /* keep last-valid variables in bodyTextarea until the user fixes the syntax error */ }
    bodyTextarea.value = JSON.stringify({ query: _gqlQuery, variables });
  }

  async function _mountGqlEditors() {
    gqlQueryMount.innerHTML = '';
    gqlVariablesMount.innerHTML = '';
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') !== 'light';

    _gqlQueryEditor = await createGraphqlEditor({
      parent: gqlQueryMount, value: _gqlQuery, isDark,
      onChange: (v) => { _gqlQuery = v; _syncGqlBodyTextarea(); },
      getVarsList: () => _allVarsList,
    });
    if (!_gqlQueryEditor) {
      _gqlQueryFallback = document.createElement('textarea');
      _gqlQueryFallback.className = 'input-sm body-json-editor';
      _gqlQueryFallback.style.cssText = 'width:100%;min-height:140px;font-family:var(--font-mono);font-size:12px;line-height:1.6;resize:vertical;';
      _gqlQueryFallback.spellcheck = false;
      _gqlQueryFallback.value = _gqlQuery;
      _gqlQueryFallback.placeholder = '{ users { id name } }';
      _gqlQueryFallback.addEventListener('input', () => { _gqlQuery = _gqlQueryFallback.value; _syncGqlBodyTextarea(); });
      gqlQueryMount.appendChild(_gqlQueryFallback);
    }

    _gqlVariablesEditor = await createJsonEditor({
      parent: gqlVariablesMount, value: _gqlVariables, isDark,
      onChange: (v) => { _gqlVariables = v; _syncGqlBodyTextarea(); },
      getVarsList: () => _allVarsList,
    });
    if (!_gqlVariablesEditor) {
      _gqlVariablesFallback = document.createElement('textarea');
      _gqlVariablesFallback.className = 'input-sm body-json-editor';
      _gqlVariablesFallback.style.cssText = 'width:100%;min-height:100px;font-family:var(--font-mono);font-size:12px;line-height:1.6;resize:vertical;';
      _gqlVariablesFallback.spellcheck = false;
      _gqlVariablesFallback.value = _gqlVariables;
      _gqlVariablesFallback.placeholder = '{\n  "id": "1"\n}';
      _gqlVariablesFallback.addEventListener('input', () => { _gqlVariables = _gqlVariablesFallback.value; _syncGqlBodyTextarea(); });
      gqlVariablesMount.appendChild(_gqlVariablesFallback);
    }

    _syncGqlBodyTextarea();
  }

  function _unmountGqlEditors() {
    _gqlQueryEditor?.destroy();
    _gqlVariablesEditor?.destroy();
    _gqlQueryEditor = null;
    _gqlVariablesEditor = null;
    _gqlQueryFallback = null;
    _gqlVariablesFallback = null;
    gqlQueryMount.innerHTML = '';
    gqlVariablesMount.innerHTML = '';
  }
```

- [ ] **Step 3: Split `graphql` out of the raw text editor's `_setBodyType` branch**

Find the current `_setBodyType` function:

```js
  function _setBodyType(type) {
    const prevType = activeBodyType;
    if (prevType === 'form') _formRows = formBodyTable.getRows();
    else if (prevType === 'multipart') _multipartRows = multipartBodyTable.getRows();

    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
    const isText = type === 'raw' || type === 'graphql';

    if (!isText && _cmEditor) {
      // Leaving text mode — read current value before destroying
      bodyTextarea.value = _cmEditor.getValue();
      _cmEditor.destroy();
      _cmEditor = null;
      cmWrap.style.display = 'none';
      _bodyFallbackOverlay.el.style.display = 'none';
      _cmActive = false;
    }

    if (type === 'form') formBodyTable.setRows(_formRows);
    else if (type === 'multipart') multipartBodyTable.setRows(_multipartRows);
    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    multipartBodyTable.el.style.display = type === 'multipart' ? '' : 'none';
    bodyVarBtn.style.display = isText ? '' : 'none';
    formatBtn.style.display = isText ? '' : 'none';
    minifyBtn.style.display = isText ? '' : 'none';
    jsonErrorEl.style.display = 'none';

    if (isText) {
      _cmActive = true;
      cmWrap.style.display = '';
      _bodyFallbackOverlay.el.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      if (type === 'graphql') bodyFallback.placeholder = '{ "query": "{ users { id name } }" }';
      else bodyFallback.placeholder = '{\n  "key": "value"\n}';
    }
  }
```

Replace it entirely with:

```js
  function _setBodyType(type) {
    const prevType = activeBodyType;
    if (prevType === 'form') _formRows = formBodyTable.getRows();
    else if (prevType === 'multipart') _multipartRows = multipartBodyTable.getRows();
    else if (prevType === 'graphql') _unmountGqlEditors();

    activeBodyType = type;
    bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.type === type);
    });
    const isRawText = type === 'raw';
    const isGraphql = type === 'graphql';

    if (!isRawText && _cmEditor) {
      // Leaving raw text mode — read current value before destroying
      bodyTextarea.value = _cmEditor.getValue();
      _cmEditor.destroy();
      _cmEditor = null;
      cmWrap.style.display = 'none';
      _bodyFallbackOverlay.el.style.display = 'none';
      _cmActive = false;
    }

    if (type === 'form') formBodyTable.setRows(_formRows);
    else if (type === 'multipart') multipartBodyTable.setRows(_multipartRows);
    formBodyTable.el.style.display = type === 'form' ? '' : 'none';
    multipartBodyTable.el.style.display = type === 'multipart' ? '' : 'none';
    gqlWrap.style.display = isGraphql ? '' : 'none';
    bodyVarBtn.style.display = isRawText ? '' : 'none';
    formatBtn.style.display = isRawText ? '' : 'none';
    minifyBtn.style.display = isRawText ? '' : 'none';
    jsonErrorEl.style.display = 'none';

    if (isRawText) {
      _cmActive = true;
      cmWrap.style.display = '';
      _bodyFallbackOverlay.el.style.display = 'none';
      _activateCmEditor(bodyTextarea.value);
      bodyFallback.placeholder = '{\n  "key": "value"\n}';
    } else if (isGraphql) {
      _mountGqlEditors();
    }
  }
```

Note what changed: `graphql` no longer shares `_cmEditor`/`cmWrap`/`bodyFallback` with `raw` (that sharing was the root cause of the content-leak bug). The format/minify/insert-variable toolbar buttons (`formatBtn`, `minifyBtn`, `bodyVarBtn`) now only show for `raw` — they operate on `_getBodyValue()`/`_setBodyValue()` which are JSON/raw-text-shaped and don't map cleanly onto a two-pane editor; the Variables pane still gets `{{var}}` highlighting/autocomplete/hover "for free" from `createJsonEditor`'s own built-in support (same as raw), and the Query pane gets the same from `createGraphqlEditor` (Task 2).

- [ ] **Step 4: Append `gqlWrap` to the body section's DOM**

Find:

```js
  bodySection.appendChild(bodyTypeGroup);
  bodySection.appendChild(bodyTextarea);   // hidden — source of truth for _save()
  bodySection.appendChild(cmWrap);
  bodySection.appendChild(_bodyFallbackOverlay.el);
  bodySection.appendChild(jsonErrorEl);
  bodySection.appendChild(formBodyTable.el);
  bodySection.appendChild(multipartBodyTable.el);
```

Add one line after it:

```js
  bodySection.appendChild(gqlWrap);
```

- [ ] **Step 5: Make the "load example" dropdown handle GraphQL bodies**

The examples dropdown swaps body *content* for the currently-active type without changing the type (existing, deliberate behavior — an example is a prior capture for the same endpoint, so its body type always matches the parent request's). It does this through `_setBodyValue()`, which currently only knows how to write into the raw editor's `bodyTextarea`/`_cmEditor`/`bodyFallback`. Find:

```js
  function _setBodyValue(val) {
    bodyTextarea.value = val; // always keep hidden textarea in sync for _save()
    if (_cmActive && _cmEditor) { _cmEditor.setValue(val); return; }
    if (_cmActive) { bodyFallback.value = val; return; }
  }
```

Replace it with:

```js
  function _setBodyValue(val) {
    if (activeBodyType === 'graphql') {
      try {
        const gql = JSON.parse(val || '{}');
        _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
        _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
      } catch (e) { _gqlQuery = ''; _gqlVariables = '{}'; }
      if (_gqlQueryEditor) _gqlQueryEditor.setValue(_gqlQuery);
      else if (_gqlQueryFallback) _gqlQueryFallback.value = _gqlQuery;
      if (_gqlVariablesEditor) _gqlVariablesEditor.setValue(_gqlVariables);
      else if (_gqlVariablesFallback) _gqlVariablesFallback.value = _gqlVariables;
      _syncGqlBodyTextarea();
      return;
    }
    bodyTextarea.value = val; // always keep hidden textarea in sync for _save()
    if (_cmActive && _cmEditor) { _cmEditor.setValue(val); return; }
    if (_cmActive) { bodyFallback.value = val; return; }
  }
```

- [ ] **Step 6: Keep GraphQL panes' `{{var}}` highlighting live when the known-vars list refreshes**

Find `_refreshKnownVarNames()`:

```js
  async function _refreshKnownVarNames() {
    const vars = await getAllVars();
    _knownVarNames = new Set(vars.map(v => v.key));
    _allVarsList = vars;
    paramsTable.restyleAll();
    headersTable.restyleAll();
    pathVarsTable.restyleAll();
    formBodyTable.restyleAll();
    multipartBodyTable.restyleAll();
    _authFieldInputs.forEach(inp => applyVarStyle(inp, _knownVarNames));
    _authFieldOverlays.forEach(o => o.refresh());
    _renderUrlTokens();
    _scriptTextareaOverlays.forEach(o => o.refresh());
    _bodyFallbackOverlay?.refresh();
    _extractorNameInputs.forEach(inp => _styleExtractorNameInput(inp));
    assertionBuilder.restyleAll();
    _cmEditor?.refresh?.();
  }
```

Add two lines right after `_cmEditor?.refresh?.();`:

```js
    _gqlQueryEditor?.refresh?.();
    _gqlVariablesEditor?.refresh?.();
```

- [ ] **Step 7: Verify no syntax errors**

```bash
node --check /mnt/ext-drive/qaclan/agent/web/static/api/views/request-editor-view.js
```

Expected: no output (exit code 0).

- [ ] **Step 8: Commit**

```bash
cd /mnt/ext-drive/qaclan/agent
git add web/static/api/views/request-editor-view.js
git commit -m "fix(api): give GraphQL request bodies their own query/variables editor state

Raw and GraphQL body types previously shared one CodeMirror instance and
one backing textarea, so switching between them leaked/overwrote content.
GraphQL now gets independent state (mirroring the existing form/multipart
row-state pattern) and a real split Query + Variables editor instead of a
single JSON-blob textarea wearing a label."
```

---

### Task 4: Manual verification walkthrough

**Files:** none (verification only — no code changes)

**Interfaces:** none

- [ ] **Step 1: Start the dev server**

```bash
cd /mnt/ext-drive/qaclan/agent
python qaclan.py serve --port 7823
```

- [ ] **Step 2: Verify the buffer-separation fix (the original bug)**

In the browser, open the API testing UI, create or open a request. In the body section:
1. Click **raw**, type `{"hello":"world"}`.
2. Click **graphql** — the Query pane must be **empty** (not `{"hello":"world"}`). This is the bug fix — confirm it directly.
3. Type `{ characters(page: 1) { results { name } } }` into the Query pane, and `{"page": 1}` into the Variables pane.
4. Click back to **raw** — the raw editor must still show `{"hello":"world"}` (unchanged, not overwritten by the GraphQL content).
5. Click **graphql** again — Query/Variables panes must still show what was typed in step 3.

- [ ] **Step 3: Verify the smart Query editor**

In the Query pane, type `query GetCharacters($page: Int!, $name: String!) {` and press Enter. Confirm:
- Syntax highlighting is present (keywords/braces colored, not plain monochrome text).
- Auto-indent/bracket-matching behaves like the other CM6 editors in this app (e.g. typing `{` doesn't require manually typing the matching `}`... verify at minimum that typing a `{` highlights its matching `}` when the cursor is adjacent, matching existing `bracketMatching()` behavior already used elsewhere in the app).
- No red lint squiggles/errors appear under valid GraphQL syntax (schema-less mode must not produce false-positive errors — confirmed in planning by reading `cm6-graphql`'s `lint` extension source, which returns `[]` when no schema is loaded).

- [ ] **Step 4: Verify save/reload round-trip**

1. With the Query/Variables from Step 2 still in place, fill in a URL (e.g. `https://rickandmortyapi.graphcdn.app/`), method `POST`, and set body type to `graphql`.
2. Save the request.
3. Navigate away (open a different request or reload the page) and reopen the saved request.
4. Confirm body type is still `graphql` and the Query/Variables panes show exactly what was saved.

- [ ] **Step 5: Verify send works end-to-end**

1. On the same request (URL `https://rickandmortyapi.graphcdn.app/`, method `POST`, body type `graphql`), set:
   - Query:
     ```graphql
     query GetCharacters($page: Int!, $name: String!) {
       characters(page: $page, filter: { name: $name }) {
         info {
           count
           pages
         }
         results {
           id
           status
           species
           image
         }
       }
     }
     ```
   - Variables: `{"page": 1, "name": "Rick"}`
2. Click **Send**.
3. Confirm the response is a `200` with a JSON body containing `data.characters.results` — this is the same live GraphQL API from the curl example that originally motivated this plan, so a successful response confirms `cli/api_runner.py`'s existing `body_type == "graphql"` handling (query/variables serialization, `Content-Type: application/json` override) still works unchanged against the new editor's output.

- [ ] **Step 6: Verify unaffected body types**

Quickly confirm `none`, `raw` (non-GraphQL JSON), `form`, and `multipart` body types still work exactly as before this change — create one request of each type, switch between all five type tabs in various orders, save, reload. Nothing about their behavior should have changed; this is a regression check on the `_setBodyType` rewrite in Task 3 Step 3.

- [ ] **Step 7: Verify "Copy as cURL" for a GraphQL request**

On the request from Step 5, click **Copy as cURL** and paste the clipboard contents somewhere visible. Confirm the `--data-raw` payload is the combined `{"query":...,"variables":{...}}` JSON — this exercises `_copyAsCurl` (`web/static/api/views/request-editor-view.js` line ~1069-1088), which reads `bodyTextarea.value` directly and was **not modified** by this plan; a correct cURL output here confirms the continuous `_syncGqlBodyTextarea()` sync (Task 3 Step 2) is working.

---

## Self-Review

**Spec coverage:**
- Buffer-separation bug (raw/graphql sharing one editor) → Task 3 Steps 2-3, verified in Task 4 Step 2. ✅
- Smart Query editor (not a plain string field) → Task 1 (bundle) + Task 2 (component) + Task 3 Step 2 (mounting), verified in Task 4 Step 3. ✅
- No backend/DB change → confirmed in Global Constraints and Task 3's Interfaces note; no Python files appear in the File Structure. ✅
- Auto-detection kept out of scope → stated in Global Constraints, pointed at the parked future doc. ✅
- `operationName` dropped from scope (per earlier discussion — nothing in `cli/api_runner.py` reads it today) → not present anywhere in this plan's wire format (`{query, variables}` only), consistent. ✅

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" language present — every step has complete, copy-pasteable code or an exact command with expected output.

**Type consistency:** `createGraphqlEditor` in Task 2 returns `{ getValue, setValue, refresh, focus, destroy }` — Task 3 calls exactly these five methods (`.destroy()` in `_unmountGqlEditors`, `.setValue()` in `_setBodyValue`, `.refresh()` in `_refreshKnownVarNames`) and no others. `_gqlQuery`/`_gqlVariables` names are used consistently across Task 3 Steps 2, 3, and 5 — no renaming drift.

---

## Related / Out of Scope

- **GraphQL auto-detection during discovery** (heuristic scoring of captured HAR traffic, maker-checker suggestion badge, optional introspection-verify button) — fully designed in conversation but explicitly parked. See `docs/superpowers/plans/future-plan/27-graphql-auto-detection.md`.
- **`operationName` field** — not read anywhere in `cli/api_runner.py` today; adding a UI field for it without also wiring send-time support would be decorative. Revisit only alongside multi-operation-per-document support.
- **Schema-aware autocomplete / introspection** — needs a fetched `GraphQLSchema` passed into `createGraphqlEditor`'s `graphql(schema)` call; natural follow-on to the auto-detection future doc's "Verify via introspection" idea, since a successful introspection probe would hand you the schema for free.
