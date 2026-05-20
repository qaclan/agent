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

### 2.2 Wizard shape — persistent shell + compact tabs (shipped)

**Decision history.** Three layout options were considered, in shipping
order:

- **A. Forward-only sequential chain** (initial draft). Rejected: user
  cannot navigate freely between phases. Forced order. Skipping a phase
  required opening + closing its modal.
- **B. Stepper strip with jump-ahead modals** (shipped Step 3). Each
  phase opened its own modal with a stepper header that let the user jump.
  Worked, but every jump tore down and re-opened a modal — visible flip /
  flicker, animations re-played, modal-card DOM rebuilt. Still felt like
  "three separate modals" not "one tool."
- **C. Persistent shell + compact tabs** (shipped Step 5, current). One
  modal opens and stays open for the whole flow. A compact tab strip at
  the top swaps the body in-place on tab click. No modal teardown between
  phases — same modal-card, just different body HTML and a re-titled
  Apply button. Feels like one tool with three views.

**Why C.** Standard pattern for any multi-section configuration UI: VS
Code's panel tabs, GitHub repo settings, Stripe dashboard sub-views,
Linear's filter+sort panel. The user's complaint with B was concrete: the
flip animation made it feel like the wizard was opening *new* modals
between phases instead of moving between sections of one.

**Layout.**

```
┌─ Review & Improve ──────────────────────────────────────────────────┐
│  Bind ⓷   Waits ②   Typed ① ✓                                      │  <-- compact tabs
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  <current phase body — Bind rows, Wait rows, or Typed rows>          │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│   [ Skip step ]                              [ Apply Bindings (3) ]  │
└──────────────────────────────────────────────────────────────────────┘
```

- Single-line tabs with count badge + status icon (✓ applied, – skipped).
- Active tab: underline accent + bold.
- Empty tabs disabled (greyed).
- Tab-strip height ~32px (vs old stepper ~80px).

**Scan timing.** Same as B: scans run up-front for all three phases so
tab counts appear immediately. After each Apply the wizard re-scans
every phase against the mutated script and re-renders the tab strip
(via `_wizardRenderTabs(state)`). Pre-scanning is cheap — all
client-side, configs cached on `state.cfgs`.

**Tab states** (CSS classes on `.qc-wizard-tab`):

| State | Class | Visual | Clickable? |
|---|---|---|---|
| Current | `.is-current` | underlined accent, bold | No (no-op handler) |
| Applied | `.is-applied` | green text + ✓ icon | Yes if count > 0 (re-evaluate) |
| Skipped | `.is-skipped` | muted + – icon | Yes if count > 0 |
| Empty | `.is-empty` | dimmed | No (disabled) |
| Pending | (no extra class) | normal | Yes |

**Tab click semantics.** `_qcWizardSwitchTo(idx)` calls the current
handler's `dispose()` (cleans globals), updates `state.currentIdx`, calls
`_qcWizardMountCurrent()` which mounts the new phase into the persistent
body slot via that phase's `mountInto`. The wizard's shared footer
buttons stay mounted; the Apply label/count refresh via
`_qcWizardSyncCurrent()`. **No modal close/reopen, no flip.**
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

### 4.3 `mountInto` body-render contract (shipped Step 5)

The wizard owns the modal shell. Each phase renders its body **only**
into the wizard's `#qc-wizard-body` slot. To enable this, each modal
core accepts an optional `mountInto: HTMLElement` parameter:

- `_showFieldReviewModalCore({ ..., mountInto = null })`
- `_showWaitReviewModalCore({ ..., mountInto = null })`
- `_showTypedInputReviewModalCore({ ..., mountInto = null })`

When `mountInto` is set:

1. Skip the `modalShowFn` call entirely — no new modal opens.
2. Write the body HTML directly into `mountInto.innerHTML`.
3. Set up the same per-phase globals (`_qcWaitReviewRoot` etc.) but
   pointing at the slot, not a modal-root.
4. Return a **control handle**: `{ apply, dispose, sync, canApply?, empty }`.
   - `apply()` — collects picks, rewrites content, returns `{ newContent, meta }`.
     Returns `null` for soft-error cases (Bind: env not picked → toast).
   - `dispose()` — clears globals registered by this phase. Called on tab
     switch / Apply advance / wizard close.
   - `sync()` — returns the current "change count" for the Apply button
     label (e.g. 3 selected dropdowns / 2 toggled checkboxes / 1
     conversion). Read by `_qcWizardSyncCurrent()`.
   - `canApply()` (Bind only) — returns `false` when no env is selected
     so the wizard greys the Apply button.
   - `empty: true` — set when the phase has zero candidates; the wizard
     auto-skips.

When `mountInto` is `null` (standalone callers — dropdown shortcuts,
post-record fallback, devtools), the core opens its own modal as before.
Zero regression on standalone paths.

**Sync hook.** Inside the modal cores, `_qcWaitReviewSync` /
`_qcTypedReviewSync` / `_onFieldReviewSelect` / `_onReviewEnvChange` all
call `window._qcWizardSyncCurrent?.()` after updating local state. The
wizard's footer Apply button auto-updates label and disabled-state from
the handler's `sync()` return.

### 4.4 Tab UX details (shipped Step 5)

- **Empty tabs** render with `disabled` attr + greyed text. Wizard
  auto-skips them when picking next pending phase. Click does nothing
  (no silent re-route).
- **Applied tabs** show ✓ icon and green tint. Re-clickable if rescan
  finds remaining candidates (partial apply). Clicking remounts the
  phase against the post-apply content; the candidate list is freshly
  computed, so previously-applied changes do not reappear.
- **Skipped tabs** show – icon, muted text, but stay clickable (same as
  Pending) so user can change mind.
- **Re-applies are additive in the summary toast.** `phase.applied +=
  appliedCount` on every Apply, so the end-of-wizard toast reports
  cumulative changes per phase.
- **No Back button.** Tabs are the navigation. After Apply or Skip, the
  wizard advances to the next pending populated tab in script order
  (then wraps). User can override by clicking any tab.
- **Apply auto-advances.** Apply applies the current phase, re-scans,
  then auto-mounts the next pending phase. The wizard closes when no
  pending phases remain and fires the summary toast.
- **No flip / no animation between tabs.** `_qcWizardSwitchTo` mutates
  `#qc-wizard-body`'s innerHTML in place. The modal-card stays mounted.
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

### 5.3 Frontend — wizard shell (shipped Step 5)

Single contiguous block in `web/static/app.js` after the typed-input
helpers:

- `_wizardLoadContext(source, scriptId)` — editor vs post-record content fetch
- `_wizardCommit(source, scriptId, newContent)` — editor.setValue vs PUT
- `_wizardScanBind` / `_wizardScanWait` / `_wizardScanTyped` /
  `_wizardScanAll(state)` — per-phase scan + config caching. Called
  up-front and after each Apply.
- `_wizardTabsHTML(state)` — renders the compact tab strip.
  `_wizardRenderTabs(state)` updates `#qc-wizard-tabs` innerHTML.
- `_qcWizardSwitchTo(idx)` — tab click handler. Disposes current phase
  handler, updates `currentIdx`, calls `_qcWizardMountCurrent`.
- `_qcWizardMountCurrent()` — calls the right `_wizardMountX(state, slot)`
  for the current phase, stores the returned handler on
  `window._qcWizardActive.current`, refreshes tabs + Apply button.
- `_wizardMountBind` / `_wizardMountWait` / `_wizardMountTyped` — each
  delegates to the corresponding `_show*ReviewModalCore` with
  `mountInto: slot`. The cores return `{ apply, dispose, sync, ... }`.
- `_qcWizardSyncCurrent()` — global hook called by modal cores when row
  state changes. Reads current handler's `sync()` and updates the Apply
  button's label + disabled state.
- `_qcWizardApply()` — footer Apply click. Calls
  `w.current.handler.apply()`, commits via `_wizardCommit`, marks the
  phase applied (cumulative), re-scans all, calls `_qcWizardAdvance`.
- `_qcWizardSkip()` — footer Skip click. Marks phase skipped, advances.
- `_qcWizardAdvance()` — disposes current handler, picks the next
  pending populated phase (script-order, wraps), mounts it; if none
  remain, fires summary toast and closes.
- `_qcWizardClose()` — disposes handler, nulls `_qcWizardActive`,
  closes the modal.
- `_wizardSummaryToast(state)` — closing toast listing non-zero applied
  phases.
- `openReviewWizard(scriptId, opts)` — public entry. Loads content,
  pre-scans all phases, opens **one** modal via `showOverlayModal` (editor
  context) or `showModal` (post-record), tags footer buttons with
  `data-wizard-btn="skip"|"apply"`, stores wizard state on
  `window._qcWizardActive`, mounts the first non-empty phase.

State on `window._qcWizardActive`:

```js
{
  state: {
    source, scriptId, envName, language, content,
    cfgs: { bind?, wait?, typed? },     // cached per-language configs
    phases: [
      { id, label, status, count, applied, _scan: { fills | candidates } },
      ...
    ],
    currentIdx,
  },
  current: { phaseId, handler },        // current handler (apply/dispose/sync)
}
```

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

### Step 4 — Option B refactor: jump-ahead stepper ✓ (superseded by Step 5)
- Replaced the forward-only sequential `await phase1; await phase2; await
  phase3` chain with a state-machine loop driven by a stepper.
- Each phase still opened its own modal; the stepper let the user jump
  between them via `_qcWizardJumpTo(idx)`.
- Caught in user review: the modal close-and-reopen between phases
  showed a flip animation — felt like "three modals" not "one wizard."
- Stepper CSS + threading of `wizardStepper` HTML string into each
  modal core. All later replaced.

### Step 5 — Persistent shell + compact tabs (current) ✓
- Replaced the stepper + per-phase modal-flip pattern with **one
  persistent modal** that swaps body content in-place on tab click.
- Refactored each `_show*ReviewModalCore` to accept `mountInto:
  HTMLElement`. When set, the core writes body HTML into the slot and
  returns `{ apply, dispose, sync, canApply?, empty }` instead of opening
  its own modal (§4.3).
- New wizard shell functions: `_qcWizardSwitchTo`, `_qcWizardMountCurrent`,
  `_qcWizardApply`, `_qcWizardSkip`, `_qcWizardAdvance`, `_qcWizardClose`,
  `_qcWizardSyncCurrent`. State on `window._qcWizardActive`.
- Tab strip CSS replaces stepper CSS — compact underline tabs (~32px
  height vs old ~80px stepper).
- Modal cores call `window._qcWizardSyncCurrent?.()` after row state
  changes so the wizard's footer Apply button auto-updates label +
  disabled.
- `wizardStepper` parameter is no longer used in standalone callers
  (still in core signatures for back-compat, defaults to '').

### Step 6 — Verification on the client's failing script (deferred — needs browser)
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
