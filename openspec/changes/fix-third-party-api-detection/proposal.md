## Why

Reviewing captured API requests (Run a script/suite with "Capture API Requests" → "Save as collection") labels main vs. third-party APIs using the wrong reference point: the first *captured* request's domain, not the domain the script was actually recorded/run against. Real-world traffic order is not guaranteed to put the tested app's own API first — a page that loads a Maps widget, analytics, or any other third-party script before its own backend call gets its classification inverted: the real API is flagged "third-party" and the actual third-party call is treated as "main." In suites with multiple scripts recorded against different base URLs, a single shared reference point additionally mis-classifies every request belonging to any script other than whichever one happens first in the list.

## What Changes

- Classification of a captured request as "main" vs. "third-party" is sourced from the owning script's recorded `start_url_value` (captured once at codegen time, already stored on the `scripts` table) instead of the first item in the captured-requests list.
- Classification is evaluated per request against its *own* owning script's start URL, not one shared value for the whole review modal — so a suite mixing scripts recorded against different domains classifies each script's own API as "main" for that script, regardless of run/capture order or which script's requests appear first.
- The run-execution response already looks up `start_url_value` per script (for URL-placeholder resolution) but never returns it to the frontend; it now includes that field in each script's result payload so the review UI has it without any new query.

## Capabilities

### New Capabilities
- `captured-api-classification`: Defines how a captured API request is classified as "main" (same site as the recording script) vs. "third-party" (different site) when reviewing captured requests before saving them as a collection.

### Modified Capabilities
(none — no existing spec covers captured-request review/classification)

## Impact

- `web/routes/runs.py` — the three per-language `script_results.append(...)` blocks in `execute_run` gain a `start_url_value` field, reusing the `item` row already fetched via the existing `suite_items` ⨝ `scripts` query (no new SQL).
- `web/static/app.js` — `showRunResults` carries each script's `start_url_value` onto its flattened captured requests (alongside the existing `_scriptName` tag) before handing them to the review modal.
- `web/static/api/views/request-review-modal.js` — the main/third-party comparison (`_rootDomain` check used by `thirdPartyCount`, `_visible()`, and the per-row `isThirdParty` flag) compares each request's hostname against its own request's start URL instead of a single hoisted `startRootDomain` derived from `requests[0].url`.
- No database schema or migration change — `scripts.start_url_key` / `scripts.start_url_value` already exist and are already queried by `execute_run`.
- No change to the Record-APIs-mode review path (`record-apis-view.js`), which already passes the correct recorded start URL and is single-script only.
