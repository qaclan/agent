# 03 - Recorded Action Editor (Timeline View)

Deep-dive on feature #3 from [feature-ideas.md](../feature-ideas.md). Covers step-ordering risk, the ordering guard (locked anchors), and the source-of-truth model between timeline and code.

---

## The ordering problem

E2E steps have hard dependencies. Reordering blind breaks tests:

- **Navigation before interaction.** `goto('/login')` must precede `fill('#email')`.
- **Fill before submit.** `fill(password)` before `click('Sign In')`.
- **Wait before read.** `wait_for(modal)` before `click(modal button)`.
- **State setup before use.** Login step before visiting `/dashboard`.

Drag step 3 above step 1 → script runs `fill` on a page not yet loaded → fail. So reorder cannot be a dumb list drag.

## Ordering guard — Locked Anchors (decision)

Chosen approach: **mark structural steps as anchors and block illegal moves.**

### Anchor types

| Step type | Anchor role |
|---|---|
| `goto` / `wait_for_url` | Navigation anchor. Everything after it depends on that page being loaded. |
| `wait_for_selector(S)` | Binds to the next action that uses `S`. Cannot be separated from it. |
| Variable definition | Any step defining a var is a hard anchor for steps that use the var. |

### Drag rules

- A step cannot be dragged above the navigation anchor of the page it operates on.
- A `wait_for` and its bound action move as a pair.
- A var-using step cannot move above its var-defining step.
- Free reordering allowed only *within* the same anchor segment (between two navigation anchors).

### UX

- Anchors render with a lock icon and a tinted band.
- Illegal drop target greys out during drag. Drop is rejected with a tooltip: "Can't move above the page load in step 2".
- Legal drop zones highlight green.

## Source of truth — Timeline, with custom-code lockout (decision)

### The conflict

If both code and timeline are editable, one clobbers the other. User hand-edits code, then drags a card → regen overwrites the manual edit.

### Resolution

**Timeline is source of truth — but only for linear recorded scripts.**

- Script is pure linear action list → timeline editable, regen safe.
- Script contains a loop, conditional, function, or any custom code → timeline goes **read-only**. Banner: "Script has custom logic — edit as code". Code tab becomes the only editor.

Detection: parse script into action list. If parser hits a node it can't represent as a card (control flow, custom call, multi-line expression), flag `has_custom_logic = true` and lock the timeline.

### Live preview

- Drag / edit a card → regenerate code in the side panel **instantly**.
- Changed lines highlight.
- File is **not written** until user clicks Save. Preview is in-memory only.

## Data model

Parse codegen output into an action list:

```
{
  index, action, selector, value, anchor_type,
  bound_to,        // index of paired wait/anchor, null if none
  screenshot_ref,  // thumbnail from re-run capture
  line_range       // source line span for highlight
}
```

Store transiently per edit session. On Save, regenerate the whole script file from the list via the active strategy's generator.

## Implementation outline

1. **Parser** per strategy in [cli/script_strategies/](../../cli/script_strategies/): `parse_to_actions(source) -> list[Action] | CustomLogicError`.
2. **Generator** per strategy: `actions_to_source(list[Action]) -> str`. Round-trip must be stable: `parse(generate(x)) == x`.
3. **Anchor detector**: tag each action with `anchor_type` and resolve `bound_to` pairs.
4. **UI timeline**: cards with thumbnails, drag-drop honoring anchor rules, inline value edit.
5. **Live preview pane**: regenerate-on-change, line highlight, Save commits to file.
6. **Custom-logic lockout**: if parse raises `CustomLogicError`, render read-only timeline + code-only banner.

## Open questions

- **Thumbnails.** Capturing a screenshot per step needs a re-run. Do it lazily on first timeline open, cache per script version.
- **Round-trip fidelity.** Comments and formatting in hand-edited code get lost on regen. Mitigated by custom-logic lockout — but a script with just a stray comment shouldn't lock. Decide: tolerate comment loss, or treat comments as custom logic?
- **Multi-language parser cost.** Each strategy needs its own parser + generator. Start with one language (Python), prove the round-trip, then port.

## Next concrete step

Build `parse_to_actions` + `actions_to_source` for the Python strategy only. Write a round-trip test on 5 real codegen outputs. If stable, add the anchor detector, then the UI.
