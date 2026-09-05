## Why

`POST /api/sync/push` drains the sync queue with a 30s server-side deadline. When items don't finish in time, the UI shows a neutral "will retry in background" toast and then never checks again — `GET /api/sync/status` (which already reports `queue_depth`/`failing`) is unused by the frontend outside its own route file. When the background worker later finishes that same push (success or failure), the user gets no notification at all: the push silently "worked" or "failed" with zero UI trace, defeating the point of the failing-entity visibility added in `sync-queue-diagnostics`.

## What Changes

- `triggerPush()` (`web/static/app.js`), when the push response reports `remaining > 0` and `failing` empty (the ambiguous "still working" case), starts a bounded client-side poll of `GET /sync/status`: every ~5s, up to ~6 attempts (~30s).
- Poll stops and shows a success toast the moment `queue_depth` reaches 0.
- Poll stops and shows an error toast (naming the entity + `last_error`) if `failing` becomes non-empty mid-poll.
- If the attempt cap is reached with nothing resolved, the poll stops silently — no toast, no false "success" claim.
- A new push click cancels any in-flight poll from a previous click (single active poller at a time).
- No backend changes — reuses the existing `/api/sync/status` endpoint added by the archived `sync-failure-visibility` change.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `sync-queue-diagnostics`: adds a requirement that async completion of a backgrounded push (success or later-discovered failure) is surfaced to the user, not just the immediate push response.

## Impact

- `web/static/app.js` — `triggerPush()`, new bounded poll helper, module-level poll-handle guard
- No backend/API/schema changes
