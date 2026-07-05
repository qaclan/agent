# API Script-Run Capture — Design Spec
Date: 2026-07-05

## Problem

The original API testing design (`2026-06-19-api-testing-design.md`, Section 5, Path 2) describes "Capture from Playwright Run" as passive discovery: every script run should record the XHR/fetch calls the browser made, so users can save them as API requests afterward without touching DevTools or HAR files. This was spec'd but never implemented — no `captured_requests.json` is written today, and there's no "Captured Requests" tab on the run detail page.

This is distinct from Playwright codegen (`cli/commands/web/record.py`), which wraps an external `playwright codegen` subprocess QAClan has no listener hooks into — request capture is not possible during live recording. It only becomes possible once a script is saved and actually **run** through QAClan's own generated harness, which QAClan controls.

## Decisions

| Question | Decision |
|---|---|
| Where does capture happen | During any script run (Run button or suite run) — not during codegen recording |
| New API calls triggered | None — capture only observes calls the browser makes as a side effect of normal script execution |
| Capture mechanism | Extend the harness's existing `page.on("request"/"requestfinished"/"requestfailed")` handlers (currently used only for smart-wait network settling) |
| Trigger | Always on, every run — matches "Passive. No extra steps" from the original spec. No CLI flag, no opt-in. |
| Failure handling | A capture failure on one request is swallowed; never fails the run |

---

## Section 1: Harness Capture

`cli/script_strategies/{python,javascript,javascript_test,typescript}_strategy.py` each already register `_track_network(page)` handlers that count in-flight requests for smart-wait. Extend these handlers to additionally record, per request:

- method, URL
- request headers, request body (if present and decodable)
- response status, response headers, response body
- `duration_ms` (time between request start and finish/fail)

**Filtering:** skip `resourceType` in `document`, `stylesheet`, `image`, `font`, `script` — same "static assets hidden by default" convention already used by the other three discovery paths (Record APIs mode, HAR import, OpenAPI import).

**Cap:** stop recording new entries past 200 captured requests per run (guards against unbounded memory growth on long-running suites). Entries past the cap are silently dropped — not an error, not surfaced to the user as a warning in this version.

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

New **"Captured Requests"** tab on the run detail page, alongside existing Steps/Screenshots tabs.

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

- Surfacing a warning when the 200-entry cap is hit
- Capturing WebSocket traffic
- Capturing calls made by concurrent/background pages beyond the primary tab

## Open Questions

None — all decisions made above.
