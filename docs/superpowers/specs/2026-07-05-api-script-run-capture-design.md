# API Script-Run Capture — Design Spec
Date: 2026-07-05

> **Revision 2026-07-17:** Reversed the original "always on, no opt-in" decision below after review flagged two risks: (1) every script run — including pure UI-automation scripts with no interest in API capture — would pay redaction/DB-write overhead unconditionally, and (2) response bodies had no size cap, only an entry-count cap, so a single large payload could bloat `script_runs.captured_requests` and slow the run-detail page for unrelated scripts. Capture is now opt-in per run, off by default. See the updated Decisions table and new Section 0.

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

---

## Section 0: Opt-In Control

**UI:** a "Capture API Requests" checkbox on the suite-run modal (`web/static/app.js`, alongside the existing "Headless" / "Stop on first failure" checkboxes), unchecked by default. Not added to the solo-run quick action (`▶ Run Script`) — that path has no options UI today (browser/resolution/headless are all hardcoded there too), so adding one checkbox just for this would be new scope; a 1-item suite run covers the ad hoc case.

**Wire-through:** the checkbox value is posted as `capture_requests: bool` to `POST /api/runs` (`web/routes/runs.py:execute_run`) exactly like `headless` is today, persisted on `suite_runs.capture_requests` (new column, same pattern as the existing `suite_runs.headless`), and passed to each script's subprocess as `child_env["QACLAN_CAPTURE_REQUESTS"] = "1" if capture_requests else "0"` — same mechanism as `QACLAN_HEADLESS`.

**Harness gating:** each of the 4 strategy templates reads `QACLAN_CAPTURE_REQUESTS` once at startup into `_CAPTURE_ENABLED`. When falsy, `_capture_request`/`_captureRequest` returns immediately as its first statement — before the resource-type check, before touching `_capture_starts`, before any `resp.text()` read. This is a real skip, not just a UI hide: a script run with capture off does none of the extra work (no per-request header dict copy, no response-body read, no redaction pass, no DB write to the two new columns beyond `NULL`/`0`).

**Second call site:** `web/routes/scripts.py:run_script_solo` inlines its own copy of the run logic (it does not call `execute_run` internally) and independently sets `child_env["QACLAN_HEADLESS"]`. Per the decision above it hardcodes `child_env["QACLAN_CAPTURE_REQUESTS"] = "0"` rather than exposing a param — but this is the one existing call site besides `execute_run` that touches `child_env`, and any future change to the capture env var name/protocol must update both.

---

## Section 1: Harness Capture

`cli/script_strategies/{python,javascript,javascript_test,typescript}_strategy.py` each already register `_track_network(page)` handlers that count in-flight requests for smart-wait. Extend these handlers to additionally record, per request:

- method, URL
- request headers, request body (if present and decodable)
- response status, response headers, response body
- `duration_ms` (time between request start and finish/fail)

**Filtering:** skip `resourceType` in `document`, `stylesheet`, `image`, `font`, `script` — same "static assets hidden by default" convention already used by the other three discovery paths (Record APIs mode, HAR import, OpenAPI import).

**Cap:** stop recording new entries past 200 captured requests per run (guards against unbounded memory growth on long-running suites). Entries past the cap are silently dropped — not an error, not surfaced to the user as a warning in this version. Independently, each entry's `request_body`/`response_body` is truncated at 200KB — guards against a single large payload (report download, big JSON) bloating the artifacts file and the `script_runs.captured_requests` DB column; truncation is also silent, matching the count cap's convention.

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

New **"Captured Requests"** tab on the run detail page, alongside existing Steps/Screenshots tabs. Absent entirely (not shown empty) when the run had capture off, same as when a captured run made zero XHR/fetch calls — both cases mean `s.captured_requests` is empty/null.

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

- Static assets hidden by default (already filtered out at capture time — this list only ever contains XHR/fetch calls).
- Sensitive-looking values (keys matching `password`, `token`, `secret`, `authorization`) auto-replaced with `{{var_name}}` placeholders before display — same redaction logic as the other three discovery paths.
- **[Save Selected]** opens the shared Discovery save screen (see `2026-07-05-api-variant-library-design.md`) — same Save as Flow / Save as Library choice used by every discovery path.

---

## Out of Scope (This Version)

- Surfacing a warning when the 200-entry cap or the 200KB per-body cap is hit
- Capturing WebSocket traffic
- Capturing calls made by concurrent/background pages beyond the primary tab
- A capture toggle on the solo-run quick action (no options UI exists there at all today; use a 1-item suite run)
- Remembering the checkbox state per-suite (it resets to unchecked each time the run modal opens)

## Open Questions

None — all decisions made above.
