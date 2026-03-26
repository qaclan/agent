# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QAClan CLI (`qaclan`) — a local-first QA test management and execution tool. Python CLI using Click + Rich + SQLite. All state stored at `~/.qaclan/`. No cloud dependency.

## Development Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# For browser recording: pip install playwright && playwright install chromium
```

## Running

```bash
python cli.py [command]           # Run directly
python cli.py --help              # See all commands
bash build.sh                    # Nuitka build → dist/qaclan
```

There are no tests, linter, or CI configured yet.

## Architecture

**Entry point:** `cli.py` — creates the root Click group, calls `init_db()` on every invocation, and registers all command groups.

**Two layers below root:**
- **Shared commands** (no channel prefix): `project`, `env`, `status`, `runs`, `run show`
- **Channel commands**: `web` (fully implemented), `api` (stubs only — prints "coming soon")

**Core modules:**
- `cli/db.py` — singleton SQLite connection (`get_conn()`), schema init (`init_db()`), ID generation (`generate_id(prefix)` → `prefix_8hexchars`)
- `cli/config.py` — reads/writes `~/.qaclan/config.json`, provides `get_active_project(console)` which every command calls as a guard

**Command pattern:** Every command module follows the same structure:
1. Call `get_active_project(console)` — returns `None` (with error printed) if no project active
2. Use `get_conn()` for DB access, `generate_id("prefix")` for new entities
3. Output via `rich.console.Console` — green `✓` for success, red `✗` for failure, yellow `⚠` for warnings, `rich.table.Table` for lists

**Data hierarchy:** Project → Feature (channel: web|api) → Script → Suite → Run → Script Results

**Script storage:** Recorded/imported Python files live at `~/.qaclan/scripts/<script_id>.py`. The DB stores metadata; the filesystem stores the actual script content.

**Execution model (`cli/commands/web/run.py`):** Scripts run as subprocesses (`subprocess.run`) with environment variables injected from the selected environment. Exit code 0 = PASSED, non-zero = FAILED. Results recorded per-script in `script_runs` table. Supports `--stop-on-fail` to skip remaining scripts.

## Conventions

- Entity IDs use type prefixes: `proj_`, `feat_`, `script_`, `suite_`, `env_`, `run_`, `srun_`, `si_`, `evar_`, `step_`
- Error messages always suggest the next command to run
- Channel label `[WEB]` or `[API]` shown in create confirmations and headers
- Confirmation prompts required before deletes
- `runs` is a group with `invoke_without_command=True`; `run show <id>` is separately registered at root level for convenience
