# Harness Template Implementation Plan (the root plan ref: docs/harness-template-editor-rollout/harness-template-editor-plan.md)

## Phase 1 — expose starter template, keep scaffolding editable (low risk)

Add `ScriptStrategy.starter_template() -> str` on `base.py`. Default impl: `return self._render_harness("")`. Promote `_render_harness` to a protected method shared by Python and JS (already effectively is). TypeScript inherits for free.

New endpoint in `web/routes/scripts.py`: 
### API
Add a new endpoint in `web/routes/scripts.py`:

- `GET /api/scripts/starter-template?language=<lang>`

 Validate language in `SUPPORTED_LANGUAGES`

Response:

```json
{
  "ok": true,
  "content": "..."
}


## Frontend `createScriptModal()`

Fetch starter template for the default language on open and seed the editor.

On `#script-language` change, if the current editor value equals the previously-loaded template (untouched), swap to the new template; otherwise keep content and show a hint toast (no destructive prompt).

Leave `editScriptModal()` alone — existing scripts already have their content; don't overwrite.

## Phase 2 — optional UX polish (defer unless asked)

Use CM6 decorations + a `changeFilter`/`EditorState.transactionFilter` to visually dim and prevent edits outside the `BEGIN`/`END` markers. Skip for textarea fallback. This is non-trivial and can ship later without breaking Phase 1.
