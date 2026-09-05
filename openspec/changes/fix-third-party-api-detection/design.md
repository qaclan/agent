## Context

See proposal.md - Why/What Changes for the bug and its cause.

Relevant existing code:
- `web/routes/runs.py::execute_run` already fetches `sc.start_url_value` per suite item at query time (line ~304), keeps it in scope through the whole per-script execution loop, and uses it for URL-placeholder resolution — but the three `script_results.append(...)` blocks (python/js/ts branches) never copy it into the JSON returned to the frontend.
- `web/static/app.js::showRunResults` flattens each script's `captured_requests` into `window._runCapturedRequests`, tagging each item with `_scriptName` only (`app.js:4403`).
- `web/static/app.js::reviewRunCapturedRequests` calls `showRequestReviewModal(requests, 'Recorded APIs', requests[0].url, ...)` — using the first captured item's own URL as the reference "start URL," which is arbitrary (network completion order, not navigation order — capture is XHR/fetch only, the page's own navigation request is never captured).
- `web/static/api/views/request-review-modal.js` derives one `startRootDomain` from that `startUrl` param and applies it to every row via `_rootDomain()` compares (`thirdPartyCount`, `_visible()`, per-row `isThirdParty`).
- `record-apis-view.js` (the separate live-record → review flow) already passes the correct recorded URL as `startUrl` and is unaffected — it's always single-script, so the existing single global value happens to be correct there.

## Goals / Non-Goals

**Goals:**
- Make "main" vs "third-party" classification deterministic and correct for both single-script and multi-script (suite) review, sourced from data already captured at record time.
- Do it without any new database column, migration, or query — the value already exists and is already fetched.

**Non-Goals:**
- Not changing the registrable-domain algorithm (`_rootDomain` / `COMPOUND_SUFFIXES` in `request-review-modal.js`) — it's adequate for this fix; overhauling it (e.g. full public-suffix-list support) is a separate concern.
- Not touching the HAR/cURL/Postman/OpenAPI/Bruno import review paths — none of them pass a per-request script reference today and none of them exhibited this bug (they either have no "third-party" concept or are already single-source).
- Not changing what counts as "captured" (still XHR/fetch only, per `CAPTURE_ALLOWED_RESOURCE_TYPES`).

## Decisions

**Compare each request against its own owning script's start URL, not a single shared value.**
Considered a "majority root domain across all captured requests" heuristic instead (probabilistic, no schema/plumbing change). Rejected: non-deterministic across runs (depends on click path / how many times each API happens to be called), and still wrong whenever third-party calls outnumber first-party ones — a correctness bug traded for a subtler correctness bug. Per-request/per-script comparison is exact and free once the start URL is threaded through, so there's no reason to accept a heuristic.

**Thread `start_url_value` through the existing per-script result object instead of adding a lookup.**
The value is already in scope inside `execute_run`'s per-script branches; adding one field to an existing dict literal (×3 call sites, one per language branch) is simpler and cheaper than having the frontend fetch script metadata separately or the backend do a second query.

**Attach the start URL to each flattened captured-request item (`_scriptStartUrl`) rather than keeping a separate script→URL map in the frontend.**
Mirrors the existing `_scriptName` tagging already done at the same call site (`app.js:4403`), so the review modal's per-row logic stays a simple per-item field read with no auxiliary lookup structure.

**When a script has no start URL, that script's requests are never flagged third-party (fail open, per-script).**
Matches today's existing top-level behavior (`!startRootDomain` short-circuits classification entirely). Scoping the fallback to the owning script only (instead of disabling classification for the whole reviewed list) preserves correct classification for other scripts in the same suite that do have a start URL.

## Risks / Trade-offs

- [Older/cached suite-run responses in the frontend (e.g. an already-open run-results panel from before this change) won't carry `start_url_value` yet] → Frontend falls back to the current `requests[0].url` behavior only when `_scriptStartUrl` is absent on a given item, so a stale response degrades to today's behavior rather than breaking.
- [Registrable-domain heuristic (`_rootDomain`) is a small hardcoded compound-suffix list, not a full public suffix list] → Unchanged by this fix; pre-existing limitation, out of scope here.

## Migration Plan

Backend and frontend land together (same PR/change) since the frontend read depends on the new response field; no separate rollout phases, no data migration (no schema change). No feature flag needed — purely a correctness fix to an existing review-only UI, safe to ship directly.
