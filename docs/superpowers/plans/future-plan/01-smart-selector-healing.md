# 01 - Smart Selector Healing

Deep-dive on feature #1 from [feature-ideas.md](../feature-ideas.md). Covers when selectors break, frequency, scoring approach, and incremental build path.

---

## When selectors break

Real-world triggers, ordered by frequency:

1. **Dev rename during refactor** — `#submit-btn` → `#submit-button-primary`. Most common. Happens when frontend devs clean up naming or move to design-system tokens.
2. **Design-system migration** — Tailwind → BEM, Bootstrap → custom, MUI v4 → v5. Bulk class renames hit all selectors at once.
3. **Component library swap** — different `data-testid` conventions between libraries. Same component, new wrapper structure.
4. **A/B test variants ship to prod** — extra wrapper `<div>` inserted, breaks XPath and `nth-child` selectors.
5. **i18n / copy change** — button text "Submit" → "Send" breaks `text=Submit` and `getByText` selectors.
6. **DOM restructure** — nested wrapper added for layout. Absolute XPath dies. CSS child combinators die.
7. **Framework upgrade** — React 18 → 19, Vue 2 → 3. Hydration order, conditional rendering changes.

## How often

| Project state | Break frequency |
|---|---|
| Mature app, stable UI | Rare. Weekly-ish per suite. |
| Active development | Daily. Multiple breaks per sprint. |
| Refactor-heavy sprint | Many breaks at once. Whole test files unusable. |

Worst pain: flaky tests that pass locally on Monday, fail in CI on Tuesday after a teammate merges. User has no idea what changed.

## Scoring — heuristic first, ML later

### Why no ML for v1

- No training data yet. Need user accept/reject signal first.
- Heuristic catches ~80% per published research (Healenium, Selenium-Heal papers).
- ML adds inference latency + model bundle size to binary. Bad fit for local-first CLI.
- Ship heuristic, collect labeled data via accept/reject UX, train ML in v2.

### Heuristic scoring formula

```
score = w1*tag_match + w2*text_similarity + w3*attr_overlap
      + w4*dom_position_distance + w5*role_match
```

| Signal | Method | Why |
|---|---|---|
| `tag_match` | Binary. Same HTML tag? | `<button>` heal target must be `<button>`, not `<a>`. |
| `text_similarity` | Levenshtein ratio on innerText. | "Submit" → "Submit Form" still high score. |
| `attr_overlap` | Jaccard on `class` + `id` + `data-*` token set. | `submit-btn` vs `submit-button-primary` share token `submit` → high. |
| `dom_position_distance` | Tree-edit distance from old DOM anchor (parent path). | Element moved 1 level deep, still findable. |
| `role_match` | Binary ARIA role match. | `role="button"` survives class renames. |

Weights to start: `w1=0.15, w2=0.25, w3=0.30, w4=0.15, w5=0.15`. Tune from accept-rate data.

### Decision gate

| Score | Action |
|---|---|
| `> 0.80` | Auto-heal. Run action. Log heal. Suggest script update. |
| `0.50 – 0.80` | Pause run. UI shows candidate + "Use this?" prompt. |
| `< 0.50` | Fail run normally. No heal attempted. |

## Implementation path

### Phase 1 — capture only (no healing)

- Wrap Playwright locator calls in script harness.
- On `TimeoutError`, snapshot DOM + intended action.
- Store in new table `selector_heal_attempts`:
  ```
  id, run_id, script_id, old_selector, action, dom_snapshot,
  candidates_json, picked_selector, score, accepted, created_at
  ```
- No heal yet. Just data collection. Validates how often selectors break in real usage.

### Phase 2 — heuristic heal with manual accept

- Compute candidate elements + scores on break.
- UI: "Selector broken. Top match: `getByRole('button', {name: 'Submit'})`. Score 0.87. [Accept] [Reject]".
- Accept → rewrite script file. Reject → keep failure.
- Track accept rate per scoring signal. Identify which weights matter.

### Phase 3 — auto-heal above threshold

- Score > 0.80 → heal mid-run, no prompt. Run continues.
- Background notification: "3 selectors healed in this run. Review?".
- One-click bulk-accept rewrites all heals to script.

### Phase 4 — ML scoring (only if data justifies)

- Train sentence-transformer embedding model on element context (tag + attrs + text + parent path).
- Features: cosine similarity of embeddings + existing heuristics.
- Bundle as ONNX runtime, ~30MB. Optional download via `qaclan setup --ml`.
- Fallback to heuristic if model not installed.

## Open questions

- **Storage cost of DOM snapshots** — full HTML per failed locator could balloon. Strategy: store only candidate elements + their parent path, not full page.
- **Script rewrite safety** — what if user has uncommitted edits? Need diff preview before overwriting.
- **Multi-language heal** — selector syntax differs across Python/JS/TS strategies in [cli/script_strategies/](../../cli/script_strategies/). Rewriter needs per-language AST handling.
- **State pollution** — if heal triggers different element than original intent, downstream steps may operate on wrong target. Need post-heal assertion: "did the action have the expected effect?".

## Next concrete step

Add `selector_heal_attempts` table to [cli/db.py](../../cli/db.py) migrations. Wrap locator timeouts in harness templates under [cli/script_strategies/](../../cli/script_strategies/) to capture data. Ship Phase 1 first — heal logic comes after we see real break patterns.
