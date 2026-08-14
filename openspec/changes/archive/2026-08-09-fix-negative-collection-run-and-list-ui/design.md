## Context

See `proposal.md` — Why. Three defects in the negative-testing collection surface, spanning backend run logic, request-list CSS/markup, and the run-confirmation dialog.

Current state (verified in code):

- Enablement resolution is `_resolve_negative_check(req, col)` at `web/api/services/runner_service.py:53-59` (request tri-state override wins; `inherit` falls back to collection `negative_check_default`, default `off`).
- `_negatives_for_run` (`runner_service.py:89-129`) gates negatives. Line 109 reads `if mode != "only" and not _resolve_negative_check(...)` — so in **only** mode the resolution is skipped and negatives run for any request that merely has cases. Its docstring (`:96-98`) codifies this wrong contract.
- The collection loops (`_execute_collection` `:421-444`, `run_collection` `:508-529`) send **every** request in only-mode with `assertions=[]` + schema off and record a result — no skip for non-qualifying requests.
- `plan_collection_negatives` (`:310-336`) sets `has_negatives` from `_enabled_negative_cases` alone (`:322-323`) without resolution, while `mutating_requests` already filters through `_resolve_negative_check` (`:324` continue).
- `cli/api_runner.py::run_api_request` (`:943-952`) already runs negatives only when `negative_enabled AND negative_cases` — it faithfully honors the tuple; no change needed there.
- Request rows render in `web/static/api/views/collections-view.js`: `_renderRequestNode` (`:337-348`), `_featureBadges` (`:322-335`, inline-styled `Δ`=schema/accent, `⊘`=negative/warning, each slot `width:12px;flex:none`, group `margin-left:auto`), `_effectiveOn` (`:311-317`). The request-name is a **bare unstyled `<span>`** (`:346`) with no truncation/wrap.
- CSS in `web/static/style.css`: `.api-sidebar` width `280px` (`:1479-1498`), `.api-request-item` flex row (`:1510-1519`), `.api-request-item.active` sets `color:var(--accent)` (`:1536-1540`), `.remove-from-col-btn` also uses `margin-left:auto` shown on hover (`:1521-1547`) — a second auto-margin competing with the badge group.
- Run dialog `qcCollectionRunConfirm` in `web/static/api/api-section.js` (`:108-170`); red warning block (`:135-140`) uses `var(--danger)` border/text/bg and inlines the full `mutating_requests` list into the sentence.

## Goals / Non-Goals

**Goals:**

- Only-negatives collection run executes negatives only for requests that are effective-on **and** have cases; all others are skipped (not sent, not recorded).
- Run-confirmation dialog uses a warning (not error) theme, a clear message, and a collapsed/expandable affected-API list.
- Request rows align consistently; name takes max width and wraps on overflow; the two markers take minimum width and stay visible, including on the selected row.

**Non-Goals:**

- No change to single-request "Run negatives" behavior, generation (`negative_gen.py`), severity/verdict (`negative_check.py`), or `run_api_request`'s negative gate.
- No change to the schema-check (`Δ`) marker's meaning — only the shared row layout it sits in.
- No new columns, migrations, or sync-shape changes.

## Decisions

### 1. Fix only-mode enablement in `_negatives_for_run`

Remove the `mode != "only"` exemption on `runner_service.py:109` so only-mode also requires `_resolve_negative_check(req, col)` to be true. Rewrite the docstring: only-mode runs negatives for requests **resolved-on AND with cases**, not "regardless of enablement". Result: a request that is off returns `(False, [])`.

Alternative rejected: keep the exemption and filter in the loop only — leaves the misleading contract in the helper and the wrong `has_negatives`.

### 2. Skip non-qualifying requests in only-mode loops

In both `_execute_collection` (`:421-444`) and `run_collection` (`:508-529`), after computing `neg_enabled, neg_cases`, add: in only-mode, if `not neg_enabled` → `continue` (no send, no `create_request_result`). This ensures the only-negatives run shows exactly the qualifying requests. In default/off modes the loop is unchanged (happy-path still runs for all).

### 3. Tighten `has_negatives` in `plan_collection_negatives`

Set `has_negatives` from the **intersection**: `_resolve_negative_check(req, col) AND _enabled_negative_cases(req)` (`:322-323`). Then the mode chooser appears only when at least one request will actually run negatives; if the collection default is off and nothing is overridden on, the run proceeds normally with no chooser. `mutating_requests` already filters by resolution — it stays the authoritative affected-API list for the dialog.

### 4. Request-row layout (CSS + markup)

- Widen `.api-sidebar` from `280px` to `320px` (min-width bumped accordingly).
- Give the request-name span a class (e.g. `api-req-name`) with `flex:1; min-width:0` and **wrapping** (`overflow-wrap:anywhere; word-break:break-word`) per the user's "wrap when width crosses" — not ellipsis.
- Change `.api-request-item` `align-items` to `flex-start` so markers align to the top when the name wraps to multiple lines; keep the method badge and markers from stretching.
- Give the badge group a fixed minimum footprint (`flex:none`) and keep it right-aligned; ensure the `⊘`/`Δ` slots are the only width they need. Resolve the double `margin-left:auto` conflict: the badge group keeps `margin-left:auto`; the hover remove-button is repositioned (absolute, or placed after markers without its own auto-margin) so revealing it does not shift the marker column.
- Selected-row marker: markers keep inline colors (they already beat `.active`'s `color`), and the layout fix stops overflow from pushing `⊘` out of the 320px panel — so the selected row keeps its negative marker.
- **Marker requires cases:** `_featureBadges`/`_effectiveOn` (`collections-view.js:311-335`) currently show `⊘` on enablement alone, ignoring whether cases exist — so an on-but-no-cases request shows a marker yet runs nothing. Change the negative marker to require **effective-on AND ≥1 enabled case**, matching what actually runs and the tightened `has_negatives`. The row's `req` must carry its `negative_cases` (or a precomputed active-negatives boolean) in the list payload; if it does not, derive the flag server-side and include it. The editor negative-tab marker uses the same on-AND-has-cases rule.

Alternative rejected: ellipsis truncation of the name — user explicitly wants wrapping. Alternative rejected: marker on enablement alone — misleads when no cases exist.

### 5. Run-dialog warning theme + collapsible affected list

In `qcCollectionRunConfirm` (`api-section.js:135-140`), replace the `var(--danger)` block with a warning-themed block (`var(--warning)` border/text, subtle warning bg). New copy: a short sentence that state-changing negative payloads (POST/PUT/PATCH/DELETE) will be sent against `<env>` and may alter data — no inline dump of every request. Add a "Show N affected requests" toggle that expands a compact list built from `plan.mutating_requests` (name + methods). Toggle is a plain click handler on the injected node (consistent with existing `button[data-mode]` wiring). The three run-mode buttons and return contract are unchanged.

## Risks / Trade-offs

- **Only-mode now records fewer request results** (skipped requests vanish from the run) → intended; matches the fix. Downstream run-history/report already iterate the recorded results, so fewer rows is safe. Verify the collection-run view handles a run whose request set is a subset.
- **Wrapping names increase row-height variability** → `align-items:flex-start` keeps markers/badge aligned to the first line; acceptable.
- **Collapsible list adds interaction to a template-string dialog** → single click handler, no framework; low risk.
- **`has_negatives` tightening could hide the chooser** in a collection where cases exist but all are off → correct behavior (nothing would run in only-mode anyway); run proceeds as plain happy-path.

## Migration Plan

Pure code change; no DB migration, no data backfill. Rollback = revert the commit. Per the repo maintenance rule, `docs/api-negative-testing-reference.md` is updated in the same change to reflect the corrected only-mode semantics and the new confirmation presentation.
