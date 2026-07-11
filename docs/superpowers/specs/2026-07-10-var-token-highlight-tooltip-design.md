# {{var}} per-token text coloring + value tooltip

## Relationship to prior work

`2026-07-05-var-exists-highlighting-design.md` (shipped, see commits
`774350a`, `34803d1`, `a894171`, `63c1bb9`, `c6f57da`) added whole-field
background tinting (`kv-value--var-ok` / `kv-value--var-missing`) to
headers/params/path-vars/auth value inputs. That feature is **unchanged and
stays in place**. This spec adds a second, independent layer on top of it:
coloring the `{{token}}` text itself (Postman-style) plus a hover tooltip
showing the variable's current value — motivated by two gaps in the shipped
feature: (1) a mixed-token field only shows one whole-field verdict, not
which specific token is the problem; (2) users can't see a variable's
current value without leaving the field.

## Problem

`.kv-value--var-ok`/`--var-missing` tint the whole input's background/border.
Two problems:

1. In a mixed field (`Bearer {{token}} {{typo}}`) the whole field just shows
   "missing" (red) — no visual indication of *which* token is the problem.
2. Users can't see what a variable currently resolves to without leaving the
   field and checking the Environments/Collection Variables UI.

## Scope

**In scope:** same four surfaces as the shipped feature — headers table,
query-params table, path-vars table, auth fields (bearer token, basic
auth user/pass, API key value, OAuth2 token_url/client_id/client_secret) —
**plus** the URL bar input (`request-editor-view.js`'s `urlInput`), which
had no `{{var}}` treatment at all before this.

**Out of scope (explicit non-goals for this pass):**
- Whole-field background tint for the URL bar. The shipped tint is
  designed for short header/param values; tinting an entire URL green/red
  based on whether *all* its vars resolve is noisy for a long string mixing
  literal path/query text with var references. The URL bar gets token-text
  coloring + tooltip only.
- `{{` autocomplete / var-picker button on the URL bar. Today `urlInput` has
  no `inline-var-drop`/`var-picker` wiring at all. Adding that is a
  separate feature; this spec only adds visual coloring + tooltip to
  whatever the user types or pastes there.
- Form-urlencoded / multipart body tables, the raw/JSON body editor
  (CodeMirror), pre/post script textareas — unchanged, same exclusions as
  the shipped feature.
- Secret masking in the tooltip (see Tooltip section) — deliberately not
  doing this; tooltip always shows the plain value.

## Existence rule

Unchanged from the shipped feature: a variable "exists" if its name is in
the `Set` built from `getAllVars()` (active environment + bound collection
vars). Same accepted tradeoff — pre-script `qc.set(...)` runtime vars are
not included and show as missing.

**Per-token verdict, not whole-field verdict:** each `{{name}}` token's own
color is decided independently — `knownNames.has(name) ? ok : missing` —
unlike the shipped whole-field tint, which collapses any mix of ok/missing
tokens into one "missing" verdict for the whole field. Both coexist: the
field-level tint keeps its existing (mixed → missing) rule; the token-level
text color is per-token and finer-grained.

## Visual design

- Whole-field bg/border tint (`kv-value--var-ok`/`--var-missing`): **unchanged**, still applied by existing `var-style.js` logic, still only on headers/params/path-vars/auth (not URL bar).
- New: the `{{name}}` substring itself renders in green (`var-tok--ok`) or red (`var-tok--missing`) text, replacing the current uniform (transparent-ish/default) text color for that substring only. Non-token text keeps the normal input text color.
- Colors reuse the existing solid `--success` (`#10b981`) / `--danger` (`#ef4444`) custom properties as text color — the same ones `response-status-ok`/`response-status-err` and `record-status-badge` already use for readable colored text (`style.css`). NOT `--success-border`/`--danger-border` — those are low-alpha (10-28%) values meant for subtle backgrounds/borders and would be nearly invisible as text color. No new color values invented.

## Tooltip

Hovering a `{{name}}` token shows a small floating tooltip:

- **Known variable:** `{{name}}` (bold) + its current value (plain text,
  monospace) + a small `Environment` / `Collection` group label, matching
  the `group` field `getAllVars()` already returns.
- **Missing variable:** `{{name}}` (bold) + `Not defined in environment or
  collection` in the danger color.
- **No secret masking.** `is_secret` vars show their plain value in the
  tooltip, unlike the dropdown previews in `var-picker.js`/
  `inline-var-drop.js`, which mask secrets. This is a deliberate,
  explicitly chosen inconsistency — the tooltip's job is "let me see the
  value without leaving this field," which is undermined by masking.
- No custom tooltip CSS exists in this repo today (grep confirmed) — this
  introduces the first one. Single shared floating `<div>`, same
  positioning pattern as `var-picker.js`'s popup (`position:fixed`,
  appended to `document.body`, flips above/below based on viewport space).

## Why an overlay, not CodeMirror or contenteditable

A plain `<input>` cannot render per-substring text color — this is a hard
platform limitation, not a missing feature. Three ways to work around it
were considered:

1. **Overlay technique (chosen):** the real `<input>` stays as the source
   of truth for editing (value, caret, selection, paste) with its text
   color set to transparent; a synced, non-interactive `<div>` sits on top
   rendering the same text with colored `<span>`s per token. All existing
   caret-based logic — `inline-var-drop.watchInput`'s `{{` detection via
   `selectionStart`, URL-paste parsing, `var-picker` button anchoring —
   keeps working completely unmodified, because the real input never stops
   being a real, normally-behaving `<input>`. Smallest diff, lowest risk.
2. **CodeMirror 6 single-line instances:** CM6 is already vendored
   (`window.CM6`, used by `json-editor.js` for the JSON body editor) and
   has a built-in `hoverTooltip` extension that's a natural fit. Rejected
   for this pass because it would mean instantiating one CM6 editor per
   table row (headers/params/path-vars can each have many rows) and
   rebuilding the existing caret-based `{{` autocomplete on CM6's APIs
   instead of reusing `inline-var-drop.js` as-is — a much larger rewrite
   for a single-line-field use case CM6 wasn't set up for here.
3. **contenteditable div:** native per-character styling, but requires
   reimplementing value get/set, caret/selection (`selectionStart`/
   `setSelectionRange` don't exist on contenteditable), and paste handling
   for every affected field type. Rejected as highest risk, most code
   churn, for the smallest incremental benefit over option 1.

## Components

### 1. `var-style.js` — additive change

New export alongside the existing `varTokensIn`/`applyVarStyle` (both
unchanged):

- `tokenSpansIn(value: string) -> Array<{name: string, start: number, end: number}>`
  — same token extraction as `varTokensIn`, but keeps the match's character
  offsets (`start`/`end` are indices into `value`, `end` exclusive,
  covering the full `{{...}}` span including braces) instead of just the
  trimmed name. Used by the overlay renderer to slice `value` into
  plain-text and token segments.

### 2. `var-token-overlay.js` (new)

`attachTokenOverlay(inp: HTMLInputElement, getKnownVarNames: () => Set<string>|null) -> { refresh(): void }`

- Wraps `inp` in a `position: relative` container inserted in `inp`'s
  place in the DOM (caller swaps in the wrapper element instead of the
  bare input at the point where it's added to the page — the `inp`
  reference itself is unchanged and still used for `.value`/listeners
  everywhere else).
- Creates the overlay `<div>` (`pointer-events: none`, absolutely
  positioned to fill the wrapper), copies `inp`'s computed
  padding/border/font-family/font-size/letter-spacing/line-height at
  attach time via `getComputedStyle(inp)` so the overlay lines up
  pixel-for-pixel regardless of which CSS class `inp` has (`kv-value`,
  `req-url-input`, or auth `input-sm`) — no per-surface CSS duplication.
- Sets `inp.style.color = 'transparent'` and an explicit `caretColor` so
  the real glyphs are invisible but the text cursor stays visible.
- Re-renders the overlay's `innerHTML` from `tokenSpansIn(inp.value)` on
  every `'input'` event: plain segments HTML-escaped as text, token
  segments wrapped in `<span class="var-tok var-tok--ok">` or
  `<span class="var-tok var-tok--missing">` per that token's own
  `knownNames.has(name)` check.
- Syncs `overlay.scrollLeft = inp.scrollLeft` on `inp`'s `'scroll'` event,
  so overlay content tracks the input's internal horizontal scroll once
  text overflows the visible width.
- One `mousemove` listener on `inp`: on each move, rect-tests
  `event.clientX/clientY` against the overlay's currently-rendered
  `.var-tok` spans' `getBoundingClientRect()` (geometry APIs work fine
  despite `pointer-events: none`); a hit shows the shared tooltip anchored
  to that span; no hit (or `mouseleave`) hides it. Deliberately not using
  per-span `mouseenter`/`mouseleave` listeners, since spans are destroyed
  and recreated on every keystroke.
- `refresh()`: re-runs the render step (same logic as the `'input'`
  handler) without requiring a value change — called once the async
  known-vars cache resolves, same pattern as `key-value-table.js`'s
  existing `restyleAll()`.

### 3. Shared tooltip singleton (inside `var-token-overlay.js`)

One `<div>` lazily created on first use, appended to `document.body`,
reused across all attached inputs (mirrors the single shared popup pattern
already used by `var-picker.js`). Positioned via the hovered span's
`getBoundingClientRect()`, flipping above/below based on remaining
viewport space, same logic shape as `inline-var-drop.js`'s `_position()`.

### 4. `key-value-table.js` — wiring

Value inputs for the three in-scope tables (headers/params/path-vars, not
form/multipart body) additionally call `attachTokenOverlay(valInput,
getKnownVarNames)` at row-creation time when `getKnownVarNames` was
provided (mirrors how `_styleValueInput` already branches on that same
option). The returned wrapper element (not the bare `valInput`) is what
gets appended into the table cell. `restyleAll()` additionally calls
`refresh()` on each row's attached overlay.

### 5. `request-editor-view.js` — wiring

- Auth fields: `_makeField` calls `attachTokenOverlay(inp, () =>
  _knownVarNames)` for every field it creates (bearer/basic/api-key,
  including `type=password` ones — the browser's masking dots are drawn in
  `currentColor` too, so `color: transparent` hides them the same way it
  hides normal text, letting the overlay's colored token spans show
  through uniformly). `_refreshKnownVarNames` additionally calls
  `refresh()` on each tracked auth overlay.
- URL bar: `urlInput` gets `attachTokenOverlay(urlInput, () =>
  _knownVarNames)` once, at creation. No whole-field tint class is ever
  applied to it (see Scope). No `inline-var-drop`/`var-picker` wiring is
  added (see Scope).

### 6. CSS (`web/static/style.css`)

```css
.var-tok--ok {
  color: var(--success-border);
}
.var-tok--missing {
  color: var(--danger-border);
}
```

Plus a new (first-of-its-kind in this repo) tooltip block, styled to match
existing popup surfaces (`var-picker.js`/`inline-var-drop.js` popups) —
dark-on-light or light-on-dark background per theme, small padding,
monospace value line, subtle shadow, `z-index` above other floating UI.

## Scope amendment: Body, Pre/Post Scripts, Assertions

The sections above (headers/params/path-vars/auth/URL bar) were the
original scope. Adding three more sections from the request-details view
(`request-editor-view.js`, sections switched ~line 175), none of which
have any `{{var}}` exists/missing awareness today (confirmed by code
search — inline-drop autocomplete exists on body/scripts, but no
`applyVarStyle` anywhere near them; assertions have zero var-awareness of
any kind, no imports from `var-style.js`/`inline-var-drop.js`/
`var-picker.js`).

These three are not structurally uniform, so each gets the technique that
fits its actual DOM shape:

### Assertions — `assertion-builder.js` (plain `<input>`s, easiest)

`extraInput` (path/header-key, `assertion-builder.js:51-56`) and `valInput`
(expected value, `:64-69`) are plain text inputs — same shape as auth
fields. Both get `attachTokenOverlay(inp, getKnownVarNames)` (per-token
text color + tooltip) directly; `valInput` additionally keeps the option
of the whole-field bg tint via `applyVarStyle`, for parity with
headers/params (mixed content is common in expected-value assertions).
`createAssertionBuilder()` (called with no args today at
`request-editor-view.js:325`) gains a `getKnownVarNames` option, threaded
through the same way `key-value-table.js` already does it.

### Pre-request / Post-response scripts — plain `<textarea>` (multi-line overlay)

Both script panes are plain `<textarea>` (`request-editor-view.js:921-930`,
built once in `makeScriptSection()` and reused by `makePreScriptSection`/
`makePostScriptSection`). `attachTokenOverlay` is extended to support
`<textarea>` as well as `<input>`: the overlay div switches to
`white-space: pre-wrap` (matching textarea's line-wrapping instead of an
input's single line), and scroll sync additionally tracks `scrollTop` (not
just `scrollLeft`) since textareas scroll vertically. Token
extraction/coloring logic (`tokenSpansIn`, span rendering, mousemove
hit-testing) is unchanged — only the CSS/scroll-sync branch differs by
element type. No CM6 migration for scripts in this pass — they stay plain
textareas; this is the same technique already designed for inputs, just
generalized to handle wrapped multi-line text.

### Body — CM6 (primary path) + `bodyFallback` textarea (rare path)

The raw/JSON body editor is CM6-based (`createJsonEditor`,
`json-editor.js`) except when `window.CM6` fails to load, in which case
`bodyFallback` (a plain `<textarea>`, `request-editor-view.js:387-390`)
is shown instead. Both paths get highlighting, via two different
mechanisms:

- **`bodyFallback` (rare path):** same multi-line `attachTokenOverlay`
  technique as the script textareas above — no new infrastructure.
- **CM6-active (common path, real fix for the user's complaint):** the
  vendored `web/static/vendor/codemirror/cm6.js` bundle currently only
  exposes `EditorState, EditorView, Compartment, basicSetup, oneDark,
  indentUnit, python, javascript, json, jsonParseLinter, linter,
  lintGutter` on `window.CM6` (confirmed via `REBUILD.md` and the bundle's
  own end-of-file export list) — no `Decoration`, `ViewPlugin`,
  `StateEffect`, `RangeSetBuilder`, or `hoverTooltip`, which are the CM6
  primitives required to color arbitrary text spans and show hover
  tooltips inside a real CM6 editor. `REBUILD.md` already documents a
  ready-made "entry.js with scaffolding" that adds exactly
  `Decoration`/`ViewPlugin`/`ViewUpdate`/`RangeSetBuilder`/`Compartment` —
  this spec additionally needs `hoverTooltip` added to that same import
  list and `window.CM6` export object (one more line in the documented
  process, not a new mechanism).

  Once available, `json-editor.js` gets a new `ViewPlugin` that:
  1. Scans the current document text for `{{name}}` tokens
     (`tokenSpansIn`, reused from `var-style.js` — CM6's doc is plain text
     under the hood, same regex applies) on every doc change
     (`ViewUpdate.docChanged`).
  2. Builds a `Decoration` set marking each token span with a CSS class
     (`var-tok--ok`/`var-tok--missing`, same classes as the input overlay
     — one shared CSS rule set, no duplication) via `Decoration.mark`.
  3. Registers a `hoverTooltip` extension that, given a hovered position,
     checks whether it falls inside a token's range and if so returns the
     same tooltip content (name/value/group or "not defined") as the
     shared tooltip used elsewhere — reusing the *content-building* logic
     from `var-token-overlay.js` (extracted into a small shared function)
     even though the *rendering* mechanism differs (CM6's own tooltip DOM
     vs. the hand-rolled floating div used for plain inputs).
  4. Is passed `getKnownVarNames` the same way `createJsonEditor` already
     receives `onChange` — a new option on `createJsonEditor({...,
     getKnownVarNames})`, re-evaluated on the async known-vars refresh via
     a small `forceRedecorate` call (CM6's decoration `ViewPlugin` needs an
     explicit dispatch to recompute when its *inputs* change without a doc
     edit — same "refresh after async load" shape as `restyleAll()`
     elsewhere).

  **Graceful degradation:** `json-editor.js` feature-detects
  `window.CM6.Decoration` before registering this extension; if the vendor
  bundle hasn't been rebuilt yet (e.g. a dev environment that skipped the
  rebuild step), the CM6 editor still works exactly as it does today,
  just without token coloring — never a hard failure, matching the
  existing `createJsonEditor` → `null` graceful-fallback pattern already
  in this codebase.

**Vendor bundle rebuild is in scope for this plan** (per your choice):
one task follows `REBUILD.md`'s documented process (throwaway dir, pin
`@codemirror/*@6` + `esbuild`, add `hoverTooltip` to the scaffolded
`entry.js`, run `esbuild --bundle --format=iife --minify`, commit the
regenerated `cm6.js`) — a one-time, repo-blessed process (the scaffold in
`REBUILD.md` strongly suggests this was already anticipated), requiring
npm registry access during implementation.

## Known limitations (accepted, not building)

- Native text selection/copy on an overlaid input still functions
  (selecting still copies the real, invisible text) but looks visually odd
  — a selection highlight band appears with no visible glyphs under it,
  since the real characters are transparent and the overlay text isn't
  itself selectable.
- IME composition (CJK/other composed input) isn't specially handled — the
  overlay re-renders on whatever `'input'` events the browser fires during
  composition. Not automated-tested (no test framework in this repo);
  flagged as a manual-check item.
- Per-keystroke overlay re-render (`innerHTML` rebuild) is unbounded by
  debounce, matching the existing `_applyVarStyle` pattern of running on
  every `'input'` event — acceptable given these are short single-line
  field values, including the URL bar.
- Tooltip hit-testing depends on the overlay's spans existing in the DOM
  at the moment of `mousemove`; a token that scrolled out of the input's
  visible viewport (long values) won't be hoverable until scrolled back
  into view — acceptable, matches how the visible text itself works.
- Script/body textareas reuse the same per-keystroke, no-debounce overlay
  rebuild; textarea values (script bodies) can be much longer than a
  header/param value, so this is a slightly bigger re-render per keystroke
  than the single-line case — acceptable at expected script sizes, not
  optimized further in this pass.
- The CM6-active body editor's hover tooltip uses CM6's own `hoverTooltip`
  DOM/positioning (not the hand-rolled floating div used everywhere else),
  so it will look visually distinct (CM6's default tooltip chrome) unless
  explicitly restyled to match — restyling to match is a nice-to-have, not
  required for correctness, and left to implementation-time judgment.
- If the CM6 vendor bundle rebuild can't complete during implementation
  (e.g. no npm registry access in the build environment), the plan's CM6
  decoration task is blocked but everything else (inputs, textareas,
  `bodyFallback`) ships independently — the feature-detection guard means
  this is a soft dependency, not an all-or-nothing gate.
