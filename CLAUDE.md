# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QAClan Agent is a local-first Playwright test management CLI and web UI. It organizes, records, executes, and analyzes Playwright-based E2E tests locally with optional cloud sync to qaclan.com.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

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
- `cli/script_strategies/` — One strategy per language (Python today; JS/TS later). Each strategy owns the codegen target, harness template, URL-placeholder rewriting, and subprocess argv used at run time. Scripts are self-contained harnesses that read `QACLAN_*` env vars (state path, artifacts path, browser, headless, viewport) set by the runner.
- Scripts stored as files in `~/.qaclan/scripts/` and referenced by the `scripts` table.
- Run execution (`web/routes/runs.py`): one subprocess per script under `~/.qaclan/runs/<run_id>/`. Shared `state.json` in that dir carries cookies / localStorage between scripts — the cross-language state mechanism. Per-script timeout is 300s.

**Binary distribution:** Nuitka compiles to standalone binaries. `build.sh` handles platform-specific bundling. GitHub Actions (`.github/workflows/release.yml`) builds Linux/macOS binaries on version tags.

## Key Patterns

- **Local-first, cloud-optional:** All features work offline. Cloud sync adds team collaboration but is never required.
- **Active project context:** Most commands operate on the "active" project set via `qaclan project use <name>`. Stored in config.json.
- **Database migrations:** `cli/db.py` runs `_run_migrations()` on init to evolve the schema (e.g., adding `cloud_id` columns).
- **Rich terminal output:** CLI uses the `rich` library for formatted tables and colored output.
- **Nuitka binary detection:** Several modules check if running as a compiled binary to adjust paths (e.g., Playwright browser/driver paths).
