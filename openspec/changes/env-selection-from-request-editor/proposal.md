## Why

Today the only place a user can pick, create, or bind an environment is the collection-detail view (`#cdv-env-sel`). When a user is deep in the request editor — e.g. naming a variable in the Post-Script → Extractor tab — the variable picker shows a dead-end message ("No variables — add env or collection vars" / "No variables available. Select an environment or add collection variables"). To act on it they must abandon the editor, click back to the collection, open its Variables/env settings, select or create an environment, add a variable, then return. That round-trip is the source of the confusion in the reported screenshots: the affordance to fix the empty state is nowhere near where the empty state is shown.

The same round-trip afflicts *every* collection-level setting: auth, variables, schema-check and negative-testing defaults all live only in the collection view, so any time an editor user needs one they must leave the request they are working on. The request editor already has its own request-scoped Auth, Schema Check and Negative Testing tabs, so the collection-level versions must be surfaced without colliding with them.

## What Changes

- Add a persistent **environment selector** to the request-editor header that shows the collection's currently-bound environment (or "No environment") and lets the user switch to any of the project's environments in place. Selecting one persists the binding to the collection via the existing `PATCH /api/collections/<id>` (`{ env_name }`) — the same write the collection-detail selector already performs, so both selectors stay consistent.
- Add an inline **"+ New environment"** action in that selector: it creates a project environment (`POST /api/envs`) and binds it to the collection in one step, without leaving the current view.
- Make the variable-picker **empty state actionable**: replace the dead "No variables…" text with inline actions to select/create an environment and to add a variable right where the picker is shown.
- Allow **adding a variable inline** from the request editor — a collection variable (`PUT /api/collections/<id>/vars/<key>`) or an environment variable (`POST /api/envs/<env_name>/vars/append`) — after which the picker refreshes to show the new variable immediately.
- Make the request editor **react live** to the bound environment changing: when the binding changes (from the editor's own selector or from the collection-detail selector) the editor re-fetches its variable list (`_refreshKnownVarNames()`) instead of only reflecting the environment captured at open time.
- Keep environment binding as a **single collection-level property** (`api_collections.env_name`). Environment selection stays collection-specific; there is no per-request environment, no new table, and no new persistence concept.
- Add a **Collection settings drawer** — a slide-over opened from the request-editor header, headed "Collection: <name>", that reuses the existing collection-detail tabs (Auth, Variables, Schema Check, Negative) so every collection-level setting is viewable and editable in context without navigating away. The editor's own request-scoped tabs are left unchanged, so request-level and collection-level settings stay visually and conceptually distinct (no two same-named tabs in one strip).

## Capabilities

### New Capabilities
- `api-environment-selection`: Reaching a collection's configuration from any API view including the request editor — its bound environment and variables, plus its auth / schema-check / negative-testing defaults (via a collection-settings drawer) — with the collection as the single binding point and collection-scoped settings kept distinct from the editor's request-scoped tabs.

### Modified Capabilities
(none)

## Impact

- Frontend (primary):
  - `web/static/api/views/request-editor-view.js` — add the header environment selector and the collection-settings drawer trigger, make variable loading react to binding changes, wire the empty-state actions and inline variable add.
  - `web/static/api/components/inline-var-drop.js`, `web/static/api/components/var-picker.js` — actionable empty state (callbacks for select/create env and add variable).
  - `web/static/api/views/collection-detail-view.js` — keep `#cdv-env-sel` in sync with the editor's selector (shared state / event) via a reused selector component, and expose its Auth/Variables/Schema Check/Negative tab renderers so the drawer can host them without duplication.
  - New drawer host (e.g. `web/static/api/components/collection-settings-drawer.js`) that mounts those existing tab renderers in a slide-over labeled by collection.
  - `web/static/api/views/collections-view.js`, `web/static/api/api-section.js` — thread live environment state into the editor instead of the static `collectionEnvName` argument, and forward updates back.
- Backend: no schema or route changes. Reuses `GET/POST /api/envs`, `POST /api/envs/<name>/vars/append`, `PATCH /api/collections/<id>`, `PUT /api/collections/<id>/vars/<key>`, and the collection auth / schema-check / negative endpoints the collection-detail tabs already call.
- No changes to run-time variable resolution or its precedence (collection vars over environment vars).
