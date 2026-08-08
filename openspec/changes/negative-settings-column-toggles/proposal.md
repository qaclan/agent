## Why

The negative-testing authoring grid already lets a user bulk-toggle a whole mutation-type column, but the control is an invisible click-on-the-header-text with no widget and no state feedback — users don't discover it, and can't tell at a glance whether a column is fully on, fully off, or mixed. The column headers also give no real explanation of what each attack sends or how a pass is judged, so the injection/fuzz columns (SQLi, XSS, Traversal, Null byte) read as bare labels.

## What Changes

- Add a visible **checkbox** to every mutation-type column header in the negative authoring matrix — both the input-validation and the injection/fuzz tables. The **Field** column gets no checkbox.
- The header checkbox bulk-toggles its whole column and reflects the column's state: **checked** when every cell in the column is on, **unchecked** when all are off, **indeterminate** (native dash) when mixed.
- Replace the current click-on-text bulk-toggle with the checkbox as the explicit control (clicking the header label still toggles, for discoverability).
- Enrich each column header **tooltip** with a short description of the column's identity — what it sends, how it is judged, and what a pass means. The four injection columns get specific copy naming their payload and the no-5xx / not-reflected contract.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `api-negative-testing`: the **Negative-case authoring surface** requirement is refined — mutation-type bulk-toggle is now an explicit per-column header checkbox that reflects tri-state column status (all-on / all-off / mixed), the target (Field) column carries no such control, and each mutation-type column header carries a descriptive tooltip.

## Impact

- `web/static/api/views/request-editor-view.js` — `renderGrid` header rendering (`th[data-col]`), the header bulk-toggle handler, `_NEG_STYLE` (checkbox styling in header cells), and the `SUB_META` tooltip strings for the four injection subtypes.
- `docs/api-negative-testing-reference.md` — the settings-grid / authoring-surface section, per the negative-testing maintenance rule (must stay in step with the UI).
- No backend, database, sync, CLI, or report changes. Frontend authoring surface + doc only; case generation, execution, and result rendering are untouched.
