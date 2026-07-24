# Request Body Multi-Format Storage — Design Spec
Date: 2026-07-24

## Problem

`api_requests` stores exactly one body slot: `body_type` (discriminator) + `body` (TEXT, whatever format `body_type` names). The request editor UI (`web/static/api/views/request-editor-view.js`) presents four independent body-format tabs — Raw, x-www-form-urlencoded, form-data/multipart, GraphQL — each with its own in-memory draft (`_rawValue`, `_formRows`, `_multipartRows`, `_gqlQuery`), so a user can type into one tab, switch to another, and come back without losing anything — but only the currently *active* tab's draft is ever persisted, into the single shared `body` column.

This produces three bugs, all downstream of the same root cause:

1. **Raw tab shows captured form-data/multipart content.** `_rawValue` is seeded unconditionally from `r.body` on load (`request-editor-view.js:635`), with no gate on `body_type` — unlike `_formRows`/`_multipartRows`/`_gqlQuery`, which *are* gated (lines 788-789, 815). Discovery (`cli/api_discovery/har_parser.py:313,329` and the other importers) writes form/multipart content into that same shared `body` column, so it leaks into Raw the moment the tab is opened.
2. **No real "two bodies" at the data layer** — the runner (`cli/api_runner.py:545-614`) reads exactly one column, chosen by `body_type`, so execution is never actually ambiguous. The *appearance* of ambiguity is a client-side illusion: multiple tab drafts coexist in memory, but saving silently discards every draft except the active one.
3. **Selecting "none" (or switching tabs) discards the other formats.** Because there is one storage slot, whichever type is active at save time wins and everything else is lost — on save, and again on refresh once the loss round-trips through the DB.

## Decision

Adopt Postman's model: the body object holds **all** modes' content simultaneously; `body_type`/`mode` only marks which one is active at send time. Switching modes, or picking "none", never destroys another mode's data.

| Question | Decision |
|---|---|
| Storage shape | 3 new columns (`body_form`, `body_multipart`, `body_graphql`) alongside the existing `body`. `body` becomes raw-only, forever. `body_type` keeps its existing role as pure mode-selector. |
| "None" behavior | Sets `body_type = NULL`. All 4 content columns keep their last saved value — nothing is cleared. Switching back to any prior type (even after a refresh) restores its content. |
| Existing captured requests (pre-fix) | One-time backfill migration relocates `body` into the correct new column for rows where `body_type` is form/multipart/graphql, then nulls `body` for those rows. Without this, already-captured requests keep leaking into Raw forever. |
| `api_request_examples` | Out of scope — it's an immutable point-in-time snapshot (no tabbed editing UI), single `body` column stays as-is. |
| Server (qaclan-server) | Mirrors the same 3-column split — it's the sync target for this same table. |
| Rollout order | Server migration + route support ships **first**, agent fix ships after. See "Rollout ordering" below. |

---

## Section 1: Data model (agent, SQLite)

```sql
ALTER TABLE api_requests ADD COLUMN body_form TEXT DEFAULT NULL;
ALTER TABLE api_requests ADD COLUMN body_multipart TEXT DEFAULT NULL;
ALTER TABLE api_requests ADD COLUMN body_graphql TEXT DEFAULT NULL;
```

New migration function in `cli/db.py` (same guarded-ALTER pattern as `_migrate_var_picker`/`_migrate_nested_folders` — check column existence via `PRAGMA table_info`, then `ALTER TABLE` if missing):

- Add the 3 columns.
- Backfill: `SELECT id, body_type, body FROM api_requests WHERE body_type IN ('form','multipart','graphql') AND body IS NOT NULL`. For each row, `UPDATE api_requests SET body_{type} = body, body = NULL WHERE id = ?` (mapping `form`→`body_form`, `multipart`→`body_multipart`, `graphql`→`body_graphql`).

Column contents are unchanged JSON shapes — just relocated:
- `body_form` / `body_multipart`: JSON array of `{key, value, enabled, ...}` rows (same as today's `body` for these types).
- `body_graphql`: JSON object `{query, variables}` (same shape `_setBodyValue`/`_syncGqlBodyTextarea` already produce).
- `body`: raw text only, from now on.

`_DEFAULTS` in `web/api/repositories/request_repo.py` gets 3 new `None` entries; `create()`/`update()` column lists extend to include them. No special `_serialize`/`_deserialize` handling needed — same as `body` today, these are stored pre-stringified by the frontend, not auto-JSON-encoded by the repo.

---

## Section 2: Frontend (`request-editor-view.js`)

**Load:** each draft seeds unconditionally from its own column — the `body_type` gating on `_formRows`/`_multipartRows`/`_gqlQuery` (lines 788-789, 815) becomes unconditional too, and `_rawValue = r.body || ''` (line 635) is now safe as unconditional, since `body` can no longer hold another type's content.

**Tab switching (`_setBodyType`):** unchanged — it already correctly flushes the outgoing tab's live DOM state into its cache var before switching (lines 905-908).

**Save (`_buildPayload`, ~line 1682):** flush the *currently active* tab's live DOM state into its cache (same flush `_setBodyType` does), then send all 4 fields every time, not just the active one:

```js
body_type: activeBodyType !== 'none' ? activeBodyType : null,
body: _rawValue || null,
body_form: JSON.stringify(activeBodyType === 'form' ? formBodyTable.getRows() : _formRows),
body_multipart: JSON.stringify(activeBodyType === 'multipart' ? multipartBodyTable.getRows() : _multipartRows),
body_graphql: JSON.stringify({ query: _gqlQuery, variables: _gqlLastValidVariables }),
```

`_rawValue` is already reliable regardless of which tab is currently active — it's updated on every keystroke by both the CM path (line 768) and the no-CM fallback path (lines 726, 755), and unlike `bodyTextarea.value` it is never clobbered by the graphql tab's continuous `_syncGqlBodyTextarea()` writes (the exact reason `_rawValue` exists as a private cache in the first place, per the comment at lines 631-634). So `body` can read `_rawValue` directly — no new helper needed.

No dedicated non-active-tab cache is needed for graphql: `_gqlQuery`/`_gqlLastValidVariables` are already module-level and are never reset when the user switches away from the graphql tab (`_setBodyType` only calls `_unmountGqlEditors()` for the outgoing graphql tab, line 908 — it doesn't touch the vars themselves), so they already hold the last-edited draft regardless of which tab is active. The seed-on-load gate at line 815 (`if (r.body_type === 'graphql')`) becomes unconditional, same as the other three drafts.

**None:** `body_type` goes `null`, but the other 3 payload fields still carry their last cached values, per the decision above — no special-casing needed, this falls out of "always send all 4" naturally.

---

## Section 3: Request execution (`cli/api_runner.py`)

Line ~545-546 changes from a single lookup to a per-type lookup:

```python
body_type = req.get("body_type")
_column = {"raw": "body", "form": "body_form", "multipart": "body_multipart", "graphql": "body_graphql"}.get(body_type)
body_raw = req.get(_column) if _column else None
```

Everything downstream (lines 551-614: `json.loads`, var resolution, httpx `data`/`files`/`content` construction) is unchanged — only the source column moves.

---

## Section 4: Discovery / import parsers

Same one-line-per-type fix in each — route content into the matching dedicated key instead of the shared `body`, leave `body` untouched (`None`) for non-raw types:

| File | Current | Change |
|---|---|---|
| `cli/api_discovery/har_parser.py` (~283-332, 384-400) | writes `body` for all types | write `body_form`/`body_multipart`/`body_graphql` per type; `body` only for the `"raw"` and bare-fallback branches |
| `cli/api_discovery/postman_parser.py` (~142-154) | same | same |
| `cli/api_discovery/curl_parser.py` (~184-207) | same | same |
| `cli/api_discovery/openapi_parser.py` (~82-175) | same | same |
| `cli/api_discovery/bruno_parser.py` (~193-247) | same | same |
| `cli/api_discovery/postman_exporter.py` (`_body_block`, ~55-68, 143) | reads `body` for all types | read the matching field per type |
| `cli/api_discovery/bruno_parser.py` (`_bru_body_block`, ~376-397, exporter side) | reads `body` for all types | read the matching field per type |
| `cli/api_discovery/variant_grouper.py` (`_body_signature`, ~33-45, and ~79-172) | reads `body` for all types | read the matching field per type |

Downstream call sites in `web/api/services/discovery_service.py` and `web/api/routes/discovery.py` that currently forward a parser's `{body_type, body}` pair into `RequestRepo.create()` need to forward all 4 fields instead.

---

## Section 5: Server (qaclan-server) — sync mirror

Same shape, since `cloud_api_requests` mirrors `api_requests` 1:1 for cloud sync/restore. Full detail in the companion spec at `qaclan-server/docs/2026-07-24-request-body-multi-format-storage-design.md` — summary:

- Alembic migration: 3 nullable Text columns on `cloud_api_requests`, same backfill.
- `CloudApiRequest` model + `to_dict()` (`api/app/models/cloud_metadata.py:330,367`): add the 3 fields.
- `POST /api-request` route (`api/app/routes/sync.py:729-730`): add 3 fields to the upsert dict.
- `GET /api/pull/workspace` needs no separate change — it calls `to_dict()`, which already picks up the new fields.
- `cli/sync.py` (agent's push side, ~line 323, 343): extend the SELECT and payload dict to include the 3 new fields — otherwise they're captured locally but never reach the cloud.
- Next.js docs viewer (`web/src/app/api-collections/[id]/requests/[requestId]/page.tsx:38-39,189-199`): Body tab reads the field matching `body_type` instead of always `request.body`.

### Rollout ordering

An **old CLI → new server** is safe: old CLI never sends the 3 new fields, server defaults them `NULL`, behavior unchanged.

A **new CLI → unmigrated server** is not: the new CLI would push `body: null` for form/multipart/graphql requests (since `body` is now raw-only), while an unmigrated server still only reads/displays `body` — existing cloud docs would show "No body" for those requests until the server catches up. So **the server migration and route change must be deployed before the new agent binary reaches users.**

---

## Section 6: Testing (manual — no automated test suite in this project)

- Capture a multipart request via discovery → Raw tab empty, Form-data tab populated.
- Fill Form-data rows + unrelated JSON in Raw tab, save, reload the editor → both persist independently, each in its own tab.
- Set Raw content → switch body type to "none" → save → refresh browser → switch back to Raw → content still present.
- Run a collection containing a multipart-body request after the change → still executes correctly (regression check on the `api_runner.py` dispatch change).
- Open a request captured *before* this fix, after the migration has run → confirm the backfill correctly relocated its content into the right tab and Raw is empty.
- Server: push a request with all 4 body fields populated (edge case — user filled raw + form + graphql across tabs before settling on one), then pull it back down (simulating a restore on a new machine) → all 4 fields round-trip via `/api/pull/workspace`.
- Server: POST to `/api-request` without the 3 new fields (simulating an old CLI binary) → still 200, unaffected.
