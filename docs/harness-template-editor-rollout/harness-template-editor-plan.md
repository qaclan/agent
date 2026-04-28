# Harness Template in Script Editor

## Goal
Make the language-specific harness template visible by default in the script editor for new scripts, not only for recorded scripts.

## Current Flow
Manual scripts:
- In `web/static/app.js`, the editor content is built in `createScriptModal()` and `editScriptModal(id)`
- Scripts are saved through the create/update script endpoints in `web/routes/scripts.py`
- In this flow, content is mostly saved as entered

Recorded scripts:
- Start in `record_script_route()` in `web/routes/scripts.py`
- Continue through `record_script()` in `cli/commands/web/record.py`
- Raw Playwright code is processed by `post_process_recording()` in each strategy:
  - `cli/script_strategies/python_strategy.py`
  - `cli/script_strategies/javascript_strategy.py`
  - `cli/script_strategies/typescript_strategy.py`

In each strategy, recording is processed by:
- `_extract_actions()`
- `_patch_goto_wait()`
- `_render_harness()` using `_HARNESS_TEMPLATE` and `{ACTIONS}`

## Problem
Manual scripts and recorded scripts follow different structure rules. Recorded scripts are normalized into a harness template, but manual scripts are not.

## Desired Behavior
Show the language-specific harness template by default in the editor for new scripts.
Users should mainly write inside the action section of that template, such as the `run(...)` body in Python.

## Questions
1. Should non-action template sections remain editable or be locked?
2. Should harness templates come from the backend instead of being duplicated in the frontend?
3. How should manual and recorded script flows be unified around the same template model?

## Review Request
Please review the current flow and recommend the best architecture and UX for implementing this consistently across Python, JavaScript, and TypeScript.