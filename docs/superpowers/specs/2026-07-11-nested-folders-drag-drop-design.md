# Nested Folders + Drag-and-Drop Reordering — Design Spec
Date: 2026-07-11

## Problem

Two related gaps in the API testing feature:

1. **Collections are single-level.** The original spec (`2026-06-19-api-testing-design.md`) explicitly chose "one level only — no nested folders" to avoid Postman-style hierarchy hell. In practice, collections grow past ~15-20 requests (especially after "Save as Library" auto-creates one request per endpoint) and become unwieldy flat lists with no way to group logically-related requests.
2. **No manual ordering.** `api_requests` and `api_collections` have no `order_index` column — display order is purely `ORDER BY created_at`, insertion order. There's no way to arrange requests to match a logical flow (e.g. login → create → verify → delete) without recreating them in that order.

This spec adds nested folders inside a collection, and drag-and-drop reordering/reparenting across collections, folders, and requests — reusing the native-HTML5-DnD pattern already proven for suite-script reordering (`app.js:3838-3880`, `PUT /api/suites/<id>/order`).

## Decisions

| Question | Decision |
|---|---|
| Folder nesting depth | Unlimited (self-referencing `parent_folder_id`), matches Postman/Insomnia mental model |
| Folders vs. collections | Folders are a separate concept nested *inside* a collection. Collections stay the top-level container (unchanged run/export/env/auth semantics) |
| Drag-drop scope | Both reorder (siblings) and reparent (move to a different folder), via one gesture |
| Cross-collection drag | Not supported — drag/reorder/reparent stays within one collection's tree. Moving a request to a different collection remains the existing `PATCH .../collection_id` action |
| Collection-level ordering | Included — collections themselves become drag-reorderable in the sidebar |
| Request/folder creation | Inline `+ New Request` / `+ New Folder` rows per folder (recursive application of the existing per-collection pattern), not a picker dropdown |
| Folder delete | Cascades — deletes sub-folders and their requests, matches existing collection-delete behavior. Confirmation dialog shows counts before deleting |

---

## Section 1: Data Model

### New table: `api_folders`

```sql
CREATE TABLE api_folders (
    id               TEXT PRIMARY KEY,          -- "apifold_xxxxxxxx"
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    collection_id    TEXT NOT NULL REFERENCES api_collections(id) ON DELETE CASCADE,
    parent_folder_id TEXT REFERENCES api_folders(id) ON DELETE CASCADE,  -- NULL = root of collection
    name             TEXT NOT NULL,
    order_index      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
```

### Modified: `api_requests`

```sql
ALTER TABLE api_requests ADD COLUMN folder_id TEXT REFERENCES api_folders(id) ON DELETE CASCADE;
ALTER TABLE api_requests ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0;
```

`folder_id = NULL` means the request sits at the root of its collection (today's behavior, unchanged for existing rows). `ON DELETE CASCADE` on `folder_id` — deleting a folder deletes the requests inside it, matching the "folder delete cascades" decision above and mirroring existing collection-delete cascade behavior.

### Modified: `api_collections`

```sql
ALTER TABLE api_collections ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0;
```

### Ordering rule

Folders and requests that share a parent scope (same `collection_id` + `folder_id`/`parent_folder_id`) share one `order_index` space and interleave freely in display order — no forced "folders-first" sort. The user's drag position is authoritative. This matches how `suite_items.order_index` already works for scripts+api_requests mixed in one suite.

### Migration cost for existing data

`folder_id` defaults NULL, `order_index` defaults 0 on all three tables. Existing collections/requests render exactly as they do today (flat list, insertion order via `id`/`created_at` tiebreak) until a user actively creates a folder or drags something. Zero-cost migration, no backfill needed.

---

## Section 2: Backend

New file `web/api/repositories/folder_repo.py`, `web/api/services/folder_service.py`, `web/api/routes/folders.py` — same 3-layer pattern as the rest of `web/api/`.

### Routes

- `POST /api/collections/<col_id>/folders` — create folder. Body `{name, parent_folder_id}`. `order_index` computed as `MAX(order_index)+1` within the target parent scope (mirrors existing `POST /suites/<id>/items` pattern).
- `PATCH /api/api-folders/<id>` — rename (`{name}`).
- `DELETE /api/api-folders/<id>` — cascade delete (FK handles sub-folders + requests).
- `GET /api/collections/<col_id>/tree` — single call returning `{folders: [...], requests: [...]}`, every folder/request in the collection regardless of depth, each row carrying its `parent_folder_id`/`folder_id`. Client assembles the nested tree in JS. This replaces `collections-view.js`'s current N+1 pattern (one `GET /api-requests?collection_id=` fetch per collection) — a net perf improvement, not a new cost.

### Reorder / move — one endpoint shape for both cases

A drop always resolves to "this node's new parent scope + that parent's new child order," whether it's a same-parent reorder or a cross-parent reparent:

- `PUT /api/collections/<col_id>/tree-order` — body `{parent_folder_id: <id|null>, items: [{type: "folder"|"request", id}, ...]}`. Writes `order_index` 0..N for every item in that one parent scope via a single batched `UPDATE ... CASE` (same shape as the existing `reorder_suite_scripts` loop in `web/routes/suites.py:317`). A same-parent drag fires one call; a reparent drag fires two (old parent's list, new parent's list).
- `PUT /api/collections/order` — project-scoped, no `col_id`. Body `{items: [{id}, ...]}`. Reorders collections themselves in the sidebar.

### Existing endpoints, extended

- `POST /api/api-requests` / `PATCH /api/api-requests/<id>` — accept `folder_id` alongside the existing `collection_id` field. Same pattern already used today for "remove from collection" (`PATCH {collection_id: null}`).

---

## Section 3: Frontend

### Tree fetch + render (`collections-view.js`)

On collection expand: one `GET /collections/<id>/tree` call (replaces today's per-collection `GET /api-requests?collection_id=`). Build a nested tree client-side from the flat `folders`+`requests` arrays via `parent_folder_id`/`folder_id` linking, then a recursive render function:

- Folder row: indentation by depth, expand/collapse chevron, `⠿` drag handle, name, inline `+ New Request` / `+ New Folder` rows as its last children, rename (inline edit) and delete (🗑, cascade-delete confirmation) actions — same visual language as the existing collection header row.
- Request row: unchanged from today, just rendered at whatever depth its folder puts it.
- Root level of a collection keeps today's exact behavior (flat list + trailing `+ New Request`) plus a new trailing `+ New Folder` row.
- Collections themselves gain the same `⠿` drag handle in the sidebar.

### Drag-and-drop mechanics

Extends the existing native-HTML5-DnD pattern (`app.js:3838-3880`) — no new library, no `Sortable.js`/`interact.js` dependency added.

- `dragstart` — tag the dragged element with its `type` (`folder`/`request`) and current parent scope (`collection_id`, `folder_id`).
- `dragover` — reuses the existing midpoint-based insert-before/after logic for between-row drops (sibling reorder). New: dropping onto the **center third** of a folder row (rather than its top/bottom edge) reparents the dragged item to become that folder's first/last child — needs a distinct hover highlight (folder row background tint) versus the existing insertion-line indicator for between-row drops.
- `dragend` — diff the dragged item's old parent scope vs. new parent scope:
  - Same parent → one `PUT .../tree-order` call.
  - Different parent → `PATCH` the moved item's `folder_id` (request) or the folder's own `parent_folder_id` (nested folder move, via `PATCH /api/api-folders/<id>`) first, then two `tree-order` calls (old parent's remaining list, new parent's new list).
- **Cycle guard** — dragging a folder onto one of its own descendants must be blocked client-side before any request fires: walk the dragged folder's subtree (already in memory from the tree fetch) and disallow the drop if the hovered target is inside it. Prevents orphaning/cycling the tree.
- Cross-collection drags are not handled — the drop-target logic only considers rows within the same collection's rendered subtree, consistent with the "same collection only" scope decision.

### CSS

Reuse `.suite-script-row`/`.dragging`/drag-handle styles from `style.css:1163-1193` as the base; add the folder-row center-drop highlight as a new small addition.

---

## Section 4: Performance & Efficiency

- Collection expand cost goes **down**, not up: one `/tree` call replaces N+1 per-collection request fetches.
- Reorder writes are scoped to the affected parent(s) only, not the whole tree — a drag inside a 50-request folder writes 50 rows in one batched `UPDATE`, cost bounded by folder size, not collection size.
- No recursive SQL anywhere. `parent_folder_id` is used only for FK integrity and client-side tree assembly (flat fetch, tree built in JS).
- Zero migration cost for existing data (see Section 1).

---

## Section 5: Discovery Integration — Suggested Folders on Save

Once folders exist, the Discovery review flow can place saved requests into folders automatically instead of always dumping them flat at collection root. The web UI's HAR/OpenAPI/Postman/Bruno/cURL import views and Record APIs all call a `/discover/*/preview` endpoint and hand the parsed list to the same shared `request-review-modal.js` → this feature lands in exactly one place and applies uniformly across every web-UI discovery path.

### Decisions

| Question | Decision |
|---|---|
| Scope | Applies to **both** "Save as Flow" and "Save as Library" equally — folder placement (by endpoint resource) is orthogonal to variant grouping (by param/body differences), so it is not tied to Library's grouping modal |
| Suggestion depth | One level — folder name is the first meaningful path segment (e.g. `GET /api/v1/users/123` → folder "users"). No path-mirroring, no multi-level nesting from discovery |
| User control | One checkbox in the existing review modal, next to "Include in API Documentation" — "Organize into folders by endpoint", **checked by default**. Unchecking it saves flat at collection root exactly as today |
| CLI import path | `qaclan api import` (OpenAPI/Postman/Bruno/HAR) calls `DiscoveryService.import_openapi/import_postman/import_bruno/import_har` directly — a separate code path from the web UI's preview+review-modal flow, with its own pre-existing per-tag/per-folder collection grouping. This plan does not touch it; it is unaffected by `organize_into_folders` |

### Suggestion heuristic

New pure module `cli/api_discovery/folder_suggester.py`, `suggest_folder_name(url) -> str | None`. Reuses the existing `url_normalizer.normalize_url()` — which already collapses numeric/UUID/hex path segments to `{param}` placeholders — so no new ID-detection logic is needed. Skips a small namespace-noise list (`api`, `rest`, `graphql`, `gateway`, `gql`) and version-literal segments (`v1`, `v2.0`, ...). Returns the first remaining real segment, or `None` when nothing meaningful is left (root path, or an API that's all namespace/version/IDs) — a `None` result means the request stays at collection root, same as today.

### Save-path integration

Every discovery save path already funnels through one function, `discovery_service._save_requests()` (used directly by "Save as Flow" and by Library's "keep separate" branch) — plus one direct `_req_repo.create()` call in `save_library()`'s "merge" branch. Both gain an `organize_into_folders: bool = False` parameter (default `False` so Postman/OpenAPI/Bruno imports, which never pass it, are untouched). A shared per-save-call `folder_cache: dict[str, str]` (folder name → folder id) is threaded through both, so e.g. ten requests that all suggest "users" share one folder — via a new `FolderRepo.get_or_create_root(project_id, collection_id, name)` — instead of creating ten duplicates.

---

## Out of Scope (This Version)

- Cross-collection drag-and-drop (moving a request into a different collection stays a deliberate `PATCH collection_id` action, not a drag gesture)
- Folder-level auth/env/vars inheritance (folders are pure organization, no new config surface — requests still inherit only from their collection, unchanged)
- Bulk multi-select drag (one item dragged at a time, matches existing suite-script drag behavior)
- Folder export/import mapping for Postman/Bruno formats (existing import flattens nested folders into one collection name today; this spec does not change import/export behavior)
