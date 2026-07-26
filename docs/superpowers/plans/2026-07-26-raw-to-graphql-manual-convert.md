# Raw → GraphQL Manual Convert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** When a user switches a request's body-type tab from `raw` to `graphql` for the first time, auto-seed the query/variables editors from the raw JSON body if it looks GraphQL-shaped (`{query, variables}`), instead of opening two empty editors and forcing the user to hand-retype what they already captured.

**Architecture:** One file, `web/static/api/views/request-editor-view.js`. Reuse the existing `_setBodyValue()` graphql-parse branch (already handles JSON.parse + malformed/missing-query fallback) by calling it once, guarded by a one-shot flag, right before `_mountGqlEditors()` runs inside `_setBodyType()`'s `isGraphql` branch. Add one inline hint element for the case where the raw body doesn't parse as GraphQL-shaped, wired to hide on first edit.

**Tech Stack:** Vanilla JS, no framework, no bundler, no test runner for this file (per `CLAUDE.md`: "There are no automated tests or linting configured").

## Global Constraints

- No backend, schema, or database changes — everything needed already exists in `request-editor-view.js`.
- No new files — all edits land in the existing `web/static/api/views/request-editor-view.js`.
- `body_graphql` shape stays `{query: string, variables: object}` — no `operationName` (matches `postman_parser.py`, `bruno_parser.py`, and the existing save payload at line 1727).
- No automated JS test runner exists for this codebase — verification is manual, in a running dev server + browser, per `CLAUDE.md` and the project's UI-change rule (start dev server, exercise the golden path and edge cases before claiming done).
- The seed attempt must never overwrite content the user already typed or that was already loaded from a saved `body_graphql` — gate on a one-shot flag, not on live emptiness of `_gqlQuery` (live emptiness would let a deliberate "user cleared the field to start over" get silently re-filled on the next tab revisit).

---

### Task 1: Auto-seed graphql editors from raw body on first empty visit, with non-match hint

**Files:**
- Modify: `web/static/api/views/request-editor-view.js:839-867` (state + hint element setup)
- Modify: `web/static/api/views/request-editor-view.js:876-914` (`_mountGqlEditors` — hide hint on first edit)
- Modify: `web/static/api/views/request-editor-view.js:930-984` (`_setBodyType` — seed attempt in the `isGraphql` branch)

**Interfaces:**
- Consumes: `_setBodyValue(val)` (existing, line 659) — graphql branch already parses `val` as JSON, sets module-level `_gqlQuery`/`_gqlVariables`/`_gqlLastValidVariables`, no-ops safely on editors that aren't mounted yet. `_rawValue` (existing, line 645) — private cache of the raw tab's own content, non-empty whenever the request has ever had raw body text. `activeBodyType` (existing, line 568) — already set to `'graphql'` by the time the `isGraphql` branch runs (assignment happens earlier in the same function, line 936).
- Produces: `_gqlSeedAttempted` (new module-level boolean) — nothing outside this task reads it. `gqlHintEl` (new DOM node) — nothing outside this task reads it.

- [x] **Step 1: Add the seed-tracking flag and hint element**

Read the current block first to confirm line numbers still match (the file may have shifted slightly since this plan was written):

```bash
grep -n "_gqlLastValidVariables = {}\|gqlWrap.append" web/static/api/views/request-editor-view.js
```

Expected: a line near 841 reading `let _gqlLastValidVariables = {};` and a line near 867 reading `gqlWrap.append(gqlQueryLabel, gqlQueryMount, gqlVariablesLabel, gqlVariablesMount);`. If the surrounding code differs materially from the excerpt below, stop and re-read the full `839-867` range before editing.

Replace:
```js
  let _gqlQuery = '';
  let _gqlVariables = '{}';
  let _gqlLastValidVariables = {};
  try {
    const gql = JSON.parse(r.body_graphql || '{}');
    _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
    _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
    _gqlLastValidVariables = gql.variables ?? {};
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
```

With:
```js
  let _gqlQuery = '';
  let _gqlVariables = '{}';
  let _gqlLastValidVariables = {};
  try {
    const gql = JSON.parse(r.body_graphql || '{}');
    _gqlQuery = typeof gql.query === 'string' ? gql.query : '';
    _gqlVariables = JSON.stringify(gql.variables ?? {}, null, 2);
    _gqlLastValidVariables = gql.variables ?? {};
  } catch (e) { /* malformed saved body — start both panes empty */ }

  // Set true the first time _setBodyType('graphql') attempts to seed the
  // editors from _rawValue — gates on this flag, not live emptiness of
  // _gqlQuery, so a deliberate user-clear of the query field is never
  // silently re-filled on a later tab revisit.
  let _gqlSeedAttempted = false;

  let _gqlQueryEditor = null;
  let _gqlVariablesEditor = null;
  let _gqlQueryFallback = null;
  let _gqlVariablesFallback = null;

  const gqlWrap = document.createElement('div');
  gqlWrap.style.display = 'none';

  const gqlQueryLabel = document.createElement('div');
  gqlQueryLabel.textContent = 'Query';
  gqlQueryLabel.style.cssText = 'font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);margin:8px 0 2px;';

  const gqlHintEl = document.createElement('div');
  gqlHintEl.textContent = "Raw body doesn't look like GraphQL — start typing your query below.";
  gqlHintEl.style.cssText = 'font-size:12px;color:var(--text-muted);font-style:italic;margin:0 0 6px;display:none;';

  const gqlQueryMount = document.createElement('div');

  const gqlVariablesLabel = document.createElement('div');
  gqlVariablesLabel.textContent = 'Variables';
  gqlVariablesLabel.style.cssText = 'font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--text-muted);margin:8px 0 2px;';
  const gqlVariablesMount = document.createElement('div');

  gqlWrap.append(gqlQueryLabel, gqlHintEl, gqlQueryMount, gqlVariablesLabel, gqlVariablesMount);
```

- [x] **Step 2: Hide the hint on first edit to the query field**

Replace (inside `_mountGqlEditors`, two call sites — the CodeMirror `onChange` and the fallback textarea's `input` listener):
```js
    _gqlQueryEditor = await createGraphqlEditor({
      parent: gqlQueryMount, value: _gqlQuery, isDark,
      onChange: (v) => { _gqlQuery = v; _syncGqlBodyTextarea(); },
      getVarsList: () => _allVarsList,
    });
```
With:
```js
    _gqlQueryEditor = await createGraphqlEditor({
      parent: gqlQueryMount, value: _gqlQuery, isDark,
      onChange: (v) => { _gqlQuery = v; _syncGqlBodyTextarea(); gqlHintEl.style.display = 'none'; },
      getVarsList: () => _allVarsList,
    });
```

Replace:
```js
      _gqlQueryFallback.addEventListener('input', () => { _gqlQuery = _gqlQueryFallback.value; _syncGqlBodyTextarea(); });
```
With:
```js
      _gqlQueryFallback.addEventListener('input', () => { _gqlQuery = _gqlQueryFallback.value; _syncGqlBodyTextarea(); gqlHintEl.style.display = 'none'; });
```

- [x] **Step 3: Run the seed attempt when switching into the graphql tab**

Read the current `isGraphql` branch first to confirm it still matches:

```bash
grep -n "_mountGqlEditors();" web/static/api/views/request-editor-view.js
```

Expected: one hit inside `_setBodyType`'s `if (isRawText) { ... } else if (isGraphql) { _mountGqlEditors(); }` block, near line 980.

Replace:
```js
    } else if (isGraphql) {
      _mountGqlEditors();
    }
```
With:
```js
    } else if (isGraphql) {
      if (!_gqlSeedAttempted && !_gqlQuery && _rawValue) {
        _gqlSeedAttempted = true;
        _setBodyValue(_rawValue);
        gqlHintEl.style.display = _gqlQuery ? 'none' : '';
      }
      _mountGqlEditors();
    }
```

Note: `_setBodyValue` reads `activeBodyType` to decide which branch to take, and `activeBodyType = type;` already ran earlier in `_setBodyType` (before this `if (isRawText) ... else if (isGraphql) ...` block) — so by this point `activeBodyType` is already `'graphql'` and `_setBodyValue` correctly takes its graphql-parsing branch. `_setBodyValue`'s attempts to call `.setValue()` on `_gqlQueryEditor`/`_gqlVariablesEditor` are no-ops here since those are still `null` (not yet mounted) — the values it actually needs to set, `_gqlQuery`/`_gqlVariables`/`_gqlLastValidVariables`, are plain module variables, and `_mountGqlEditors()` (called right after) reads those into the editors' initial `value`.

- [x] **Step 4: Manual verification — start the dev server**

```bash
python qaclan.py serve --port 7823
```

Open `http://localhost:7823` in a browser, navigate to the API testing section, and open (or create) a request.

- [x] **Step 5: Verify the match case**

Create/edit a request with body type `raw` and body:
```json
{"query":"{ users { id name } }","variables":{"id":1}}
```
Save it, reopen it, click the `graphql` tab. Expected: the Query editor shows `{ users { id name } }` and the Variables editor shows `{"id": 1}` (pretty-printed), with no hint text visible.

- [x] **Step 6: Verify the non-match case**

Create/edit a different request with body type `raw` and a plain REST-shaped body, e.g.:
```json
{"id":1,"name":"widget"}
```
Save it, reopen it, click the `graphql` tab. Expected: both editors are empty, and the hint text "Raw body doesn't look like GraphQL — start typing your query below." is visible above the Query editor. Type any character into the Query editor. Expected: the hint disappears immediately and does not return even if you delete the typed character again.

- [x] **Step 7: Verify no-clobber on tab toggling**

On the request from Step 6, after typing a query and switching to the `raw` tab and back to `graphql` at least twice: expected — the typed query is preserved exactly, the seed logic does not run again (no flicker/reset), and the raw tab still shows the original `{"id":1,"name":"widget"}` untouched.

- [x] **Step 8: Verify existing graphql-native requests are unaffected**

Open a request that was already `body_type='graphql'` before this change (or create one fresh via the graphql tab, save, reopen). Expected: query/variables load exactly as before, no hint ever appears (raw cache is empty for a request that's never touched the raw tab, so the seed guard's `_rawValue` check fails and the seed path never runs).

- [x] **Step 9: Commit**

```bash
git add web/static/api/views/request-editor-view.js
git commit -m "$(cat <<'EOF'
feat: auto-seed GraphQL editor from raw body on first tab switch

Clicking the graphql tab on a request saved as raw previously opened
two empty editors even when the raw body was already GraphQL-shaped
JSON, forcing users to hand-retype the query and variables. Reuses
the existing _setBodyValue parse branch, gated by a one-shot flag so
a deliberate clear of the query field is never silently re-filled.
Shows an inline hint (not a placeholder attr — the CM-based editor
doesn't support one) when the raw body isn't GraphQL-shaped.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:** Auto-seed on first empty visit (Step 3), one-shot guard via `_gqlSeedAttempted` not live emptiness (Step 3 + Global Constraints), reuse of existing `_setBodyValue` parse branch (Step 3), inline hint element not placeholder attribute (Step 1), hint hidden on first edit to either editor path — CM and fallback (Step 2), data shape unchanged (Global Constraints), reversibility / no data loss (inherent — no step touches `_rawValue` or the save payload). All five spec sections have a corresponding step.

**Placeholder scan:** No TBD/TODO. Every step has literal code or literal manual-check text, no "add appropriate handling" language.

**Type consistency:** `_gqlSeedAttempted` (boolean), `gqlHintEl` (DOM node) — each named once and referenced identically across Steps 1-3. `_setBodyValue`, `_rawValue`, `_gqlQuery`, `activeBodyType` all match their existing names in the file verified by direct reads during plan authoring, not assumed.
