# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QAClan Agent is a local-first Playwright test management CLI and web UI. It organizes, records, executes, and analyzes Playwright-based E2E tests locally with optional cloud sync to qaclan.com.

## Commands

```bash
# Install Python dependencies (dev only — production binary self-bootstraps)
pip install -r requirements.txt

# Provision isolated Playwright runtime under ~/.qaclan/runtime/
# (Node deps + Python venv + Chromium). Replaces global npm/pip installs.
python qaclan.py setup --runtime-only           # dev mode
qaclan setup                                    # binary mode (full: PATH + runtime)

# Wipe just the runtime (keeps DB, scripts, config) — rebuild from scratch
qaclan reset-runtime
qaclan setup --runtime-only

# Run CLI directly
python qaclan.py --help

# Start web UI (Flask dev server at localhost:7823)
python qaclan.py serve --port 7823

# Build standalone binary (Nuitka)
bash build.sh          # Release: single-file binary in dist/
bash build.sh --dev    # Dev: standalone directory (faster)

# Docker
docker-compose up -d
```

There are no automated tests or linting configured.

## Architecture

**Entry point:** `qaclan.py` — Click CLI that registers all command groups and initializes the SQLite database on every invocation via `init_db()`.

**Two interfaces to the same data:**
- **CLI** (`cli/commands/`) — Click commands for terminal use (project, auth, env, status, runs, sync)
- **Web UI** (`web/`) — Flask server + vanilla JS SPA (`web/static/app.js`). Routes in `web/routes/` are REST endpoints consumed by the frontend.

**Data layer:**
- `cli/db.py` — SQLite schema (11 tables), migrations, thread-local connections (`threading.local`). WAL mode enabled. All data stored in `~/.qaclan/qaclan.db`.
- `cli/config.py` — Reads/writes `~/.qaclan/config.json` (auth_key, active_project, server_url).

**Cloud sync** (`cli/api.py`, `cli/sync.py`) — Best-effort REST calls to qaclan.com. Sync never blocks CLI operations; failures are silently caught. Tables have `cloud_id` columns for mapping local to remote entities.

**Playwright integration:**
- `cli/script_strategies/` — One strategy per language (Python, JavaScript, JavaScript-test, TypeScript). Each strategy owns the codegen target, harness template, URL-placeholder rewriting, and subprocess argv used at run time. Scripts are self-contained harnesses that read `QACLAN_*` env vars (state path, artifacts path, browser, headless, viewport) set by the runner.
- **Isolated runtime** (`cli/runtime_setup.py`): per-user deps live at `~/.qaclan/runtime/` — `node_modules/` (`playwright`, `@playwright/test`, `tsx`), `venv/` (pip `playwright`), `browsers/` (Chromium). Strategy `_resolve_*` helpers prefer runtime paths first, then fall back to global installs with a one-time deprecation warning (`emit_deprecation_warning()`). Phase-out planned for major-version bump.
- **Pinned versions** live in `cli/runtime_assets/package.json` — single source of truth, scannable by Renovate/Dependabot. `runtime_setup.PINNED_PLAYWRIGHT_VERSION` is derived from it. The file is bundled into the Nuitka binary via `--include-data-dir=cli/runtime_assets=cli/runtime_assets` and copied to `~/.qaclan/runtime/package.json` at setup time.
- **`qaclan setup`** orchestrates: PATH config, copy template `package.json`, `npm install`, create venv, pip-install playwright, install Chromium under `runtime/browsers/`. Idempotent — sha256 hash sentinel (`runtime/.package.sha256`) skips `npm install` when template unchanged. Flags: `--path-only`, `--runtime-only`, `--no-path`, `--no-move`, `--no-chromium`, `--force`. `qaclan reset-runtime` wipes `runtime/` only so setup can rebuild from scratch.
- `validate_runtime()` on each strategy checks deps pre-flight. When called from a request, broken runtime returns `needs_setup: true` + `setup_command` in the JSON so the UI can render a setup banner.
- Scripts stored as files in `~/.qaclan/scripts/` and referenced by the `scripts` table.
- Run execution (`web/routes/runs.py`): one subprocess per script under `~/.qaclan/runtime/runs/<run_id>/`. Located inside `runtime/` so Node's parent-dir module walk hits `runtime/node_modules` first — prevents a stray `~/node_modules` (e.g. user-installed playwright at home) from shadowing the runtime's pinned playwright. Shared `state.json` in that dir carries cookies / localStorage between scripts — the cross-language state mechanism. Per-script timeout is 300s. `PLAYWRIGHT_BROWSERS_PATH` resolved via `runtime_setup.browsers_path_if_present()` (runtime), then frozen-binary default, then unset.

**API testing integration:**
- `cli/api_runner.py` — executes `api_requests` rows via `httpx`, in-process (no subprocess for the HTTP call itself). Handles `{{var}}` resolution, auth injection (bearer/basic/api_key/oauth2), no-code extractors, pre/post script sandboxes, and assertion evaluation.
- Pre/post scripts (`pre_script`/`post_script`, JS or Python) run as real subprocesses via the runtime venv/Node — see `_build_python_sandbox`/`_build_js_sandbox`/`_run_script_sandbox`. Full syntax reference, exact bindings (`qc.set`/`qc.setHeader`/etc.), and known gaps: **`docs/api-script-reference.md`**.
- **Maintenance rule:** any change to pre/post script behavior — sandbox builders/bindings in `cli/api_runner.py`, the `pre_script`/`post_script`/`pre_extractor`/`post_extractor` columns in `cli/db.py`, storage in `web/api/repositories/request_repo.py`, Postman/Bruno import mapping of test scripts (`cli/api_discovery/postman_parser.py`, `bruno_parser.py`), or the script editor UI (`web/static/api/views/request-editor-view.js`, `collection-detail-view.js`) — must be reflected in `docs/api-script-reference.md` in the same change. Grep for `pre_script\|post_script\|qc\.\|pre_extractor\|post_extractor` if unsure whether a touched file is in scope. That doc is the syntax source of truth and must never drift from the code.
- **Maintenance rule:** any change to no-code assertion behavior — `TYPE_OPS`/`OP_LABELS`/row wiring in `web/static/api/components/assertion-builder.js`, `_compare`/`_evaluate_assertions` in `cli/api_runner.py`, the `assertions` column handling in `web/api/repositories/request_repo.py`, or assertion-result rendering in `web/static/api/components/response-panel.js` and `web/static/api/views/collection-run-view.js` — must be reflected in `docs/api-assertions-reference.md` in the same change. Grep for `assertion\|TYPE_OPS\|_compare` if unsure whether a touched file is in scope.
- Response schema check (opt-in drift detection): each run can compare the inferred response type-tree against the request's **frozen `response_schema` baseline** and fail on breaking changes / notify on additive ones. The baseline reuses the existing `response_schema` column — captured once (first JSON response or HAR/discovery import), then never auto-overwritten, changed only via "Update response schema". Diff+severity+verdict live in `cli/schema_diff.py`; the check runs in `cli/api_runner.py::run_api_request`; enablement resolution (request `schema_check` tri-state override + collection `schema_check_default`, inheritance) and baseline capture live in `web/api/services/runner_service.py`. Verdicts persist as `schema_drift` on `api_request_results`/`api_runs`. Full reference: **`docs/api-schema-check-reference.md`**.
- **Maintenance rule:** any change to response-schema-check behavior — `diff_schemas`/severity/verdict in `cli/schema_diff.py`, the runner wiring in `cli/api_runner.py`, resolution/capture in `web/api/services/runner_service.py`, the `schema_check`/`schema_check_default`/`schema_drift` columns and the frozen-`response_schema` baseline in `cli/db.py` and their repositories (`request_repo.py`, `collection_repo.py`, `collection_run_repo.py`, `api_run_repo.py`), sync mapping (`cli/sync.py`, `cli/commands/pull.py`), the HTML report (`cli/api_report.py`), or the UI (`web/static/api/components/response-panel.js`, `web/static/api/views/request-editor-view.js`, `collection-detail-view.js`, `collection-run-view.js`) — must be reflected in `docs/api-schema-check-reference.md` in the same change. Grep for `schema_check\|response_schema\|schema_drift\|diff_schemas` if unsure whether a touched file is in scope.

**Binary distribution:** Nuitka compiles to standalone binaries. `build.sh` handles platform-specific bundling. GitHub Actions (`.github/workflows/release.yml`) builds Linux/macOS/Windows (amd64+arm64) binaries on version tags. Both `build.sh` and the Windows inline Nuitka calls in the workflow must include `--include-data-dir=cli/runtime_assets=cli/runtime_assets` — without it, the bundled `package.json` is missing and `runtime_setup` raises a clear error at first call.

## Key Patterns

- **Local-first, cloud-optional:** All features work offline. Cloud sync adds team collaboration but is never required.
- **Active project context:** Most commands operate on the "active" project set via `qaclan project use <name>`. Stored in config.json.
- **Database migrations:** `cli/db.py` runs `_run_migrations()` on init to evolve the schema (e.g., adding `cloud_id` columns).
- **Rich terminal output:** CLI uses the `rich` library for formatted tables and colored output.
- **Nuitka binary detection:** Several modules check if running as a compiled binary to adjust paths (e.g., Playwright browser/driver paths).
- **Installer / setup split:** `install.sh` (Linux/macOS) places the binary in `/usr/local/bin/` (universal PATH) and runs `qaclan setup --runtime-only`. `install.ps1` (Windows) copies to `~/.qaclan/bin/`, writes user PATH via `[Environment]::SetEnvironmentVariable`, then `qaclan setup --runtime-only`. Direct binary downloaders run `qaclan setup` (no flags) to do PATH+move+runtime in one shot. The full `qaclan setup` would re-do the move+PATH that installers already handle — `--runtime-only` skips that duplicate work.
