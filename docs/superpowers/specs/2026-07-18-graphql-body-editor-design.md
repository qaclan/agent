# GraphQL request body: buffer-separation fix + smart split-pane editor

## Problem

Two related issues in the API-testing request editor's body section (`web/static/api/views/request-editor-view.js`), reported while investigating why discovery/recording never surfaces GraphQL calls distinctly from REST:

1. **Bug:** the `raw` and `graphql` body-type tabs share a single CodeMirror instance and a single backing textarea (`isText = type === 'raw' || type === 'graphql'` at the current `_setBodyType`). Switching between them shows/overwrites the same content instead of keeping independent state, unlike `form`/`multipart`, which already keep separate row-sets (`_formRows`/`_multipartRows`) specifically so switching tabs doesn't leak one type's content into another's.
2. **UX gap:** even where `body_type='graphql'` is correctly set (currently only via Postman import — `cli/api_discovery/postman_parser.py:81-84`), the editor renders it as a single raw-JSON textarea with a placeholder hint (`'{ "query": "{ users { id name } }" }'`). It works functionally (`cli/api_runner.py:602-614` parses `{query,variables}` correctly at send time) but isn't a real GraphQL editor — no syntax highlighting, no dedicated query/variables split, unlike Postman/Insomnia/GraphiQL.

## Relationship to prior investigation

Root-caused via `superpowers:systematic-debugging`: confirmed HAR-based discovery (`web/api/routes/discovery.py` record/HAR capture → `cli/api_discovery/har_parser.py`) never tags anything `body_type='graphql'` — only Postman import does. Auto-detecting GraphQL calls during discovery was explored in depth (signal design, industry precedent, adversarial gap analysis) and **explicitly parked** — see `docs/superpowers/plans/future-plan/27-graphql-auto-detection.md`. This spec covers only the editor-side fix for body types the user (or Postman import) has already tagged `graphql`.

## Scope

**In scope:**
- Independent state for `graphql` body content, so switching `raw`↔`graphql` never leaks or overwrites content (the bug fix).
- A real two-pane GraphQL editor: a syntax-highlighted **Query** pane (GraphQL text) + a **Variables** pane (JSON, reusing the existing JSON editor).
- Adding a GraphQL language pack to the vendored CM6 bundle (`web/static/vendor/codemirror/cm6.js`) so the Query pane gets actual GraphQL syntax highlighting, not plain text.

**Explicit non-goals for this pass:**
- **Auto-detection of GraphQL requests during discovery/recording.** Fully designed, parked — see the future-plan doc above. Nothing in this spec changes `har_parser.py`'s body-type classification.
- **`operationName` field.** Confirmed via repo-wide grep that nothing reads it today — `cli/api_runner.py`'s graphql send path only uses `query`/`variables`, and `postman_parser.py`'s graphql import already silently drops it. Adding a UI field for it without also wiring send-time support would be decorative. The wire format this spec produces stays `{query, variables}` only.
- **Schema-aware autocomplete / introspection.** The Query editor is schema-less: syntax highlighting, bracket matching, and GraphQL-grammar completion only — no field/type-aware suggestions (that needs a fetched `GraphQLSchema`, tied to the same future introspection-probe idea in the parked doc).
- **Backend, database, or wire-format changes.** `body_type='graphql'` + `body = '{"query":...,"variables":{...}}'` in the existing `body` column is unchanged — `cli/api_runner.py` already parses exactly this shape.
- **Regressions to `none`/`raw`/`form`/`multipart`.** Their behavior must be byte-for-byte unchanged; this spec's job is to stop `graphql` from riding on `raw`'s state, not to touch the other three.

## Why this approach (alternatives considered)

**For the buffer-separation fix:** mirror the existing `form`/`multipart` pattern (own state variables, captured on leaving the tab, restored on entering it) rather than inventing a new mechanism. This is the established precedent in the same file for exactly this problem (two body types that must not share content) — no reason to design something new.

**For the Query editor, three options considered:**

1. **Plain `<textarea>`, keep current behavior, just fix the buffer bug.** Rejected as the sole fix — user explicitly asked for a real editor ("smart editor like what postman do, instead of showing only string, as string would be tough to edit"). A raw string field for a structured query language is a real usability gap, not a nice-to-have.
2. **Reuse the existing JSON editor (`createJsonEditor`) for the Query pane too**, since GraphQL bodies are "just JSON with a query string inside." Rejected — the *combined* `{query,variables}` blob is JSON, but the *query* value itself is GraphQL syntax (braces, field selections, `$variable: Type!` defs, directives), not JSON. Editing it inside a JSON-mode editor means no real syntax awareness for the actual language being written, and awkward escaping of newlines/quotes as a JSON string value while typing. This is precisely what "showing only string" meant — technically it's JSON-editing, but the thing the user is actually composing is a GraphQL document.
3. **Add a real GraphQL language pack to the vendored CM6 bundle (chosen).** Verified live during design: `cm6-graphql@0.2.1` exists on npm, peer-depends only on packages already in this repo's CM6 stack (`@codemirror/{state,view,language,autocomplete,lint}@^6`), and exports a `graphql(schema?, opts?)` function usable with **no schema** — confirmed by reading its shipped `.d.ts` and un-minified `dist/index.js`: the bundled `lint` extension explicitly returns `[]` when no schema is loaded (`if (!schema) return [];`), so schema-less mode is safe and won't show false-positive error squiggles under valid queries. This matches the existing codebase pattern exactly: CM6 is already vendored offline (no CDN, checked into the repo, bundled into the Nuitka binary — `REBUILD.md`), and `createJsonEditor` is the direct template to mirror for a new `createGraphqlEditor`.

**Query and Variables as two separate panes**, not one editor with a toggle, because that's the actual Postman/Insomnia/GraphiQL convention the user is asking to match, and because the two panes have genuinely different content types (GraphQL text vs. JSON) that benefit from different language modes running simultaneously, side by side.

## Architecture

**Wire format unchanged.** On disk and over the wire, a GraphQL body is still exactly one JSON string: `{"query": "...", "variables": {...}}`, stored in the existing `body` column with `body_type='graphql'`. Every backend consumer (`cli/api_runner.py:602-614`'s send-time query/variables resolution, `cli/api_discovery/postman_parser.py:81-84`'s import, `web/static/api/curl-builder.js:83-84`'s cURL export) keeps working against this shape completely unchanged — none of them are touched by this spec.

**Client-side state.** The editor gains a third piece of independent body-type state, alongside the existing `_formRows`/`_multipartRows`:

```
_gqlQuery: string       // raw GraphQL text, Query pane's content
_gqlVariables: string   // JSON text, Variables pane's content
```

Two new CM6 editor instances (Query via the new `createGraphqlEditor`, Variables via the existing `createJsonEditor`) are mounted/unmounted together whenever the active body type enters/leaves `graphql`, exactly parallel to how the raw editor's single `_cmEditor` is mounted/unmounted today.

**Continuous sync to the hidden save-buffer.** The existing hidden `bodyTextarea` element is the file's single documented "source of truth for `_save()`" and is also read directly by two other call sites — `_copyAsCurl` (cURL export) and a curl-paste dirty-check — neither of which this spec touches. Rather than adding a `graphql`-specific branch to every one of those read sites, both new panes' `onChange` handlers immediately re-serialize `{query: _gqlQuery, variables: JSON.parse(_gqlVariables)}` into `bodyTextarea.value` on every keystroke — the same "keep the hidden textarea live" pattern the raw editor's own `onChange` already uses. This means `_buildPayload()`, `_copyAsCurl`, and the dirty-check all continue working with **zero changes**, verified by tracing all three call sites during design.

**Invalid-JSON-mid-typing handling.** If the Variables pane currently contains invalid JSON (user mid-edit), the sync step keeps the *last successfully parsed* variables object in `bodyTextarea.value` rather than corrupting the save buffer — the Variables pane's own inline JSON linter (inherited for free from reusing `createJsonEditor`) gives the user live error feedback without that transient invalid state ever reaching what gets saved or sent.

**No auto-migration of content across type switches.** Switching `raw → graphql` (or back) never tries to parse one type's content into the other's shape — matches the existing, deliberate `form`/`multipart` behavior (explicit code comment: "otherwise switching tabs would show one type's fields under the other's tab"). A fresh `graphql` tab starts with empty Query/Variables panes unless the request was already saved as `graphql` (or is being loaded from an example), in which case both panes are seeded by parsing the existing `body` JSON.

**Format/minify/insert-variable toolbar** (currently shared by `raw`/`graphql`) becomes `raw`-only. It operates on a single JSON/text buffer's value, which doesn't map cleanly onto two independently-scrolled panes; the Variables pane still gets `{{var}}` highlighting/autocomplete/hover "for free" via `createJsonEditor`'s existing `getVarsList` support, and the new Query editor gets the identical `{{var}}` treatment ported into `createGraphqlEditor` (same `tokenSpansIn`-based decoration/hover-tooltip/autocomplete primitives `json-editor.js` already uses, just attached to the GraphQL-mode editor instead).

**Offline/CM6-unavailable fallback.** Both new panes degrade to plain `<textarea>` if `createGraphqlEditor`/`createJsonEditor` return `null` (CM6 failed to load) — same graceful-degradation contract every other CM6 usage in this codebase already follows. In practice this is a rarely-hit path: CM6 ships bundled inside the Nuitka binary, not fetched from a CDN, so it's defensive rather than a real day-to-day scenario.

## Components

### `web/static/vendor/codemirror/cm6.js` (regenerated) + `REBUILD.md` (updated)

Add `cm6-graphql@0.2` (+ its `graphql@16` and `@lezer/highlight@1` peers) to the documented rebuild's dependency list and `entry.js` scaffold, exposing `graphql` (the `(schema?, opts?) => Extension[]` function) on `window.CM6`. One-time manual rebuild process, already documented and repo-blessed for exactly this kind of addition (the same process previously added `Decoration`/`ViewPlugin`/`hoverTooltip`/`autocompletion` for the `{{var}}` highlighting feature).

Bundle size grows meaningfully — `graphql-js` and `graphql-language-service` (both transitive deps of `cm6-graphql`, needed even in schema-less mode since their imports are static) are not small. Accepted tradeoff for a local-first desktop app bundled once into the binary, not fetched per page load; actual measured delta gets recorded in `REBUILD.md` when the rebuild is performed.

### `web/static/api/components/graphql-editor.js` (new)

`createGraphqlEditor({ parent, value, isDark, onChange, getVarsList }) → Promise<editor|null>` — structurally a direct mirror of `createJsonEditor` in `json-editor.js` (same return shape: `{ getValue, setValue, refresh, focus, destroy }`, same `{{var}}` decoration/hover-tooltip/autocomplete wiring), swapping the `json()`/`jsonParseLinter` extensions for `graphql()` called with no schema argument.

### `web/static/api/views/request-editor-view.js` (modified)

- New `_gqlQuery`/`_gqlVariables` state, seeded from the loaded request's `body` when `body_type === 'graphql'`.
- New DOM: a `gqlWrap` container (hidden unless `graphql` is the active type) holding labeled Query and Variables mount points.
- `_setBodyType` splits `graphql` out of the `raw`-shared `isText` branch into its own mount (`_mountGqlEditors`) / unmount (`_unmountGqlEditors`) pair, called on entering/leaving the type — same lifecycle shape the raw editor's `_activateCmEditor`/`.destroy()` already follow.
- `_setBodyValue` (used by the "load example" dropdown, which swaps body *content* without changing body *type*) gains a `graphql` branch that pushes parsed `{query,variables}` into both panes.
- `_refreshKnownVarNames` additionally calls `.refresh()` on both new editors, keeping `{{var}}` highlighting live when the known-variables list changes — same treatment every other var-aware field in this file already gets.

## Testing

No automated test framework exists in this repo (confirmed in `CLAUDE.md`). Verification is a manual browser walkthrough via the Flask dev server, covering:
- The buffer-separation fix directly (type into `raw`, switch to `graphql`, confirm empty; type into `graphql`, switch back to `raw`, confirm unchanged).
- Syntax highlighting and absence of false-positive lint errors in the schema-less Query editor.
- Save → reload round-trip preserves both panes.
- A real end-to-end send against a live public GraphQL API (`https://rickandmortyapi.graphcdn.app/`), confirming `cli/api_runner.py`'s existing graphql send-path still works unchanged against the new editor's output.
- Regression pass on `none`/`raw`/`form`/`multipart` — unaffected by this change.
- `Copy as cURL` on a graphql request — confirms the continuous `bodyTextarea` sync is correct without that code path needing any direct changes.

## Known limitations (accepted, not building)

- Format/minify/insert-variable toolbar buttons don't apply to the Query pane in this pass (see Architecture) — acceptable, GraphQL text isn't JSON so "format/minify" doesn't have an obvious meaning there anyway; CM6's own auto-indent/bracket-matching cover the common case.
- No schema-aware autocomplete (field/type suggestions) — explicitly out of scope, needs introspection (parked future idea).
- Bundle size grows by an unmeasured-until-rebuild-time amount from `graphql-js`/`graphql-language-service` — accepted for a locally-bundled desktop app; actual number recorded during implementation, not blocking.
- If the CM6 vendor bundle rebuild can't complete during implementation (e.g. no npm registry access in the build environment), the new Query editor falls back to a plain textarea via the existing feature-detection pattern (`createGraphqlEditor` returns `null`) — soft dependency, not an all-or-nothing gate, same contract `createJsonEditor` already has.
