# qaclan-server API Testing Web UI — Design

**Companion doc:** `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-ui-plan.md` (the task-by-task implementation plan this design produces). Also depends on `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` (the backend DB migration + `/api/pull`/`/api/sync` contract this UI reads — that plan's Sections 1–3 must be deployed before this one can ship).

## Purpose

The CLI's API-testing feature (HTTP collections, nested folders, requests, collection vars, run history, docs cache) will sync to qaclan-server once the backend sync plan ships. Teams need a way to *see* that data on the web dashboard — qaclan-server's Next.js frontend (`web/`) currently has no page for any of it. This design adds read-only browsing, mirroring how Scripts/Suites/Runs/Environments already work.

## Scope

In scope — one page (or page pair) per pulled entity:
- Collections, nested folders, requests → list + drill-down tree + per-request detail
- Collection-scoped variables → shown inline on the collection detail page (not a standalone page — same treatment as env vars under an environment)
- Standalone collection-run history → list + detail
- Server-computed API-docs cache → per-project browsable list with expandable schema blocks

Out of scope (explicit, per user decision):
- **Any write path.** No create/edit/delete/reorder for collections, folders, requests, vars, or docs entries. The web dashboard is read-only for this feature, full stop — creation/editing happens in the CLI only.
- **Discovery / Postman-Bruno import UI.** That's a CLI-only feature (`cli/api_discovery/`); it has no server-side or web concept at all.
- **Variant-library examples** (`cloud_api_request_examples`) and **mixed-suite API results** (`cloud_run_api_results`). Neither is exposed by the backend sync plan's pull contract yet (`GET /api/pull/workspace` doesn't return them, there's no `pull_api_request_examples` endpoint) — nothing to build against. Mixed-suite API results, once available, belong on the existing `/runs/[id]` page (interleaved with script results), not a new page.
- Any new Flask route, SQLAlchemy model, or migration. Every endpoint this plan calls is already fully specified in the backend sync plan.

## Why zero backend work

Read of the live `qaclan-server` repo confirmed `api/app/middleware/auth.py`'s `require_auth` decorator already accepts **both** the web session JWT and CLI `qc_`-prefixed API keys on the same route (`_resolve_user_from_jwt() or _resolve_user_from_api_key()`). Every `/api/pull/*` route — including the ones the backend sync plan adds (`api_collections`/`api_folders`/`api_requests`/`collection_vars` on `GET /api/pull/workspace`; new `GET /api/pull/api-runs`, `GET /api/pull/api-runs/<id>`, `GET /api/pull/api-docs`) — is therefore usable by the web frontend with no changes. This mirrors exactly how `ScriptsPage`/`SuitesPage`/`RunsPage` already call `GET /api/pull/workspace` and `GET /api/pull/runs` today.

## Architecture

Pure frontend addition, following the established page pattern exactly (`web/src/app/{scripts,suites,runs,environments}/page.tsx`):

1. `"use client"` page component wrapped in `AppShell` (auth redirect) → `UpgradeGate` (community-plan block) → `PageHeader`.
2. `useEffect` fetches from `apiFetch()` once `session?.jwt` is available; list pages hit `GET /api/pull/workspace` (or a dedicated paginated endpoint for high-volume data like runs), detail pages either filter the already-fetched workspace payload client-side (collections/folders/requests — cheap, whole-team dataset) or hit a dedicated per-id endpoint (`GET /api/pull/api-runs/<id>` — run detail has a large `request_results` array not worth bulk-loading).
3. `useProject()` context filters everything to the active project client-side, same as every existing page — these endpoints are team-scoped server-side, not project-scoped.
4. No new shared `types/` directory (matches existing convention of per-page inline interfaces); one shared `web/src/lib/api-testing.ts` module holds only what's genuinely reused across 3 pages (method/auth-type label maps, the folder-tree builder) — same rationale as the existing `web/src/lib/chart-config.ts`.

## Entity → Page Mapping

| Entity (from sync plan) | Page(s) | Data source |
|---|---|---|
| `api_collections` | `/api-collections` (list), `/api-collections/[id]` (detail) | `GET /api/pull/workspace` → `api_collections` |
| `api_folders` | nested tree inside `/api-collections/[id]` | `GET /api/pull/workspace` → `api_folders` |
| `api_requests` | leaf nodes in the tree; `/api-collections/[id]/requests/[requestId]` (full detail) | `GET /api/pull/workspace` → `api_requests` (already full-fidelity per request — headers/body/scripts/assertions all inline, no separate detail endpoint needed, unlike `scripts/[id]`'s `file_content` split) |
| `collection_vars` | inline card on `/api-collections/[id]` | `GET /api/pull/workspace` → `collection_vars` |
| `cloud_api_collection_runs` + `cloud_api_request_results` | `/api-runs` (list), `/api-runs/[id]` (detail) | `GET /api/pull/api-runs`, `GET /api/pull/api-runs/<id>` |
| `cloud_api_doc_entries` | `/api-docs` (project-scoped browser) | `GET /api/pull/api-docs?project_id=` |

## Folder Tree Rendering

`api_folders` is self-referential (`parent_folder_id`) and arrives as a flat array. `buildFolderTree()` (in `api-testing.ts`) converts it to a `FolderTreeNode` tree client-side for one collection at a time: a `Map<folderId, node>` pass links each folder to its parent (or a virtual root if the parent is missing/absent), then requests attach to their `folder_id` (or the root, for top-level requests). This is a pure rendering concern — unlike the CLI's pull-merge (which must insert parents before children to satisfy local FK constraints and handle out-of-order server responses), the web UI only ever reads already-synced data, so there's no ordering/retry logic needed, just a safe fallback-to-root for any dangling reference.

## Auth & Project Scoping

- Every page gates on `session.plan` exactly like Scripts/Suites/Runs/Environments: community-plan users see `<UpgradeGate>`.
- `jwt` from `useSession()` → `apiFetch(path, { jwt })` → `Authorization: Bearer` header, resolved server-side by `require_auth`. No new auth code.
- Project filtering is client-side against `selectedProject.id` from `useProject()`. Collections carry `project_id` directly; folders/requests inherit scoping transitively through their collection (no direct filter needed once the parent collection list is scoped); `api_collection_runs` carry `collection_id` but not `project_id` directly, so `/api-runs` builds a `collectionId → project_id` map from `workspace.api_collections` to filter runs by project (same indirection pattern `/runs` already uses for `suite_id → project_id` via suites).

## Error Handling

No new error-handling primitives — reuse `apiFetch()`'s existing behavior (401 → sign-out redirect, non-2xx → thrown `Error` with the server's `error` message). Every page's `.finally(() => setLoading(false))` and not-found branches (`!collection`, `!request`, `!run`) match the exact pattern already in `scripts/[id]` and `runs/[id]`.

## Testing

No automated test coverage exists for any `app/*/page.tsx` in this codebase (Vitest specs only cover `components/marketing/*`), so this plan doesn't introduce one either — consistent with "follow established patterns." Verification per task is `npx tsc --noEmit` + `npm run lint`, with a full `npm run build` as the final integration check, plus manual browser verification against a running dev stack once the backend plan's endpoints are live.

## Self-Review Notes

- Every entity the backend sync plan's pull contract (Sections 3, 3.2, 3.3) exposes has a corresponding view; nothing pulled is left unrendered.
- Every entity the backend plan explicitly marks Phase 2/optional (`api_request_examples`) or doesn't expose to pull at all (`cloud_run_api_results`) is explicitly out of scope here too, not silently dropped.
- No write path anywhere — verified against the plan's Self-Review Notes (no `<form>`, no mutating `apiFetch` call in any of the 6 new pages).
- Consistent with the sync plan: field names and JSON shapes referenced here match Sections 1–3 of `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` exactly — no renaming drift.
