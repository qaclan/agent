## 1. Project Setup

- [x] 1.1 Create directory structure: `cli.py`, `cli/`, `cli/commands/`, `cli/commands/web/`, `cli/commands/api/` with `__init__.py` files
- [x] 1.2 Create `requirements.txt` with click, rich, playwright dependencies
- [x] 1.3 Create `build.sh` with Nuitka build command

## 2. Local Storage & Config

- [x] 2.1 Implement `cli/config.py` — read/write `~/.qaclan/config.json`, ensure `~/.qaclan/` and `~/.qaclan/scripts/` directories exist
- [x] 2.2 Implement `cli/db.py` — SQLite connection, `init_db()` creating all 11 tables, helper for short UUID generation with type prefixes
- [x] 2.3 Add `get_active_project()` helper that reads config and validates project exists in DB, printing error if not set

## 3. Project Commands

- [x] 3.1 Implement `cli/commands/project.py` — `project create`, `project list`, `project use`, `project show`
- [x] 3.2 Wire project group into `cli.py` entrypoint with Click

## 4. Environment Commands

- [x] 4.1 Implement `cli/commands/env.py` — `env create`, `env set` (with `--secret`), `env list` (all or specific), `env delete` (with confirmation)
- [x] 4.2 Wire env group into `cli.py`

## 5. Web Feature Commands

- [x] 5.1 Implement `cli/commands/web/feature.py` — `feature create`, `feature list`, `feature delete` (with confirmation and script warning)
- [x] 5.2 Register web group in `cli/commands/web/__init__.py` and wire into `cli.py`

## 6. Web Recording

- [x] 6.1 Implement `cli/commands/web/record.py` — launch Playwright codegen, capture output, save script file, create DB record with `source = CLI_RECORDED`
- [x] 6.2 Handle error cases: Playwright missing, empty recording, feature not found

## 7. Web Script Commands

- [x] 7.1 Implement `cli/commands/web/script.py` — `script list` (with `--feature` filter), `script show`, `script import` (with `--feature` required), `script delete` (with suite warning)

## 8. Web Suite Commands

- [x] 8.1 Implement `cli/commands/web/suite.py` — `suite create`, `suite add`, `suite reorder`, `suite remove`, `suite show`, `suite list`, `suite delete`

## 9. Web Execution

- [x] 9.1 Implement `cli/commands/web/run.py` — load suite items, validate channel, inject env vars, execute scripts via subprocess, track pass/fail/skip per script
- [x] 9.2 Implement `--stop-on-fail` flag to halt on first failure and mark remaining as SKIPPED
- [x] 9.3 Implement run summary output with failed script details and run ID
- [x] 9.4 Update `suites` table with `last_run_at`, `last_run_status`, and `first_run_at` on each run

## 10. Status & Run History

- [x] 10.1 Implement `cli/commands/status.py` — show project state grouped by channel with feature/script tree and warnings
- [x] 10.2 Implement `cli/commands/runs.py` — `runs` (list all, filter by `--suite`), `run show` (detailed per-script results)

## 11. API Channel Scaffold

- [x] 11.1 Implement `cli/commands/api/__init__.py` and `cli/commands/api/stubs.py` — register `api` group with `feature`, `suite`, `run` subcommands that all print `⚠ API testing is coming soon.`

## 12. CLI Entrypoint & Integration

- [x] 12.1 Implement `cli.py` — create root Click group, register all command groups (project, env, status, runs, web, api), call `init_db()` on startup
- [x] 12.2 Verify all commands are accessible and help text displays correctly
