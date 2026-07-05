# {{var}} exists/missing highlighting

## Problem

Inputs that accept `{{var}}` tokens (headers, query params, path vars, auth
fields) currently tint blue (`kv-value--var-ref`) whenever the value contains
*any* `{{...}}` token, regardless of whether that variable actually resolves.
A typo'd or deleted variable name looks identical to a valid one until the
request is sent and `resolve_vars()` logs a warning and substitutes an empty
string. Users want the field itself to signal exists vs. missing while
they're still editing.

## Scope

**In scope:** headers table, query-params table, path-vars table, auth
fields (bearer token, basic auth user/pass, API key value, OAuth2
token_url/client_id/client_secret).

**Out of scope:** form-urlencoded / multipart body tables (same
`key-value-table.js` component, but left on the existing single-color
behavior — no regression risk introduced there), the raw/JSON body editor
(CodeMirror), and pre/post script textareas. None of these get the new
coloring.

## Existence rule

A variable "exists" if its name appears in the same list `getAllVars()`
already returns for autocomplete — i.e. the active environment's variables
plus the bound collection's variables. This list is static per editor load;
it does not include variables a pre-script sets at runtime via
`qc.set(...)` (those live in `state.qaclan_vars` and are only known after
that script actually runs). A pre-script-set variable referenced elsewhere
in the request will show as "missing" even though it will resolve
correctly at send time. This is an accepted, documented tradeoff — not
solved by this design.

## Mixed-token behavior

A value can contain more than one `{{var}}` token (e.g.
`Bearer {{token}} / {{other}}`). If every token resolves, the field is
"exists" (green). If at least one token doesn't resolve, the whole field is
"missing" (red) — no separate third "mixed" state.

## Colors

- Exists: green tint/border (replaces nothing existing — this is a new
  state).
- Missing: red tint/border.
- No `{{...}}` tokens present, or the known-vars list hasn't loaded yet:
  neutral (no special class) — avoids a flash of false-red before the
  first `getAllVars()` fetch resolves.

The existing `.kv-value--var-ref` blue tint is left untouched in the CSS
and continues to apply, unchanged, to the form/multipart body tables that
opt out of the new behavior.

## Components

### 1. `web/static/api/components/var-style.js` (new)

Small shared helper, no state of its own:

- `varTokensIn(value: string) -> string[]` — extract all `{{name}}` token
  names (trimmed) via `/\{\{([^}]+)\}\}/g`.
- `applyVarStyle(inp: HTMLInputElement, knownNames: Set<string>|null) -> void`
  — computes token list from `inp.value`; if empty or `knownNames === null`,
  removes both `kv-value--var-ok` and `kv-value--var-missing`; otherwise
  toggles `kv-value--var-ok` when every token is in `knownNames`, else
  toggles `kv-value--var-missing`.

Both `key-value-table.js` and `request-editor-view.js` (for auth fields)
import this instead of duplicating the regex/class logic.

### 2. `key-value-table.js` changes

- New optional option `getKnownVarNames?: () => Set<string>|null`.
- When provided: each value `<input>`'s `input` listener calls
  `applyVarStyle(valInput, getKnownVarNames())` instead of the current
  `_applyVarStyle`/`_isVarRef` path.
- When omitted (form/multipart body tables' call sites, which won't pass
  this new option): existing `_isVarRef`/`kv-value--var-ref` behavior is
  unchanged — zero regression there.
- New returned method `restyleAll()`: iterates all current rows' value
  inputs and re-runs `applyVarStyle` — used after the known-vars cache
  finishes its first async load, so rows rendered before the fetch
  resolved get colored retroactively.

### 3. `request-editor-view.js` changes

- One shared `_knownVarNames` cache, initialized to `null`.
- `_refreshKnownVarNames()`: calls the existing `getAllVars()`, builds
  `new Set(vars.map(v => v.key))`, stores it, then calls `restyleAll()` on
  the headers/params/path-vars tables and re-applies styling to all
  currently-rendered auth `<input>`s (tracked in a small array pushed to
  in `_makeField`). Invoked once, fire-and-forget, right after those
  tables/fields are constructed.
- `getKnownVarNames: () => _knownVarNames` passed into `createKeyValueTable`
  for `paramsTable`, `headersTable`, `pathVarsTable` only (not
  `formBodyTable` / `multipartBodyTable`).
- `_makeField()` (auth fields) calls `applyVarStyle(inp, _knownVarNames)` on
  its own `input` listener, mirroring the key-value-table wiring.

### 4. CSS (`web/static/style.css`)

Add alongside the existing `.kv-value--var-ref` rule (untouched):

```css
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
```

`--success-bg`/`--success-border`/`--danger-bg`/`--danger-border` are
already defined in `style.css` (lines 21-26, redefined per-theme at
65-68) — same tokens other status UI in this file already uses.

## Known limitations (accepted, not building)

- No live refresh on environment switch mid-edit; cache is fetched once
  per editor load.
- Runtime-only variables (set by a pre-script via `qc.set`) always show as
  "missing" since they're not in the static `getAllVars()` list.
- Auth fields' known-vars tracking uses a plain array of created
  `<input>` elements re-styled on refresh; fine at this scale (at most a
  handful of auth fields per request).
