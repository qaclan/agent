# 02 - Visual Element Picker

Deep-dive on feature #2 from [feature-ideas.md](../feature-ideas.md). Covers target users, overlap with codegen / healing / NL-to-step, and decision on whether to build.

---

## Who actually needs this

Picker target = users editing scripts by hand in QAClan editor. Not pure non-tech (they live in codegen). Not senior devs (they know locator API). Middle tier:

- QA who can read code but not write locators from scratch.
- Devs adding assertions to a recorded flow.
- Anyone fixing one broken selector without re-recording the whole flow.

## Codegen vs picker — not either/or

Codegen covers the "record happy path" workflow. Picker fills the gaps codegen can't:

- **Cleanup phase.** Codegen output rarely ships as-is. Remove dead clicks, parametrize values, add waits. That cleanup = hand edit.
- **Add what didn't happen.** Codegen can't record an action the user never performed. Need to add a click on a button the recorder skipped? Picker.
- **Mid-flow fix.** Codegen breaks mid-recording. User wants to add one action without re-running 20 steps. Picker.
- **Assertion authoring.** Codegen records actions, not assertions. `expect(locator).toBeVisible()` needs an element pick.

## Overlap with other planned features

| Feature | Overlap | Implication |
|---|---|---|
| #1 Smart Selector Healing | Healing fixes broken selectors automatically. Picker fixes them manually with a click. | If healing works well, picker need shrinks. Picker is fallback when healing score < 0.5. |
| #5 Natural Language to Step | NL: "click login button" → code. Picker: click button → code. | Same user. NL faster if accurate. Picker deterministic, no LLM dep. |
| #3 Recorded Action Editor | Timeline edits existing recorded steps. Picker adds new ones. | Complementary. Picker = "add step" button inside timeline. |

## Decision matrix

| Option | Pitch | Cost | Risk |
|---|---|---|---|
| A. Build picker standalone | Deterministic. Offline. No LLM. Ships fast. | Low | Low |
| B. Defer picker, build #5 NL-to-step first | Bigger marketing hook. | Med | LLM cost, latency, accuracy |
| C. Build both, picker as NL fallback | Best UX. | High | Double effort |
| D. Skip picker — codegen + healing cover 90% | Cheapest. | None | Bets users tolerate codegen-only workflow |

## Decision

**Option A — build picker standalone.**

Rationale:

- Small scope, deterministic logic. Reuse Playwright's selector generator (same code as `codegen`).
- No model dependency. No bundle bloat. Works offline.
- Pairs cleanly with #1 Healing: healing repairs, picker authors. Together they cover the selector lifecycle without LLM.
- NL-to-step (#5) becomes polish layer later, not blocker.

## Scope for v1

In:

- "Pick Element" button in script editor.
- Launches Playwright browser with overlay injected.
- Hover highlight, click → selector returned.
- Inserts snippet at cursor in current strategy's language (Python / JS / TS).
- WebSocket between subprocess and web UI for round-trip.

Out (v2+):

- Pick multiple elements at once.
- Pick and generate assertion (`toBeVisible`, `toHaveText`).
- Pick from a paused run (combine with #13 Step-by-Step Replay).
- Pick from screenshot of failed run (offline picker).

## Implementation outline

1. New web route: `POST /api/picker/start` — launches Playwright via subprocess with `--no-headless` and overlay script injected as init script.
2. Overlay JS: hover → outline element, click → `postMessage` with element handle ref.
3. Subprocess resolves handle → Playwright's `_generateLocatorString` (internal API; or replicate via tag + role + text + testid priority).
4. Selector posted back over WebSocket to UI.
5. UI inserts snippet at editor cursor, language-aware via strategy's `format_action_snippet(action, selector)` (new method on each strategy in [cli/script_strategies/](../../cli/script_strategies/)).

## Open questions

- **Browser lifecycle.** One picker browser per editor session, or new browser per pick? Per-session = faster, but state leaks. Per-pick = clean, but slow startup.
- **Selector priority.** Match Playwright codegen order: `getByRole` → `getByTestId` → `getByText` → CSS fallback. Configurable per-project?
- **Cross-strategy snippet format.** Python uses `await page.locator(...)`, JS uses `await page.locator(...)`, TS-test uses `await expect(page.locator(...))`. Each strategy owns its snippet template.

## Next concrete step

Prototype overlay JS + selector extraction in a standalone script. Validate selector quality against codegen output on 10 real pages. If parity, wire into web UI behind a feature flag.
