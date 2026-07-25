# Body Format Active Indicator — Design Spec
Date: 2026-07-25

## Problem

The multi-format body storage work (`docs/superpowers/specs/2026-07-24-request-body-multi-format-storage-design.md`) made all 4 body formats (Raw, x-www-form-urlencoded, form-data/multipart, GraphQL) persist simultaneously per request, with `body_type` as the sole discriminator marking which one is active — the one actually sent when the request runs.

The request editor's body-format tab bar (`web/static/api/views/request-editor-view.js`) already highlights the active tab via a `.active` CSS class (accent background/color, `web/static/style.css:1788`), and clicking a tab both switches the view and reassigns `activeBodyType` in `_setBodyType()`. But that signal is color-only — nothing textual or iconic marks a tab as "this is what gets sent," and a colorblind or quickly-scanning user has no non-color cue. The pre-save discovery/import review modal (`web/static/api/views/request-review-modal.js`) shows a body preview already correctly sourced from the matching column per `body_type`, but its heading just says "Request Body" with no indication of which format that content actually is.

## Decision

Add an explicit, non-color signal of the active format in both places — no new abstractions, no backend/DB changes, both files already read the correct per-type column.

| Question | Decision |
|---|---|
| Editor tab bar signal | CSS-only checkmark prefix on the `.active` tab button (`::before { content: "✓ "; }`), plus a `title` tooltip explaining it. No JS logic change beyond setting `title`. |
| Editor "none" case | Treated like any other tab — checkmark lands on the "none" pill, tooltip reads "No body — nothing sent when you Run this request." |
| Review modal signal | Append the resolved format label to the "Request Body" section heading, e.g. "Request Body — form-data/multipart". Omitted (heading stays plain) when `body_type` is null/raw, matching the existing implicit-default assumption. |
| Label source | New small local label map in `request-review-modal.js`, mirroring the editor's existing `BODY_TYPE_LABELS` — kept local rather than extracted to a shared module, consistent with this file's existing pattern of duplicating its own small helpers (`_esc`, `_fmt`, etc.) rather than importing from the editor. |
| Scope | Confirmed via repo-wide grep for `body_type` in `web/static/`: only these 2 frontend files touch it. No run-results/response-panel view displays request body, so nothing else needs a signal. |

---

## Section 1: Editor tab bar (`request-editor-view.js`, `style.css`)

`_setBodyType()` (`request-editor-view.js:930-979`) already toggles `.active` correctly on every switch, including to "none," at lines 937-939:

```js
bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
  b.classList.toggle('active', b.dataset.type === type);
});
```

Add a `title` tooltip in the same loop:

```js
bodyTypeGroup.querySelectorAll('.req-body-type-btn').forEach(b => {
  const isActive = b.dataset.type === type;
  b.classList.toggle('active', isActive);
  b.title = isActive
    ? (type === 'none' ? 'No body — nothing sent when you Run this request' : 'Active — sent when you Run this request')
    : '';
});
```

In `web/static/style.css`, next to the existing rule at line 1788:

```css
.req-body-type-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.req-body-type-btn.active::before { content: "✓ "; }
```

No other change — the checkmark rides on the class that's already correctly maintained through every tab switch and on initial load (`_setBodyType(activeBodyType)` at line 981).

---

## Section 2: Review modal (`request-review-modal.js`)

Add a local label map near the top of the file, matching the editor's existing labels:

```js
const _BODY_TYPE_LABELS = { form: 'x-www-form-urlencoded', multipart: 'form-data/multipart', graphql: 'GraphQL' };
```

Change the heading construction in `_detailHTML()` (currently line 69):

```js
const bodySection = _section('Request Body', bodyContent);
```

to:

```js
const _bodyTypeLabel = req.body_type && req.body_type !== 'raw' ? _BODY_TYPE_LABELS[req.body_type] || req.body_type : null;
const bodySection = _section(_bodyTypeLabel ? `Request Body — ${_bodyTypeLabel}` : 'Request Body', bodyContent);
```

`raw` and null/undefined `body_type` both render the plain "Request Body" heading — raw is the implicit default and doesn't need calling out; only form/multipart/graphql get the suffix.

---

## Section 3: Testing (manual — no automated test suite in this project)

- Open the request editor on a request with `body_type = 'multipart'` → the "form-data/multipart" tab shows the checkmark and accent highlight; hovering shows the tooltip.
- Click through Raw → x-www-form-urlencoded → GraphQL → none, without saving → checkmark follows the click on each tab immediately.
- Set body type to "none" → the "none" pill shows the checkmark with the "No body" tooltip, other tabs show no checkmark despite possibly holding cached draft content.
- Run a HAR/Postman/cURL import that produces a mix of raw, form, multipart, and graphql requests → open the pre-save review modal → each request's body section heading shows the correct format suffix (or plain "Request Body" for raw), matching the content rendered below it.
- Import a request with `body_type = null` (e.g. GET with no body) → review modal heading stays plain "Request Body", body content shows the em-dash placeholder.
