## Context

See proposal.md - Why. Relevant current-state facts:

- `triggerPush()` (`web/static/app.js:454-475`) branches on `res.failing`/`res.remaining` from `POST /sync/push` but never calls `GET /sync/status` again afterward — confirmed by grep, `/sync/status` has zero references in `app.js` outside its own definition.
- `push_now()` (`web/routes/sync.py:16-40`) enqueues, wakes the worker, and calls `flush_sync(deadline=30)` — a synchronous best-effort drain capped at 30s. Anything not drained in that window stays queued for the background worker (`cli/sync_queue.py::_worker_loop`, `IDLE_SLEEP=30`).
- `GET /sync/status` (`web/routes/sync.py:68-70`) already returns `queue_depth` and `failing` (via `list_failing()`, added by the archived `sync-failure-visibility` change) — exactly the two signals needed to know whether a backgrounded push later succeeded or failed. No backend change needed.
- `toast(message, type)` (`web/static/app.js:700-710`) is the existing notification primitive; auto-dismisses after 3s.

## Goals / Non-Goals

**Goals:**
- Notify the user when a push that didn't finish within the server's 30s deadline later resolves (success or failure) in the background.
- Never show a false "success" toast if the outcome is still unknown when polling stops.
- Keep the change frontend-only, reusing the existing status endpoint.

**Non-Goals:**
- An always-on sync status badge/indicator independent of the Push button (considered, deferred — see proposal's "What Changes"; broader surface than this fix needs).
- Polling for failures/success on flows other than an explicit Push click (e.g. autosync triggered by edits) — same rationale.
- Any change to server-side drain deadlines, worker cadence, or the `/sync/push`/`/sync/status` response shape.

## Decisions

**1. Poll only the ambiguous case: `remaining > 0` and `failing` empty.**
If `failing` is already non-empty in the push response, the existing error toast (added by `sync-failure-visibility`) already tells the user what's wrong — no need to poll. If `remaining === 0`, the existing success toast already fires. Polling is only useful for the third case: items still queued, not yet known to be broken, outcome pending in the background.

**2. Bounded poll: ~6 attempts, 5s apart (~30s total), via `setTimeout` chaining (not `setInterval`).**
`setTimeout` re-armed after each response avoids overlapping requests if a status call is slow. ~30s roughly matches the server's own `flush_sync` budget already spent once — a second ~30s window gives the background worker (`IDLE_SLEEP=30`) about one more full cycle to resolve before giving up. Longer would keep polling past the point a user is still watching for feedback; shorter would miss the worker's own retry cadence entirely.
Alternative considered: exponential backoff. Rejected — fixed short window is simpler and the total duration is already small; no need to taper.

**3. On cap exhaustion, stay silent — no toast, no error.**
Showing "still pending" again would just repeat the toast already shown when the push response came back; showing a fake success would misinform. Silence is honest: the item is still queued and either the next natural status touchpoint (another push click) or the background worker will eventually resolve it.
Alternative considered: after cap, fall back to a permanent small indicator. Rejected as scope creep — that's the deferred "badge" option.

**4. Single active poller, guarded by a module-level handle.**
`let _pushPollTimer = null` in `app.js`; starting a new poll clears any previous `setTimeout` first. Without this, clicking Push twice in a row (e.g. user impatient) would produce two independent pollers and could double-toast. This directly backs the spec's "new push supersedes in-progress poll" scenario.

**5. Poll via plain `fetch`/existing `api()` helper — no new abstraction.**
Reuses whatever `api('GET', '/sync/status')` helper `triggerPull`/`triggerPush` already use for consistency (auth headers, base URL, error shape).

## Risks / Trade-offs

- [User closes/navigates away mid-poll] → `setTimeout` is page-scoped; poll simply stops on unload. No cleanup needed, no stale toast risk (toast target no longer exists).
- [Poll window (~30s) not long enough for slow networks/large queues] → Accepted: matches the Non-Goals boundary — this is a UX nicety for the common case, not a guarantee. The `failing` list (already surfaced on the next status check via existing UI, or the next push) still catches truly stuck items.
- [Extra `/sync/status` requests during the poll window] → Bounded to ~6 requests max, only when the ambiguous case is hit (not on every push), negligible load.

## Open Questions

(none)
