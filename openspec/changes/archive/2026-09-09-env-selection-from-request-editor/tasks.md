## 1. Shared environment-selector component

- [x] 1.1 Create `web/static/api/components/env-selector.js` — a reusable selector that lists project environments (`GET /api/envs`), renders the "No environment" state, marks the collection's bound env selected, and exposes a `+ New environment` action. Takes a collection id, the current `env_name`, and an `onChange(envName)` callback.
- [x] 1.2 In the component, implement bind-on-change: call `PATCH /api/collections/<id>` with `{ env_name }`, then invoke `onChange` with the new value only after the PATCH succeeds.
- [x] 1.3 In the component, implement `+ New environment`: prompt for a name, `POST /api/envs`, then bind it (task 1.2 path); surface the backend's duplicate-name error to the user without creating a duplicate.

## 2. Per-collection env-change signal

- [x] 2.1 Add a lightweight signal for "collection env changed" — a document-level `CustomEvent` carrying `{ collectionId, envName }` (dispatch helper + subscribe helper), used by every mounted selector and the request editor.
- [x] 2.2 Have the shared selector (task 1.2) dispatch this signal after a successful bind so all views for the same collection converge on one `env_name`.

## 3. Request-editor integration

- [x] 3.1 In `web/static/api/views/request-editor-view.js`, replace the frozen `collectionEnvName` argument with mutable editor state initialized from it, and mount the shared env-selector (task 1) in the editor header.
- [x] 3.2 Subscribe the editor to the env-change signal (task 2); on a signal for this editor's collection, update the bound-env state and call the existing `_refreshKnownVarNames()` so the variable list re-fetches (and picker 30s caches invalidate via `u.invalidate()`).
- [x] 3.3 Ensure `getAllVars()` reads the mutable bound-env state (not the original argument) so environment variables load from the currently bound environment.

## 4. Actionable empty state in variable pickers

- [x] 4.1 In `web/static/api/components/inline-var-drop.js` and `web/static/api/components/var-picker.js`, replace the dead empty-state text with actions ("select or create environment", "add variable") that invoke callbacks passed in by the mounting view; keep the components presentation-only.
- [x] 4.2 In the request editor, supply those callbacks: "select/create environment" opens the shared selector's flow; "add variable" opens the add-variable flow (task 5). After either completes, refresh the picker so the resulting variables appear without reopening the editor.

## 5. Inline add-variable from the request editor

- [x] 5.1 In the request editor, implement add-variable with two targets: a collection variable via `PUT /api/collections/<id>/vars/<key>` (default), and an environment variable via `POST /api/envs/<env_name>/vars/append` (only when an environment is bound).
- [x] 5.2 When the user chooses an environment variable but no environment is bound, route them to select/create an environment first (task 1.3 / 3.1) before accepting the environment variable.
- [x] 5.3 After a successful add, call `_refreshKnownVarNames()` so the new key is immediately insertable as `{{key}}`; make the add-variable UI state which store it writes to.

## 6. Keep the collection-detail view in sync

- [x] 6.1 In `web/static/api/views/collection-detail-view.js`, replace the inline `#cdv-env-sel` population/persist logic (`:415-434`) with the shared component (task 1) so both selectors share behavior.
- [x] 6.2 Subscribe the collection-detail selector to the env-change signal (task 2) so a bind made from the request editor updates `#cdv-env-sel` and the Variables tab's `getAllVars()`.

## 7. Thread live env state through the entry points

- [x] 7.1 In `web/static/api/views/collections-view.js` and `web/static/api/api-section.js`, stop relying solely on the static `collectionEnvName` passed into `renderRequestEditor`; ensure the editor's mutable state and the env-change signal are the source of truth after open.
- [x] 7.2 Confirm the Send path still resolves against the collection's bound env (Send posts `{}`; backend inherits `col.env_name`) — no `env_name` needs to be added to the Send body.

## 8. Collection settings drawer

- [x] 8.1 Extract the collection-detail Auth / Variables / Schema Check / Negative tab renderers from `web/static/api/views/collection-detail-view.js` into callable functions that take a collection id, so they can mount outside that view; keep collection-detail as their first caller (no behavior change there).
- [x] 8.2 Create the drawer host (e.g. `web/static/api/components/collection-settings-drawer.js`): a slide-over headed "Collection: <name>" that mounts the extracted tab renderers for a given collection and closes back to the caller.
- [x] 8.3 Add a "Collection settings" trigger in the request-editor header (next to the env selector) that opens the drawer for the request's collection; ensure closing it leaves the editor and its unsaved request edits intact.
- [x] 8.4 Subscribe the drawer's Variables/env content to the env-change signal (task 2) so it stays consistent with the header selector, and ensure edits made in the drawer persist via the same endpoints the collection-detail tabs already use.
- [x] 8.5 Confirm the editor's own request-scoped tab strip is unchanged — no second Auth / Schema Check / Negative tab is added to it.

## 9. Verify end to end

- [ ] 9.1 Manually verify: open a request with no env → picker empty state offers select/create env and add var; create an env inline → it binds, and the collection-detail selector shows it.
- [ ] 9.2 Manually verify: add a collection variable and an environment variable from the editor → both appear in the picker as `{{key}}` and resolve on Send.
- [ ] 9.3 Manually verify: change the env in collection-detail while the editor is open → the editor's selector and variable list update without reopening.
- [ ] 9.4 Manually verify precedence unchanged: a collection var and env var with the same key → collection value wins at run time.
- [x] 9.5 Manually verify the drawer: open it from the editor → Auth/Variables/Schema Check/Negative show for the collection, labeled by name; edit each → change persists and matches editing from the collection view; the collection-detail view still works unchanged.
- [x] 9.6 Manually verify no scope confusion: the editor's request-scoped tabs and the drawer's collection-scoped tabs are visibly separate; a setting existing at both scopes is clearly labeled which scope it edits.

## 10. Header refinement (distinguish request save from collection controls)

- [x] 10.1 Gate the editor's Save button on the existing `_dirty` flag: muted/disabled until the request has unsaved edits, re-synced from `_markDirty()` and after `_save()`. Env/collection auto-saves never enable it, so Save clearly means "save request".
- [x] 10.2 Rename the drawer trigger from "⚙ Collection" to "⚙ Config" and group it with the env selector as one collection-context unit, divided from Save by a thin separator — no extra header width.
- [x] 10.3 Toast on environment bind (`window._toast`) so the already-instant auto-save is confirmed to the user ("Environment → dev" / "Environment cleared").
- [ ] 10.4 Manually verify: Save stays muted until a request field is edited; changing env or opening Config never enables Save; a toast confirms env selection.

## 11. Working empty-state actions (custom env dropdown + drawer add-var)

- [x] 11.1 Rebuild `createEnvSelector` as a custom dropdown (trigger button + fixed-positioned menu: No environment / each env / "+ New environment…"), replacing the native `<select>`. Keep bind/toast/emit logic and `setEnv`; add an `open()` method. Handle outside-click/Escape close, theme via CSS vars, cross-browser positioning. Both the editor header and collection-detail header use it unchanged.
- [x] 11.2 Make `renderCollectionSettingsTabs` return a controller exposing `openTab(id)` and `addVariable()` (switch to Variables, append an empty row, focus the key input).
- [x] 11.3 Extend `openCollectionSettingsDrawer(col, opts)` with `{ tab, addRow, onClose }` — open on the given tab, trigger add-row when asked, and call `onClose` when the drawer closes.
- [x] 11.4 Repoint the request editor's empty-state actions: "+ Add variable" → open the drawer on Variables with a focused new row (`onClose: _refreshKnownVarNames`); "Select environment" → `_envSelector.open()`. Remove the now-unused `_openAddVarDialog`.
- [x] 11.5 Ensure the empty-state buttons reliably fire (fix the "nothing happens" bug) — verified by actually running the app.
- [x] 11.6 Manually verify in light AND dark themes: "+ Add variable" opens the drawer Variables tab with a focused empty row; saving it makes `{{key}}` insertable; "Select environment" opens the env menu; both work in Chromium and Firefox.
