# Typed-Input Conversion Plan

## Goal

Recorded scripts use `locator.fill('text')` for every text input. Codegen has no
heuristic to switch to typed entry. For most fields that is correct: `.fill()` is
fast, idempotent, dispatches a single `input` event — fine for login, signup, any
form bound to a controlled component reading `.value`.

It is **wrong** for search-as-you-type and similar fields whose handler debounces
on per-key events (`keydown` / `keyup`). `.fill()` sets the value and fires one
`input` event; the debounced listener never sees the keystrokes, the search XHR
never fires, the next assertion times out.

This plan lets the user convert specific `.fill()` calls in a recorded script to
`.pressSequentially()` (JS / TS) or `.press_sequentially()` (Python) **through the
UI**, with plain-language descriptions — no Playwright knowledge required.

Hard constraint: recording is a sealed `codegen` subprocess we cannot instrument;
the conversion runs after the fact, the same way Auto-Wait does.

---

## 1. The reported failure (postmortem)

### Client's script

```js
await page.getByRole('link', { name: ' Candidates' }).click();
await _waitForNetworkSettle(page);                                  // table loads — fine
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).click();
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).fill('asdfdf');
await _waitForNetworkSettle(page);                                  // resolves immediately
await expect(page.getByText('No data found')).toBeVisible();        // FAILS
```

### Timeline of the bug

```
t=0.00s  click "Candidates"      -> SPA fires GET /api/candidates
t=0.01s  _waitForNetworkSettle   -> waits for table load, settles when ready
t=4.50s  table rendered, helper resolves
t=4.51s  click search textbox    -> field focused, no network
t=4.52s  fill "asdfdf"           -> value set, ONE input event dispatched
                                    keydown / keyup NEVER fired
                                    debounce(onKeyUp, 300ms) never armed
                                    NO search XHR
t=4.53s  _waitForNetworkSettle   -> in-flight = 0, grace probe returns
t=4.54s  expect("No data found") -> text not present, auto-wait polls 30s
t=34.5s  TIMES OUT               -> FAILED
```

### Why each thing does / does not save us

| Mechanism | Helps? | Why |
|---|---|---|
| Existing `_waitForNetworkSettle` | No | Nothing to wait for. `.fill()` triggered no XHR — `in-flight` is 0 from the start. |
| Bigger `_ACTION_TIMEOUT` | No | The handler is never armed. Waiting longer for an event that will never fire. |
| Add a wait *before* the fill | No | Wait does not change what `.fill()` dispatches. |
| `.press(' ')` + `.press('Backspace')` after fill | Hack | One synthetic keystroke nudges the listener. Brittle: some apps debounce-trail / reset-on-equal-value. |
| `.pressSequentially('asdfdf', { delay: 50 })` | Yes | Per-key `keydown`/`keypress`/`input`/`keyup`. Mirrors real typing. Debounce fires. XHR runs. |
| Auto-replace **all** `.fill()` calls | No | Side-effects on masked inputs / per-key validators / paste-only fields — see §2. |

### Manual typing reproduces the search; `.fill()` does not

Confirmed by the user: typing any character into the search field by hand fires
the search XHR; `.fill('asdfdf')` does not. Two-step grace probe (auto-wait plan
§3) is not the bug — the network helper is functioning, there is simply no
network event to wait for.

### Why "auto-replace every fill" is rejected

Side-effects on non-search fields:

- **Masked inputs** (`(___) ___-____`, `MM/DD/YYYY`) — per-key fires mask logic,
  can mangle the value.
- **Per-key validators** — reject mid-typing values (`"12"` invalid before `"123"`
  valid). Flaky races.
- **Autocomplete dropdowns on email / address** — each char fires suggest;
  dropdown can swallow focus, intercept Enter / Tab.
- **Paste-only fields** — some inputs block keystrokes, accept only paste.
  `.fill()` works; sequential fails.
- **Speed** — `delay: 50` × N chars. 20-char email = 1s vs `.fill()` ~10ms. Multiply
  per script.

Conclusion: same shape as Auto-Wait — **user picks per field**, agent does not
auto-rewrite. Recommended defaults skew conservative (high-confidence only).

---

## 2. Is this best practice?

Honest answer: **codegen has no built-in solution**. Playwright's docs are explicit:
`.fill()` is the default; `.pressSequentially()` is the documented escape hatch
"if there is special keyboard handling on the page"
(https://playwright.dev/docs/input#type-characters). Codegen never emits
`.pressSequentially()` — open feature requests exist, none merged. The team's
stance: codegen is a scaffold, the human edits for app-specific quirks.

That edit step is exactly what a non-technical QAClan user cannot do. So the
feature is **a UI-driven version of the manual edit** every Playwright user
already does, surfaced through the same scan-and-review pattern as Auto-Wait
and Scan & Bind. No magic, no auto-mutation — review, tick, apply.

**Design decision — user picks, agent does not silently rewrite.** Silent
rewrite at record time was rejected for the same reasons as auto-injected
waits (§2 of `auto-wait-plan.md`): hidden script mutation kills debuggability
and consent. Reviewable scan + per-row toggle is the contract.

---

## 3. Solution overview

Two moving parts:

1. A per-language **rewrite snippet** baked into each strategy: how to turn a
   `.fill(value)` call on the same locator chain into a `.pressSequentially(value,
   { delay: 50 })` call. No new harness helpers — `pressSequentially` is built
   into Playwright.
2. A **"Scan & Convert Search Inputs"** UI flow — the user scans a script, sees
   each `.fill()` step described in plain language with a confidence badge, ticks
   the ones that need typed entry, and applies. QAClan rewrites the matched
   `.fill()` lines.

### Why a separate scan from Auto-Wait

Two reasons to keep them as **separate scan buttons** (in the same toolbar) rather
than merging into one mega-modal:

- Different action verbs — `.click()` / `.goto()` for waits, `.fill()` for typed
  entry. Different defaults, different copy, different recommendation rules.
- Different blast radius — adding a wait line cannot break correctness; rewriting
  `.fill()` to `.pressSequentially()` can (mask / validator side-effects). Keeping
  them apart prevents an accidental "Convert all" sliding past a tired user who
  meant to bulk-apply waits.

Both scans can be chained after recording (Scan & Bind → Add Waits → Convert
Search Inputs) so the freshly recorded script gets all three passes in one flow.

### What is rewritten — exactly

The input line:

```js
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).fill('asdfdf');
```

becomes:

```js
await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).pressSequentially('asdfdf', { delay: 50 });
```

The locator chain is untouched. Only the trailing `.fill(<arg>)` becomes
`.pressSequentially(<arg>, { delay: 50 })`. `<arg>` may be a literal, a template
variable (`'{{username}}'`), or an expression — preserved verbatim.

Pre-fill `.click()` / `.focus()` on the same locator is **not** removed even if
no longer needed. Codegen records them, the user can delete by hand; the
rewriter touches one call only.

### Why `delay: 50` and not `delay: 0`

`delay: 0` fires every key back-to-back in the same event-loop tick. Pure
debounced search still works — debounce coalesces on the trailing edge — but
modern frameworks break. React / Vue / Angular controlled inputs batch state
updates; if the next `keydown` arrives before the framework has committed the
previous `setState`, the handler reads stale `.value` and earlier keystrokes
get dropped from state.

Example — React controlled search input, `pressSequentially("ab", { delay: 0 })`:

```jsx
function Search() {
  const [q, setQ] = useState('');
  return <input value={q} onChange={e => setQ(e.target.value)} />;
}
```

```
t=0ms   'a' keydown -> React schedules setQ('a')
t=0ms   'b' keydown -> React still batching, schedules setQ('b') over stale state
t=1ms   React flushes -> only the last write wins, q = 'b'
                         the 'a' is lost from component state
```

The DOM shows `"b"`, the search XHR fires `?q=b`, the assertion expecting
`"No data found"` for `"ab"` fails even though typing worked at the event level.

`delay: 50` gives the event loop one tick between keys — React commits, the
next `onChange` reads fresh state, every keystroke lands. 50ms × N chars is the
cheap insurance: 300ms overhead on a 6-char search beats a 30s timeout on a
flaky frame.

This is also why Playwright's official docs example uses `delay: 50`
(https://playwright.dev/docs/input#type-characters) and why real human typing
sits around 80–150ms per key — the framework batching window assumes humans,
not bots, are at the keyboard.

---

## 4. The UI feature — "Scan & Convert Search Inputs"

Modelled on Scan & Add Smart Waits (`auto-wait-plan.md` §4) and Scan & Bind
(`scanAndBindFromEditor()` in `web/static/app.js`). Same shape: a scan button +
review modal + apply step.

### 4.1 Entry points

- **In-editor:** a `Scan & Convert Search Inputs` button next to `Scan & Add Waits`
  in the script editor toolbar.
- **Post-recording:** chained after the Auto-Wait review in the same flow that
  follows `reviewRecordedScriptFields()`. Order is: field binding → add waits →
  convert search inputs. Each pass is independently skippable.

### 4.2 The scan

Client-side. Line-scan the script body for statements that call `.fill(`. Each
match becomes a **candidate**:

```javascript
{
  index:           0,                       // position in candidates array (0-based)
  stepNumber:      4,                        // 1-based position among ALL actions
                                             //   in the script — "Step N" in UI
  lineNumber:      16,
  lineText:        "await page.getByRole('textbox', { name: 'Search by Candidate Name /' }).fill('asdfdf');",
  locatorChain:    "page.getByRole('textbox', { name: 'Search by Candidate Name /' })",
  fillArg:         "'asdfdf'",                // exact source-text argument, preserved
  fillStart:       483,                       // offset of `.fill(` in script
  fillEnd:         522,                       // offset just past the matching `)`
  label:           'Type into "Search by Candidate Name /"',
  signal:          'role-searchbox' | 'role-combobox' | 'input-type-search'
                 | 'name-keyword' | 'placeholder-keyword' | 'label-keyword'
                 | 'none',
  confidence:      'high' | 'medium' | 'low',
  alreadyTyped:    false,                    // true if line already uses pressSequentially
  recommended:     true                       // default tick state, see 4.5
}
```

`fillStart` / `fillEnd` bound the **single call** to rewrite. The locator chain
before `fillStart` and the rest of the line after `fillEnd` are untouched. Like
Auto-Wait, rewrites run **back-to-front** so earlier offsets stay valid.

A per-language map supplies the rewrite snippet and the already-typed detector:

| Strategy | Original | Rewrite |
|---|---|---|
| JavaScript / JS-test / TypeScript / TS-test | `.fill(<arg>)` | `.pressSequentially(<arg>, { delay: 50 })` |
| Python | `.fill(<arg>)` | `.press_sequentially(<arg>, delay=50)` |

### 4.3 Detection — confidence tiers

Signals are checked top-to-bottom on the **locator chain text**. First match wins.

**High confidence (default ticked, "Recommended" badge):**

- `getByRole('searchbox'` — `searchbox` is by definition a typed search field.
- `getByRole('combobox'` — combobox with text input is the typed-suggest pattern.
- `locator('input[type="search"]'` or `[type=search]` — semantic HTML search input.

**Medium confidence (default ticked, "Likely needs typing" badge):**

Locator chain text contains any of these keywords case-insensitively in a
**name / placeholder / label / aria-label argument**:

```
search   filter   query   find     lookup
autocomp suggest  typeahead
keyword
"search by"  "type to search"  "start typing"  "search anything"
```

Short-name attribute matches (whole-word, `name=` or `id=` argument): `q`, `s`,
`searchTerm`, `keyword`.

**Low confidence (default UNticked, hidden behind "Show all fill steps" toggle):**

`.fill(` on any other locator. Surfaced only so a user with an unusual field
name can opt in manually; not shown by default to avoid noise on long forms.

**Already typed (disabled, pre-ticked, "Already converted" badge):**

The line already calls `.pressSequentially(` / `.press_sequentially(` on the
same locator chain.

### 4.4 The review modal

Plain-language, non-technical. No mention of "pressSequentially", "keystroke",
"XHR", "debounce", or "event" in any user-facing copy. Exact strings in §4.7.

```
┌──────────────────────────────────────────────────────────────────┐
│  Convert Search Inputs                                            │
├──────────────────────────────────────────────────────────────────┤
│  Some inputs only react when you type, letter by letter — search  │
│  boxes, autocomplete fields, filter pickers. Test recordings fill │
│  these in one shot, so the search never runs and the test fails   │
│  even though your app is fine.                                    │
│                                                                   │
│  Converting a step makes the test type into it character by       │
│  character, like a real person. We've pre-selected the steps that │
│  look like search fields — adjust if you know your app better.    │
│                                                                   │
│  [ Convert every step ]   [ Clear all ]   [ Show all type steps ] │
│   "Convert every step" risks slowing typing in regular forms.     │
│                                                                   │
│  ☑  Step 4 — Type into "Search by Candidate Name /"               │
│        Recommended — looks like a search field.                   │
│        line 16:  ...textbox', { name: 'Search by Candidate ...'}  │
│                                                                   │
│  ☐  Step 2 — Type into "Email Address *"                          │
│        Usually not needed — regular form field.                   │
│        line 9:   ...textbox', { name: 'Email Address *' })...     │
│        (hidden until "Show all type steps" is on)                 │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│           [ Skip for now ]      [ Convert Steps (1) ]             │
└──────────────────────────────────────────────────────────────────┘
```

- **"Convert every step"** — master toggle that ticks every visible candidate.
  Its helper text names the tradeoff (slow on regular forms) so a non-technical
  user is not surprised when login takes a second longer.
- **"Show all type steps"** — reveals low-confidence rows (default OFF). A
  power-user escape hatch for "my search field is named `dataLookup` and the
  scan missed it."
- Each row: checkbox, friendly step label, one-line reason, source line for
  reference.
- Already-converted rows render disabled and pre-ticked with the reason replaced
  by "Already converted."
- Apply button counts ticked rows: `Convert Steps (1)`.

### 4.5 Step labels

Reuse the label derivation from Auto-Wait §4.4, with `kind = 'fill'`:

| Locator | Label |
|---|---|
| `getByRole('textbox', { name: 'Search by Candidate Name /' })` | `Type into "Search by Candidate Name /"` |
| `getByPlaceholder('Search by mobile')` | `Type into "Search by mobile"` |
| `getByLabel('Email')` | `Type into "Email"` |
| `locator('#password')` | `Type into "password"` |
| fallback | `Step N` |

The `_describeAction` helper added during Auto-Wait already supports
`kind === 'fill'` — reuse it as-is.

### 4.6 Apply

On `Convert Steps`:

1. Collect ticked candidates.
2. Rewrite the script body **back-to-front**: for each, replace the substring
   `[fillStart, fillEnd)` with the per-language `.pressSequentially(...)` call,
   preserving `fillArg` verbatim.
3. In-editor flow: `editor.setValue(newContent)`.
   Post-record flow: `PUT /api/scripts/<id>` with the new content.
4. Rewritten lines stay inside the BEGIN/END action markers — fully editable in
   the script editor after.

### 4.7 UI copy — exact strings

Rules: no jargon ("pressSequentially", "keystroke", "XHR", "debounce", "event");
every message states *what* and *why*; "fails" always paired with reassurance
that the app itself is fine.

**Modal title:** `Convert Search Inputs`

**Intro (always visible):**

> Some inputs only react when you type, letter by letter — search boxes,
> autocomplete fields, filter pickers. Test recordings fill these in one shot,
> so the search never runs and the test fails even though your app is fine.
>
> Converting a step makes the test type into it character by character, like a
> real person. We've pre-selected the steps that look like search fields —
> adjust if you know your app better.

**Buttons:**

| Element | Label | Helper / sub-text |
|---|---|---|
| Master toggle | `Convert every step` | `"Convert every step" risks slowing typing in regular forms.` |
| Clear toggle | `Clear all` | — |
| Reveal toggle | `Show all type steps` | `Show form fields too, in case the scan missed a search box.` |
| Footer cancel | `Skip for now` | — |
| Footer apply | `Convert Steps (N)` | N = count of ticked rows; disabled when N = 0 |

**Step row — label:** `Step {N} — Type into "{field name}"` (label from §4.5).

**Step row — reason line (one of):**

| Case | Reason text |
|---|---|
| High confidence — search/combobox role / `type=search` | `Recommended — this looks like a search field.` |
| Medium confidence — name / placeholder / label keyword | `Recommended — the field name suggests it is a search or filter.` |
| Low confidence — generic fill | `Usually not needed — regular form field.` |
| Already converted | `Already converted.` |

**Empty state (scan finds no `.fill(`):**

> Nothing to convert here — this script does not type into any inputs.

**Empty state (scan finds fills, but no high / medium matches):**

> No search-style fields detected. Click "Show all type steps" if your app has
> a search field with an unusual name.

**Success toast (after apply):**

> Converted {N} steps to typed input. You can edit them anytime in the script
> editor.

**Post-recording prompt (chained after the Auto-Wait review, §5.5):**

> Recording saved. Convert search fields to typed input so they fire correctly?
> `[ Convert ]`  `[ Not now ]`

---

## 5. Where the code changes — and why

### 5.1 No harness changes

`pressSequentially` / `press_sequentially` are built into Playwright. No helper
to inject. The 4 harness templates are not touched by this feature.

### 5.2 Per-language rewrite snippet on the strategy

**File:** `cli/script_strategies/base.py` — add three strategy hooks (overridden
per language):

- `typed_fill_call(value_source: str) -> str` — given the source-text of the
  fill argument (e.g. `"'asdfdf'"`, `"'{{phone}}'"`), return the replacement
  call. JS/TS: `.pressSequentially(<value_source>, { delay: 50 })`. Python:
  `.press_sequentially(<value_source>, delay=50)`.
- `typed_fill_marker() -> str` — substring to test against a line for the
  already-converted state. JS/TS: `'pressSequentially'`. Python:
  `'press_sequentially'`.
- `fill_call_marker() -> str` — substring the scanner uses to find candidate
  fills. JS/TS / Python both: `'.fill('` — defined per-strategy in case a
  future language differs.

**Why:** mirrors the `settle_call_snippet()` / `is_settle_call()` design from
Auto-Wait §5.2. Strategy already owns per-language transforms; exposing rewrite
text as data lets the scan stay client-side.

### 5.3 Backend — serve scan config

**File:** `web/routes/scripts.py` — extend the wait-config route added by
Auto-Wait (or add `/api/scripts/<id>/typed-input-config`) to also return:

```json
{
  "ok": true,
  "typed_call_template": ".pressSequentially({value}, { delay: 50 })",
  "typed_marker": "pressSequentially",
  "fill_marker": ".fill(",
  "high_confidence_signals": [
    "getByRole('searchbox'",
    "getByRole('combobox'",
    "type=\"search\"",
    "type='search'"
  ],
  "keyword_signals": [
    "search", "filter", "query", "find", "lookup",
    "autocomplete", "suggest", "typeahead", "keyword",
    "search by", "type to search", "start typing", "search anything"
  ],
  "short_name_signals": ["q", "s", "searchTerm", "keyword"]
}
```

- `typed_call_template` — `{value}` placeholder is substituted with the verbatim
  fill argument source-text by the frontend rewriter.
- `typed_marker` — substring frontend checks to set `alreadyTyped`.
- `fill_marker` — the scanner's anchor for candidate detection.
- The three signal arrays drive the §4.3 confidence tiers.

The two configs (wait + typed-input) can share one endpoint — `/api/scripts/<id>/scan-config`
returning both blocks — or stay separate. Pick whichever simplifies the route
file; the frontend asks for what it needs.

No backend scan endpoint — parsing and rewriting are client-side.

### 5.4 Frontend — scan + modal + apply

**File:** `web/static/app.js` — add, mirroring the Auto-Wait functions:

- `_parseFillCandidates(scriptBody, config)` — finds `.fill(` calls, captures
  `locatorChain`, `fillArg`, offsets; produces the candidate objects in §4.2.
- `_classifyFillCandidate(candidate, config)` — sets `signal` and `confidence`
  using the §4.3 rules; sets `recommended`.
- `_describeAction` — already extended in Auto-Wait to handle `kind === 'fill'`;
  reuse as-is.
- `scanAndConvertSearchInputsFromEditor()` — entry point, analogue of
  `scanAndAddWaitsFromEditor()`.
- `_showTypedInputReviewModal(...)` — the modal (§4.4) with "convert every",
  "clear all", "show all type steps".
- `_rewriteScriptWithTypedInputs(content, candidates, picks, config)` —
  back-to-front substring replacement, analogue of
  `_rewriteScriptWithWaits`.

Add the `Scan & Convert Search Inputs` button next to the existing `Scan & Bind`
and `Scan & Add Waits` buttons (4 editor toolbar locations).

### 5.5 Post-recording hook

**File:** wherever the post-record review chain lives (extended by Auto-Wait to
run the wait review after the field-binding review). Add the typed-input
review as a third step after the wait review. Each step is independently
skippable; declining one does not skip the others.

Order, mnemonic: **Bind → Wait → Type.** Bind data first (so the script has
real values), then add waits (so the script does not race the app), then
convert typed inputs (so search-style fields actually fire).

### 5.6 What is NOT changed

- `cli/commands/web/record.py` — no record-time rewrite. Recording stays
  untouched.
- No `auto_typed_input` config flag. Feature is invoked on demand from the UI.
- No harness templates — `pressSequentially` is built into Playwright.

---

## 6. Out of scope

- **Auto-replace at record time** — explicitly rejected (§1, §2). User decides
  per field.
- **Non-English locale keyword matching** — v1 ships English-only. Documented as
  a known limit. Power users can use "Show all type steps" to opt in by hand.
  Locale-aware keywords are a possible follow-up but not in this version.
- **Configurable `delay`** — hardcoded `50ms` per char in the rewrite template.
  A power user can hand-edit a converted line. Global override (e.g.
  `config.json` `typed_input: { delay_ms: 30 }`) is a follow-up.
- **Detection by attribute introspection** (querying the running app for `role`
  or `type=search` instead of regexing the locator source) — requires a live
  page handle which the scan does not have. Locator-source signals are
  sufficient for codegen output, which uses consistent `getByRole` / `locator`
  forms.
- **Conversion of `.type(` (deprecated Playwright API)** — codegen never emits
  it; skipped. A user who hand-wrote `.type(` can hand-rewrite to
  `.pressSequentially(`.
- **Removing the redundant pre-fill `.click()`** — codegen emits `.click()` then
  `.fill()` on the same locator; once `.fill()` becomes `.pressSequentially()`
  the click is harmless but unnecessary. Leaving it in keeps the rewrite to a
  single call and preserves the user's recording as much as possible.

## 7. Rollout

1. Strategy hooks: `typed_fill_call()`, `typed_fill_marker()`,
   `fill_call_marker()` on base + per-strategy overrides.
2. Backend scan-config route extended (or new endpoint) — returns the
   templates, marker, and signal arrays.
3. Frontend: parse + classify + modal + rewrite; wire the `Scan & Convert
   Search Inputs` button into all 4 editor toolbars.
4. Chain the typed-input review after the wait review in the post-recording
   flow.
5. Re-record the client's Candidates script, run Scan & Add Waits, run Scan &
   Convert Search Inputs, verify the search XHR fires and the "No data found"
   assertion passes (timeline below).

### Verification timeline (after user converts the Candidates search fill)

```
t=0.00s  click "Candidates"            -> GET /api/candidates fires
t=0.01s  _waitForNetworkSettle         -> blocks on in-flight = 1
t=4.50s  table renders, helper resolves
t=4.51s  click search textbox          -> field focused
t=4.52s  pressSequentially("asdfdf", { delay: 50 })
                                       -> 'a': keydown/keyup/input, debounce armed
                                          'asdf' typed in ~200ms
                                          'asdfdf' fully typed at t=4.82s
t=5.12s  debounce (300ms) elapses      -> GET /api/candidates?search=asdfdf fires
t=5.13s  _waitForNetworkSettle         -> grace probe, in-flight = 1, BLOCKS
t=5.90s  search response resolves      -> in-flight = 0
t=6.30s  quiet window elapsed          -> helper resolves
t=6.31s  expect("No data found")       -> text present -> PASSED
```
