# API Variant Library — Design Spec
Date: 2026-07-05

## Problem

All four Discovery paths (Record APIs mode, HAR import, OpenAPI import, and the new script-run capture) can surface the same endpoint many times with different query params or bodies — a filtered list view hit with three sort orders, a PATCH sent with three different field combinations. Two use cases pull in opposite directions:

1. **Testing a real flow** — the repeats matter. Replaying the exact recorded sequence, filters and all, is a legitimate, valuable test. Collapsing duplicates here would make the "test" meaningless.
2. **Building a reusable request library** — the same repeats are noise. A tester maintaining a collection long-term wants one clean `GET /cart` request, not five near-identical rows that all need updating when the endpoint changes.

Neither Postman nor Bruno resolve this well. Postman's answer — saved **Examples** (one request definition, multiple alternate request/response pairs) — is well-liked but entirely manual: you send a request, then manually click "Save Response as Example" each time. Bruno has no equivalent at all; it's an open, actively-requested feature there ([usebruno/bruno#5965](https://github.com/usebruno/bruno/issues/5965), [#5657](https://github.com/usebruno/bruno/issues/5657)).

QAClan's differentiator: auto-detect the variants from real captured traffic at save time, and let the user decide per group — instead of requiring manual example-saving after the fact, or offering nothing at all.

## Decisions

| Question | Decision |
|---|---|
| Where this applies | Save-time UI shared by all Discovery paths, not a new standalone screen |
| Flow replay vs library | Explicit user choice at save time — "Save as Flow" (today's behavior, unchanged) vs "Save as Library" (new) |
| Grouping key | `(method, normalized_path)` via existing `url_normalizer.normalize_url()` |
| Exact duplicates | Auto-collapsed silently — no value in asking the user about byte-identical repeats |
| Distinct variants | Shown in a comparison view; user picks per group |
| Data model for merged variants | New `api_request_examples` table — the mechanism behind "Postman Examples, but auto-populated" |

---

## Section 1: Save-Time Choice

Every Discovery path's save screen (Record APIs mode, HAR import, OpenAPI import, script-run capture) gains this choice before the final save:

```
Captured 12 requests
┌─────────────────────────────────────────────────────┐
│  ○ Save as Flow        preserve exact order + repeats │
│                        → for replaying this real flow │
│  ○ Save as Library     group by endpoint, show variants│
│                        → for building reusable requests│
└─────────────────────────────────────────────────────┘
```

- **Save as Flow** — unchanged existing behavior. Creates one ordered `api_collection`; every captured request becomes its own row in capture order, duplicates included. (This already works today via `_save_requests` + `collection_id`; no backend change.)
- **Save as Library** — new. Triggers the grouping flow in Section 2.

---

## Section 2: Grouping & Comparison UI

**Grouping key:** `(method, normalize_url(url))` — reuses `cli/api_discovery/url_normalizer.py`, already built for the API Docs feature. No new normalization logic.

**Within a group:** requests that are byte-identical (same params, same body) collapse automatically — these are not shown as a choice, just silently deduplicated to one row. Requests that differ in query params or body are shown as separate comparison rows.

```
GET /cart — 2 variants captured
┌───┬────────────────┬──────┬──────┐
│ ☑ │ ?sort=price     │ 200  │ 89ms │
│ ☑ │ ?sort=date      │ 200  │ 94ms │
└───┴────────────────┴──────┴──────┘

POST /users — 3 variants captured
┌───┬───────────────────────────────┬──────┐
│ ☑ │ {"name","role":"admin"}       │ 201  │
│ ☑ │ {"name","role":"viewer"}      │ 201  │
│ ☑ │ {"name","role","dept"}        │ 201  │  ← extra field, different shape
└───┴───────────────────────────────┴──────┘

Per group:
○ Keep as separate named requests
○ Merge into one parameterized request
```

Each group is decided independently — a user can merge `GET /cart`'s variants while keeping `POST /users`'s as three separate named requests.

---

## Section 3: Keep as Separate

Plain `api_requests` rows, one per selected variant. No schema change — reuses the existing table as-is.

**Auto-naming:** suffix the base endpoint name with the differentiating value(s):
- Query param variants: `GET /cart (sort=price)`, `GET /cart (sort=date)`
- Body variants: name by the field that differs, e.g. `POST /users (role=admin)`. If no single field cleanly distinguishes (structurally different shapes, like the `dept` example above), fall back to `POST /users (variant 2)`.

---

## Section 4: Merge into One Parameterized Request

The differing values become `{{var}}` placeholders in the merged request (URL query params and/or body fields); the first captured variant's values become the defaults. Every other captured variant is preserved as a **saved example**, not discarded.

### New table: `api_request_examples`

```sql
CREATE TABLE api_request_examples (
    id              TEXT PRIMARY KEY,          -- "apiex_xxxxxxxx"
    api_request_id  TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,             -- e.g. "sort=date" or "role=viewer"
    params          TEXT NOT NULL DEFAULT '[]', -- JSON, same shape as api_requests.params
    body            TEXT DEFAULT NULL,
    response_status INTEGER,
    response_headers TEXT,                     -- JSON
    response_body   TEXT,
    created_at      TEXT NOT NULL
);
```

**Request editor:** the response panel gains an "Examples" dropdown next to Send — selecting one fills the params/body fields with that example's captured values, so the user can re-send with any previously-observed variant without retyping it. Read-only display of the example's originally captured response is available alongside (not re-fetched).

**Merged request's own schema:** `request_schema`/`response_schema` columns on the merged `api_requests` row are populated via the existing `merge_schemas()` (`cli/api_discovery/schema_merger.py`) across all variants — same mechanism already used by the API Docs feature, applied here to the merge choice instead of doc generation.

---

## Section 5: Backend Contract

The existing Discovery save endpoints (`/api/discover/*/save`, `import_har`, `import_openapi`, etc., in `web/api/services/discovery_service.py`) gain a `mode: "flow" | "library"` parameter.

- `mode: "flow"` — today's behavior, default, unchanged.
- `mode: "library"` — runs the grouping in Section 2 server-side and returns the grouped structure (groups, variants, auto-suggested names) for the comparison UI to render, before the user's per-group choices are submitted in a second call that performs the actual save (plain rows or `api_request_examples` rows per Sections 3–4).

No CLI command changes — this is Discovery UI/service-layer behavior only, triggered from the web UI's save screen.

---

## Out of Scope (This Version)

- Editing an example after it's saved (examples are captured snapshots; edit the parent request instead)
- Auto-detecting variants across separate Discovery sessions (grouping only considers requests captured/imported together, in one save action)
- Mock server responses driven by examples (Postman's mock-matching-by-example is not in scope)

## Open Questions

None — all decisions made above.
