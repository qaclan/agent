# Collection Header Redesign + Auth Tab Reorder

**Date:** 2026-06-23
**Status:** Approved

## Scope

Two UI changes to the API collections interface:
1. Reorder request editor tabs (Auth moves earlier)
2. Redesign the cluttered collection header button row

---

## 1. Request Editor Tab Reorder

**Current order:** Params, Headers, Body, Auth, Pre-Script, Post-Script, Assertions

**New order:** Params, **Auth**, Headers, Body, Pre-Script, Post-Script, Assertions

**File:** `web/static/api/views/request-editor-view.js`

Change the `SECTIONS` array. No other logic changes — all tab rendering and sectionMap entries remain identical.

---

## 2. Collection Header Redesign

### Problem

Current header row packs 6 controls into a tiny space:
`[env selector] [Auth] [Vars] [▶ Run] [✕] [▾]`

Text-labeled buttons for low-frequency actions (Auth, Vars, Delete) waste space and make the row feel cluttered.

### New Layout

```
[Collection Name]  [N requests]          [env: <select>] [⋯] [▾]
```

- **Env selector** — stays visible inline; small `<select>` styled to match row height. Behavior unchanged (PATCH on change).
- **⋯ button** — opens a positioned dropdown menu below the button.
- **▾/▸ button** — expand/collapse request list. Behavior unchanged.

### Dropdown Menu (⋯)

```
▶  Run Collection
──────────────────
🔒 Auth
{} Variables
──────────────────
🗑 Delete
```

| Item | Action |
|------|--------|
| Run Collection | calls `_runCollection(col.id, col.name, col.env_name)` — same as before |
| Auth | opens Auth modal |
| Variables | opens Variables modal |
| Delete | opens confirm dialog, then `_deleteCollection` |

Dropdown closes on: item click, Escape, click outside.

### Auth Modal

- Title: "Collection Auth"
- Body: existing `authPanel` DOM content (auth type selector + dynamic fields)
- Footer: Save button (fires existing PATCH), Cancel
- Replaces the current inline `authPanel` that toggled `display:none` below the header

### Variables Modal

- Title: "Collection Variables"
- Body: existing `varsPanel` DOM content (key-value table)
- Footer: Save button (fires existing PATCH), Cancel
- Replaces the current inline `varsPanel`

### Delete Confirm

- Simple modal/dialog: "Delete collection '{name}'? This cannot be undone."
- Confirm → `_deleteCollection`. Cancel → close.
- Replaces the current in-place deletion with no confirmation (or existing confirm if present).

---

## Files Changed

| File | Change |
|------|--------|
| `web/static/api/views/request-editor-view.js` | Reorder `SECTIONS` array |
| `web/static/api/views/collections-view.js` | Header row layout, ⋯ dropdown, modals for Auth/Vars/Delete |

---

## Out of Scope

- Auth inheritance / cascading from collection to requests
- Auth type additions (Bearer, OAuth2, etc.)
- Any changes to key-value table, var-picker, or other components
