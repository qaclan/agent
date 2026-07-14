# qaclan-server: API Testing Web UI Plan (Next.js)

> **Target repo:** `qaclan-server` (separate codebase from this one), specifically the `web/` Next.js 16 / React 19 / TypeScript App Router directory. Zero changes to `api/` (Flask) in this plan — every endpoint used here is already fully specified in `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` Sections 1–3 (`GET /api/pull/workspace` gains `api_collections`/`api_folders`/`api_requests`/`collection_vars`; `GET /api/pull/api-runs`, `GET /api/pull/api-runs/<run_id>`, `GET /api/pull/api-docs?project_id=` are new). **This plan cannot ship until that plan's Sections 1–3 are deployed** — the pages below call those exact endpoints and read those exact JSON shapes with no fallback.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Run all commands from `qaclan-server/web/`.

**Goal:** Give the qaclan-server web dashboard read-only pages for the API-testing data teams sync from the CLI — collections, nested folders, requests, collection variables, standalone collection-run history, and the server-computed API-docs cache — mirroring the existing Scripts/Suites/Runs/Environments pages exactly.

**Architecture:** Pure frontend addition. Every new page is a `"use client"` component that calls `apiFetch()` against already-planned `/api/pull/*` endpoints, using the same `AppShell` → `UpgradeGate` → `PageHeader` → `Card` skeleton every existing page uses. No new Flask routes, no new SQLAlchemy models, no new auth path — `require_auth` already accepts both the web JWT and CLI `qc_` API keys on every `/api/pull/*` route, so nothing here is CLI- or web-specific at the transport layer.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, `next-auth` (`useSession()` for JWT + plan), `lucide-react` icons. No test framework covers `app/*/page.tsx` files today (only `components/marketing/*.test.tsx` have Vitest specs) — verification is `npx tsc --noEmit`, `npm run lint`, and manual browser checks, matching the convention already in place for every other dashboard page.

**Companion docs:**
- `docs/superpowers/specs/2026-07-13-qaclan-server-api-testing-ui-design.md` — the approved design this plan implements.
- `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` — the backend contract every endpoint/payload shape below reads.

## Global Constraints

- **View-only, no exceptions:** no create/edit/delete/import UI for any API-testing entity anywhere in this plan. Collections/folders/requests/vars/runs/docs are pushed from the CLI only; the web dashboard only ever displays them — identical to how Scripts, Suites, and Environments pages work today (their empty states literally say "...from the CLI to see them here").
- **No discovery/import UI:** Postman/Bruno import and endpoint discovery are CLI-only features (`cli/api_discovery/` in the agent repo). Nothing in this plan reads or writes anything related to them.
- **Tool-independent by construction:** every field rendered here (`method`, `url`, `headers`, `body`, `assertions`, `pre_script`, ...) is generic HTTP request/response data defined by the `cloud_api_*` schema in the sync plan — nothing is Playwright- or qaclan-CLI-specific. Any client that pushes to the same tables via the same contract renders identically here.
- Follow the exact conventions already established in `web/src/app/{scripts,suites,runs,environments}/page.tsx`: `"use client"`, `AppShell` wrapper, `UpgradeGate` gate for community-plan users, `PageHeader`, `Card`/`CardContent`, `EmptyState`, `Pagination`/`usePagination`, a spinner block while `loading`, and **per-page inline TypeScript interfaces** — this codebase has no shared `types/` directory and duplicates minimal interfaces per page on purpose; do not introduce one.
- Every new page is gated exactly like Scripts/Suites/Runs/Environments: `if (!session?.plan || session.plan === "community") return <UpgradeGate>{null}</UpgradeGate>;`
- `jwt` comes from `useSession().data?.jwt` and is passed as `{ jwt }` to `apiFetch()` — it becomes the `Authorization: Bearer` header. Never fetch without checking `jwt` is set first (`useEffect` guards with `if (!jwt) return;`, matching every existing page).
- Project scoping uses `useProject()` (`web/src/lib/project-context.tsx`) exactly as Scripts/Suites/Runs do: filter workspace-derived lists by `selectedProject.id` client-side, there is no server-side project filter on these endpoints beyond team scoping.
- Commit after each task, e.g. `feat(web): add API collections list page`.

---

## File Structure

```
web/src/lib/api-testing.ts                                   (new — shared constants + folder-tree builder)
web/src/app/api-collections/page.tsx                          (new — list)
web/src/app/api-collections/[id]/page.tsx                     (new — collection detail: tree + vars)
web/src/app/api-collections/[id]/requests/[requestId]/page.tsx (new — request detail)
web/src/app/api-runs/page.tsx                                  (new — list)
web/src/app/api-runs/[id]/page.tsx                              (new — run detail)
web/src/app/api-docs/page.tsx                                   (new — docs cache browser)
web/src/components/layout/Sidebar.tsx                           (modify — add nav items)
```

---

### Task 1: Shared helpers — `web/src/lib/api-testing.ts`

**Files:**
- Create: `web/src/lib/api-testing.ts`

**Interfaces:**
- Produces: `METHOD_COLORS`, `AUTH_TYPE_LABELS`, `ApiFolder`, `ApiRequestSummary`, `FolderTreeNode`, `buildFolderTree()` — consumed by Task 3 (collection detail) and Task 4 (request detail).

- [ ] **Step 1: Write the file**

```typescript
// web/src/lib/api-testing.ts
export const METHOD_COLORS: Record<string, string> = {
  GET: "text-info bg-info-muted",
  POST: "text-success bg-success-muted",
  PUT: "text-warning bg-warning-muted",
  PATCH: "text-warning bg-warning-muted",
  DELETE: "text-danger bg-danger-muted",
  HEAD: "text-text-tertiary bg-bg-elevated",
  OPTIONS: "text-text-tertiary bg-bg-elevated",
};

export const AUTH_TYPE_LABELS: Record<string, string> = {
  none: "No Auth",
  inherit: "Inherit",
  bearer: "Bearer Token",
  basic: "Basic Auth",
  api_key: "API Key",
  oauth2: "OAuth 2.0",
};

export interface ApiFolder {
  id: string;
  name: string;
  order_index: number;
  collection_id: string;
  parent_folder_id: string | null;
}

export interface ApiRequestSummary {
  id: string;
  name: string;
  method: string;
  url: string;
  order_index: number;
  collection_id: string | null;
  folder_id: string | null;
}

export interface FolderTreeNode {
  folder: ApiFolder | null; // null = virtual root (top-level requests/folders of the collection)
  children: FolderTreeNode[];
  requests: ApiRequestSummary[];
}

/**
 * Builds a folder tree for one collection from the flat arrays returned by
 * GET /api/pull/workspace. A folder/request whose parent isn't present in
 * `folders` (shouldn't happen with synced data, but keep this safe) falls
 * back to the root rather than being dropped.
 */
export function buildFolderTree(
  folders: ApiFolder[],
  requests: ApiRequestSummary[],
  collectionId: string
): FolderTreeNode {
  const collectionFolders = folders
    .filter((f) => f.collection_id === collectionId)
    .sort((a, b) => a.order_index - b.order_index);
  const collectionRequests = requests
    .filter((r) => r.collection_id === collectionId)
    .sort((a, b) => a.order_index - b.order_index);

  const nodeByFolderId = new Map<string, FolderTreeNode>();
  for (const f of collectionFolders) {
    nodeByFolderId.set(f.id, { folder: f, children: [], requests: [] });
  }

  const root: FolderTreeNode = { folder: null, children: [], requests: [] };
  for (const f of collectionFolders) {
    const node = nodeByFolderId.get(f.id)!;
    const parent = f.parent_folder_id ? nodeByFolderId.get(f.parent_folder_id) : undefined;
    (parent || root).children.push(node);
  }
  for (const r of collectionRequests) {
    const target = r.folder_id ? nodeByFolderId.get(r.folder_id) : undefined;
    (target || root).requests.push(r);
  }
  return root;
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
```
Expected: no errors referencing `api-testing.ts` (the file has no consumers yet, so this only checks it parses/type-checks standalone).

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/api-testing.ts
git commit -m "feat(web): add API-testing shared constants and folder-tree builder"
```

---

### Task 2: `/api-collections` — list page

**Files:**
- Create: `web/src/app/api-collections/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/workspace` → `api_collections`, `api_folders`, `api_requests` (per the sync plan Section 3 payload shapes).
- Produces: nothing consumed by later tasks (leaf list page), but establishes the `/api-collections/[id]` link target used by Task 3.

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-collections/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { UpgradeGate } from "@/components/upgrade-gate";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import { Pagination, usePagination } from "@/components/ui/Pagination";
import { AUTH_TYPE_LABELS } from "@/lib/api-testing";
import { Webhook, ChevronRight, Search } from "lucide-react";

interface ApiCollection {
  id: string;
  name: string;
  description: string | null;
  env_name: string | null;
  auth_type: string;
  order_index: number;
  project_id: string;
}

export default function ApiCollectionsPage() {
  const { data: session } = useSession();
  const { selectedProject } = useProject();
  const [collections, setCollections] = useState<ApiCollection[]>([]);
  const [folderCounts, setFolderCounts] = useState<Record<string, number>>({});
  const [requestCounts, setRequestCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt) return;
    apiFetch("/api/pull/workspace", { jwt })
      .then((data) => {
        setCollections(data.api_collections || []);
        const folders: { collection_id: string }[] = data.api_folders || [];
        const requests: { collection_id: string | null }[] = data.api_requests || [];
        setFolderCounts(
          folders.reduce<Record<string, number>>((acc, f) => {
            acc[f.collection_id] = (acc[f.collection_id] || 0) + 1;
            return acc;
          }, {})
        );
        setRequestCounts(
          requests.reduce<Record<string, number>>((acc, r) => {
            if (!r.collection_id) return acc;
            acc[r.collection_id] = (acc[r.collection_id] || 0) + 1;
            return acc;
          }, {})
        );
      })
      .finally(() => setLoading(false));
  }, [jwt]);

  if (!session?.plan || session.plan === "community") {
    return <UpgradeGate>{null}</UpgradeGate>;
  }

  const projectCollections = collections.filter(
    (c) => !selectedProject || c.project_id === selectedProject.id
  );

  const q = search.toLowerCase().trim();
  const filtered = q
    ? projectCollections.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          (c.description || "").toLowerCase().includes(q)
      )
    : projectCollections;

  const sorted = [...filtered].sort((a, b) => a.order_index - b.order_index);
  const { currentPage, setCurrentPage, paginatedItems, totalItems, pageSize } = usePagination(sorted);

  return (
    <AppShell>
      <PageHeader
        title="API Collections"
        description={`${projectCollections.length} collections`}
      />

      {loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : projectCollections.length === 0 ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <EmptyState
              icon={Webhook}
              title="No API collections yet"
              description="Sync API collections from the CLI to see them here."
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-tertiary" />
            <input
              type="text"
              placeholder="Search collections..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-border-default bg-bg-surface pl-9 pr-3 py-2 text-sm text-text-primary placeholder:text-text-muted hover:border-border-emphasis focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-all"
            />
          </div>

          {filtered.length === 0 ? (
            <Card className="mx-auto max-w-lg">
              <CardContent>
                <EmptyState icon={Webhook} title="No matching collections" description="Try a different search term." />
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardContent className="p-0">
                  <div className="divide-y divide-border-subtle">
                    {paginatedItems.map((c) => (
                      <Link
                        key={c.id}
                        href={`/api-collections/${c.id}`}
                        className="flex items-center justify-between px-5 py-4 hover:bg-bg-elevated transition-colors"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="h-2.5 w-2.5 rounded-full bg-accent shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-text-primary truncate">{c.name}</p>
                            <p className="text-[11px] text-text-tertiary truncate">
                              {c.description || "No description"}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4 shrink-0">
                          {c.env_name && (
                            <span className="text-[10px] text-text-tertiary font-medium uppercase tracking-wide">
                              {c.env_name}
                            </span>
                          )}
                          <span className="inline-flex items-center rounded-md bg-bg-elevated px-2 py-0.5 text-[11px] text-text-secondary border border-border-subtle">
                            {AUTH_TYPE_LABELS[c.auth_type] || c.auth_type}
                          </span>
                          <span className="text-xs text-text-secondary font-mono">
                            {requestCounts[c.id] || 0} req{(requestCounts[c.id] || 0) !== 1 ? "s" : ""}
                            {folderCounts[c.id] ? ` · ${folderCounts[c.id]} folder${folderCounts[c.id] !== 1 ? "s" : ""}` : ""}
                          </span>
                          <ChevronRight className="h-4 w-4 text-text-muted" />
                        </div>
                      </Link>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Pagination currentPage={currentPage} totalItems={totalItems} pageSize={pageSize} onPageChange={setCurrentPage} />
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass with no errors. If a local dev stack is running (`make dev` from repo root) and you have a team-plan session with synced API collections, open `http://localhost:3000/api-collections` and confirm the list renders (or the "No API collections yet" empty state, if the backend plan isn't deployed yet / no data synced).

- [ ] **Step 3: Commit**

```bash
git add web/src/app/api-collections/page.tsx
git commit -m "feat(web): add API collections list page"
```

---

### Task 3: `/api-collections/[id]` — collection detail (folder tree + vars)

**Files:**
- Create: `web/src/app/api-collections/[id]/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/workspace` → `api_collections`, `api_folders`, `api_requests`, `collection_vars`; `buildFolderTree`, `ApiFolder`, `ApiRequestSummary`, `FolderTreeNode`, `AUTH_TYPE_LABELS`, `METHOD_COLORS` (Task 1).
- Produces: links to `/api-collections/[id]/requests/[requestId]` (Task 4).

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-collections/[id]/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { UpgradeGate } from "@/components/upgrade-gate";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";
import {
  AUTH_TYPE_LABELS,
  METHOD_COLORS,
  buildFolderTree,
  ApiFolder,
  ApiRequestSummary,
  FolderTreeNode,
} from "@/lib/api-testing";
import { Webhook, Folder, ChevronRight, ChevronDown } from "lucide-react";

interface ApiCollection {
  id: string;
  name: string;
  description: string | null;
  env_name: string | null;
  auth_type: string;
  project_id: string;
}

interface CollectionVar {
  collection_id: string;
  key: string;
  initial_value: string;
}

function FolderNode({
  node,
  collectionId,
  depth,
  expanded,
  toggle,
}: {
  node: FolderTreeNode;
  collectionId: string;
  depth: number;
  expanded: Set<string>;
  toggle: (id: string) => void;
}) {
  const isExpanded = node.folder ? expanded.has(node.folder.id) : true;
  return (
    <div>
      {node.folder && (
        <button
          onClick={() => toggle(node.folder!.id)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-bg-elevated transition-colors"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-text-muted shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-text-muted shrink-0" />
          )}
          <Folder className="h-3.5 w-3.5 text-text-tertiary shrink-0" />
          <span className="text-sm text-text-primary">{node.folder.name}</span>
        </button>
      )}
      {isExpanded && (
        <div>
          {node.children.map((child) => (
            <FolderNode
              key={child.folder!.id}
              node={child}
              collectionId={collectionId}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
            />
          ))}
          {node.requests.map((r) => (
            <Link
              key={r.id}
              href={`/api-collections/${collectionId}/requests/${r.id}`}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-bg-elevated transition-colors"
              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
            >
              <span
                className={`inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide shrink-0 ${
                  METHOD_COLORS[r.method] || "text-text-tertiary bg-bg-elevated"
                }`}
              >
                {r.method}
              </span>
              <span className="text-sm text-text-primary truncate">{r.name}</span>
              <span className="text-xs text-text-tertiary truncate ml-auto font-mono">{r.url}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ApiCollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: session } = useSession();
  const [collection, setCollection] = useState<ApiCollection | null>(null);
  const [folders, setFolders] = useState<ApiFolder[]>([]);
  const [requests, setRequests] = useState<ApiRequestSummary[]>([]);
  const [vars, setVars] = useState<CollectionVar[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt || !id) return;
    apiFetch("/api/pull/workspace", { jwt })
      .then((data) => {
        const collections: ApiCollection[] = data.api_collections || [];
        setCollection(collections.find((c) => c.id === id) || null);
        setFolders(data.api_folders || []);
        setRequests(data.api_requests || []);
        setVars((data.collection_vars || []).filter((v: CollectionVar) => v.collection_id === id));
      })
      .finally(() => setLoading(false));
  }, [jwt, id]);

  if (!session?.plan || session.plan === "community") {
    return <UpgradeGate>{null}</UpgradeGate>;
  }

  const toggle = (folderId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  };

  const tree = collection ? buildFolderTree(folders, requests, collection.id) : null;
  const isEmpty = tree && tree.children.length === 0 && tree.requests.length === 0;

  return (
    <AppShell>
      <PageHeader
        title={collection?.name || "Collection"}
        description={collection?.description || ""}
        breadcrumbs={[{ label: "API Collections", href: "/api-collections" }]}
      />

      {loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : !collection ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Webhook className="h-10 w-10 text-text-muted" />
              <p className="text-sm text-text-secondary">Collection not found</p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            {collection.env_name && (
              <span className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs text-text-secondary border border-border-subtle">
                Env: {collection.env_name}
              </span>
            )}
            <span className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs text-text-secondary border border-border-subtle">
              {AUTH_TYPE_LABELS[collection.auth_type] || collection.auth_type}
            </span>
          </div>

          {vars.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Collection Variables</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {vars.map((v) => (
                  <div key={v.key} className="flex items-center gap-3 rounded-md bg-bg-elevated px-3 py-2">
                    <code className="text-xs font-mono text-accent font-medium shrink-0">{v.key}</code>
                    <span className="text-xs text-text-tertiary">=</span>
                    <code className="text-xs font-mono text-text-secondary truncate">{v.initial_value}</code>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Requests</CardTitle>
            </CardHeader>
            <CardContent className={isEmpty ? "" : "p-0"}>
              {isEmpty ? (
                <EmptyState
                  icon={Webhook}
                  title="No requests in this collection"
                  description="Sync requests into this collection from the CLI to see them here."
                />
              ) : (
                <div className="pb-3">
                  {tree!.children.map((child) => (
                    <FolderNode
                      key={child.folder!.id}
                      node={child}
                      collectionId={collection.id}
                      depth={0}
                      expanded={expanded}
                      toggle={toggle}
                    />
                  ))}
                  {tree!.requests.map((r) => (
                    <Link
                      key={r.id}
                      href={`/api-collections/${collection.id}/requests/${r.id}`}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 mx-2 hover:bg-bg-elevated transition-colors"
                    >
                      <span
                        className={`inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide shrink-0 ${
                          METHOD_COLORS[r.method] || "text-text-tertiary bg-bg-elevated"
                        }`}
                      >
                        {r.method}
                      </span>
                      <span className="text-sm text-text-primary truncate">{r.name}</span>
                      <span className="text-xs text-text-tertiary truncate ml-auto font-mono">{r.url}</span>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass. In a running dev stack with synced data, navigate from `/api-collections` into a collection and confirm nested folders expand/collapse and requests link out.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/api-collections/[id]/page.tsx
git commit -m "feat(web): add API collection detail page (folder tree + vars)"
```

---

### Task 4: `/api-collections/[id]/requests/[requestId]` — request detail

**Files:**
- Create: `web/src/app/api-collections/[id]/requests/[requestId]/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/workspace` → `api_collections`, `api_requests` (full field set per the sync plan Section 3 `api_requests` payload); `METHOD_COLORS`, `AUTH_TYPE_LABELS` (Task 1).

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-collections/[id]/requests/[requestId]/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { UpgradeGate } from "@/components/upgrade-gate";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { METHOD_COLORS, AUTH_TYPE_LABELS } from "@/lib/api-testing";
import { Webhook } from "lucide-react";

interface HeaderRow {
  key: string;
  value: string;
  enabled: boolean;
}

interface Assertion {
  type: string;
  op: string;
  value: unknown;
}

interface Extractor {
  name: string;
  path: string;
  prefix: string;
}

interface ApiRequestDetail {
  id: string;
  name: string;
  method: string;
  url: string;
  headers: HeaderRow[];
  params: HeaderRow[];
  path_params: HeaderRow[];
  body_type: string | null;
  body: string | null;
  auth_type: string;
  auth_config: Record<string, unknown>;
  pre_script: string | null;
  pre_lang: string;
  pre_extractor: Extractor[] | null;
  post_script: string | null;
  post_lang: string;
  post_extractor: Extractor[] | null;
  assertions: Assertion[];
  follow_redirects: boolean;
  timeout_ms: number;
  include_in_docs: boolean;
  collection_id: string | null;
}

interface ApiCollection {
  id: string;
  name: string;
}

function KeyValueTable({ rows, emptyLabel }: { rows: HeaderRow[]; emptyLabel: string }) {
  const enabled = rows.filter((r) => r.key);
  if (enabled.length === 0) {
    return <p className="text-xs text-text-tertiary py-2">{emptyLabel}</p>;
  }
  return (
    <div className="space-y-1">
      {enabled.map((r, i) => (
        <div
          key={i}
          className={`flex items-center gap-3 rounded-md px-3 py-1.5 ${r.enabled === false ? "opacity-40" : ""} bg-bg-elevated`}
        >
          <code className="text-xs font-mono text-accent font-medium shrink-0">{r.key}</code>
          <span className="text-xs text-text-tertiary">=</span>
          <code className="text-xs font-mono text-text-secondary truncate">{r.value}</code>
        </div>
      ))}
    </div>
  );
}

export default function ApiRequestDetailPage() {
  const { id, requestId } = useParams<{ id: string; requestId: string }>();
  const { data: session } = useSession();
  const [request, setRequest] = useState<ApiRequestDetail | null>(null);
  const [collection, setCollection] = useState<ApiCollection | null>(null);
  const [loading, setLoading] = useState(true);
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt || !requestId) return;
    apiFetch("/api/pull/workspace", { jwt })
      .then((data) => {
        const requests: ApiRequestDetail[] = data.api_requests || [];
        setRequest(requests.find((r) => r.id === requestId) || null);
        const collections: ApiCollection[] = data.api_collections || [];
        setCollection(collections.find((c) => c.id === id) || null);
      })
      .finally(() => setLoading(false));
  }, [jwt, id, requestId]);

  if (!session?.plan || session.plan === "community") {
    return <UpgradeGate>{null}</UpgradeGate>;
  }

  return (
    <AppShell>
      <PageHeader
        title={request?.name || "Request"}
        description={request?.url || ""}
        breadcrumbs={[
          { label: "API Collections", href: "/api-collections" },
          { label: collection?.name || "Collection", href: `/api-collections/${id}` },
        ]}
      />

      {loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : !request ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Webhook className="h-10 w-10 text-text-muted" />
              <p className="text-sm text-text-secondary">Request not found</p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`inline-flex items-center justify-center rounded px-2 py-1 text-xs font-semibold uppercase tracking-wide ${
                METHOD_COLORS[request.method] || "text-text-tertiary bg-bg-elevated"
              }`}
            >
              {request.method}
            </span>
            <span className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs text-text-secondary border border-border-subtle">
              {AUTH_TYPE_LABELS[request.auth_type] || request.auth_type}
            </span>
            <span className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs text-text-secondary border border-border-subtle">
              Timeout: {request.timeout_ms}ms
            </span>
            <span className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs text-text-secondary border border-border-subtle">
              {request.follow_redirects ? "Follows redirects" : "No redirect follow"}
            </span>
            {request.include_in_docs && (
              <span className="inline-flex items-center rounded-md bg-accent-muted px-2.5 py-1 text-xs text-accent border border-accent/20">
                In API Docs
              </span>
            )}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Headers</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValueTable rows={request.headers} emptyLabel="No headers." />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Query Params</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValueTable rows={request.params} emptyLabel="No query params." />
            </CardContent>
          </Card>

          {request.path_params.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Path Params</CardTitle>
              </CardHeader>
              <CardContent>
                <KeyValueTable rows={request.path_params} emptyLabel="No path params." />
              </CardContent>
            </Card>
          )}

          {request.body && (
            <Card>
              <CardHeader>
                <CardTitle>Body {request.body_type ? `(${request.body_type})` : ""}</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <pre className="p-4 text-sm font-mono text-text-primary overflow-x-auto leading-relaxed whitespace-pre-wrap">
                  {request.body}
                </pre>
              </CardContent>
            </Card>
          )}

          {request.pre_script && (
            <Card>
              <CardHeader>
                <CardTitle>Pre-request Script ({request.pre_lang})</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <pre className="p-4 text-sm font-mono text-text-primary overflow-x-auto leading-relaxed whitespace-pre-wrap">
                  {request.pre_script}
                </pre>
              </CardContent>
            </Card>
          )}

          {request.post_script && (
            <Card>
              <CardHeader>
                <CardTitle>Post-request Script ({request.post_lang})</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <pre className="p-4 text-sm font-mono text-text-primary overflow-x-auto leading-relaxed whitespace-pre-wrap">
                  {request.post_script}
                </pre>
              </CardContent>
            </Card>
          )}

          {request.assertions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Assertions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {request.assertions.map((a, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center rounded-md bg-bg-elevated px-2.5 py-1 text-xs font-mono text-text-secondary border border-border-subtle"
                    >
                      {a.type} {a.op} {JSON.stringify(a.value)}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {(request.pre_extractor?.length || request.post_extractor?.length) ? (
            <Card>
              <CardHeader>
                <CardTitle>Extractors</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {[...(request.pre_extractor || []), ...(request.post_extractor || [])].map((e, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-md bg-bg-elevated px-3 py-2">
                    <code className="text-xs font-mono text-accent font-medium shrink-0">{e.name}</code>
                    <span className="text-xs text-text-tertiary">=</span>
                    <code className="text-xs font-mono text-text-secondary">{e.prefix}{e.path}</code>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass. With real data, confirm a request's headers/body/scripts/assertions render and the breadcrumb links back to its collection.

- [ ] **Step 3: Commit**

```bash
git add "web/src/app/api-collections/[id]/requests/[requestId]/page.tsx"
git commit -m "feat(web): add API request detail page"
```

---

### Task 5: `/api-runs` — standalone collection-run history list

**Files:**
- Create: `web/src/app/api-runs/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/api-runs?per_page=50` (sync plan Section 3.2), `GET /api/pull/workspace` → `api_collections` (for project scoping only — `collection_name`/`env_name` already come inline on each run row).

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-runs/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { UpgradeGate } from "@/components/upgrade-gate";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import { Pagination, usePagination } from "@/components/ui/Pagination";
import { Send, ChevronRight, Search } from "lucide-react";

interface ApiRun {
  id: string;
  cli_collection_run_id: string;
  collection_id: string;
  collection_name: string;
  env_name: string | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  error_count: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

interface ApiCollection {
  id: string;
  project_id: string;
}

const statusFilters = ["all", "passed", "failed", "error"] as const;

export default function ApiRunsPage() {
  const { data: session } = useSession();
  const { selectedProject } = useProject();
  const [runs, setRuns] = useState<ApiRun[]>([]);
  const [collections, setCollections] = useState<ApiCollection[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt) return;
    Promise.all([
      apiFetch("/api/pull/api-runs?per_page=50", { jwt }),
      apiFetch("/api/pull/workspace", { jwt }),
    ])
      .then(([runsData, workspace]) => {
        setRuns(runsData.runs || []);
        setCollections(workspace.api_collections || []);
      })
      .finally(() => setLoading(false));
  }, [jwt]);

  if (!session?.plan || session.plan === "community") {
    return <UpgradeGate>{null}</UpgradeGate>;
  }

  const collectionProjectMap = Object.fromEntries(collections.map((c) => [c.id, c.project_id]));
  const projectRuns = runs.filter(
    (r) => !selectedProject || collectionProjectMap[r.collection_id] === selectedProject.id
  );

  const q = search.toLowerCase().trim();
  const filtered = projectRuns.filter((run) => {
    if (statusFilter !== "all" && run.status !== statusFilter) return false;
    if (!q) return true;
    const date = new Date(run.started_at).toLocaleDateString();
    const dateTime = new Date(run.started_at).toLocaleString();
    return (
      run.collection_name.toLowerCase().includes(q) ||
      run.status.toLowerCase().includes(q) ||
      date.includes(q) ||
      dateTime.includes(q)
    );
  });

  const { currentPage, setCurrentPage, paginatedItems, totalItems, pageSize } = usePagination(filtered);

  return (
    <AppShell>
      <PageHeader title="API Run History" description={`${projectRuns.length} runs`} />

      {loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : projectRuns.length === 0 ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <EmptyState icon={Send} title="No API runs found" description="Run a collection from the CLI to see history here." />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-tertiary" />
              <input
                type="text"
                placeholder="Search by collection, status, date..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-lg border border-border-default bg-bg-surface pl-9 pr-3 py-2 text-sm text-text-primary placeholder:text-text-muted hover:border-border-emphasis focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-all"
              />
            </div>
            <div className="flex gap-1.5">
              {statusFilters.map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`rounded-md px-3 py-2 text-xs font-medium capitalize transition-all duration-150 ${
                    statusFilter === f
                      ? "bg-accent text-white shadow-sm"
                      : "bg-bg-surface border border-border-default text-text-secondary hover:border-border-emphasis hover:text-text-primary"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <Card className="mx-auto max-w-lg">
              <CardContent>
                <EmptyState icon={Send} title="No matching runs" description="Try a different search or filter." />
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardContent className="p-0">
                  <div className="divide-y divide-border-subtle">
                    {paginatedItems.map((run) => (
                      <Link
                        key={run.id}
                        href={`/api-runs/${run.id}`}
                        className="flex items-center justify-between px-5 py-4 hover:bg-bg-elevated transition-colors"
                      >
                        <div className="flex items-center gap-4">
                          <div
                            className={`h-2.5 w-2.5 rounded-full shrink-0 ${
                              run.status === "passed" ? "bg-success" : run.status === "failed" ? "bg-danger" : "bg-warning"
                            }`}
                          />
                          <div>
                            <p className="text-sm font-medium text-text-primary">{run.collection_name}</p>
                            <p className="text-[11px] text-text-tertiary">{new Date(run.started_at).toLocaleString()}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          {run.env_name && (
                            <span className="text-[10px] text-text-tertiary font-medium uppercase tracking-wide">
                              {run.env_name}
                            </span>
                          )}
                          <span className="text-xs text-text-secondary font-mono">
                            {run.passed}/{run.total} passed
                          </span>
                          {run.duration_ms !== null && (
                            <span className="text-xs text-text-tertiary font-mono">{(run.duration_ms / 1000).toFixed(1)}s</span>
                          )}
                          <StatusBadge status={run.status as "passed" | "failed" | "running" | "partial"} size="sm" />
                          <ChevronRight className="h-4 w-4 text-text-muted" />
                        </div>
                      </Link>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Pagination currentPage={currentPage} totalItems={totalItems} pageSize={pageSize} onPageChange={setCurrentPage} />
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass. With real data, confirm status filters and search narrow the list, and each row links to `/api-runs/<id>`.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/api-runs/page.tsx
git commit -m "feat(web): add API run history list page"
```

---

### Task 6: `/api-runs/[id]` — run detail

**Files:**
- Create: `web/src/app/api-runs/[id]/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/api-runs/<run_id>` (sync plan Section 3.2 — header fields + `request_results[]`); `METHOD_COLORS` (Task 1).

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-runs/[id]/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { METHOD_COLORS } from "@/lib/api-testing";
import { CheckCircle2, XCircle, MinusCircle, ChevronDown } from "lucide-react";

interface AssertionResult {
  type: string;
  op: string;
  value: unknown;
  passed: boolean;
  actual: unknown;
}

interface ApiRequestResult {
  cli_request_id: string;
  request_name: string;
  method: string | null;
  url: string | null;
  order_index: number;
  status: string;
  status_code: number | null;
  duration_ms: number | null;
  response_body: string | null;
  response_headers: Record<string, string> | null;
  assertion_results: AssertionResult[] | null;
  error_message: string | null;
}

interface ApiRunDetail {
  id: string;
  cli_collection_run_id: string;
  collection_name: string;
  env_name: string | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  error_count: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  request_results: ApiRequestResult[];
}

export default function ApiRunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: session } = useSession();
  const [run, setRun] = useState<ApiRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt || !id) return;
    apiFetch(`/api/pull/api-runs/${id}`, { jwt })
      .then((data) => setRun(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [jwt, id]);

  const toggle = (requestId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(requestId)) next.delete(requestId);
      else next.add(requestId);
      return next;
    });
  };

  return (
    <AppShell>
      <PageHeader
        breadcrumbs={[{ label: "API Runs", href: "/api-runs" }, { label: run?.collection_name || "Run Detail" }]}
        title=""
      />

      {loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : !run ? (
        <Card className="mx-auto max-w-lg">
          <CardContent className="py-16 text-center">
            <h2 className="text-lg font-semibold text-text-primary">Run not found</h2>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-semibold text-text-primary tracking-tight">{run.collection_name}</h1>
            <StatusBadge status={run.status as "passed" | "failed" | "running" | "partial"} />
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "Duration", value: run.duration_ms !== null ? `${(run.duration_ms / 1000).toFixed(1)}s` : "—" },
              { label: "Requests", value: `${run.passed}/${run.total} passed` },
              { label: "Started", value: new Date(run.started_at).toLocaleDateString(), sub: new Date(run.started_at).toLocaleTimeString() },
              {
                label: "Completed",
                value: run.completed_at ? new Date(run.completed_at).toLocaleDateString() : "—",
                sub: run.completed_at ? new Date(run.completed_at).toLocaleTimeString() : undefined,
              },
            ].map((stat) => (
              <div
                key={stat.label}
                className="relative rounded-xl border border-border-subtle bg-bg-surface p-4 overflow-hidden before:absolute before:inset-0 before:bg-gradient-to-br before:from-white/[0.03] before:to-transparent before:pointer-events-none"
              >
                <div className="relative">
                  <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-tertiary">{stat.label}</p>
                  <p className="mt-1 text-xl font-medium text-text-primary">{stat.value}</p>
                  {stat.sub && <p className="text-xs text-text-tertiary">{stat.sub}</p>}
                </div>
              </div>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Request Results</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="divide-y divide-border-subtle">
                {[...run.request_results]
                  .sort((a, b) => a.order_index - b.order_index)
                  .map((rr) => {
                    const hasDetails = rr.response_body || rr.error_message || (rr.assertion_results && rr.assertion_results.length > 0);
                    const isExpanded = expanded.has(rr.cli_request_id);
                    return (
                      <div key={rr.cli_request_id}>
                        <div
                          className={`flex items-center justify-between px-5 py-3.5 ${hasDetails ? "cursor-pointer hover:bg-bg-elevated" : ""} transition-colors`}
                          onClick={hasDetails ? () => toggle(rr.cli_request_id) : undefined}
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            {rr.status === "passed" ? (
                              <CheckCircle2 className="h-5 w-5 text-success shrink-0" />
                            ) : rr.status === "failed" ? (
                              <XCircle className="h-5 w-5 text-danger shrink-0" />
                            ) : (
                              <MinusCircle className="h-5 w-5 text-text-tertiary shrink-0" />
                            )}
                            {rr.method && (
                              <span
                                className={`inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide shrink-0 ${
                                  METHOD_COLORS[rr.method] || "text-text-tertiary bg-bg-elevated"
                                }`}
                              >
                                {rr.method}
                              </span>
                            )}
                            <div className="min-w-0">
                              <span className="text-sm font-medium text-text-primary">{rr.request_name}</span>
                              {rr.error_message && (
                                <p className="text-xs text-danger mt-0.5 truncate">{rr.error_message}</p>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-3 shrink-0">
                            {rr.status_code !== null && (
                              <span className="text-xs text-text-tertiary font-mono">{rr.status_code}</span>
                            )}
                            {rr.duration_ms !== null && (
                              <span className="text-xs text-text-tertiary font-mono">{(rr.duration_ms / 1000).toFixed(2)}s</span>
                            )}
                            {hasDetails && (
                              <ChevronDown className={`h-4 w-4 text-text-tertiary transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                            )}
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="px-5 pb-4 space-y-3">
                            {rr.assertion_results && rr.assertion_results.length > 0 && (
                              <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-1.5">Assertions</p>
                                <div className="flex flex-wrap gap-2">
                                  {rr.assertion_results.map((a, i) => (
                                    <span
                                      key={i}
                                      className={`inline-flex items-center rounded-md px-2.5 py-1 text-xs font-mono border ${
                                        a.passed
                                          ? "bg-success-muted text-success border-success/20"
                                          : "bg-danger-muted text-danger border-danger/20"
                                      }`}
                                    >
                                      {a.type} {a.op} {JSON.stringify(a.value)} → {JSON.stringify(a.actual)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                            {rr.response_body && (
                              <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-1.5">Response Body</p>
                                <pre className="rounded-lg bg-bg-sunken border border-border-subtle p-3 text-xs font-mono text-text-secondary overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                                  {rr.response_body}
                                </pre>
                              </div>
                            )}
                            {rr.error_message && (
                              <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-1.5">Error</p>
                                <pre className="rounded-lg bg-danger-muted border border-danger/20 p-4 text-xs text-danger overflow-x-auto font-mono">
                                  {rr.error_message}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass. With real data, confirm request rows expand to show assertions/response body/error, matching the pattern of `/runs/[id]`.

- [ ] **Step 3: Commit**

```bash
git add "web/src/app/api-runs/[id]/page.tsx"
git commit -m "feat(web): add API run detail page"
```

---

### Task 7: `/api-docs` — server-computed docs cache browser

**Files:**
- Create: `web/src/app/api-docs/page.tsx`

**Interfaces:**
- Consumes: `GET /api/pull/api-docs?project_id=<id>` (sync plan Section 3.3); `METHOD_COLORS` (Task 1); `useProject()`.

- [ ] **Step 1: Write the file**

```tsx
// web/src/app/api-docs/page.tsx
"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { UpgradeGate } from "@/components/upgrade-gate";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import { METHOD_COLORS } from "@/lib/api-testing";
import { FileJson, ChevronDown, ChevronRight } from "lucide-react";

interface DocEntry {
  id: string;
  method: string;
  path_pattern: string;
  description: string | null;
  request_schema: unknown;
  response_schema: unknown;
  headers_schema: unknown;
  params_schema: unknown;
  source_request_ids: string[];
  include_in_docs: boolean;
  first_seen_at: string;
  last_seen_at: string;
}

function SchemaBlock({ label, schema }: { label: string; schema: unknown }) {
  if (!schema) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-1.5">{label}</p>
      <pre className="rounded-lg bg-bg-sunken border border-border-subtle p-3 text-xs font-mono text-text-secondary overflow-x-auto max-h-64 overflow-y-auto">
        {JSON.stringify(schema, null, 2)}
      </pre>
    </div>
  );
}

export default function ApiDocsPage() {
  const { data: session } = useSession();
  const { selectedProject } = useProject();
  const [entries, setEntries] = useState<DocEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const jwt = session?.jwt;

  useEffect(() => {
    if (!jwt || !selectedProject) return;
    setLoading(true);
    apiFetch(`/api/pull/api-docs?project_id=${selectedProject.id}`, { jwt })
      .then((data) => setEntries(data.doc_entries || []))
      .finally(() => setLoading(false));
  }, [jwt, selectedProject?.id]);

  if (!session?.plan || session.plan === "community") {
    return <UpgradeGate>{null}</UpgradeGate>;
  }

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const sorted = [...entries].sort((a, b) => a.path_pattern.localeCompare(b.path_pattern) || a.method.localeCompare(b.method));

  return (
    <AppShell>
      <PageHeader title="API Docs" description={`${entries.length} documented endpoints`} />

      {!selectedProject ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <EmptyState icon={FileJson} title="Select a project" description="Pick a project to view its documented endpoints." />
          </CardContent>
        </Card>
      ) : loading ? (
        <div className="flex items-center gap-3 py-20 justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        </div>
      ) : sorted.length === 0 ? (
        <Card className="mx-auto max-w-lg">
          <CardContent>
            <EmptyState
              icon={FileJson}
              title="No documented endpoints yet"
              description="Sync API requests with 'Include in docs' enabled from the CLI to populate this view."
            />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border-subtle">
              {sorted.map((entry) => {
                const isExpanded = expanded.has(entry.id);
                return (
                  <div key={entry.id}>
                    <button
                      onClick={() => toggle(entry.id)}
                      className="flex w-full items-center justify-between px-5 py-4 hover:bg-bg-elevated transition-colors text-left"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <span
                          className={`inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide shrink-0 ${
                            METHOD_COLORS[entry.method] || "text-text-tertiary bg-bg-elevated"
                          }`}
                        >
                          {entry.method}
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm font-mono text-text-primary truncate">{entry.path_pattern}</p>
                          {entry.description && (
                            <p className="text-[11px] text-text-tertiary truncate">{entry.description}</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="text-[11px] text-text-tertiary">
                          {entry.source_request_ids.length} synced request{entry.source_request_ids.length !== 1 ? "s" : ""}
                        </span>
                        <span className="text-[11px] text-text-tertiary">
                          Last seen {new Date(entry.last_seen_at).toLocaleDateString()}
                        </span>
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-text-muted" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-text-muted" />
                        )}
                      </div>
                    </button>

                    {isExpanded && (
                      <div className="px-5 pb-4 space-y-3 bg-bg-elevated border-t border-border-subtle">
                        <SchemaBlock label="Headers Schema" schema={entry.headers_schema} />
                        <SchemaBlock label="Params Schema" schema={entry.params_schema} />
                        <SchemaBlock label="Request Schema" schema={entry.request_schema} />
                        <SchemaBlock label="Response Schema" schema={entry.response_schema} />
                        {!entry.request_schema && !entry.response_schema && !entry.headers_schema && !entry.params_schema && (
                          <p className="text-xs text-text-tertiary py-2">No schema data captured yet.</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}
```

- [ ] **Step 2: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
```
Expected: both pass. With real data, confirm entries expand to show schema JSON blocks and collapse again.

- [ ] **Step 3: Commit**

```bash
git add web/src/app/api-docs/page.tsx
git commit -m "feat(web): add API docs cache browser page"
```

---

### Task 8: Wire up the sidebar

**Files:**
- Modify: `web/src/components/layout/Sidebar.tsx`

**Interfaces:**
- Consumes: nothing new — links to routes created in Tasks 2, 5, 7.

- [ ] **Step 1: Add the icon imports**

Change:
```tsx
import {
  LayoutDashboard,
  Play,
  Layers,
  FileCode,
  ListChecks,
  Globe,
  BarChart3,
  Settings,
  CreditCard,
  Users,
  LogOut,
  Lock,
  ShieldCheck,
  BookOpen,
} from "lucide-react";
```
to:
```tsx
import {
  LayoutDashboard,
  Play,
  Layers,
  FileCode,
  ListChecks,
  Globe,
  BarChart3,
  Settings,
  CreditCard,
  Users,
  LogOut,
  Lock,
  ShieldCheck,
  BookOpen,
  Webhook,
  Send,
  FileJson,
} from "lucide-react";
```

- [ ] **Step 2: Add the nav items**

Change:
```tsx
const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Features", href: "/features", icon: Layers },
  { label: "Scripts", href: "/scripts", icon: FileCode },
  { label: "Suites", href: "/suites", icon: ListChecks },
  { label: "Runs", href: "/runs", icon: Play },
  { label: "Reports", href: "/reports", icon: BarChart3 },
  { label: "Environments", href: "/environments", icon: Globe },
];
```
to:
```tsx
const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Features", href: "/features", icon: Layers },
  { label: "Scripts", href: "/scripts", icon: FileCode },
  { label: "Suites", href: "/suites", icon: ListChecks },
  { label: "Runs", href: "/runs", icon: Play },
  { label: "Reports", href: "/reports", icon: BarChart3 },
  { label: "Environments", href: "/environments", icon: Globe },
  { label: "API Collections", href: "/api-collections", icon: Webhook },
  { label: "API Runs", href: "/api-runs", icon: Send },
  { label: "API Docs", href: "/api-docs", icon: FileJson },
];
```

- [ ] **Step 3: Verify manually**

```bash
cd web
npx tsc --noEmit
npm run lint
npm run build
```
Expected: all three pass — `npm run build` is the full integration check for this plan, compiling every page added in Tasks 2–7 together. In a running dev stack, confirm the sidebar shows "API Collections" / "API Runs" / "API Docs" after "Environments", each with active-state highlighting matching the existing items when on their route.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/layout/Sidebar.tsx
git commit -m "feat(web): wire API testing pages into the sidebar"
```

---

## Self-Review Notes

- **Spec coverage:** every in-scope entity from the sync plan's Section 3 pull payload has a page — collections+folders+requests (Tasks 2–4), collection vars (shown inline in Task 3, no standalone page since they're few-per-collection metadata, matching how env vars are shown inline under their environment rather than on their own page), standalone collection runs (Tasks 5–6), docs cache (Task 7). `api_request_examples` (variant library, Phase 2/optional in the sync plan) and mixed-suite `cloud_run_api_results` (folded into the existing `/runs/[id]` E2E run detail, not a standalone entity) are intentionally out of scope here — nothing in the sync plan's Section 3 pull contract exposes either to the web UI yet, so there is nothing to build against.
- **No placeholders:** every page has complete, real TSX — no `// TODO`, no stub components, no unshown code.
- **Type consistency:** `ApiFolder`/`ApiRequestSummary`/`FolderTreeNode` are defined once in `api-testing.ts` (Task 1) and imported verbatim by Tasks 3–4; `METHOD_COLORS`/`AUTH_TYPE_LABELS` keys match the CLI's actual `method`/`auth_type` column values from `cli/db.py` (`GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS`, `none/inherit/bearer/basic/api_key/oauth2`) and the sync plan's payload examples exactly.
- **View-only confirmed:** no `<form>`, no `POST`/`PUT`/`DELETE` `apiFetch` call, no create/edit/delete button anywhere in Tasks 2–7 — every page is a pure `GET` + render.
