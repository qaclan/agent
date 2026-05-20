# Search-input stabilization plan

## Goal

The Candidates flow still fails after the typed-input conversion:

```js
await page.getByRole('link', { name: ' Candidates' }).click();
await _waitForNetworkSettle(page);
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).click();
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).pressSequentially('fdsd', { delay: 50 });
await _waitForNetworkSettle(page);
await expect(page.getByText('No data found')).toBeVisible();
```

User report: after the Candidates link click, the search input already
contains a stale value (carried over by `storageState` or by the app's own
client-side cache). The app then runs through this sequence:

1. `GET /api/candidates` — empty list query, table renders.
2. App rehydrates search box from cache → debounced handler fires →
   `GET /api/candidates?search=<stale>` → "No data found" appears briefly.
3. App resets search to empty (or the rehydration is undone) → another
   `GET /api/candidates` → table reappears, "No data found" disappears.
4. Test types `fdsd` → debounced search → races against the in-flight
   reset response.
5. Final visible state oscillates; `expect("No data found")` never holds
   for the assertion's polling window → times out.

`_waitForNetworkSettle()` cannot fix this. It correctly detects that no
XHR is in flight between bursts, then returns — but the next burst starts
*after* it has returned. The helper is doing its job; the problem is that
the app has a multi-step rehydrate-then-reset choreography the script
walks into mid-flight.

## 1. Why each obvious "fix" does not work alone

| Attempted fix | Why insufficient |
|---|---|
| Bigger `_ACTION_TIMEOUT` | The assertion is polling for 30s already. The text is genuinely absent at most poll instants. More time = same race. |
| Bigger `quietMs` on settle | After step 3 the app *does* go quiet briefly. Helper resolves. Next typing starts. New burst begins. No `quietMs` value catches "wait until the app has finished its own rehydrate cycle." |
| Sleep after Candidates click | Hides the bug; brittle on slow CI. Also: the rehydrate fires *whenever* the app decides to, not on a fixed schedule. |
| Drop `storageState` | Forces full re-login per run, multiplies suite time, and the app may rehydrate from `sessionStorage` / `localStorage` anyway, which `storageState` *does* capture. |
| Convert search to `.pressSequentially()` | Already done. Solves the *typed-event* problem — search XHR now fires — but the **stale-value** + **rehydrate race** is a separate failure mode. |

## 2. Solution — three layers, smallest first

Apply in order. Each layer is independently shippable; stop as soon as the
flow passes for two consecutive runs.

### Layer 1 — Force-clear the search field before typing (deterministic, minimal)

After the Candidates click settles, explicitly set the search to empty,
wait for the resulting "empty search" response to land, *then* type. This
removes the dependency on the app's rehydrate-then-reset behavior — the
test owns the field's value from a known starting point.

```js
await page.getByRole('link', { name: ' Candidates' }).click();
await _waitForNetworkSettle(page);

const search = page.getByRole('textbox', { name: 'Search by Candidate Name /' });
await search.click();
await search.fill('');                 // forces value = '' + input event
await _waitForNetworkSettle(page);     // wait for the empty-result fetch to land

await search.pressSequentially('fdsd', { delay: 50 });
await _waitForNetworkSettle(page);
await expect(page.getByText('No data found')).toBeVisible();
```

**Why this works**

- `.fill('')` is synchronous from the DOM's perspective — the value is
  zero after the call returns, regardless of what the app's rehydrate
  tries to write next.
- The subsequent `_waitForNetworkSettle` consumes whatever XHR burst the
  app fires in response to the empty value (its rehydrate-then-reset
  cycle fires *before* our typing, not during it).
- `.pressSequentially` then runs against a known-empty field. The
  debounced search fires for `f`, `fd`, `fds`, `fdsd` with no stale-value
  race in the middle.

**Cost:** two extra lines. No new helper. Same `_waitForNetworkSettle`.

### Layer 2 — Wait on the specific search response (stronger guarantee)

If Layer 1 still flakes (the empty-search burst takes longer than
`_waitForNetworkSettle`'s quiet window), pin the test to the exact
response it cares about instead of "no XHR for N ms":

```js
const search = page.getByRole('textbox', { name: 'Search by Candidate Name /' });
await search.click();
await search.fill('');
// Wait for the GET that has no `search` query param (or has an empty one)
// to come back 200 before we begin typing.
await page.waitForResponse(r =>
  r.request().method() === 'GET' &&
  /\/api\/candidates(\?|$)/.test(r.url()) &&
  !/search=[^&]/.test(r.url()) &&
  r.status() === 200
, { timeout: 10000 });

const searchResp = page.waitForResponse(r =>
  /\/api\/candidates\?[^#]*search=fdsd/.test(r.url()) &&
  r.status() === 200
, { timeout: 10000 });
await search.pressSequentially('fdsd', { delay: 50 });
await searchResp;
await expect(page.getByText('No data found')).toBeVisible();
```

**Why this works**

- `waitForResponse` is targeted — the test no longer guesses how long the
  app is busy. It blocks on the *exact* request whose result it needs.
- Two probes: one for the empty-search settle, one for the typed-search.
- The assertion happens only after the typed search has actually
  resolved, removing the polling race.

**Cost:** higher coupling to the app's API URL shape. If the URL pattern
changes (`/api/candidates` → `/api/v2/candidates`), the test breaks. But
the breakage is *visible* (timeout in `waitForResponse`), not flaky.

### Layer 3 — Strip search state from `storageState` (only if Layers 1 + 2 still flake)

If the app rehydrates the search field synchronously from
`localStorage` *every time* the component mounts, even the empty `.fill()`
+ settle can race with the rehydrate. In that case the storage itself is
the problem.

Two ways to address:

1. **Don't persist `storageState`** for this script. Set
   `QACLAN_STORAGE_STATE=''` for the run. Cost: full re-login per
   execution.
2. **Strip the search keys from `storageState` post-Login** by editing
   the JSON the harness writes:
   ```js
   // After login, before any other action:
   await page.evaluate(() => {
     localStorage.removeItem('candidatesSearch');  // or whatever the app uses
   });
   ```
   Requires inspecting the app to find the exact key. One-line addition;
   most surgical.

**Cost:** small, but requires app-internal knowledge (the storage key
name). Recommend running this only if the simpler layers do not stick.

## 3. Where to apply each layer

| Layer | Type of change | Where it lives |
|---|---|---|
| 1 | Manual edit to the recorded script | `~/.qaclan/scripts/<script>.spec.ts` (or via the script editor in the web UI) |
| 2 | Manual edit | Same |
| 3 | Manual edit *or* extending the harness `_trackNetwork` setup | Same, or `cli/script_strategies/typescript_test_strategy.py` if we decide to add a `_clearAppCache(page)` helper baked into every harness |

None of this needs the wizard or any backend route changes — the fix is
content the user (or QAClan) can apply post-record. The wizard's three
scans (Bind / Wait / Typed) cannot infer "this is a search field whose
state persists across sessions" — that is app-specific knowledge.

## 4. Wider implication for the wizard

The Bind / Wait / Typed wizard solved three categories of recorded-script
brittleness. This bug is a **fourth category**: client-side state
persistence across sessions causes ghost activity that races with the
recorded actions.

A future wizard phase ("Stabilize app state") could:

- On scan, find every field that the recorded script `.fill()`s or
  `.pressSequentially()`s.
- For each one, offer a one-click pre-clear: insert `.fill('')` +
  `_waitForNetworkSettle` before the first interaction on that field.

This is mechanical and safe (clearing a field never breaks correctness),
unlike the Bind / Typed scans which can pick the wrong field. A 4th
stepper pill — `Pre-clear inputs` — would slot in cleanly between
`Add waits` and `Typed inputs`:

```
① Bind data    ② Add waits    ③ Pre-clear inputs    ④ Typed inputs
```

**Not in this plan; flagged as a strong v2 candidate.**

## 5. Recommended immediate action

Apply **Layer 1** to the Candidates script and re-run. Two lines, no
framework change, no new helper. If the flow goes green, the layered
plan stops there.

If Layer 1 flakes after 5 runs, escalate to Layer 2. Re-evaluate
Layer 3 only if Layer 2 still flakes.

## 6. What this plan deliberately does *not* do

- **No global "auto-clear all `.fill` targets"** patch baked into the
  harness. Some fields *should* keep their value (e.g. a multi-step
  wizard where step 1 stores a name and step 3 reads it back). Decision
  is per-field, like Bind / Wait / Typed.
- **No retry-loop around the assertion.** Flaky retries hide the
  underlying race; the fix here removes the race.
- **No change to `_waitForNetworkSettle`.** The helper is correct;
  applying it before *and* after the empty-fill is enough.
- **No `waitForTimeout` sleeps.** Every wait in the proposed code is
  event- or response-anchored.
