## Why

Cloud sync (`cli/sync_queue.py`) retries forever and silently: when an entity's cloud push fails every attempt (e.g. a project the server rejects), the queue keeps it and every dependent under it (features, suites, scripts) failing in a loop, but the only trace is the `sync_queue.last_error` column — nothing in `GET /api/sync/status`, the Push response, or the UI ever surfaces it. Users click Push, see "N still pending, will retry in background," and it never resolves — with zero indication of why or what's stuck. Each dependent also re-attempts its already-broken parent's sync on every dispatch, repeating the same doomed HTTP call instead of recognizing the parent is already known-broken.

## What Changes

- `GET /api/sync/status` returns a `failing` list alongside `queue_depth`: rows from `sync_queue` with `attempts > 0`, each with `entity_type`, `entity_id`, a human-readable label (project/feature/suite/script name, looked up locally), `attempts`, and `last_error`.
- `POST /api/sync/push` response includes the same `failing` detail (not just a bare `remaining` count) whenever `remaining > 0`, so the same request that triggers a push can tell you why leftovers didn't clear.
- Web UI (`triggerPush()` in `web/static/app.js`) shows a distinct error-styled toast naming the failing entity and its error when the push response reports `failing` items, instead of the current neutral "will retry in background" message for every non-zero `remaining`.
- `cli/sync_queue.py::_dispatch` skips re-deriving a parent's cloud id when that parent already has its own `sync_queue` row with `attempts > 0` and a `last_attempt_at` within a short cooldown window — the dependent is marked failed with a `last_error` of `blocked on parent: <error>` instead of re-issuing the same doomed HTTP call for the parent.

## Capabilities

### New Capabilities
- `sync-queue-diagnostics`: exposing failing/stuck sync-queue entries (with cause) through the status and push endpoints and the UI, and short-circuiting dependent entities whose parent is already known-broken instead of silently re-attempting it.

### Modified Capabilities
(none — no existing spec covers sync-queue behavior; see `openspec/specs/` for confirmation)

## Impact

- `web/routes/sync.py` — `sync_status()`, `push_now()`
- `cli/sync_queue.py` — `queue_depth`/new query helper for failing rows, `_dispatch`, `_fetch_batch` (or a sibling query) for the parent-cooldown check
- `web/static/app.js` — `triggerPush()` toast handling
- No DB schema change — `sync_queue.attempts`/`last_error`/`last_attempt_at` columns already exist and are already populated by `drain_once()`
