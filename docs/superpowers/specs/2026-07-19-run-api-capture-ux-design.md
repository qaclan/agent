# Run-level API capture: save, UX, and filter parity

## Problem

Web-automation script runs passively capture XHR/fetch traffic per script
(`docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md`), shown
today as a collapsed "Captured Requests" accordion under each
`.script-result-card` in the run-results modal (`web/static/app.js:4336-4378`),
with a "Save Selected" button per script that creates one new collection per
script (`saveCapturedRequests()` → `showRequestReviewModal` →
`POST /api/discover/save-requests`, `web/api/routes/discovery.py:119`).

Three problems with this:

1. **Fragmented saves.** A run with 5 scripts that each capture requests
   produces up to 5 separate collections, when conceptually they all belong
   to one run.
2. **UX noise.** The run-results modal's primary job is showing pass/fail.
   Today, every script with captured requests grows an extra accordion,
   competing with the pass/fail signal for attention.
3. **No unsaved-work warning.** Captured requests exist only in-memory on
   the fresh `execute_run()` response — closing the modal without saving
   loses them silently, with no confirmation.

Separately, a fourth, related problem: the capture-time filter that decides
which requests are worth keeping has drifted out of sync with discovery's
equivalent filter (`cli/api_discovery/har_parser.py`), and is duplicated
across 4 harness files.

## Goal

1. Captured requests are still shown **per script** (so the user can see
   which script produced what), but **saved as one collection per run**.
2. The run-results modal surfaces captured requests as a single
   header-level summary, not per-script accordions — pass/fail stays the
   visual focus.
3. Closing the run-results modal with unsaved captured requests prompts a
   confirmation, using the repo's existing in-app dialog convention.
4. The script-capture filter is unified with discovery's filter model
   (allowlist + static-content heuristics), with a single source of truth
   for the allowed resource types.

## A. Save flow: one collection per run

- Remove the per-script "Save Selected" button. Add one "Save Captured
  Requests" action at the run level (in the new header summary, see
  Section B).
- Clicking it opens a review panel listing every captured request across
  all scripts in the run, **grouped by originating script name**, each with
  its own checkbox (default checked) — this replaces the per-script
  accordions as the place where requests are actually reviewed/selected.
- No deduplication. If two scripts hit the same endpoint, both occurrences
  are listed and both get saved if selected — full run fidelity.
- Save dialog lets the user either:
  - type a name to create a new collection, or
  - pick an existing collection (via `GET /api/collections`) to append
    into.
- Backend: `POST /api/discover/save-requests`
  (`web/api/routes/discovery.py:119`) gains an optional `collection_id`
  field. When present, skip `CollectionRepo().create()` and call
  `_save_requests(pid, requests_list, collection_id=collection_id)`
  directly against the existing collection; `collection_vars`/
  `collection_auth` extras still apply the same way. When absent, behavior
  is unchanged (creates a new collection from `collection_name`).
- Frontend: extend the existing shared `request-review-modal.js`
  (already used for HAR/Postman/Bruno import) with a "group by script"
  rendering mode and an existing-collection picker, rather than building a
  parallel component.

## B. Run-modal UX: header-level summary

- Remove `capturedRequestsBlock` from each `.script-result-card`
  (`web/static/app.js:4336-4378`).
- Add one line near the `.stats-row` at the top of the run-results modal,
  shown only when the run has captured requests:
  - Fresh run (`s.captured_requests` present on at least one script item):
    `"N API requests captured · Save as collection"` — clicking opens the
    run-level review panel from Section A.
  - Historical/reopened run (only `captured_requests_count` columns
    available, per-request data never persisted —
    `web/routes/runs.py:144-189` only selects the count): keep today's
    existing behavior, a plain non-interactive
    `"Captured N requests during this run (not saved)"` text — there is no
    data to review or save.
- Per-script `.script-result-card`s keep no captured-request UI of their
  own; the grouping-by-script happens only inside the review panel opened
  from the header summary.

## C. Close-confirm for unsaved captures

- The repo's established convention for "you'll lose something" gates is
  an in-app confirm dialog (`window._confirmDialog()`,
  `web/static/api/api-section.js:98-99`), not a native `beforeunload`
  guard — there is no native guard anywhere in this repo, and this feature
  doesn't introduce one.
- `closeModal()` (`web/static/app.js:583`) is shared across every modal in
  the app (X button, backdrop click, and any "Close" footer button all
  call it). To scope the guard to just the run-results modal without
  touching other call sites: when the run-results modal opens with
  unsaved captured requests, it sets a module-level guard callback (e.g.
  `window._modalCloseGuard`); `closeModal()` checks it first and, if set,
  awaits `window._confirmDialog("You have N unsaved captured API
  requests — close anyway?", ...)` before proceeding. The guard is cleared
  when: the run-results modal's own save action completes successfully, or
  the user confirms closing anyway, or the modal closes via any path.
  Opening any other modal in the meantime is unaffected since the guard is
  only checked, never assumed present.

## D. Filter parity

**Current state:** the harness-side filter is a 5-type blocklist
(`_CAPTURE_SKIP_TYPES = {"document", "stylesheet", "image", "font",
"script"}`), duplicated identically in `python_strategy.py:129`,
`javascript_strategy.py:64`, `javascript_test_strategy.py`, and
`typescript_test_strategy.py`. Discovery's filter
(`cli/api_discovery/har_parser.py`) is an allowlist (`resourceType in
{"xhr", "fetch"}`) with a heuristic fallback (`_is_static()`: content-type,
static extensions, static/beacon paths) used only when `_resourceType` is
absent. The script-capture path bypasses that heuristic entirely today by
hardcoding `"_resourceType": "fetch"` in the synthetic HAR entry it builds
(`cli/api_discovery/captured_request_parser.py`), so requests like
`fetch('/static/config.json')` or a lazy-loaded JS chunk pass through
uncaught in both paths.

**Fix — two stages:**

1. **Harness-side coarse filter (bounds memory/volume, unchanged
   mechanism, corrected content):** add one canonical tuple to
   `cli/script_strategies/_shared.py`:

   ```python
   # Resource types kept during capture-run request recording. Matches
   # discovery's live-record filter (cli/api_discovery/har_parser.py
   # _API_RESOURCE_TYPES) — allowlist, not blocklist, so unknown/future
   # Playwright resource types are excluded by default.
   CAPTURE_ALLOWED_RESOURCE_TYPES = ("xhr", "fetch")
   ```

   Each of the 4 harness templates (`_HARNESS_TEMPLATE` string constants in
   `python_strategy.py`, `javascript_strategy.py`,
   `javascript_test_strategy.py`, `typescript_test_strategy.py`) gains a new
   `{CAPTURE_ALLOWED_TYPES_JSON}` placeholder, filled at render time via the
   same `.replace()` mechanism already used for `{ACTIONS}`
   (`python_strategy.py:558`):

   ```python
   rendered = rendered.replace(
       "{CAPTURE_ALLOWED_TYPES_JSON}",
       json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES)),
   )
   ```

   `json.dumps(["xhr", "fetch"])` is valid literal syntax in both Python
   (`set([...])`) and JS (`new Set([...])`), so the same substitution call
   works for all 4 templates. The per-request check flips from "skip if in
   blocklist" to "keep only if in allowlist" (e.g.
   `python_strategy.py`'s `_capture_request()`:
   `if req.resource_type not in _CAPTURE_ALLOWED_TYPES: return`). This
   still filters at capture time, before the `_CAPTURE_CAP = 200` limit, so
   memory/volume stays bounded exactly as today.

2. **Parser-side heuristic second pass (catches static content mislabeled
   as fetch/xhr):** in `cli/api_discovery/captured_request_parser.py`,
   `_to_har_entry()` stops hardcoding `"_resourceType": "fetch"` — it
   simply omits the field. With no `_resourceType` on the synthetic entry,
   `parse_har()`'s existing `_should_skip()` (in `har_parser.py`, entirely
   unchanged) falls through to its real `_is_static()` heuristic branch for
   every captured entry — the same extension/path/content-type checks
   discovery already applies to third-party HAR imports. This is pure
   reuse: no new filtering logic is written, no changes to `har_parser.py`
   itself. Since stage 1 already guarantees only `xhr`/`fetch`-typed
   entries reach this point, stage 2 is strictly a refinement on top, not a
   replacement.

Net result: one canonical resource-type tuple, two-stage filtering (cheap
type allowlist at capture time, heuristic content check at parse time),
and the script-capture path can no longer drift from discovery's filter
without both stages being touched deliberately.

## Data flow (save action)

```
run finishes → each script's harness emits captured_requests (already
  filtered to xhr/fetch by the stage-1 harness allowlist, Section D)
  → runs.py calls parse_captured_requests() per script (defined in
    captured_request_parser.py; stage-2 heuristic filter applies here,
    now that _resourceType is no longer faked)
  → execute_run() response carries captured_requests per script-result item
  → run-results modal renders header summary: "N requests captured"
  → user clicks it → review panel opens, grouped by script, all selected
  → user (optionally) deselects some, names/picks a collection, saves
  → POST /api/discover/save-requests {requests, collection_name |
    collection_id, ...} → one collection now holds every selected request
    from every script in the run
```

## Error handling

- Save with zero requests selected: existing `save_requests()` 400
  behavior (`"No requests provided"`) is unchanged — the review panel's
  save button should be disabled when the selection is empty, mirroring
  today's per-script UX.
- Picking an existing collection that has since been deleted mid-session:
  `_save_requests(..., collection_id=<stale id>)` fails at the DB layer;
  surface the existing error response inline in the panel, do not silently
  fall back to creating a new collection.
- Close-confirm guard: if the user confirms "close anyway," captured
  requests are discarded exactly as today (they were never persisted
  beyond the in-memory response) — no new data-loss behavior, just a
  warning where none existed before.

## Testing

No automated test suite in this repo (per `CLAUDE.md`). Manual
verification:

1. Run a suite with 2+ scripts that each capture requests; confirm the
   run-results modal shows one header-level summary (not per-script
   accordions) with the correct total count.
2. Open the review panel; confirm requests are grouped by script name, all
   checked by default, and duplicate endpoints from different scripts both
   appear (no dedup).
3. Save with a new collection name; confirm one collection is created
   containing all selected requests. Repeat, picking an existing
   collection instead; confirm requests append into it without creating a
   duplicate collection.
4. Close the run-results modal with unsaved captures present; confirm the
   confirm dialog appears and blocks the close until answered. Save first,
   then close; confirm no dialog appears.
5. Record/run a script that calls `fetch()` against a static path (e.g.
   `/static/config.json`) or triggers a lazy-loaded JS chunk; confirm it
   is filtered out of `captured_requests` (stage 2 heuristic), while a
   real API `fetch()` call to a JSON endpoint is still captured.
6. Confirm a script whose harness only does document/stylesheet/image/
   font/script/manifest/media/websocket/other-typed requests captures
   nothing (stage 1 allowlist covers types beyond the old 5-type
   blocklist, e.g. `manifest`/`media`/`websocket`/`other`).

## Explicitly not doing

- No dedup of identical requests across scripts in a run — full fidelity,
  every occurrence saved if selected.
- No native `beforeunload`/browser-level close guard — in-app modal-close
  confirm only, matching existing repo convention.
- No persistence of full captured-request bodies to the DB for historical
  runs — `captured_requests_count` remains the only persisted signal for a
  reopened run; this spec doesn't change that limitation.
- No changes to `har_parser.py`'s `_should_skip()`/`_is_static()` logic
  itself — reused as-is, not modified, not duplicated.
