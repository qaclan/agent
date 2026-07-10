# API Variant Library — Design Spec
Date: 2026-07-05
Revised: 2026-07-10 (UI detail pass — see Sections 1-5)

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
| Modal architecture | Two-step: existing `request-review-modal.js` unchanged (flat checklist + third-party filter), Flow/Library radio added near Save; "Save as Library" opens a **new** second modal (grouping/comparison) instead of saving immediately |
| Grouping equality (exact-dup) | `(method, normalize_url(url), headers-after-ignore-list, params, body)` — headers now participate, but only after stripping a fixed ignore-list of volatile headers |
| Header ignore-list | `authorization, cookie, set-cookie, x-request-id, x-correlation-id, traceparent, user-agent, date, content-length, x-csrf-token` — stripped before any equality/diff check, both for dedup and for variant display |
| Merge field selection | Auto-detected diff fields are pre-checked as `{{var}}` candidates; user can uncheck any field to keep it hardcoded to the first variant's value instead |
| Example replay in editor | Selecting an example fills Params/Body with its captured values and switches the response panel into a banner-flagged "captured, not live" read-only mode (reuses the existing Body/Headers/Assertions/Variables tabs) — Send always fires live and clears the banner |
| Collection run vs examples | V1: collection runs always use the merged request's stored defaults; examples are manual-reference + docs-enrichment only (via `merge_schemas()`), not part of automated runs. Fast-follow, not this pass: opt-in "run once per example" during collection execution — data model already supports it, no migration needed later |

---

## Section 1: Save-Time Choice

Every Discovery path funnels into the existing `request-review-modal.js` (flat checklist, third-party filter, collection name, docs checkbox — unchanged). It gains one addition near the Save row:

```
12 requests found. Select which to save:
[All] [None]           Hide third-party (3)
┌─────────────────────────────────────────────────────┐
│  ☑ GET /cart?sort=price          200   89ms          │
│  ☑ GET /cart?sort=date           200   94ms          │
│  ☑ POST /users {role:admin}      201                 │
│  ...                                                  │
└─────────────────────────────────────────────────────┘
Save to collection: [Imported APIs________________]
☑ Include in API Documentation

○ Save as Flow        preserve exact order + repeats
                       → for replaying this real flow
○ Save as Library      group by endpoint, show variants
                       → for building reusable requests
                                    [Cancel]  [Save Selected / Next →]
```

- **Save as Flow** — unchanged existing behavior. Button reads "Save Selected", posts straight to `/discover/save-requests` as today; every captured request becomes its own row in capture order, duplicates included. No backend change.
- **Save as Library** — button relabels to "Next →". Posts the checked requests to a new `/discover/group-requests` call (Section 5) and opens **Modal 2** (Section 2) with the grouped result. Nothing is saved until Modal 2's own Save.

---

## Section 2: Grouping & Comparison UI (Modal 2)

**Grouping key:** `(method, normalize_url(url))` — reuses `cli/api_discovery/url_normalizer.py`, already built for the API Docs feature. No new normalization logic.

**Header handling:** before any comparison, headers are stripped of the ignore-list (`authorization, cookie, set-cookie, x-request-id, x-correlation-id, traceparent, user-agent, date, content-length, x-csrf-token`). Everything downstream — exact-dup collapse, variant diffing, auto-naming — operates on stripped headers, never the raw captured ones.

**Within a group:** requests that are byte-identical on `(stripped headers, params, body)` collapse automatically — these are not shown as a choice, just silently deduplicated to one row (with a small "N exact dups collapsed" note). Requests that differ in query params, body, **or a non-ignored header** are shown as separate comparison rows.

```
GET /cart — 2 variants (1 exact dup collapsed)
┌───┬────────────────┬──────┬──────┐
│ ☑ │ ?sort=price     │ 200  │ 89ms │
│ ☑ │ ?sort=date      │ 200  │ 94ms │
└───┴────────────────┴──────┴──────┘
○ Keep as separate named requests   ○ Merge into one parameterized request

POST /users — 3 variants captured
┌───┬───────────────────────────────┬──────┐
│ ☑ │ {"name","role":"admin"}       │ 201  │
│ ☑ │ {"name","role":"viewer"}      │ 201  │
│ ☑ │ {"name","role","dept"}        │ 201  │  ← extra field, different shape
└───┴───────────────────────────────┴──────┘
○ Keep as separate   ● Merge into one parameterized request
  ☑ role  (admin / viewer / admin) → {{role}}
  ☑ dept  (— / — / sales)          → {{dept}}
```

Per-group radio defaults to **Merge** pre-selected whenever 2+ real variants exist — the whole point of choosing "Save as Library" is building a reusable request, so merge is the path of least resistance; "Keep separate" is one click away. Each group is decided independently — a user can merge `GET /cart`'s variants while keeping `POST /users`'s as three separate named requests. The per-row checkbox still lets a user drop an individual captured variant (e.g. an errored 500 response) from the save entirely, independent of the group's separate/merge choice.

When "Merge" is selected, every auto-detected diff field is listed with its own checkbox, pre-checked as a `{{var}}` candidate (Section 4). Unchecking a field keeps it hardcoded to the first captured variant's value instead of templating it — an escape hatch for fields that differ but aren't meaningful to parameterize.

---

## Section 3: Keep as Separate

Plain `api_requests` rows, one per selected variant. No schema change — reuses the existing table as-is.

**Auto-naming:** suffix the base endpoint name with the differentiating value(s):
- Query param variants: `GET /cart (sort=price)`, `GET /cart (sort=date)`
- Body variants: name by the field that differs, e.g. `POST /users (role=admin)`. Multiple differing fields join with a comma: `POST /users (role=admin, dept=eng)`. If no single field cleanly distinguishes (structurally different shapes, like the `dept` example above), fall back to `POST /users (variant 2)`.
- Header-only variants (after ignore-list stripping): name by the differing header, e.g. `GET /profile (Accept-Language=fr-FR)`.

---

## Section 4: Merge into One Parameterized Request

The differing values become `{{var}}` placeholders in the merged request (URL query params and/or body fields, per the per-field checkboxes in Section 2); the first captured variant's values become the defaults. Every other captured variant is preserved as a **saved example**, not discarded.

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

**Request editor:** an `[Examples ▾]` dropdown appears next to Send, rendered only when `api_request_examples` rows exist for the request. Selecting one:
1. Fills the Params/Body tabs with that example's captured values (URL, headers, and auth are not templated and stay untouched).
2. Switches the existing response panel (`web/static/api/components/response-panel.js`, same Body/Headers/Assertions/Variables tabs used for live results) into a read-only "captured" mode: a banner pill (`⚠ Captured example · not live · <relative time>`) replaces the live status pill, and the panel shows that example's stored `response_status`/`response_headers`/`response_body` — not re-fetched.
3. Hitting Send always fires a real request as normal; the response panel drops the banner and shows the fresh live result.
4. The dropdown's top entry, "Default values", reverts Params/Body to the merged request's own stored defaults and clears the banner.

No new panel or tab is introduced — this reuses the response panel's existing structure with a mode flag, so live-result and captured-example display share one code path.

**Merged request's own schema:** `request_schema`/`response_schema` columns on the merged `api_requests` row are populated via the existing `merge_schemas()` (`cli/api_discovery/schema_merger.py`) across all variants — same mechanism already used by the API Docs feature, applied here to the merge choice instead of doc generation.

---

## Section 5: Backend Contract

**Flow path** — `/discover/save-requests` (existing route in `web/api/routes/discovery.py`, backed by `discovery_service._save_requests`) is unchanged. This is the only endpoint the "Save as Flow" button ever calls.

**Library path** — two new endpoints, matching the two-modal flow in Section 1:

1. `POST /discover/group-requests` — body: the checked requests from Modal 1. Server runs `normalize_url()` grouping, strips ignore-list headers, collapses exact dups, diffs remaining fields per group, and returns the grouped structure (groups, variants, auto-suggested names, default merge/separate per group, default checked/unchecked state per diff field). Nothing is persisted — this call is pure preview, rendering Modal 2.
2. `POST /discover/save-library` — body: the resolved per-group choices from Modal 2 (separate vs merge per group, which fields stayed literal, any per-row drops). Server writes plain `api_requests` rows for "separate" groups, and for "merge" groups: one `api_requests` row with `{{var}}` placeholders in the checked fields plus `merge_schemas()`-derived `request_schema`/`response_schema` across all variants (Section 4), and one `api_request_examples` row per non-default variant.

No CLI command changes — this is Discovery UI/service-layer behavior only, triggered from the web UI's save screen.

---

## Out of Scope (This Version)

- Editing an example after it's saved (examples are captured snapshots; edit the parent request instead)
- Auto-detecting variants across separate Discovery sessions (grouping only considers requests captured/imported together, in one save action)
- Mock server responses driven by examples (Postman's mock-matching-by-example is not in scope)
- Running a request once per saved example during a collection run (data-driven replay). The data model already supports this — examples store full params/body/response — so it's a runner-loop addition later with no migration needed. Revisit as a fast-follow once the save/merge UX ships and real usage shows whether it's worth it.

## Open Questions

None — all decisions made above.
