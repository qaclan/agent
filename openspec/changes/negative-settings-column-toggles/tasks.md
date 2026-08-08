## 1. Header checkbox rendering

- [x] 1.1 In `renderGrid()` (`web/static/api/views/request-editor-view.js`), render a `<input type="checkbox">` inside each mutation-type `<th data-col data-cat>` header, alongside the subtype label; leave the `Field` header (`th.tcol`) with no checkbox.
- [x] 1.2 Add `_NEG_STYLE` rules so the header checkbox aligns with the label (spacing, vertical-align, `accent-color`) and does not distort the header row height.

## 2. Tri-state wiring

- [x] 2.1 After building the `grid`/`subs`/`targets` structures, compute per-column aggregate state (all enabled / all disabled / mixed) from the cases' `enabled` flags.
- [x] 2.2 In the post-`innerHTML` pass, set each header checkbox's `checked` and `indeterminate` DOM properties from that state (indeterminate on mixed), reapplying on every render.

## 3. Bulk-toggle behavior

- [x] 3.1 Wire each header checkbox `onchange` to flip every case in its column to the same `enabled` state (any-on → all-off, else all-on), call `_markDirty?.()`, and `renderGrid()`.
- [x] 3.2 Prevent a double toggle: guard the existing `th[data-col]` `onclick` so it does not fire when the click originated on the checkbox.
- [x] 3.3 Confirm the header label click still bulk-toggles the column (discoverability path retained).

## 4. Tooltips

- [x] 4.1 Enrich the four injection subtype descriptions in `SUB_META` (`sqli`, `xss`, `path-traversal`, `null-byte`) with the agreed copy naming each payload and the no-5xx / not-reflected pass contract.
- [x] 4.2 Give the header checkbox its own short `title` ("toggle all <mutation> tests across every field"); keep the header `title` reading the enriched `_subDesc`.

## 5. Docs & verification

- [x] 5.1 Update the authoring-surface / settings-grid section of `docs/api-negative-testing-reference.md` to describe the per-column header checkbox (tri-state, Field column excluded) and the header tooltips, per the negative-testing maintenance rule.
- [ ] 5.2 Manually verify in both matrices (input-validation + injection/fuzz) and both light and dark themes: checkbox reflects all-on / all-off / mixed, bulk toggle works without double-firing, Field column has no checkbox, tooltips render.
