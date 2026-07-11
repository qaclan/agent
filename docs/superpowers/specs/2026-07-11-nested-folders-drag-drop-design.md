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

## Section 5: Execution Order — Depth-First Collection Run Walk

### Discovery auto-folder: descoped

An earlier revision of this spec had the Discovery review flow auto-place saved requests into folders named after their endpoint resource (`suggest_folder_name(url)`, first path segment). Reverted (commits `dce927c`/`3eac452`) once the actual use case was clarified: a real test flow revisits the same resource more than once (login → create job → look up user → back to job), and a folder is a single node — it can't represent "jobs, then users, then jobs again." Auto-grouping by resource optimizes for browsing, not for the ordered flow a folder tree is meant to encode here. Folders are manual and collection-scoped only: the user names a folder after a flow step (`auth`, `job creation`, `dashboard`, `logout`, ...) and mixes request types inside it freely, same as folders in Postman/Insomnia. Discovery/import paths always save flat at collection root (`folder_id = NULL`), same as before folders existed.

### Collection run must walk the tree, not a flat list

Postman's Collection Runner walks a collection's folder tree depth-first in display order — a folder's own items in order, recursing into sub-folders in their listed position — so folder order *is* run order. That's the model this spec's folder ordering is meant to support (see brainstorming conversation, 2026-07-11).

Current gap: `RunnerService.start_collection_run`/`_execute_collection` (`web/api/services/runner_service.py`) both call `RequestRepo.list(project_id, collection_id=...)`, which orders `ORDER BY order_index, created_at` — a single flat query over every request in the collection regardless of folder. But `order_index` is only unique **within one parent scope** (per the Section 1 ordering rule — each folder's children start their own `order_index` sequence at 0). A flat collection-wide `ORDER BY order_index` therefore does not reproduce the tree order: it groups everything by numeric order_index value first (all folders' "slot 0" items, then all "slot 1" items, ...), tie-broken by `created_at`, not a depth-first walk. Folder drag-order stays cosmetic for running purposes until this is fixed — the same tension flagged for browsing-vs-flow-order applies to run-order too.

**Required fix (not yet implemented — follow-up task):** collection run must build an explicit depth-first ordering before executing:
1. Fetch the collection's folder tree (`FolderService.tree`, already returns flat `folders`+`requests` with `parent_folder_id`/`folder_id`).
2. Walk it depth-first from root (`parent_folder_id = None`), at each level visiting folders+requests interleaved by `order_index` (matching the tree's `_renderTreeLevel` UI logic in `collections-view.js`), recursing into each folder's children before moving to the next sibling.
3. Flatten to a single ordered list of request rows; run that list instead of `RequestRepo.list()`'s flat query.

This changes `start_collection_run`/`_execute_collection`/`run_collection` in `runner_service.py` to resolve the run order via the new tree-walk helper (likely `FolderService.flatten_run_order(collection_id, project_id) -> list[dict]`) instead of `RequestRepo.list()` directly. `RequestRepo.list()` itself stays unchanged — it's still correct for the collection-detail page's "every request regardless of folder" consumers (plan Task 11 regression items 1–2), which don't care about run order.

---

## Out of Scope (This Version)

- Cross-collection drag-and-drop (moving a request into a different collection stays a deliberate `PATCH collection_id` action, not a drag gesture)
- Folder-level auth/env/vars inheritance (folders are pure organization, no new config surface — requests still inherit only from their collection, unchanged)
- Bulk multi-select drag (one item dragged at a time, matches existing suite-script drag behavior)
- Folder export/import mapping for Postman/Bruno formats (existing import flattens nested folders into one collection name today; this spec does not change import/export behavior)
- Discovery/import auto-placement into folders by endpoint (previously in scope, descoped — see Section 5)
- Repeat-visit flow sequencing (same request/folder appearing more than once in one ordered run) — out of scope for the depth-first collection-run walk in Section 5; that's what `suites`/`suite_items` already exist for (arbitrary repeats, mixed scripts+api_requests, own ordering)
