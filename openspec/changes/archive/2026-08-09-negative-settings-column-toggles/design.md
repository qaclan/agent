## Context

The negative authoring grid is rendered by `renderGrid()` in
`web/static/api/views/request-editor-view.js`. Non-request-level categories
(`input-validation`, `injection`) share one `<table class="neg-grid">` render
path — a `Field` column (`th.tcol`) plus one `<th data-col data-cat>` per
mutation subtype, with `<input type=checkbox data-cid>` cells. Column headers
already bulk-toggle via an `onclick` on the `<th>` (see the `th[data-col]`
handler); there is no widget and no visual state. Tooltip text comes from
`SUB_META[subtype][1]` via `_subDesc`. See proposal.md — Why.

## Goals / Non-Goals

**Goals:**
- A visible, tri-state checkbox in every mutation-type column header (both
  matrices), Field column excluded.
- Richer per-column tooltips for the four injection subtypes.

**Non-Goals:**
- No change to case generation, execution, result rendering, backend, DB, or
  sync. Cell-level toggles, the request-level list, and expected-status editing
  stay as they are.
- No new persisted state — column state is derived from the existing per-case
  `enabled` flags, never stored.

## Decisions

**Derive header state on every render, never store it.** After building the
`grid`/`subs` structures, each header checkbox's `checked`/`indeterminate` is
computed from the column's cases: all enabled → checked; none enabled →
unchecked; otherwise `indeterminate = true`. `indeterminate` cannot be set in
HTML, so it is assigned as a DOM property after `innerHTML` (in the same pass
that wires the header handlers). Re-render already happens on every toggle, so
the tri-state stays correct for free.
Alternative rejected: tracking column state separately — redundant with
`enabled` and prone to drift.

**Checkbox is the control; keep the header label clickable too.** The existing
`th` click bulk-toggle is retained for discoverability, but the `change` on the
checkbox is the primary path. To avoid a double toggle, the checkbox `onchange`
does the flip and stops propagation so the `th` `onclick` does not also fire.
Toggle direction follows the current column state: if any case is on, the action
turns the whole column off; otherwise it turns it on (matches today's `anyOn`
logic).

**Field column stays a plain `th.tcol`** — no checkbox, since it is the target
axis, not a mutation type. Header checkboxes render only for `th[data-col]`.

**Tooltip copy lives in `SUB_META`.** The four injection subtypes
(`sqli`, `xss`, `path-traversal`, `null-byte`) get enriched description strings
naming the payload and the no-5xx / not-reflected contract. Header `title`
already reads `_subDesc(st)`; the checkbox carries its own short "toggle all"
title. Input-validation subtype copy is left as-is.

## Risks / Trade-offs

- [Clicking the header checkbox also triggers the `th` click handler → double
  toggle, net no-op] → checkbox `onchange` calls `stopPropagation()` and owns
  the flip; the `th` `onclick` guards against acting when the event came from
  the checkbox.
- [`indeterminate` lost on re-render because it is a JS property, not an
  attribute] → set it explicitly after each `innerHTML`, alongside handler
  wiring, so it is reapplied every render.
- [Longer tooltip strings could wrap awkwardly] → native `title` tooltips; copy
  kept to one short sentence per column.
