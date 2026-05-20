# Auto-Wait Injection Plan

## Goal

Recorded scripts fail on slow-loading pages. Playwright `codegen` records **actions
only — never waits**. When a click triggers a slow async load (table fed by an XHR),
the next recorded action fires immediately against a not-yet-ready page and times out.

This plan lets the user add page-settle waits to recorded scripts **through the UI**,
with plain-language descriptions — no Playwright knowledge required.

Hard constraint: agent runs offline, recording happens via a sealed `codegen`
subprocess we cannot instrument live.

---

## 1. The reported failure (postmortem)

### Client's script

```js
await page.goto("{{url}}/dashboard", { waitUntil: 'domcontentloaded' });
await page.getByRole('menuitem', { name: 'Lead' }).click();
await page.getByRole('link', { name: 'Leads' }).click();      // (A) triggers slow table XHR
await page.getByPlaceholder('Search by mobile').click();       // (B) fires immediately
await page.getByPlaceholder('Search by mobile').fill('{{phone}}');
await page.getByRole('button', { name: 'search' }).click();
await expect(page.getByRole('cell', { name: '8801673092950' })).toBeVisible();
```

### Timeline of the bug

```
t=0.00s  click "Leads"            -> SPA fires GET /api/leads (table data)
t=0.01s  click "Search by mobile" -> input exists, click succeeds
t=0.02s  fill "{{phone}}"         -> input filled
t=0.03s  click "search"           -> search runs against EMPTY / stale table state
t=0.04s  expect(cell visible)     -> auto-wait starts polling, 30s ceiling
...
t=4.50s  GET /api/leads resolves  -> table finally renders (but search already ran)
t=30.0s  expect TIMES OUT         -> FAILED
```

### Why each thing does / does not save us

| Mechanism | Helps? | Why |
|---|---|---|
| Playwright auto-wait | No | Auto-wait checks **only the target element** of an action (visible/stable/enabled). Click on the *search input* waits for the *search input* — not the table. The input loads fast; the table does not. |
| Bigger `_ACTION_TIMEOUT` | No | Timeout is a **ceiling, not a wait**. Auto-wait already polls until the ceiling. Steps (B)(fill)(search-click) run before the table is ready, so the search executes against stale state. The final `expect` never sees the cell — bumping 30s → 120s only makes the failure slower. |
| `waitForLoadState('networkidle')` | Partly | Waits for *all* network idle. Breaks on apps with long-poll / websockets / analytics beacons — never goes idle. Discouraged by Playwright. |
| Explicit `waitForResponse('/api/leads')` | Yes | Targeted, fast. But requires knowing the endpoint — codegen does not record it. |
| Network-settle helper (this plan) | Yes | Generic. Waits for in-flight **XHR/fetch** count to drain. No endpoint knowledge needed. |

### Second bug — unrelated to timing

`fill('{{phone}}')` uses a template var; `expect(cell { name: '8801673092950' })` uses a
**frozen literal** codegen captured at record time. If `{{phone}}` ≠ `8801673092950`,
the assert fails regardless of any wait. Codegen cannot know `8801673092950` was the
search value. Fix belongs in the script editor / a record-time hint — out of scope for
auto-wait, but flagged here so it is not mistaken for a timing fix.

### Why "Path 1 — capture network during recording" was rejected

Original idea: attach `page.on('response')` during recording, timestamp responses and
user actions, correlate "click X → response Y → emit `waitForResponse(Y)`".

`record.py` launches codegen as a **sealed subprocess** (`subprocess.run([...,
"codegen", ...])`). QAClan holds no handle to the browser inside it — cannot attach
`page.on()`. The only data escape is `codegen --save-har`, which dumps network to a
HAR file. But:

- HAR entries carry timestamps; codegen **script output carries none**.
- No marker ties a HAR row to a generated script line.
- Correlation collapses to timestamp guessing — brittle, wrong under fast clicks.

Conclusion: targeted per-endpoint waits are not reliably recoverable. Use a **generic
settle helper** instead — no correlation needed.

---

## 2. Is this best practice?

Honest answer: **no — not idiomatic Playwright.** Stated plainly so the tradeoff is
not mistaken for textbook design.

- Idiomatic Playwright = **web-first assertions** (`await expect(locator).toBeVisible()`)
  + auto-wait. You wait on *the specific thing you need*, never blanket.
- Manual waits are discouraged; `waitForLoadState('networkidle')` is **explicitly
  discouraged** in Playwright docs.
- Hand-written test code never sprinkles a settle call after every click.

Why we do it anyway: codegen emits **bare actions only** — no web-first assertions
between steps. The idiomatic path requires a human to hand-edit every recording. The
target user is non-technical. So a `_waitForNetworkSettle` call is a **pragmatic
heuristic for machine-generated scripts** — same family as `networkidle`, but scoped
to XHR/fetch so it survives websockets / long-poll / analytics beacons that stop a
page ever going fully idle.

**Design decision — user picks, agent does not auto-inject.** Earlier drafts injected
a settle call after *every* click/goto automatically at record time. Rejected: blanket
injection taxes pure-UI clicks (grace probe, see §3) and the user has no visibility
into what changed. Instead the user reviews detected steps in the UI and **chooses**
which get waits — same pattern as **Scan & Bind** for env vars. One-click "add all" is
offered for users who want the blanket behaviour anyway.

---

## 3. Solution overview

Two moving parts:

1. A `_waitForNetworkSettle(page)` helper baked into the harness template (all
   strategies). Inert until called.
2. A **"Scan & Add Smart Waits"** UI flow — the user scans a script, sees each
   click/goto step described in plain language, ticks the ones that need a wait (or
   "add all"), and applies. QAClan rewrites the script with settle calls at the chosen
   spots.

The helper counts in-flight XHR/fetch requests, then resolves once the count has been
0 for a quiet window, capped by a timeout.

### Cost — grace probe (a speed optimization, not correctness)

Correctness comes from the **quiet-window loop alone**. After a network click the loop
sets `quietSince`, then the late-firing request flips `_inFlight` to 1 on a later poll
and the `else` branch resets `quietSince` — so the loop waits for the real settle. A
request that starts within `quietMs` (~400ms) of the loop beginning is always caught.
No grace needed for that.

The cost the grace probe addresses is **pure-UI clicks** (menu, tab, field focus — no
network ever). With the loop alone, a pure-UI click sets `quietSince` immediately but
still polls the full quiet window before returning — ~400ms dead time *per click*.
Many such clicks per script → seconds wasted.

Fix = a **grace probe**, two coupled lines: `waitForTimeout(graceMs)` then
`if (_inFlight === 0) return`. Wait a short grace (~150ms) for a request to *start*;
if in-flight is still 0, the click triggered no network — return early. Pure-UI click
pays ~150ms instead of ~400ms. A network click skips the early return and pays the
full settle.

The two lines are a **pair** — the wait is what makes the early return safe. Keep the
`if return` without the wait and it fires at t=0, before any request has started, and
returns instantly on a *network* click too — that breaks correctness. Remove both and
correctness is intact; only the pure-UI speedup is lost.

Tradeoff, stated plainly: the grace probe is **not free**. The loop alone tolerates a
request starting up to `quietMs` (~400ms) late; the early return only tolerates
`graceMs` (~150ms). A slow handler that fires its fetch at ~200ms is missed by the
early return, though the loop alone would have caught it. Accepted because pure-UI
clicks are common and handlers slower than 150ms are rare — but it is a speed/
robustness trade, not required behaviour.

This is also why the UI is opt-in per step: the user knows which clicks load data
(open a table, submit a search) and which are pure UI (open a menu). Targeted waits
skip the grace tax entirely on UI-only steps — no wait injected there at all.

---

## 4. The UI feature — "Scan & Add Smart Waits"

Modelled on the existing **Scan & Bind** flow (`scanAndBindFromEditor()` in
`web/static/app.js`). Same shape: a scan button + a review modal + an apply step.

### 4.1 Entry points

- **In-editor:** a `Scan & Add Waits` button next to the existing `Scan & Bind`
  button in the script editor toolbar.
- **Post-recording:** offered right after a recording is saved, in the same step that
  currently calls `reviewRecordedScriptFields()`. The wait review can run after the
  field-binding review.

### 4.2 The scan

Client-side, like Scan & Bind. Line-scan the script body for statements that call
`.click(` or `.goto(`. Each match becomes a **candidate**:

```javascript
{
  index:         0,                      // position in candidates array (0-based)
  stepNumber:    3,                       // 1-based position among ALL actions in
                                          //   the script — the "Step N" shown in UI
  kind:          'click' | 'goto',
  lineNumber:    14,
  lineText:      "await page.getByRole('link', { name: 'Leads' }).click();",
  label:         "Open \"Leads\"",         // human label, see 4.4
  lineEndOffset: 431,                     // offset of the END of the statement line
                                          //   (after the closing `;`) — the settle
                                          //   line is inserted here, NOT after `.click(`
  indent:        "  ",                    // leading whitespace of the matched line
  alreadyWaited: false,                   // true if next line is already a settle call
  recommended:   true                     // default tick state, see 4.5
}
```

`index` orders the candidates array (used for back-to-front rewrite, §4.6).
`stepNumber` is what the user sees — counted over every action statement in the
script, not just click/goto candidates, so "Step 3" matches the user's mental count
of the recording. `lineEndOffset` points past the end of the whole statement (a
`.click()` call may span the line beyond the `(`), so insertion never splits a line.

A small per-language map supplies the settle-call snippet and the
already-waited detector (so re-scanning an already-processed script does not
double-inject):

| Strategy | Settle call inserted |
|---|---|
| JavaScript / JS-test / TypeScript / TS-test | `await _waitForNetworkSettle(page);` |
| Python | `_wait_for_network_settle(page)` |

### 4.3 The review modal

Plain-language, non-technical. No mention of "XHR", "network", "Playwright",
"settle", or "request" in any user-facing copy. Exact strings in §4.7.

```
┌──────────────────────────────────────────────────────────────┐
│  Add Smart Waits                                              │
├──────────────────────────────────────────────────────────────┤
│  Some steps open information that takes a moment to appear —  │
│  a list, search results, or a new page. A test can run faster │
│  than the app: it moves on before the page is ready, so it    │
│  fails even though your app is fine.                          │
│                                                               │
│  A smart wait fixes this. It pauses at a step until the page  │
│  finishes loading, then continues on its own. It waits only   │
│  as long as needed — fast pages stay fast.                    │
│                                                               │
│  Tick the steps that open or load data. We've pre-selected    │
│  the ones that usually need it — adjust if you know your app. │
│                                                               │
│  [ Add a wait to every step ]   [ Clear all ]                 │
│   Safest if you're not sure. The test may run a little slower.│
│                                                               │
│  ☑  Step 3 — Open "Leads"                                     │
│        Recommended — opening a list or running a search       │
│        usually loads data.                                    │
│        line 14:  ...getByRole('link', { name: 'Leads' })...   │
│                                                               │
│  ☐  Step 4 — Open "Search by mobile"                          │
│        Usually not needed — this step opens a menu or         │
│        selects a field, with nothing to load.                 │
│        line 15:  ...getByPlaceholder('Search by mobile')...   │
│                                                               │
│  ☑  Step 6 — Click "search"                                   │
│        Recommended — opening a list or running a search       │
│        usually loads data.                                    │
│        line 17:  ...getByRole('button', { name: 'search' })...│
│                                                               │
├──────────────────────────────────────────────────────────────┤
│           [ Skip for now ]        [ Add Waits (2) ]           │
└──────────────────────────────────────────────────────────────┘
```

- **"Add a wait to every step"** — master toggle that ticks every candidate. This is
  the "all at once" option the user asked for; its helper text names the tradeoff
  honestly (slightly slower) so the user makes an informed pick.
- **"Clear all"** — unticks every candidate.
- Each row: a checkbox, a friendly step label, a one-line reason, the source line for
  reference.
- Steps already followed by a settle call render disabled and pre-ticked, with the
  reason replaced by "A wait is already added here."
- The Apply button counts the ticked rows: `Add Waits (2)`.

### 4.4 Step labels

Derive a friendly label from the locator so a non-technical user recognises the step:

- `.goto("...")`            → `Go to the page`
- `getByRole('link', { name: 'Leads' })` → `Open "Leads"`
- `getByRole('button', { name: 'search' })` → `Click "search"`
- `getByPlaceholder('Search by mobile')`  → `Open "Search by mobile"`
- fallback (no readable name) → `Step N` only.

Reuse / extend the label logic already used by Scan & Bind for field descriptions.

### 4.5 Default recommendation (which boxes start ticked)

Cheap heuristic, only sets the *default* — user overrides freely:

- `.goto(` → ticked (a page load almost always loads data).
- `.click(` on a locator whose name matches list/search/submit-ish words
  (`list`, `search`, `save`, `submit`, `load`, `view`, `open`, `go`, `next`,
  table/grid/link roles) → ticked.
- Other `.click(` (menu/tab/field focus) → unticked.

Keep the word list small and in one place; it is a hint, not correctness.

### 4.6 Apply

On `Add Waits`:

1. Collect ticked candidates.
2. Rewrite the script body **back-to-front** (so earlier offsets stay valid): after
   each ticked candidate's statement line, insert a new line — the per-language settle
   call — at matching indent.
3. In-editor flow: `editor.setValue(newContent)`.
   Post-record flow: `PUT /api/scripts/<id>` with the new content.
4. Injected lines land inside the BEGIN/END action markers → fully editable and
   deletable in the script editor afterwards.

### 4.7 UI copy — exact strings

Single source of truth for every user-facing string. Rules: no jargon ("XHR",
"network", "Playwright", "settle", "request", "subprocess"); every message states
*what* and *why*; the word "fails" is always paired with reassurance that the app
itself is fine, so the user does not panic.

**Modal title:** `Add Smart Waits`

**Intro (always visible — explains the problem, then the fix):**

> Some steps open information that takes a moment to appear — a list, search results,
> or a new page. A test can run faster than the app: it moves to the next step before
> the page is ready, so it fails even though your app is fine.
>
> A smart wait fixes this. It pauses at a step until the page finishes loading, then
> continues on its own. It waits only as long as needed — fast pages stay fast.

**Instruction line (above the step list):**

> Tick the steps that open or load data. We've pre-selected the ones that usually need
> it — adjust if you know your app better.

**Buttons:**

| Element | Label | Helper / sub-text |
|---|---|---|
| Master toggle | `Add a wait to every step` | `Safest if you're not sure. The test may run a little slower.` |
| Clear toggle | `Clear all` | — |
| Footer cancel | `Skip for now` | — |
| Footer apply | `Add Waits (N)` | N = count of ticked rows; disabled when N = 0 |

**Step row — label:** `Step {N} — {friendly action label}` (label from §4.4).

**Step row — reason line (one of):**

| Case | Reason text |
|---|---|
| `.goto(` — recommended | `Recommended — loading a new page usually needs a moment.` |
| list / search / submit click — recommended | `Recommended — opening a list or running a search usually loads data.` |
| not recommended | `Usually not needed — this step opens a menu or selects a field, with nothing to load.` |
| already has a wait | `A wait is already added here.` |

**Empty state (scan finds no `.click(` / `.goto(`):**

> Nothing to add here — this script has no page loads or clicks that could need a wait.

**Success toast (after apply):**

> Added {N} smart waits. You can edit or remove them anytime in the script editor.

**Post-recording prompt (chained after the field-binding review, §5.5):**

> Recording saved. Add smart waits so it won't fail on slow-loading pages?
> `[ Add waits ]`  `[ Not now ]`

---

## 5. Where the code changes — and why

### 5.1 Harness templates — add helper

**4 harness templates** (one per `_HARNESS_TEMPLATE`):
`cli/script_strategies/python_strategy.py`, `javascript_strategy.py`,
`javascript_test_strategy.py`, `typescript_test_strategy.py`.

`typescript_strategy.py` has **no** template of its own — `TypeScriptStrategy`
extends `JavaScriptStrategy` and inherits its harness. Do not add a template there;
editing the JS template covers TS automatically.

**Change:** add `_inFlight` counter, `_trackNetwork(page)`, `_waitForNetworkSettle(page)`
(JS/TS) and the Python sync-API equivalent to each `_HARNESS_TEMPLATE`. Call
`_trackNetwork(page)` where the existing `page.on('console')` listeners are registered.

**Why:** the helper must live in the runnable scaffolding, not the action body, so it
survives re-import and editor round-trips (scaffolding outside BEGIN/END markers is
never touched by `extract_between_harness_markers`).

#### Helper behaviour (JS / TS strategies)

```js
// Added to the harness scaffolding (above the test() block).
let _inFlight = 0;
function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
  });
  const done = req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
}

// Wait until in-flight XHR/fetch stays 0 for `quietMs`, capped at `timeoutMs`.
// Grace probe: if no request started within `graceMs`, the action triggered no
// network -> return early so pure-UI clicks pay only the grace, not the full quiet.
async function _waitForNetworkSettle(page, { graceMs = 150, quietMs = 400, timeoutMs = 15000 } = {}) {
  await page.waitForTimeout(graceMs);
  if (_inFlight === 0) return;                 // no network fired -> cost ~graceMs
  const deadline = Date.now() + timeoutMs;
  let quietSince = null;
  while (Date.now() < deadline) {
    if (_inFlight === 0) {
      if (quietSince === null) quietSince = Date.now();
      else if (Date.now() - quietSince >= quietMs) return;
    } else {
      quietSince = null;
    }
    await page.waitForTimeout(50);
  }
  // Soft cap: do not throw — let the next real action's auto-wait surface the failure.
}
```

Python strategies get the sync-API equivalent (`_wait_for_network_settle(page)`).

### 5.2 Per-language settle snippet on the strategy

**File:** `cli/script_strategies/base.py` — add two small strategy hooks (overridden
per language):

- `settle_call_snippet() -> str` — the line to inject (`await _waitForNetworkSettle(page);`
  vs `_wait_for_network_settle(page)`).
- `is_settle_call(line: str) -> bool` — true if a line already is a settle call, so
  re-scan does not double-inject.

**Why:** injection text is per-language; strategy already owns per-language transforms.
Exposing it as data lets the scan run client-side (consistent with Scan & Bind, which
is fully client-side) — the frontend asks the backend once for the active language's
snippet.

### 5.3 Backend — serve scan config

**File:** `web/routes/scripts.py` — extend (or add alongside) the existing
`/api/scripts/sensitive-patterns` route, or add `/api/scripts/<id>/wait-config`,
returning:

```json
{
  "ok": true,
  "settle_snippet": "await _waitForNetworkSettle(page);",
  "settle_marker": "_waitForNetworkSettle",
  "recommend_words": ["list", "search", "save", "submit", "load", "view", "open"]
}
```

- `settle_snippet` — the exact line the frontend inserts on apply (§4.6).
- `settle_marker` — the substring the frontend checks for to set `alreadyWaited`
  (§4.2): a candidate's next line containing this marker means a wait is already
  there. Per-language (`_waitForNetworkSettle` for JS/TS, `_wait_for_network_settle`
  for Python). This is the data form of the strategy's `is_settle_call()` (§5.2).
- `recommend_words` — drives the §4.5 default-tick heuristic.

No backend scan endpoint — parsing and rewriting happen client-side, mirroring Scan &
Bind. Script persistence reuses the existing `PUT /api/scripts/<id>`.

### 5.4 Frontend — scan + modal + apply

**File:** `web/static/app.js` — add, mirroring the Scan & Bind functions:

- `_parseActionCalls(scriptBody)` — finds `.click(` / `.goto(` candidates (analogue of
  `_parseFillCalls`).
- `_describeAction(locator, kind)` — friendly label (§4.4).
- `scanAndAddWaitsFromEditor()` — entry point, analogue of `scanAndBindFromEditor()`.
- `_showWaitReviewModal(...)` — the modal (§4.3), with "add all" / "clear all".
- `_rewriteScriptWithWaits(content, candidates, picks)` — back-to-front insertion,
  analogue of `_rewriteScriptWithBindings`.

Add the `Scan & Add Waits` button next to the four existing `Scan & Bind` buttons
(editor toolbars near `app.js` lines 1643 / 1902 / 2006 / 2119).

### 5.5 Post-recording hook

**File:** wherever `reviewRecordedScriptFields()` is invoked after a save — chain the
wait review after the field-binding review so a freshly recorded script can get both
in one pass. Skippable.

### 5.6 What is NOT changed

- `cli/commands/web/record.py` — no record-time injection. Recording stays untouched.
- No `auto_wait` config flag. The feature is invoked on demand from the UI, not gated
  by a stored toggle.

---

## 6. Out of scope

- Frozen-literal assertion bug (§1) — needs editor support or a record-time value hint.
- HAR-based targeted `waitForResponse` — rejected (§1), revisit only if a future
  codegen exposes per-action network markers.
- Auto-inject at record time — explicitly rejected (§2): the user decides per step.
- Configurable settle timings (`graceMs` / `quietMs` / `timeoutMs`) — deferred.
  Defaults are hardcoded in the helper signature (`150` / `400` / `15000`); a power
  user can hand-edit a settle call in the script editor. A global `config.json`
  override block (e.g. `network_settle: {...}`) is a possible follow-up but not in
  this version. The `timeoutMs` cap stays **soft** (no throw) — turning settle into a
  pass/fail load-time assertion is a separate feature, not in scope here.

## 7. Rollout

1. Helper in the 4 harness templates (TS inherits JS — no behaviour change, inert).
2. `settle_call_snippet()` / `is_settle_call()` on base + per-strategy overrides.
3. Backend wait-config route.
4. Frontend: parse + describe + modal + rewrite; wire the `Scan & Add Waits` button.
5. Chain the wait review into the post-recording flow.
6. Re-record the client's Leads script, run Scan & Add Waits, tick "Leads" and
   "search", verify it now passes (timeline below).

### Verification timeline (after user ticks "Leads" + "search")

```
t=0.00s  click "Leads"                 -> GET /api/leads fires, in-flight = 1
t=0.01s  _waitForNetworkSettle(page)   -> grace probe (150ms)
t=0.16s  grace done, in-flight = 1     -> BLOCKS
...
t=4.50s  GET /api/leads resolves       -> in-flight = 0
t=4.90s  quiet window elapsed          -> helper resolves, table is rendered
t=4.91s  click "Search by mobile"      -> runs against ready table (no wait — user left unticked)
t=4.92s  fill "{{phone}}"
t=4.93s  click "search"                -> GET /api/leads?phone=... fires, in-flight = 1
t=4.94s  _waitForNetworkSettle(page)   -> grace probe, then BLOCKS
t=6.05s  search response resolves      -> in-flight = 0
t=6.45s  quiet window elapsed          -> helper resolves
t=6.46s  expect(cell visible)          -> cell present -> PASSED
```
