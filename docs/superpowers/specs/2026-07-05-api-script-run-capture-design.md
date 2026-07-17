# API Script-Run Capture — Design Spec
Date: 2026-07-05

> **Revision 2026-07-17:** Reversed the original "always on, no opt-in" decision below after review flagged two risks: (1) every script run — including pure UI-automation scripts with no interest in API capture — would pay redaction/DB-write overhead unconditionally, and (2) response bodies had no size cap, only an entry-count cap, so a single large payload could bloat `script_runs.captured_requests` and slow the run-detail page for unrelated scripts. Capture is now opt-in per run, off by default. See the updated Decisions table and new Section 0.
>
> **Revision 2026-07-17 (2):** Further reversed the "persist the raw redacted array to `script_runs.captured_requests`" decision after a second review raised: (a) most captures are never saved — persisting the full array by default means paying DB storage for data nobody wanted, indefinitely; (b) a raw array that sits in the DB for days/weeks before a user gets around to reviewing it risks going stale relative to the live API, with no signal to the user that it's aged. The raw array is now **never persisted** — it only ever exists in the immediate run-response payload (in the browser's memory, for that page view) and, if the user acts on it, in whatever it gets saved as (`api_requests`/`api_collections`, via the existing unchanged save flow). Only a count persists to the DB. See the rewritten Section 0.5 and updated Section 2.

## Problem

The original API testing design (`2026-06-19-api-testing-design.md`, Section 5, Path 2) describes "Capture from Playwright Run" as passive discovery: every script run should record the XHR/fetch calls the browser made, so users can save them as API requests afterward without touching DevTools or HAR files. This was spec'd but never implemented — no `captured_requests.json` is written today, and there's no "Captured Requests" tab on the run detail page.

This is distinct from Playwright codegen (`cli/commands/web/record.py`), which wraps an external `playwright codegen` subprocess QAClan has no listener hooks into — request capture is not possible during live recording. It only becomes possible once a script is saved and actually **run** through QAClan's own generated harness, which QAClan controls.

## Decisions

| Question | Decision |
|---|---|
| Where does capture happen | During a suite run, when opted in (see Section 0) — not during codegen recording |
| New API calls triggered | None — capture only observes calls the browser makes as a side effect of normal script execution |
| Capture mechanism | Extend the harness's existing `page.on("request"/"requestfinished"/"requestfailed")` handlers (currently used only for smart-wait network settling) |
| Trigger | **Opt-in per run**, off by default. A "Capture API Requests" checkbox on the suite-run modal; unchecked, the harness does zero capture work. Solo script run (the ▶ Run Script quick action, which has no options UI at all today) always runs with capture off — use a 1-item suite run to capture ad hoc. |
| Failure handling | A capture failure on one request is swallowed; never fails the run |
| Body size | Each `request_body`/`response_body` is truncated at 200KB (`_CAPTURE_BODY_CAP_BYTES`), independent of the 200-entry count cap. Truncation is silent — same "no warning surfaced" convention as the count cap. |
| Persistence | The redacted array is **never written to the DB**. Only `script_runs.captured_requests_count` (an int) persists. The full array lives solely in that run's immediate HTTP response — the run-detail page you land on right after clicking "Run Suite" — and survives only as long as the browser holds that response in memory. Reloading the page, or opening the run later from run history, shows the count but not the list. See Section 0.5. |

---

## Section 0: Opt-In Control

**UI:** a "Capture API Requests" checkbox on the suite-run modal (`web/static/app.js`, alongside the existing "Headless" / "Stop on first failure" checkboxes), unchecked by default. Not added to the solo-run quick action (`▶ Run Script`) — that path has no options UI today (browser/resolution/headless are all hardcoded there too), so adding one checkbox just for this would be new scope; a 1-item suite run covers the ad hoc case.

**Wire-through:** the checkbox value is posted as `capture_requests: bool` to `POST /api/runs` (`web/routes/runs.py:execute_run`) exactly like `headless` is today, persisted on `suite_runs.capture_requests` (new column, same pattern as the existing `suite_runs.headless`), and passed to each script's subprocess as `child_env["QACLAN_CAPTURE_REQUESTS"] = "1" if capture_requests else "0"` — same mechanism as `QACLAN_HEADLESS`.

**Harness gating:** each of the 4 strategy templates reads `QACLAN_CAPTURE_REQUESTS` once at startup into `_CAPTURE_ENABLED`. When falsy, `_capture_request`/`_captureRequest` returns immediately as its first statement — before the resource-type check, before touching `_capture_starts`, before any `resp.text()` read. This is a real skip, not just a UI hide: a script run with capture off does none of the extra work (no per-request header dict copy, no response-body read, no redaction pass, no DB write to the two new columns beyond `NULL`/`0`).

**Second call site:** `web/routes/scripts.py:run_script_solo` inlines its own copy of the run logic (it does not call `execute_run` internally) and independently sets `child_env["QACLAN_HEADLESS"]`. Per the decision above it hardcodes `child_env["QACLAN_CAPTURE_REQUESTS"] = "0"` rather than exposing a param — but this is the one existing call site besides `execute_run` that touches `child_env`, and any future change to the capture env var name/protocol must update both.

---

## Section 0.5: Persistence Model — count in the DB, array in the response only

**What persists:** `script_runs.captured_requests_count` (INTEGER, default 0) — always, whenever capture was on, regardless of whether the user ever looks at or saves anything. Cheap, no staleness concern (it's a number, not a claim about live data), gives run history a "captured 5 requests" fact even for runs nobody revisits.

**What doesn't persist:** the redacted request/response array itself. `web/routes/runs.py:execute_run` still runs it through `parse_captured_requests()` (Section 1/Task 2 — redaction, header/param splitting, schema inference all still happen, same as before) but the result only goes into that call's own JSON response (`script_results[].captured_requests`), never into an `INSERT`. `get_run()` (the endpoint behind revisiting a run from run history) only ever returns the count column — it has nothing else to return, because nothing else was written.

**Why:** two problems this avoids —
1. **Storage for unwanted data.** Most captures are never saved as a collection/library entry. Persisting the full array by default means every capture-on run pays DB storage for data the majority of the time nobody asked to keep.
2. **Silent staleness.** A raw array sitting in the DB for days before someone gets around to it can no longer be trusted to reflect the live API, with nothing in the UI signaling that risk. Not persisting it removes the class of problem rather than trying to label it.

**What this means for the UI (see Section 2):** the interactive "Captured Requests" list with checkboxes and "Save Selected" only ever renders on the page the user lands on immediately after the run finishes (or immediately after clicking into a run whose response is still the one just returned — i.e. the same page load, not a later revisit). Reloading that page, or opening the same run later from run history, shows a static "Captured N requests during this run (not saved)" line instead — informational only, no picker, because the underlying array is gone.

**Save Selected, mechanically:** the frontend already holds the full redacted array client-side (it came in on that same response) — "Save Selected" hands the checked subset directly to the existing `/discover/save-requests` / `/discover/group-requests` / `/discover/save-library` routes exactly as every other Discovery path already does (`save_requests()`'s own docstring: "Save pre-parsed request objects directly (no re-parsing)"). No re-fetch from the server, no new save endpoint, no reference back to the harness's `artifacts.json` (which is deleted by `_cleanup_run_dir()` right after the run finishes regardless — this was always true, capture or not).

---

## Section 1: Harness Capture

`cli/script_strategies/{python,javascript,javascript_test,typescript}_strategy.py` each already register `_track_network(page)` handlers that count in-flight requests for smart-wait. Extend these handlers to additionally record, per request:

- method, URL
- request headers, request body (if present and decodable)
- response status, response headers, response body
- `duration_ms` (time between request start and finish/fail)

**Filtering:** skip `resourceType` in `document`, `stylesheet`, `image`, `font`, `script` — same "static assets hidden by default" convention already used by the other three discovery paths (Record APIs mode, HAR import, OpenAPI import).

**Cap:** stop recording new entries past 200 captured requests per run (guards against unbounded memory growth on long-running suites). Entries past the cap are silently dropped — not an error, not surfaced to the user as a warning in this version. Independently, each entry's `request_body`/`response_body` is truncated at 200KB — guards against a single large payload (report download, big JSON) bloating the artifacts file and the in-memory response; truncation is also silent, matching the count cap's convention.

**Gating:** none of the above runs unless `QACLAN_CAPTURE_REQUESTS=1` is set (see Section 0) — when unset/`0`, `_track_network`/`_trackNetwork` still installs its smart-wait handlers (that part is unrelated and always on) but the capture-specific branch is skipped before any per-request work happens.

**Output:** accumulated list written to `captured_requests.json` in the run's existing artifacts directory (same directory as trace files and screenshots) when the run finishes — success, failure, or error.

```json
[
  {
    "method": "POST",
    "url": "https://staging.app.com/api/auth/login",
    "request_headers": {"Content-Type": "application/json"},
    "request_body": "{\"email\":\"test@x.com\",\"password\":\"secret\"}",
    "status_code": 200,
    "response_headers": {"Content-Type": "application/json"},
    "response_body": "{\"token\":\"eyJ...\"}",
    "duration_ms": 142
  }
]
```

This matches the shape already described in the original spec's Path 2 section.

---

## Section 2: Run Detail UI

New **"Captured Requests"** section on the run-detail card, alongside the existing Diagnostics toggle. Two render states, both driven by what the current response actually contains (see Section 0.5):

**Fresh (this response carries the full array — right after the run finished, or you clicked into a run whose response is still on screen):**

```
Captured from: login-flow.py  (run 2 minutes ago)
┌──────────────────────────────────────────────────────┐
│ ☑  POST  /api/auth/login          200   142ms        │
│ ☑  GET   /api/users/me            200    89ms        │
│ ☐  GET   /static/icons/logo.svg   200     3ms        │  ← static asset, skip
├──────────────────────────────────────────────────────┤
│                          [Save Selected] │
└──────────────────────────────────────────────────────┘
```

**Historical (revisited later from run history — only the count survived):**

```
Captured from: login-flow.py  (run 3 days ago)
  Captured 5 requests during this run (not saved)
```
No checkboxes, no Save Selected — the array that would back them was never persisted.

**Absent entirely** — not shown at all, neither state — when the run had capture off, or a captured run made zero XHR/fetch calls. Both mean count is 0.

- Static assets hidden by default (already filtered out at capture time — this list only ever contains XHR/fetch calls).
- Sensitive-looking values (keys matching `password`, `token`, `secret`, `authorization`) auto-replaced with `{{var_name}}` placeholders before display — same redaction logic as the other three discovery paths.
- **[Save Selected]** (fresh state only) opens the shared Discovery save screen (see `2026-07-05-api-variant-library-design.md`) — same Save as Flow / Save as Library choice used by every discovery path — passing the already-in-memory selected array directly, no server round-trip to fetch it first.

---

## Out of Scope (This Version)

- Surfacing a warning when the 200-entry cap or the 200KB per-body cap is hit
- Capturing WebSocket traffic
- Capturing calls made by concurrent/background pages beyond the primary tab
- A capture toggle on the solo-run quick action (no options UI exists there at all today; use a 1-item suite run)
- Remembering the checkbox state per-suite (it resets to unchecked each time the run modal opens)

## Open Questions

None — all decisions made above.
