# Review & Improve Wizard — Combined Scan Plan

## Goal

Three "scan & apply" passes — **Bind data**, **Add waits**, **Convert search
inputs** — that today live (or are planned to live) as three independent toolbar
buttons + three independent post-record modals. As feature count grows the
toolbar clutters and post-record fatigue rises. This plan folds all three into
**one entry point** (`Review & Improve`) backed by a 3-step wizard, while
keeping the underlying scan / modal / rewrite implementations **untouched and
independently callable** — the wizard is an orchestration shell, not a rewrite
of the three features.

Companion plans (still authoritative for per-feature internals):

- `docs/auto-wait-plan.md` — fully implemented (Phase 1)
- `docs/typed-input-plan.md` — planned, retained for §1–§3 (motivation,
  detection rules, rewrite shape). UI sections (§4) are superseded by this
  document.

Hard constraints carried forward from those plans:

- No record-time auto-mutation. User reviews and ticks.
- Blast-radius separation: each phase keeps its own Apply button and its own
  ticked-row set; one master "Apply all" across phases is rejected.
- Scripts stay editable post-apply; rewrites land inside existing action
  markers.

---

## 1. Current state — verified inventory

Mapped against the working tree (branch `task/dev-auto-wait-codegen`).

### 1.1 Scan & Bind (implemented, in master flow)

- Backend: `GET /api/scripts/sensitive-patterns` — `web/routes/scripts.py:27`.
- Frontend functions (`web/static/app.js`):
  - `_parseFillCalls()` — line 1090
  - `_showFieldReviewModalCore(useOverlay)` — line 1251
  - `_showFieldReviewModal()` — line 1525 (post-record)
  - `_showFieldReviewModalForEditor()` — line 2253 (in-editor overlay)
  - `_rewriteScriptWithBindings()` — line 1540
  - `scanAndBindFromEditor()` — line 2213
- Toolbar wiring: 4 locations (`createScriptModal` 1645, `_openImportedScriptEditor`
  1905, `_renderImportBanner` 2010, `editScriptModal` 2124).
- Post-record wiring: `reviewRecordedScriptFields(...)` called at line ~1075,
  step 1 of the current 2-step chain.

### 1.2 Scan & Add Waits (implemented, current branch)

- Backend: `GET /api/scripts/wait-config` — `web/routes/scripts.py:54` returns
  per-language `settle_call`, `settle_marker`, `recommend_words`.
- Strategy hooks (`cli/script_strategies/base.py:90,99,106`): `settle_call_snippet()`,
  `settle_marker()`, `is_settle_call()`. Python override at
  `cli/script_strategies/python_strategy.py:222`. JS/JS-test/TS-test inherit
  defaults; harness templates in each strategy ship the helper.
- Frontend functions (`web/static/app.js`): `_detectScriptLanguage`,
  `_describeAction` (2291), `_fillFieldName`, `_isFieldFocusClick`,
  `_classifyAction` (2332), `_parseActionCalls` (2365), `_waitReasonText`
  (2408), `_rewriteScriptWithWaits` (2447), `_qcWaitReviewSync` (2481),
  `_qcWaitReviewSetAll` (2494), `_showWaitReviewModalCore` (2504),
  `scanAndAddWaitsFromEditor` (2595), `_promptAddWaitsAfterRecording` (2620),
  `_waitChangeToast` (2614).
- Toolbar wiring: 4 locations, side-by-side with the Bind button (lines 1646,
  1906, 2011, 2125).
- Post-record wiring: `_promptAddWaitsAfterRecording(res.id)` at line 1082,
  step 2 of the current chain.
- CSS: `.qc-toggle*` rules in `web/static/style.css:1232+`.

### 1.3 Scan & Convert Search Inputs (planned, not started)

- No backend route. No strategy hooks. No frontend functions. No buttons.
- Will be added by this plan, then surfaced through the wizard rather than as a
  third toolbar button.

### 1.4 What this means for the wizard

- **Reuse:** all three features keep their existing parse / classify / rewrite
  helpers. The wizard imports them; it does not duplicate them.
- **Hide, do not delete:** the two existing toolbar buttons (Bind, Add Waits)
  stay in the DOM, marked hidden — see §4.1. Same for the post-record direct
  prompts, which become wizard steps instead.
- **One gap to close:** typed-input backend + frontend (§3, §5). Everything
  else is orchestration.

---

## 2. UX shape — Option C (wizard + dropdown)

Decided over Option A (3 separate buttons, current state) and Option B (one
mega-modal with mixed Apply). Reasoning recapped:

- **A** clutters the toolbar as feature count grows and gives 3 sequential
  post-record modals that users skip from fatigue.
- **B** mixes blast radius — a single Apply lets a tired user rewrite a masked
  input field by accident — and hides the natural ordering (Bind → Wait → Type).
- **C** batches the entry point but keeps phases isolated. Standard pattern:
  IntelliJ refactor wizards, GitHub PR review steps, VS Code multi-step
  command palette.

### 2.1 Entry point — one primary button, optional dropdown

Replace the two existing toolbar buttons in each of the 4 locations with one
**Review & Improve** button. A small `▼` chevron on the button opens a dropdown
for surgical access:

```
[ Review & Improve ▼ ]
   ├ Run full review (Bind → Waits → Typed inputs)
   ├ ── 
   ├ Bind data only
   ├ Add waits only
   └ Convert search inputs only
```

- Default click on the button body → runs the full 3-step wizard.
- Dropdown items → invoke the existing single-feature modals directly
  (`scanAndBindFromEditor`, `scanAndAddWaitsFromEditor`,
  `scanAndConvertTypedInputsFromEditor`). Those functions stay public on
  `window.qcApp` (or the equivalent) so the dropdown is a thin shim.

### 2.2 Wizard shape — jump-ahead stepper (Option B, shipped)

**Decision history.** Three layout options were considered:

- **A. True tabs / shared shell** — one modal whose body swaps between three
  phase views. Rejected: Bind modal's `_showFieldReviewModalCore` is ~280
  lines with env-loading, per-row dropdowns and a `closeOverlayModal`
  monkey-patch; refactoring it to a body-only renderer risks regressing
  already-working code.
- **B. Stepper strip with jump-ahead** (shipped). Each phase still has its
  own modal — Bind / Wait / Typed cores stay untouched in their internals.
  At the top of every phase modal a **clickable stepper strip** is rendered
  showing all three phases, their counts and status. The current step is
  the disabled pill; the user can click any other populated step to jump
  there directly. Order is suggested (Bind → Wait → Typed) but not forced.
- **C. Drop wizard, dropdown-only** — rejected: regresses the "one button does
  it all" promise.

**Why B.** Modern wizard pattern (Stripe checkout, Linear onboarding, GitHub
PR review): visible structure, free navigation, per-phase apply. Each phase
keeps its blast-radius separation (independent ticks, independent Apply, no
mega-button). Adds a single stepper-header optional param to each existing
modal core — minimum surface for maximum UX gain.

**Layout.** Each phase modal opens with the stepper as its first body
element:

```
┌─ Review & Improve ──────────────────────────────────────────────────┐
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│  │ 1 Bind data  │  │ 2 Add waits  │  │ 3 Typed in.  │                │
│  │  3 candidates│  │ ✓ applied (2)│  │ 1 candidate  │                │
│  └──────────────┘  └──────────────┘  └──────────────┘                │
│  Click any step to jump.                                              │
├──────────────────────────────────────────────────────────────────────┤
│  (current phase body — Bind rows, Wait rows, or Typed rows)           │
├──────────────────────────────────────────────────────────────────────┤
│              [ Skip for now ]      [ Apply (N) ]                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Scan timing.** Unlike the forward-only draft, scans run **up-front for all
three phases** so the stepper can show candidate counts immediately. After
each Apply the wizard re-scans every phase against the mutated script and
updates the stepper counts (a Wait inserted in phase 2 shifts offsets in
phase 3, so phase 3's candidate list is recomputed). Pre-scanning is cheap
— it is all client-side and the configs (`/wait-config`, `/typed-input-config`)
are fetched once each and cached on the wizard state.

**Pill states** (CSS classes):

| State | Class | Badge text | Clickable? |
|---|---|---|---|
| Current | `.is-current` | candidate count or "applied" / "skipped" / "none found" | No (disabled) |
| Applied | `.is-applied` | `applied (N)` | Yes if count > 0 (re-evaluate remainder) |
| Skipped | `.is-skipped` | `skipped` | Yes if count > 0 |
| Auto-empty | `.is-empty` | `none found` | No (disabled) — nothing to jump to |
| Pending | (no extra class) | `N candidate(s)` | Yes |

**Jump semantics.** Clicking a non-current populated pill resolves the
current phase's promise with `{action: 'jump', targetIdx}`. The current
phase's ticked-but-unapplied state is discarded — same contract as
Skip-for-now. Phase status stays `pending` so the stepper continues to
offer it. Applies are still irreversible (a previously applied phase shows
the ✓ badge and re-clicking opens it again against the latest content).
- A **content slot** holding the current phase's rows + per-phase controls
  (master toggle, `Show all`, etc.).
- A **footer** with `← Back` (disabled on step 1), `Skip this step` (advances
  without applying), and the phase's **Apply button** (`Apply Bindings (N)`,
  `Apply Waits (N)`, `Convert Steps (N)` — counts the phase's ticked rows).
- A **dirty indicator** on the stepper: if a step was applied, badge shows
  "Applied (N)"; if skipped, "Skipped"; if pending, blank.

```
┌─ Review & Improve ──────────────────────────────────────────────────┐
│  ① Bind data  ──  ② Add waits  ──  ③ Typed inputs                    │
│  Applied (3)        ◉ current        pending                          │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2/3 — Add waits                                                 │
│  (intro + rows for current phase, same as today's modal body)         │
├──────────────────────────────────────────────────────────────────────┤
│  [ ← Back ]              [ Skip this step ]     [ Apply Waits (2) ]   │
└──────────────────────────────────────────────────────────────────────┘
```

Apply ≠ Next. Applying a phase **also advances**. `Skip this step` advances
without applying. `← Back` returns to a previous phase but **does not undo** a
previously applied phase — applies are irreversible (the user can re-edit in the
script editor). This matches the current per-feature modal contract.

### 2.3 Closure behaviour

- **Skip for now** advances within the wizard to the next pending populated
  phase (script order, wraps). If none remain the wizard exits with a
  summary toast.
- **X / backdrop click** closes the modal but currently does **not** signal
  the wizard's phase promise — the wizard hangs awaiting that phase. Known
  limitation, deferred to v2 (§7 plan §8): hook close via MutationObserver
  or a temporary monkey-patch of `closeOverlayModal` to resolve as
  `{action: 'close'}`. Workaround: re-open the wizard from the toolbar.
- No close-confirm dialog yet. Applied phases are already saved (editor mode
  → live editor; post-record → PUT'd), so accidental X-close loses only the
  current phase's in-progress ticks, which the user can redo by re-opening
  the wizard. Confirm dialog is cheap to add later but not load-bearing.
- After the final step's Apply (or Skip), the wizard shows a one-line summary
  toast: `Applied 3 bindings, 2 waits, 1 typed input.` Skipped phases are
  omitted from the summary.

### 2.4 Empty steps

If a phase finds zero candidates it auto-skips with a small note on the
stepper:
```
② Add waits — nothing to add, skipped automatically
```
The wizard advances to the next phase without rendering an empty modal body.
If **all three** phases come up empty, the wizard does not open; instead it
shows the toast: `Nothing to review — the script looks clean.`

### 2.5 Post-record chain → wizard

The current chain at `app.js:1075–1083`:
```js
await reviewRecordedScriptFields(res.id, env_name)   // step 1
await _promptAddWaitsAfterRecording(res.id)          // step 2
```
…becomes a single call to the wizard initialised on the freshly recorded
script id. The wizard handles all three phases in one modal. No more cascade of
separate prompts.

---

## 3. The typed-input gap — what still needs to be built

The wizard is mostly orchestration, but step 3 needs the Typed-Input feature to
exist. Implementation borrows the Auto-Wait scaffold one-for-one. See
`docs/typed-input-plan.md` §1–§3 and §5 for motivation, detection rules, and
rewrite semantics; only the UI sections (its §4) are superseded.

### 3.1 Strategy hooks

Add to `cli/script_strategies/base.py` (mirroring `settle_*` at lines 90/99/106):

- `fill_call_marker() -> str` — substring the client scanner anchors on for
  `.fill(` candidates. Base returns `".fill("`.
- `typed_fill_marker() -> str` — substring identifying an already-converted
  call (for the `alreadyTyped` flag on re-scan). Base returns
  `"pressSequentially"`.
- `typed_fill_call_template() -> str` — returns a per-language **template
  string** containing the literal placeholder `{value}`, which the client-side
  rewriter substitutes with the verbatim source-text of the original `.fill()`
  argument. Base returns `".pressSequentially({value}, { delay: 50 })"`.

Override in `python_strategy.py` (mirroring its `settle_*` override at line
222): `typed_fill_marker` → `"press_sequentially"`,
`typed_fill_call_template` → `".press_sequentially({value}, delay=50)"`.

JS / JS-test / TS / TS-test inherit defaults.

Rationale for template-with-placeholder instead of a function taking the
value: the client gets the template via JSON (§3.2) and does substitution in
JavaScript. A method that takes the value would force a second round-trip
per `.fill()` candidate just to render the call.

### 3.2 Backend route

Add to `web/routes/scripts.py`, beside `/wait-config` at line 54. The
`language` query param mirrors `/wait-config`'s contract exactly and lets the
route pick the right strategy for language-specific markers (e.g. Python
returns `press_sequentially` while JS/TS return `pressSequentially`):

```
GET /api/scripts/typed-input-config?language=<language>
→ {
    "ok": true,
    "fill_marker": ".fill(",
    "typed_marker": "pressSequentially",       // or press_sequentially for python
    "typed_call_template": ".pressSequentially({value}, { delay: 50 })",
    "high_confidence_signals": [...],          // role / type=search markers
    "keyword_signals": [...],                  // name/placeholder/label words
    "short_name_signals": ["q", "s", "searchTerm", "keyword"]
  }
```

Detection word lists come from `typed-input-plan.md` §4.3.

Optionally collapse `/wait-config` and `/typed-input-config` into a single
`/scan-config` returning both blocks. Decision: **keep separate**. Reasons:
- Each phase fetches its own config lazily so a user using only the dropdown
  shortcut does not pull config they will not use.
- `/wait-config` is already deployed; renaming touches the working tree
  unnecessarily.
- Two small routes are easier to evolve than one omnibus payload.

### 3.3 Frontend additions (`web/static/app.js`)

All modeled on the Auto-Wait functions of the same shape:

- `_parseTypedInputCandidates(scriptBody, config)` — finds `.fill(` calls,
  captures `locatorChain`, `fillArg`, `fillStart`, `fillEnd`. **Sibling to the
  existing `_parseFillCalls()` at line 1090** (which extracts arguments for
  Bind but does not record call-substitution offsets). The two parsers are
  intentionally distinct — Bind rewrites argument substrings, Typed-Input
  rewrites the whole `.fill(...)` call — and the name disambiguates them. If a
  locator-chain extraction helper can be cleanly split out of `_parseFillCalls`
  without touching its call sites, reuse it; otherwise duplicate the few
  lines. Do not refactor Bind.
- `_classifyTypedInput(candidate, config)` — applies §4.3 confidence tiers
  from `typed-input-plan.md`.
- `_typedInputReasonText(candidate)` — copy table from
  `typed-input-plan.md` §4.7.
- `_rewriteScriptWithTypedInputs(content, candidates, picks, config)` —
  back-to-front substring replacement of `[fillStart, fillEnd)` using
  `typed_call_template`.
- `_showTypedInputReviewModalCore({ candidates, config, useOverlay })` —
  modal body. Same structural pattern as `_showWaitReviewModalCore` (line
  2504). The wizard calls this in **embedded mode** (renders body into the
  wizard's content slot, no own footer). The direct-dropdown entry calls it in
  **standalone overlay mode** (own modal shell + footer), reusing the existing
  overlay infrastructure.
- `scanAndConvertTypedInputsFromEditor()` — direct entry point used by the
  dropdown's "Convert search inputs only" item and any legacy callers.

No harness changes; `pressSequentially` is native.

---

## 4. Wizard shell — what to build

### 4.1 Hiding the existing buttons (not removing)

In all 4 toolbar locations the current markup looks roughly like:

```html
<button data-act="scan-bind">Scan & Bind</button>
<button data-act="scan-waits">Scan & Add Waits</button>
```

Action: wrap each pair in a hidden container, add the new Review button:

```html
<div class="qc-legacy-scan-buttons" hidden>
  <button data-act="scan-bind">Scan & Bind</button>
  <button data-act="scan-waits">Scan & Add Waits</button>
  <!-- future: scan-typed will land here -->
</div>
<div class="qc-review-improve">
  <button data-act="review-improve">Review & Improve</button>
  <button data-act="review-improve-menu" aria-label="More options">▼</button>
</div>
```

- `hidden` attribute (HTML5) ensures CSS-irrelevant hiding; no display tricks
  needed.
- The `[data-act=...]` listeners stay registered. If a user enables a feature
  flag or runs the legacy entry from devtools (`qcApp.scanAndBindFromEditor()`),
  it still works.
- A single CSS rule `.qc-legacy-scan-buttons { display: none; }` is also
  applied for defence in depth. No JS toggle to re-show — these are dead UI by
  intent; the dropdown is the supported escape hatch.
- **Rollback path:** flip the `hidden` attribute off in markup (or remove the
  CSS rule) to bring the old buttons back if the wizard ships with a defect.

### 4.2 Wizard module structure (`web/static/app.js`)

Add a single cohesive block, conceptually one "module":

- `_buildReviewWizardState(scriptId, scriptBody, config)` — runs all three
  scans up-front and stores the candidate arrays + per-phase status (`pending`,
  `auto-skipped`, `applied`, `skipped`). Up-front scan is fast (all
  client-side), and lets the stepper header show counts immediately.
- `_renderReviewWizardShell(state)` — mounts the modal shell, stepper, content
  slot, footer.
- `_renderReviewWizardPhase(state, idx)` — swaps content slot. For phase 1
  calls `_showFieldReviewModalCore` in embedded mode; phase 2 calls
  `_showWaitReviewModalCore` in embedded mode; phase 3 calls
  `_showTypedInputReviewModalCore` in embedded mode.
- `_applyReviewWizardPhase(state, idx)` — calls the phase's rewrite function,
  PUTs the new script body, updates `state.scriptBody` so subsequent phases scan
  the latest content (e.g. waits added in phase 2 do not become typed-input
  candidates in phase 3).
- `openReviewWizard(scriptId, { source: 'editor' | 'post-record' })` — public
  entry. Loads the script, fetches the two scan-configs in parallel, runs
  scans, opens the shell.

### 4.3 Stepper-strip injection contract (shipped)

Instead of the originally drafted `renderInto` embedded-body contract (a
heavier refactor of each modal core), the shipped implementation passes a
single optional **`wizardStepper`** HTML string to each modal core:

- `_showFieldReviewModalCore({ ..., wizardStepper = '' })`
- `_showWaitReviewModalCore({ ..., wizardStepper = '' })`
- `_showTypedInputReviewModalCore({ ..., wizardStepper = '' })`

If set, the core prepends the HTML to its body and swaps the modal title to
`"Review & Improve"`. If empty (standalone callers — dropdown shortcuts,
devtools), the core renders its original title and body unchanged. Zero
regression risk for the existing standalone paths.

The stepper HTML itself comes from `_wizardStepperHTML(state)`. Click
handlers on the pills call `window._qcWizardJumpTo(idx)`, which:

1. Reads `window._qcWizardCurrent` (set by `_wizardInstallCurrent` before
   each phase modal opens) to find the current phase's resolver + close
   function.
2. Calls the close function to dismiss the modal.
3. Resolves the phase promise with `{action: 'jump', targetIdx: idx}`.

The state machine in `openReviewWizard` then routes to `targetIdx` and
opens that phase's modal.

### 4.4 Stepper UX details (shipped)

- **Empty pills** (`count === 0`) render disabled with a `none found` badge.
  Wizard auto-skips them when walking phases in script order. User cannot
  click them — avoids the silent "click → auto-skip → re-route" confusion
  caught in review.
- **Applied pills** keep a ✓ badge and stay clickable **if** rescan still
  finds remaining candidates (partial apply leaves unconverted fills).
  Clicking re-opens the phase against the post-apply content; the candidate
  list is freshly computed, so previously-applied changes do not reappear.
- **Re-applies are additive in the summary toast.** `phase.applied +=
  res.applied` on every Apply, so the end-of-wizard toast reports cumulative
  changes per phase.
- **No `Back` button.** Stepper is the navigation surface — adding a Back
  button would duplicate it. Forward-with-wrap traversal handles auto-advance
  after Apply / Skip.
- **Keyboard.** Not yet implemented; pointer navigation only. Deferred to v2.

### 4.5 Toast / summary (shipped)

Single closing toast listing only phases with **non-zero** applied changes:
`Review complete. Applied: 3 bindings, 2 waits, 1 typed input.` Phases the
user skipped or unticked completely are omitted. If every phase ended at
zero changes (user opened wizard and skipped each step, or no candidates
anywhere) the toast is suppressed entirely. Per-phase toasts inside the
wizard are also suppressed — only this single summary fires, avoiding the
"two-toast" noise problem caught in Step 3 review.

### 4.6 Single Apply All — explicitly rejected

Even though the wizard surfaces all three phases in one modal, there is no
"Apply everything" mega-button. Three separate `Apply` clicks (or `Skip`s) is
the contract. Auditing 30+ rows under one button is exactly the footgun this
plan rejects.

---

## 5. Code change map

### 5.1 Backend
| File | Change | Notes |
|---|---|---|
| `web/routes/scripts.py` | Add `/api/scripts/typed-input-config` route | Mirrors `/wait-config` at line 54. ~40 lines. |
| `cli/script_strategies/base.py` | Add `typed_fill_call`, `typed_fill_marker`, `fill_call_marker` | Mirrors `settle_*` hooks at lines 90/99/106. |
| `cli/script_strategies/python_strategy.py` | Override `typed_fill_call`, `typed_fill_marker` | Mirrors `settle_*` override at line 222. |

No new harness helpers — `pressSequentially` / `press_sequentially` are
native. No changes to `cli/script_strategies/javascript*` or
`typescript_test_strategy.py` (they inherit base).

### 5.2 Frontend — typed-input (new)
| Function | Location guidance | Mirrors |
|---|---|---|
| `_parseTypedInputCandidates` | After `_parseActionCalls` (~app.js:2365) | `_parseActionCalls` |
| `_classifyTypedInput` | After `_classifyAction` (~2332) | `_classifyAction` |
| `_typedInputReasonText` | After `_waitReasonText` (~2408) | `_waitReasonText` |
| `_rewriteScriptWithTypedInputs` | After `_rewriteScriptWithWaits` (~2447) | `_rewriteScriptWithWaits` |
| `_showTypedInputReviewModalCore` | After `_showWaitReviewModalCore` (~2504) | same shape |
| `scanAndConvertTypedInputsFromEditor` | After `scanAndAddWaitsFromEditor` (~2595) | same shape |

### 5.3 Frontend — wizard shell (shipped)

Added as one contiguous block after `_promptAddWaitsAfterRecording` in
`web/static/app.js`. Final shape (Option B, state-machine with stepper):

- `_wizardLoadContext(source, scriptId)` — editor vs post-record content fetch
- `_wizardCommit(source, scriptId, newContent)` — editor.setValue vs PUT
- `_wizardStepperHTML(state)` — stepper pills, click → `_qcWizardJumpTo`
- `_qcWizardJumpTo(idx)` — global handler, closes current modal, resolves
  current phase promise with `{action: 'jump', targetIdx}`
- `_wizardScanBind` / `_wizardScanWait` / `_wizardScanTyped` — per-phase
  scan + config caching (configs fetched once each, cached on `state.cfgs`)
- `_wizardScanAll(state)` — calls all three; invoked initially and after
  each Apply
- `_wizardInstallCurrent(state, resolve, modalCloseFn)` — stashes phase
  resolver on `window._qcWizardCurrent` so the global jump handler can find
  it
- `_wizardPhaseBind` / `_wizardPhaseWait` / `_wizardPhaseTyped` — each
  builds candidates from cached scan, opens the corresponding
  `_show*ReviewModalCore` with `wizardStepper` HTML + onApply / onSkip that
  resolve to `{action, applied, newContent}`
- `_wizardSummaryToast(state)` — final toast listing non-zero applied
  phases
- `_wizardRunCurrentPhase(state)` — dispatch by phase id
- `openReviewWizard(scriptId, opts)` — public entry. Loads content,
  pre-scans all phases, runs a state-machine loop:
  - dispatch current phase → result
  - `jump` → set currentIdx, continue
  - `applied` → update status + cumulative applied, re-scan all, find next
    pending populated phase, continue
  - `skipped` / `auto-skipped` → mark, advance to next, continue
  - no pending populated phases left → break + summary toast
  - sentinel iteration cap (64) as belt-and-braces against pathological
    jump cycles

The shared `wizardStepper` parameter (HTML string) is the only addition to
each `_show*ReviewModalCore` (§4.3) — far lighter than the originally
drafted `renderInto`/`apply`/`dispose` contract.

### 5.4 Frontend — toolbar markup
In each of the 4 toolbar locations (`app.js:1645/1646`, `1905/1906`,
`2010/2011`, `2124/2125`):

1. Wrap the existing two buttons in `<div class="qc-legacy-scan-buttons" hidden>`.
2. Add the new `Review & Improve` button + chevron next to the wrapper.
3. Wire the new buttons:
   - Main click → `openReviewWizard(scriptId, { source: 'editor' })`.
   - Chevron click → context menu with 4 items (`Run full review`, `Bind data
     only`, `Add waits only`, `Convert search inputs only`).

### 5.5 Frontend — post-record chain
At `app.js:1075–1083`, replace the two prompts with one:

```js
await openReviewWizard(res.id, { source: 'post-record' });
```

The old `reviewRecordedScriptFields` and `_promptAddWaitsAfterRecording`
functions stay defined — they just stop being called from the chain. They
remain available for dropdown callers and devtools.

### 5.6 CSS additions (`web/static/style.css`)
- `.qc-review-improve` — button container layout.
- `.qc-review-improve__chevron` — secondary chevron button.
- `.qc-review-menu` — dropdown menu styling.
- `.qc-wizard` — modal width / stepper layout.
- `.qc-wizard__stepper` — horizontal step indicator.
- `.qc-wizard__step` — per-step pill (states: current / applied / skipped /
  pending / empty).
- `.qc-wizard__body` — content slot.
- `.qc-wizard__footer` — Back / Skip / Apply layout.
- `.qc-legacy-scan-buttons` — `display: none` defence in depth.

Estimated ~80 CSS lines, ~700 JS lines (wizard shell + typed-input).

---

## 6. Rollout (shipped, Steps 1–3 + Option B refactor)

Four PR-sized increments delivered in one branch. Each step ended in a
working app. **Typed-Input never exposed as a standalone toolbar button**;
it ships as part of the wizard's step 3. The existing Bind and Wait buttons
stay in DOM the whole time and are hidden in Step 3 when the wizard goes
live. Step 4 (Option B refactor) replaced the forward-only sequential
chain with a jump-ahead stepper.

### Step 1 — Typed-Input backend + strategy hooks ✓
- Add `typed_fill_call`, `typed_fill_marker`, `fill_call_marker` to
  `cli/script_strategies/base.py`.
- Override in `cli/script_strategies/python_strategy.py`.
- Add `/api/scripts/typed-input-config` route to `web/routes/scripts.py`,
  mirroring `/wait-config` (line 54), accepting the same `language` query
  param.
- Smoke test: hit the route for each language strategy.

### Step 2 — Typed-Input frontend functions (not yet wired to any UI) ✓
- Add the 6 functions in §5.2 (`_parseTypedInputCandidates`,
  `_classifyTypedInput`, `_typedInputReasonText`,
  `_rewriteScriptWithTypedInputs`, `_showTypedInputReviewModalCore`,
  `scanAndConvertTypedInputsFromEditor`).
- **No new toolbar button added in this step.** No post-record wiring.
- `scanAndConvertTypedInputsFromEditor` is exported on `window.qcApp` so it is
  callable from devtools for end-to-end smoke test before the wizard wraps
  it.

### Step 3 — Wizard shell + entry-point swap (single PR) ✓
- Add `_buildReviewWizardState`, `_renderReviewWizardShell`,
  `_renderReviewWizardPhase`, `_applyReviewWizardPhase`, `openReviewWizard`.
- Extend the 3 `_show*ReviewModalCore` functions with the `renderInto` /
  `apply` / `dispose` contract (§4.3).
- Add wizard CSS.
- In all 4 toolbar locations:
  - Wrap the existing Bind + Wait buttons in
    `<div class="qc-legacy-scan-buttons" hidden>`.
  - Add the `Review & Improve` button + chevron + dropdown.
- Replace the post-record cascade at `app.js:1075–1083` with a single
  `openReviewWizard(res.id, { source: 'post-record' })` call.
- Old scan functions and legacy buttons remain in DOM (hidden), callable from
  the dropdown and devtools.

**Rationale for collapsing former Steps 3+4 into one PR:** if the wizard ships
without the entry-point swap, the toolbar has Bind + Wait visible plus a
hidden wizard nobody can reach — confusing intermediate state with no value
to ship-test. Better to gate the user-visible change behind one PR.

### Step 4 — Option B refactor: jump-ahead stepper ✓
- Replaced the forward-only sequential `await phase1; await phase2; await
  phase3` chain in `openReviewWizard` with a state-machine loop driven by
  the stepper.
- Added `_wizardStepperHTML(state)`, `_qcWizardJumpTo(idx)`,
  `_wizardScanAll`, `_wizardInstallCurrent`, `_wizardRunCurrentPhase`.
- Threaded a single optional `wizardStepper` HTML string into each
  `_show*ReviewModalCore` (§4.3). Modals prepend it and swap title to
  "Review & Improve" when set; standalone callers unchanged.
- Disabled empty-phase pills (caught in review: clicking an empty pill
  produced a silent auto-skip + re-route).
- CSS `.qc-wizard-stepper` + per-state pill classes appended to
  `web/static/style.css`.

### Step 5 — Verification on the client's failing script (deferred — needs browser)
- Re-record the Candidates flow.
- Run the wizard end-to-end: bind `asdfdf` → confirm Auto-Wait step →
  convert the search field. Optionally use the stepper to jump straight to
  the typed-input phase.
- Verify the search XHR fires (timeline from `typed-input-plan.md` §7) and
  `expect("No data found")` passes.
- **Rollback path** (if the wizard ships with a defect): unhide the legacy
  buttons (flip the `hidden` attribute on `.qc-legacy-scan-buttons`, drop
  the CSS hide rule) and revert the post-record `openReviewWizard` call to
  the prior two-call cascade. Step 1+2 code stays; Step 3+4 is the only
  revert target.

---

## 7. Out of scope (or deferred to v2)

- **Deleting legacy scan functions.** Stay live behind the dropdown
  shortcuts and as devtools entry points. Removal is a separate cleanup PR
  after the wizard has been in production for ≥1 release.
- **Undo for applied phases.** A phase's Apply is irreversible inside the
  wizard. Re-editing happens in the script editor. The stepper does re-open
  applied phases against fresh content, so the user can rebind / re-wait /
  re-convert as needed.
- **X / backdrop close resolves wizard as 'close'.** Currently the wizard
  hangs awaiting the phase promise when the modal is X-closed (§2.3).
  Workaround: re-open from the toolbar. Fix in v2 via MutationObserver on
  the modal root, or a scoped monkey-patch of `closeOverlayModal`.
- **Close-confirm dialog.** Trivial to add once X-close is handled; left out
  for v1 since the loss is bounded (only the current step's unapplied ticks).
- **Keyboard navigation across the stepper.** Pointer-only for now. v2 can
  add `→` / `←` between pills when no input is focused.
- **A 4th phase.** Selector hardening, schema validation, etc. — drop into
  the stepper as step 4 — designed-in shape but not built here.
- **Configurable per-phase defaults.** `delay: 50`, settle quiet window,
  high-confidence keyword lists stay hardcoded as in their respective plans.
- **Mobile / narrow viewport layout.** The script editor itself is
  desktop-first; the wizard inherits that. Responsive pass is a follow-up.
- **Mixed-Apply ("Apply everything") button.** Rejected (§4.6).
- **Locale-aware keyword detection for typed input.** English-only,
  matching `typed-input-plan.md` §6.

---

## 8. Open questions / resolved decisions

1. **Dropdown library / pattern.** Resolved: inline minimal markup +
   click-outside handler in `_toggleReviewMenu`. No new dependency.
2. **Wizard width.** Resolved: all wizard modals use the existing `'lg'`
   size (`max-width: 960px`). Stepper fits one row of three pills at this
   width with room to wrap on narrower viewports.
3. **Empty-state for the post-record path.** Resolved: if all three phases
   auto-skip, the wizard fires a single toast (`Nothing to review — script
   looks clean.`) and exits. Visible evidence the post-record pass ran.
4. **Persisting "Don't ask after recording."** Still deferred. Cheap to add
   later (one bool in `config.json`) but not needed for v1.
5. **X-close on the modal.** Known limitation, see §2.3 and §7. v2 work.
