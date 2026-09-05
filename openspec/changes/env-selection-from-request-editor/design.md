## Context

See proposal.md — Why. Relevant current state (from the codebase):

- Environments are **project-scoped** rows in `environments`/`env_vars` (`cli/db.py:59-72`), a pool **shared** with Playwright suites and the left-nav Environment page. A collection records which one it uses by **name** in `api_collections.env_name` (`cli/db.py:314-317`); there is no separate "API environment" table.
- Collection variables are a **separate** collection-scoped table (`collection_vars`), and at run time they take **precedence over** environment vars (`cli/api_runner.py:57-72`).
- The **only** env-selection UI today is `#cdv-env-sel` in `collection-detail-view.js:388-389`, populated and persisted at `:415-434` (list via `GET /api/envs`, bind via `PATCH /api/collections/<id>` with `{ env_name }`).
- The request editor receives the bound env as a **static argument** `collectionEnvName` at open time (`request-editor-view.js:27`); `getAllVars()` (`:49-65`) loads env vars via `GET /api/envs/<name>` and collection vars via `GET /api/collections/<id>/vars`. The empty-state strings live in `inline-var-drop.js:53` and `var-picker.js:60-62`. The editor has no selector and does not react to a binding change made elsewhere.
- Backend endpoints already cover every operation needed: `GET/POST /api/envs`, `POST /api/envs/<name>/vars/append`, `PATCH /api/collections/<id>`, `PUT /api/collections/<id>/vars/<key>`.
- The collection-detail view (`collection-detail-view.js`) already renders the collection's **Auth / Variables / Schema Check / Negative** tabs against those same endpoints. The request editor already has its own **request-scoped** Auth, Schema Check and Negative Testing tabs. So auth/schema/negative exist at two scopes under the same names — any attempt to surface the collection versions inside the editor must avoid producing two identically-named tabs in one strip.

## Goals / Non-Goals

**Goals:**
- Make environment select / create / bind and variable-add reachable from the request editor and the collection views, using the endpoints that already exist.
- Keep the collection-detail selector and the editor selector showing the same binding at all times.
- Turn the variable-picker empty state into something the user can act on in place.
- Make all collection-level settings (auth, variables, schema-check, negative-testing defaults) reachable from the request editor without navigating away, without duplicating the editor's request-scoped tabs.

**Non-Goals:**
- No backend, schema, or route changes; no change to run-time resolution or its precedence.
- No per-request environment and no per-user "active environment" — binding stays a single collection property.
- No new environment-management surface (rename/delete/copy stay in the existing Environment page); these entry points only **select**, **create**, and **bind**.
- No re-implementation of the collection Auth/Variables/Schema/Negative UIs — the drawer hosts the existing collection-detail tab renderers, it does not fork them.
- No merging of collection settings into the editor's request-scoped tab strip.

## Decisions

**D1 — One shared environment-selector component, reused in both places.**
Extract the selector currently inline in `collection-detail-view.js` into a small shared component (e.g. `web/static/api/components/env-selector.js`) that renders the dropdown, the "No environment" state, and the "+ New environment" action, and takes a collection id + a change callback. Both the collection-detail header and the request-editor header mount it. Rationale: a single component guarantees the two selectors behave identically and cannot drift in markup or behavior. Alternative — duplicate the markup in the editor — was rejected because it re-creates the population/persist logic and invites drift.

**D2 — Bind through the existing collection PATCH; treat `api_collections.env_name` as the single source of truth.**
Selecting an environment (from either view) writes `PATCH /api/collections/<id>` `{ env_name }`, exactly as the collection-detail selector does today. No per-request env, no new persistence. Rationale: satisfies "environment is always collection-specific" (constraint 1) with zero schema work. Alternative — a per-request `env_name` column — was rejected: it contradicts the constraint and multiplies the state to keep in sync.

**D3 — Keep the two selectors in sync with a lightweight per-collection event, and re-fetch on change.**
On a successful bind, publish a "collection env changed" signal (a document-level `CustomEvent` carrying `{ collectionId, envName }`, or an equivalent shared-state subscription). The request editor keeps its bound-env value in mutable state (not the frozen `collectionEnvName` argument), and its handler for the signal updates that value and calls the existing `_refreshKnownVarNames()` (which already invalidates the pickers' 30s caches via `u.invalidate()`). The collection-detail selector subscribes the same way. Rationale: reuses machinery already present; avoids prop-drilling through `collections-view.js` / `api-section.js`. Alternative — re-query env only on editor focus — was rejected as surprising (stale until the user clicks away and back).

**D4 — Empty-state affordances live in the picker components but the editor supplies the handlers.**
`inline-var-drop.js` and `var-picker.js` render "select/create environment" and "add variable" actions in their empty state, invoking callbacks passed in by the mounting view. The components stay presentation-only; the request editor owns the actual create-env / add-var logic (so the collection-detail Variables tab can pass its own handlers if it reuses the picker). Rationale: keeps the shared components free of collection/editor-specific API knowledge.

**D5 — "Add variable" opens the collection's Variables surface (the drawer), not a bespoke dialog.**
The empty-state "add variable" action opens the collection-settings drawer on its **Variables** tab and appends a new, empty, focused row — reusing the one Variables editor rather than a second add-variable dialog. This adds a **collection variable** (`PUT /api/collections/<id>/vars/<key>` on save), which needs no environment and is always available — exactly the store the empty state needs. Adding a variable to a specific *environment* is intentionally left to the Environment page (env vars are project-scoped, not collection-scoped), so the picker path does not offer it. On drawer close the editor re-fetches its variable list so a newly added var is immediately insertable. Rationale: one Variables implementation, consistent with D7's reuse principle; the earlier bespoke add-variable dialog is removed. Note the precedence caveat in Risks.

**D6 — Create-then-bind for new environments; let the backend enforce name uniqueness.**
"+ New environment" calls `POST /api/envs` then `PATCH /api/collections/<id>` with the new name. Environment names are keyed by `(project_id, name)`, so a duplicate name is rejected by the backend and surfaced to the user rather than pre-checked on the client.

**D7 — Surface the rest of the collection settings as a slide-over drawer that reuses the collection-detail tab renderers, not as new editor tabs.**
A "Collection settings" trigger in the editor header opens a slide-over drawer headed "Collection: <name>". Inside, it mounts the *existing* Auth / Variables / Schema Check / Negative tab renderers from `collection-detail-view.js` (extracted to be callable outside that view), pointed at the current collection. The env selector stays as the quick inline header control (D1) since it is the most frequent toggle; the heavier settings live in the drawer. The drawer shares the env-change signal (D3) so its Variables/env state stays consistent with the header selector.
Rationale: the drawer keeps the request editor's own tab strip request-scoped and untouched, so a setting that exists at both scopes (auth, schema-check, negative) never appears as two same-named tabs in one strip — the "Collection: <name>" heading names the scope. Reusing the existing renderers means one implementation of each settings UI and no behavioral drift.
Alternatives: (a) add the collection settings as extra tabs in the editor — rejected: produces duplicate Auth/Schema Check/Negative tabs and blurs which scope is being edited; (b) a separate full-page navigation to collection settings — rejected: that is the round-trip this change exists to remove; (c) fork simplified copies of the tab UIs into the editor — rejected: duplicate code that drifts from the collection-detail versions.

**D8 — Header disambiguates the request's Save from the collection's auto-saving controls.**
The env selector, the "⚙ Config" drawer trigger, and the request's Save all live in the editor header. Env/collection edits persist immediately (PATCH / PUT on change); the request Save persists the request document. To stop Save from looking like it saves the env/settings beside it: (a) Save is gated on the existing `_dirty` flag — muted/disabled until a request field changes, so the auto-saving controls never light it up; (b) the env selector + Config are grouped as one collection-context unit, divided from Save by a thin separator; (c) the label is "⚙ Config", not "⚙ Collection" (the bare noun named a thing, not an action), which is also narrower — no extra header width; (d) an env bind raises a toast so the instant auto-save is visibly confirmed. Alternatives: a separate settings row (rejected — extra vertical space); leaving Save always enabled (rejected — keeps the ambiguity the header refinement exists to remove).

**D9 — The environment selector is a custom dropdown, not a native `<select>`.**
The empty-state "select environment" action must be able to *open* the selector, and a native `<select>` cannot be opened programmatically across browsers (`HTMLSelectElement.showPicker()` throws on Safari/older engines). So `createEnvSelector` renders a trigger button plus a fixed-positioned menu (No environment / each environment / "+ New environment…"), exposing an `open()` method. It positions like the existing var pickers (fixed, anchored to the trigger, escaping overflow), closes on outside-click/Escape, is theme-aware via CSS vars, and is used by both the editor header and the collection-detail header so they stay identical. Trade-off: more code than a native select, and the outside-click/Escape/positioning must be handled by hand. Alternative — native select + `showPicker()` with a focus fallback — was rejected because "opens" would then work only on some browsers.

## Risks / Trade-offs

- Environments are shared with Playwright suites and the Environment page. Creating an env from the API editor also makes it visible to suites. → These entry points only **add** and **select** (never rename/delete), so a new env is at worst an unused extra in the shared pool; label the action clearly as creating a project environment.
- Two selectors could drift out of sync. → D1 (one component) + D3 (single event + single source of truth `env_name`) keep them identical; both read the binding back from the same PATCH result / event.
- Collection vars override env vars at run time. Adding a collection variable whose key matches an env variable silently shadows the env value. → The add-variable UI states which store it writes to; the default (collection var) is the common case, and this precedence is unchanged behavior, not new.
- Stale picker cache after a live binding change. → Reuse the existing `_refreshKnownVarNames()` path, which already calls `u.invalidate()` on each picker's 30s cache.
- Live cross-view updates could race (editor open for a collection whose env is changed twice quickly). → The event carries the resulting `envName`; the editor applies the latest value and re-fetches, so the last write wins with no partial state.
- Collection auth/schema/negative and the request's own auth/schema/negative share names, so surfacing both risks the user editing the wrong scope. → D7 keeps them in physically separate surfaces (editor tab strip vs "Collection: <name>" drawer); the drawer's heading and the request Auth tab's existing "Inherit" wording name the scope.
- Extracting the collection-detail tab renderers so the drawer can reuse them could regress the collection-detail view itself. → The extraction is a pure move-to-callable with the collection-detail view as its first caller; both call sites are exercised in the verify tasks.

## Migration Plan

Pure frontend change; no data migration. Ship the shared component and wiring together. Rollback is a straight revert of the JS changes — `api_collections.env_name` and all endpoints are untouched, so no data is affected either way.
