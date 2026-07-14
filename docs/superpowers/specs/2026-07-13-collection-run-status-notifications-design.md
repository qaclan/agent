# Collection run: persistent status + completion notifications

## Problem

Running a collection (`web/static/api/views/collections-view.js:112` "Run collection" button, or the header run button) opens a live-updating run view (`collection-run-view.js`). Two gaps:

1. **No way back.** Navigating to a request editor (or anywhere else in the API section) tears down the run view (`api-section.js:_teardown`). The only way back is knowing to click the collection's name in the sidebar, which reopens `collection-detail-view.js` with a run-status card and a "View Progress →" button — a two-click, low-discoverability path. The sidebar's pulsing dot (`data-col-dot`) hints a run is active but isn't itself clickable to jump to it.
2. **No completion signal.** If the user is idle or away from the tab when a run finishes, nothing tells them. The sidebar dot simply stops pulsing — indistinguishable from "nothing happened."

## Goals

- One-click return to a running collection's live view from anywhere in the API section.
- A signal when a run finishes, strong enough to reach a user who has stepped away from the tab/window, not just one who's watching the sidebar.
- Support the (currently possible but rare) case of more than one collection running at once.
- Don't build a persistent notification history/center — this is deliberately scoped to "while the SPA session is open," not surviving reload.

## Architecture

A single shared poller, `active-runs-tracker.js`, replaces the ad hoc polling currently duplicated per view. Three independent consumers subscribe to it:

1. **Sidebar dots** (existing, in `collections-view.js`) — same visual, now fed by the shared tracker instead of its own `setInterval`.
2. **Top-bar status chip** (new) — mounted in `api-section.js` beside the Collections/API Docs tabs. Visible whenever at least one run is active *and not the one currently on screen*. One run → label + click-to-jump. Multiple → count + dropdown, each row jumps to its own run view.
3. **Completion notifier** (new) — when a run finishes and it isn't the one currently open, shows a sticky in-app banner and, if permitted, a native OS notification.

```
active-runs-tracker.js
  ├─ sidebar dots (collections-view.js)
  ├─ run-status-chip.js  → api-section.js (topBar)
  └─ run-notification.js → api-section.js (completion handler)
```

## Components

### `web/static/api/services/active-runs-tracker.js`

```
startActiveRunsTracker({ onChange, onCompleted }) -> { stop }
```

- Polls `GET /api-collection-runs?status=RUNNING` every 3s (same endpoint the sidebar already uses).
- Keeps a `Map<runId, runSummary>` of previously-seen running runs.
- Each tick: diff the fresh RUNNING list against the map.
  - Any id present before but missing now = just completed → fetch `GET /api-collection-runs/<id>` once for final status/counts → `onCompleted(run)` → remove from map.
  - Always calls `onChange([...currentRunningList])` after the tick.
- Fetch failures are swallowed and retried next tick (same `catch(_){}` pattern as the existing `_refreshRunningStatus`) — a transient network hiccup never falsely fires a completion.
- Owns the OS-notification permission request (see below), since it's the one place that knows "a run just started."

### `web/static/api/components/run-status-chip.js`

```
mountRunStatusChip(container, tracker, { getCurrentViewedRunId, onJump })
```

- Re-renders on every tracker `onChange`, filtering out `getCurrentViewedRunId()` so the chip never refers to the run already on screen.
- 0 remaining → chip hidden (`display:none`).
- 1 remaining → `● Running: <collection name> 4/12`, click calls `onJump(runId, collectionId, collectionName)`.
- 2+ remaining → `● 2 running ▾`, click opens a small dropdown listing each (name + progress), each row calls `onJump(...)`.

### `web/static/api/components/run-notification.js`

```
notifyRunCompleted(run, { onView })
```

- Appends a sticky banner to `document.body` (own stacked container, independent of whichever view is mounted — same "outlives view teardown" approach `window._toast` already uses). Does **not** auto-dismiss. Content: collection name + `passed`/`failed`/`error_count` summary + "View Results" button + "✕" dismiss. Multiple completions stack.
- "View Results" click calls `onView()` and removes the banner.
- If `Notification.permission === 'granted'`, also fires `new Notification(title, {body})`. Its `onclick` calls `window.focus()` then `onView()`.
- If permission is `'denied'` or the `Notification` API is unavailable, silently skips the OS half — banner is the guaranteed baseline.

### Permission timing

Requested lazily from inside the tracker's `onChange`: the first time the running count goes from 0 to 1 and `Notification.permission === 'default'`, call `Notification.requestPermission()` once. This piggybacks on the user's own "Run" click as the initiating gesture, without threading a call through `collections-view.js`'s `_runCollection`.

### `api-section.js` wiring

- Instantiate one `startActiveRunsTracker(...)` when the API section mounts.
- Track a single `_currentlyViewedRunId` variable, set when `_showRunDetail` opens a run and cleared in `_emptyMain` / when any other view replaces it (`_showCollectionDetail` without an active runId, `renderRequestEditor`, etc.). Read by both the chip's `getCurrentViewedRunId` and the notifier's suppression check.
- `onJump` from the chip and `onView` from the notifier both call the existing `_showRunDetail(runId, colId, colName)` — no new navigation path, just a new entry point into it.
- `collections-view.js`'s existing `_refreshRunningStatus`/`_runningPollTimer` block is removed; it subscribes to the same tracker instance instead (passed in or exposed via `window.__qaclanApi`), so there's exactly one network timer hitting the RUNNING endpoint, not two.

## Error handling

- Tracker poll failures: swallowed, retried next tick, never mistaken for completion (a fetch error mid-tick just skips that tick's diff).
- Completion detail fetch failure (the one-off `GET /api-collection-runs/<id>` after a run drops out of RUNNING): if it fails, skip firing that notification rather than showing a banner with missing data; the run is still removed from the tracked map so it isn't retried indefinitely.
- OS notification: any exception constructing `Notification` (unsupported browser, permission race) is caught and ignored — banner already covers the guarantee.

## Explicit non-goals

- No persistent notification history/center. Dismissed or missed banners are gone; nothing is written to the DB.
- No survival across a full page reload — reload is a deliberate user action, not the "idle" case being solved for.
- No change to the printable report page (`/api-collection-runs/<id>/report?view=1`) or its "⬇ Report" button — the new chip/banner both open the existing in-app run view instead, kept as the one consistent "view results" destination.

## Manual test plan (no automated tests in this repo)

1. Start a run, navigate to a request editor, confirm the top-bar chip appears and clicking it jumps back to the correct live run view.
2. While viewing a run's own page, confirm the chip does *not* show that run (suppression).
3. Let a run finish while the chip is visible (i.e., not being viewed) — confirm the sticky banner appears with correct pass/fail counts and doesn't auto-dismiss.
4. Click the banner's "View Results" — confirm it opens the same run view and the banner clears.
5. Start two collections concurrently — confirm chip shows a count and dropdown, and each row jumps to the right run.
6. Grant OS notification permission, finish a run in background tab — confirm native popup fires and clicking it focuses the tab and opens the run.
7. Deny permission — confirm run completion still shows the in-app banner with no errors in console.
