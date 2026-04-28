# Script Strategy Migration Plan

## Context

We're migrating the script generation system from a single Python-only module (`cli/script_processor.py`) to a **strategy pattern** that supports multiple languages (Python, JavaScript, TypeScript).

Each language strategy owns its own harness template, codegen target, runtime validation, and escape rules. A registry (`get_strategy(language)`) dispatches by the script's `language` field, which is persisted in the DB and surfaced in the UI.

## Non-Goals

- No changes to Playwright recording UX beyond adding a language dropdown.
- No language-agnostic AST/IR — each strategy owns its own template.
- No sandboxing beyond the existing per-run dir (`chmod 0o700`) and isolated `child_env`.
- No hot-reload of strategies at runtime — registry is resolved at import time.

## Architectural Decisions

- **ABC over duck-typing**: `ScriptStrategy` is an explicit ABC so missing methods fail at import, not at runtime when a user clicks Run.
- **Escape logic lives on the strategy**, not in `runs.py`. Each language has different literal rules (JS needs `'`, backtick, `\r`; Python needs `\r` only). The old `_py_literal_escape` helper in `runs.py` is a leak that must be removed.
- **Codegen target ≠ file extension**: TS reuses Playwright's `javascript` codegen target (there is no `--target typescript`); only the extension and run command differ.
- **Per-run isolation**: every run gets its own dir with `0o700`, a shared `state.json`, a scrubbed `child_env`, and a 300s timeout. `validate_runtime()` runs pre-flight so missing `node`/`npx tsx` fails fast with a clear error.

## Phases

### Phase 1 — Python Strategy Migration ✅ COMPLETE

**Goal:** Move existing Python-only script generation into the strategy pattern without behavior changes.

- [x] Create `cli/script_strategies/` package
  - [x] `base.py` — `ScriptStrategy` ABC with abstract methods: `post_process_recording`, `rewrite_url_template`, `build_run_command`, `validate_runtime`, `escape_for_literal`
  - [x] `python_strategy.py` — Python harness template, action extraction, goto patching, Nuitka-aware executable resolution
  - [x] `_shared.py` — `scan_var_keys`, `substitute_template_vars` helpers
  - [x] `__init__.py` — registry: `get_strategy(language)`, `SUPPORTED_LANGUAGES`
- [x] Delete `cli/script_processor.py` (replaced by strategies)
- [x] `cli/db.py` — migration adds `language TEXT NOT NULL DEFAULT 'python'` to `scripts`
- [x] `web/routes/scripts.py` — all endpoints accept/return `language`; file rename on extension change
- [x] `web/routes/runs.py` — per-run dir with `chmod 0o700`, shared `state.json`, isolated `child_env`, 300s timeout, pre-flight `validate_runtime()`
- [x] `web/static/app.js` — language dropdown in Record Script and New Script modals; read-only language badge in Edit Script modal
- [x] `cli/sync.py` — include `language` in cloud payload
- [x] `CLAUDE.md` — architecture docs reflect new structure

### Phase 2 — JavaScript Support ✅ COMPLETE

**Goal:** Add `javascript_strategy.py` so JS scripts record, render, and run correctly.

- [x] **Escape refactor**
  - [x] Update `base.py::escape_for_literal` to handle `\r`
  - [x] Remove local `_py_literal_escape` from `runs.py`
  - [x] Replace call sites with `strategy.escape_for_literal(...)`
- [x] Create `cli/script_strategies/javascript_strategy.py`
  - [x] `codegen_target = "javascript"`, `file_extension = ".js"`
  - [x] Harness reads `process.env.QACLAN_*` env vars
  - [x] Uses `fs.existsSync` for state file check
  - [x] Attach `console`, `pageerror`, `requestfailed` event listeners
  - [x] `build_run_command` → `["node", script_path]`
  - [x] Override `escape_for_literal` to also escape `'`, backtick, `\r`
  - [x] `validate_runtime` checks `node` is on `PATH` and `playwright` npm package is resolvable (`node -e "require('playwright')"`)
- [x] Register `javascript` in `__init__.py`
- [ ] Smoke-test: record → render → run a trivial JS script end-to-end

### Phase 3 — TypeScript Support ⏳ PENDING

**Goal:** Add `typescript_strategy.py` by extending the JS strategy with minimal overrides.

- [x] Create `cli/script_strategies/typescript_strategy.py`
  - [x] Inherit from `JavaScriptStrategy`
  - [x] Override `file_extension = ".ts"` (keep `codegen_target = "javascript"` — Playwright has no `--target typescript`)
  - [x] Override `build_run_command` → `["npx", "tsx", script_path]`
  - [x] Override `validate_runtime` to check `npx tsx` is available
- [x] Register `typescript` in `__init__.py`
- [x] Smoke-test harness rendering + syntax-check all strategy files

## Constraints & Invariants

- `language` is required on every script row — no nullable, no implicit fallback in business logic.
- File extension must always match `strategy.file_extension`; renaming a script's language renames the file on disk (already handled in `scripts.py`).
- `validate_runtime()` must run **before** spawning the subprocess. Never let a missing `node` surface as a cryptic `FileNotFoundError` to the user.
- Escape functions are the single source of truth for literal embedding. No ad-hoc string formatting in `runs.py` or templates.
- Each strategy file must be standalone-importable; no circular imports between `_shared.py` and concrete strategies.

## Acceptance Criteria

- Existing Python scripts continue to record, render, and run with zero regressions.
- Recording a JS script produces a `.js` file that runs under `node` with the same env-var contract as Python.
- Recording a TS script produces a `.ts` file that runs under `npx tsx`.
- Missing `node` or `npx tsx` produces a pre-flight error with the missing tool name — not a subprocess crash mid-run.
- `grep -r "_py_literal_escape" cli/ web/` returns nothing after Phase 2.

## System Dependencies (Linux)

Playwright browser binaries require OS-level libraries not installed by default. After running `npx playwright install`, if you see errors like `libgstcodecparsers-1.0.so.0` or `libavif.so.13` missing, install them:

**Option A — Playwright all-in-one (recommended):**
```bash
npx playwright install-deps
```

**Option B — Install specific missing libraries manually (Debian/Ubuntu):**
```bash
sudo apt install -y libgstreamer-plugins-bad1.0-0 libavif13
```

These are one-time setup steps per machine. macOS and Windows users are not affected.

## Out-of-Scope Follow-ups

- Bun/Deno runtime support (would be a new strategy, not an override).
- Per-language linting / formatting on save.
- Strategy-specific recorder UI hints (e.g., "install tsx" helper).

## Session Notes

_Claude: append short dated notes here when you finish a task or hit a surprise. Keep it terse._

- 2026-04-17: Phase 2 complete. `javascript_strategy.py` added; `_py_literal_escape` removed from `runs.py`; all escape delegated to `strategy.escape_for_literal`. Smoke-test still pending.
- 2026-04-17: `validate_runtime` hardened on both strategies — JS now also checks `require('playwright')` via subprocess; Python (frozen binary mode) checks `import playwright` via subprocess. `package.json` added at repo root for contributor reference. README + CLAUDE.md updated with JS/TS install instructions.
- 2026-04-17: Documented Linux system dependency issue — `npx playwright install` may fail with missing `libgstcodecparsers-1.0.so.0` / `libavif.so.13`. Fix: `npx playwright install-deps` or `sudo apt install -y libgstreamer-plugins-bad1.0-0 libavif13`. Added to System Dependencies section.
- 2026-04-18: Phase 3 complete. `typescript_strategy.py` added; inherits `JavaScriptStrategy`, overrides `file_extension`, `build_run_command`, and `validate_runtime` (calls `super()` then checks `npx tsx --version`). Registered in `__init__.py`. All smoke-tests pass (harness render, escape, run command, py_compile).
