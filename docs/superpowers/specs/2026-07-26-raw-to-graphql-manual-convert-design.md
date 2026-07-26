# Raw → GraphQL Manual Convert — Design

## Problem

A client captured a real GraphQL call, which the discovery recorder saved as `body_type='raw'` (the recorder never tags GraphQL — see `docs/superpowers/plans/future-plan/27-graphql-auto-detection.md`, parked). Once saved, the client knew the body was GraphQL and wanted to move it into the GraphQL tab in the request editor to get the query/variables editing experience — and found no way to do it, manual or otherwise.

Root cause, confirmed in `web/static/api/views/request-editor-view.js`: the body-type tabs (raw/form/multipart/graphql) are deliberately isolated from each other. `_rawValue` is a private cache that exists specifically so switching tabs never bleeds one type's content into another (`request-editor-view.js:641-644`). `_setBodyType('graphql')` (line 930) calls `_mountGqlEditors()`, which mounts the query/variables editors from module-level `_gqlQuery`/`_gqlVariables` — seeded once at load from `r.body_graphql`, which is `null` for a request that has always been `raw`. Clicking the "graphql" tab on such a request opens two empty editors; nothing carries the raw JSON over. The client's only option was retyping the query text and variables object by hand into separate fields, copying from the raw tab themselves.

## Non-goals

Discovery-time auto-detection (flagging captured traffic as likely-GraphQL during HAR/record review) is a separate, larger, unvalidated problem — stays parked in `27-graphql-auto-detection.md`. This spec is scoped to the request editor only, for a request that already exists and already has a raw body the user recognizes as GraphQL.

## Design

### Trigger: auto-seed once on raw → graphql switch

In `_setBodyType(type)`, when switching into `'graphql'` (`isGraphql` branch, line 980), check first: if `_gqlQuery` is currently empty and `_rawValue` is non-empty, call the existing parse logic — the same try/catch already in `_setBodyValue`'s graphql branch (lines 659-673) — against `_rawValue` before mounting the editors, instead of mounting cold.

```
if (isGraphql) {
  if (!_gqlQuery && _rawValue) _setBodyValue(_rawValue);
  _mountGqlEditors();
}
```

`_setBodyValue`'s graphql branch already does exactly the right parse: `JSON.parse(_rawValue)`, take `query` if it's a string, take `variables` if present (default `{}`), and on any parse failure or non-string `query`, fall back to empty (`_gqlQuery = ''`). No new parsing code — this path already exists and is already exercised (it runs today when an example snapshot is applied to a request that's already on the graphql tab).

**Guard rationale:** gating on `!_gqlQuery` means this only fires the first time the user lands on an empty graphql tab. If they've already typed a query (or a prior seed populated one) and are just toggling tabs to compare raw vs. graphql, re-visiting graphql never overwrites their work. This makes the feature purely a helpful default for the empty case, never a surprise overwrite.

### Non-match case: inline hint, not a placeholder

`createGraphqlEditor` (`web/static/api/components/graphql-editor.js:79`) is CodeMirror-based and takes no placeholder option — only the fallback `<textarea>` path (`_gqlQueryFallback`, used when CM6 isn't loaded) supports a native `placeholder` attribute. Since the primary editor is CM in normal operation, a placeholder-only approach would silently not work for most users. Use a small inline hint element instead, which works identically for both the CM and fallback paths:

- A `<div>` sits above `gqlQueryMount` inside `gqlWrap`, hidden by default (`display:none`).
- When the auto-seed attempt runs and finds no string `query` (parse failed, or `query` present but not a string — e.g. a REST/search-DSL body with an object-shaped `query` field), show it: "Raw body doesn't look like GraphQL — start typing your query below."
- When the attempt finds a valid string `query`, the hint never shows (editors are already populated).
- Hide the hint the moment the user types anything: hook into the existing `onChange` handlers already wired for both paths (`onChange: (v) => { _gqlQuery = v; ... }` at line 883 for CM, the `input` listener at line 893 for the fallback) — first non-empty value hides the hint.
- If the user clears the query back to empty by hand, the hint does not reappear (it only ever reflects the auto-seed attempt's outcome, not general empty-state); this avoids the hint reappearing mid-edit and reading as a chastisement.

### Data shape (unchanged, confirmed against existing code)

- `body_type`: `'graphql'` (one of `BODY_TYPES = ['none','raw','form','multipart','graphql']`, `request-editor-view.js:566`).
- `body_graphql`: JSON string `{query: string, variables: object}` — matches `_buildPayload()` (line 1727), and matches what `postman_parser.py`/`bruno_parser.py` already produce on import. No `operationName` field — dropped consistently everywhere already; the convert action doesn't introduce anything new here.

### Safety / reversibility

No validation gate is needed on the convert action itself, because there is no destructive path to guard against:

- `_buildPayload()` (line 1712) always sends `body: _rawValue` on save, regardless of `activeBodyType`. The raw text is never cleared by switching tabs or by saving with a different active type.
- Switching back to the raw tab at any point shows `_rawValue` exactly as it was — untouched by whatever happened on the graphql tab.
- Worst case for a raw body that isn't actually GraphQL-shaped: the user sees the inline hint and two empty editors — functionally identical to today's default behavior, just with an explanatory line instead of silence.

## Files touched

- `web/static/api/views/request-editor-view.js` — `_setBodyType`'s `isGraphql` branch (auto-seed call), hint `<div>` creation near `gqlWrap`/`gqlQueryMount` (around line 854-867), hint show/hide wiring into the two existing `onChange`/`input` handlers (lines 883, 893).

No backend, schema, or other-file changes — everything needed already exists in this one file.

## Manual verification plan

No automated test suite in this project (per `CLAUDE.md`). Verify by hand in the running web UI:

1. Save a request with `body_type='raw'` and a body of `{"query":"{ users { id name } }","variables":{"id":1}}`. Open it, click the "graphql" tab — query and variables editors should populate immediately, no hint shown.
2. Save a request with `body_type='raw'` and a plain REST JSON body (no `query` key, or a `query` key holding an object/array). Click "graphql" tab — editors open empty, hint line visible. Type anything in the query editor — hint disappears.
3. On a request that already has `body_type='graphql'` with existing content, toggle to raw and back to graphql repeatedly — content must never be overwritten or reset.
4. After converting (case 1) and saving, switch back to the raw tab — original raw text must still be there unchanged.
