## 1. Poll helper

- [x] 1.1 Add module-level `let _pushPollTimer = null` near `triggerPush()` in `web/static/app.js`.
- [x] 1.2 Add `pollPushCompletion()`: clears any existing `_pushPollTimer`, then re-arms itself via `setTimeout` every 5s for up to 6 attempts, calling `api('GET', '/sync/status')` each tick.
- [x] 1.3 In `pollPushCompletion()`: if a tick's response has `failing.length > 0`, stop polling and show an error toast naming the first failing entity's `label` + `last_error` (with "+N more" suffix if more than one), same format as the existing push-response error toast.
- [x] 1.4 In `pollPushCompletion()`: if a tick's response has `queue_depth === 0`, stop polling and show a success toast (e.g. "Sync completed in background").
- [x] 1.5 In `pollPushCompletion()`: if the attempt cap (6) is reached with neither condition met, stop polling silently — no toast.

## 2. Wire into triggerPush

- [x] 2.1 In `triggerPush()`'s else branch (`web/static/app.js`, the branch currently showing the neutral `res.message` toast), after showing that toast, call `pollPushCompletion()` only when `res.remaining > 0` and `(!res.failing || res.failing.length === 0)`.
- [x] 2.2 Confirm the `res.failing.length > 0` branch (immediate failure in the push response itself) is unchanged and does not start a poll — it already has its answer.
- [x] 2.3 Confirm the `res.remaining === 0` success case is unchanged and does not start a poll — it already succeeded.

## 3. Verification

- [x] 3.1 Manually force the ambiguous case (e.g. temporarily lower the server's `flush_sync` deadline or add latency to a sync call so `push_now()` returns with `remaining > 0`, `failing` empty) and confirm: initial neutral toast still shows, then once the background worker drains the queue, a success toast appears within the poll window.
      Verified by extracting `pollPushCompletion()` verbatim into a Node harness with a real queued-timer fake (`setTimeout`/`clearTimeout` that only fire on explicit `advance()`, so cancellation semantics match a real browser) and stubbed `api()`/`toast()`. Fed a 3-tick sequence (`queue_depth` 3 → 1 → 0, `failing` empty throughout): exactly one `"Sync completed in background"` success toast fired, on the tick where `queue_depth` hit 0. No browser available in this environment for a visual check (same constraint noted by the prior `sync-failure-visibility` change).
- [x] 3.2 Reproduce the same setup but force the item to end up in `failing` before the queue drains (e.g. point at a URL that 4xxs) and confirm an error toast appears mid-poll, naming the entity and error.
      Verified via the same harness: fed a 2-tick sequence where tick 2's response carries `failing: [{label: 'project Foo', last_error: 'HTTP 403'}]`. Exactly one error toast fired reading `"project Foo failed to sync: HTTP 403"`, and polling stopped (no further ticks scheduled).
- [x] 3.3 Reproduce the same setup with an item that never resolves within ~30s and confirm no toast appears after the initial neutral one — no false success.
      Verified via the same harness: fed 10 available responses all with `queue_depth: 5`, `failing: []` (never resolving). Exactly 6 ticks fired (~30s at 5s/tick) then polling stopped on its own; zero toasts fired during or after — confirms the cap is honored and no false-success/false-anything toast is shown.
- [x] 3.4 Click Push twice in quick succession while a poll is in-flight and confirm only one poller ends up active (no duplicate/double toasts) — check via added `console.log`/breakpoint or by confirming only one toast fires per resolved outcome.
      Verified via the same harness: called `pollPushCompletion()` twice back-to-back before advancing the fake clock (chain A's tick still pending when chain B starts) — chain B's `clearTimeout(_pushPollTimer)` removed chain A's still-queued tick before it could fire. Advancing to completion produced exactly one success toast, not two. (An earlier version of this harness used a microtask-based fake timer that fired `setTimeout` callbacks immediately regardless of `clearTimeout`, which masked this — falsely showing 2 toasts. Rewrote the fake to a real pending-timer queue so `clearTimeout` genuinely prevents a not-yet-fired callback, matching browser semantics, before trusting the result.)
- [x] 3.5 Confirm the unchanged cases still work: immediate success (`remaining === 0`) shows the existing success toast with no poll; immediate `failing` in the push response shows the existing error toast with no poll.
      Verified by code inspection of `triggerPush()`: `pollPushCompletion()` is called only inside `if (res.remaining > 0)`, itself only reachable in the branch where `res.failing` is empty — so the immediate-`failing` branch and the immediate-`remaining === 0` branch are structurally untouched and never invoke the poller.
