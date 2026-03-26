## Context

This is a greenfield Python CLI project. There is no existing codebase. The tool targets QA engineers who need a local, portable workflow for managing web test scripts recorded via Playwright, organizing them into features and suites, and executing them with environment-specific configuration.

The user has provided a complete specification including command structure, database schema, file layout, output format, and error handling. The primary design decisions revolve around how to structure the codebase for maintainability and how to wire together Click, Rich, SQLite, and Playwright.

## Goals / Non-Goals

**Goals:**
- Deliver a fully functional local CLI for web QA test management
- Channel-based command architecture (`web`, `api`) that scales to future test types
- Clean separation: database layer, config layer, command layer
- Rich terminal output with consistent formatting
- Single-binary distribution via Nuitka

**Non-Goals:**
- Cloud sync, authentication, or remote APIs
- API test execution (scaffold only)
- Mobile testing
- Web UI or server component
- Plugin system or extensibility framework
- Parallel test execution within a suite

## Decisions

### 1. Click for CLI framework
**Choice:** Click with nested command groups.
**Rationale:** Click's group/subgroup model maps directly to the `qaclan web feature`, `qaclan web suite` hierarchy. Alternatives like argparse would require manual subcommand routing. Typer adds a typing layer that isn't needed here.

### 2. Single SQLite database with flat schema
**Choice:** One `~/.qaclan/qaclan.db` file, no ORM, raw SQL via Python's `sqlite3` module.
**Rationale:** The data model is simple (12 tables, no complex joins). An ORM like SQLAlchemy adds dependency weight without value for this schema size. Raw SQL keeps the db layer transparent and the binary small.

### 3. Short UUID IDs with type prefixes
**Choice:** 8-character UUID prefixes with type hints (`proj_`, `feat_`, `script_`, `suite_`, `env_`, `run_`, `srun_`, `step_`).
**Rationale:** Readable IDs that users can copy-paste in commands. The prefix makes IDs self-documenting in output and error messages. `uuid.uuid4().hex[:8]` provides sufficient uniqueness for a local-only tool.

### 4. Script files stored on disk, metadata in DB
**Choice:** Script Python files live at `~/.qaclan/scripts/<id>.py`. The DB stores the path, name, and metadata.
**Rationale:** Scripts may be large (recorded Playwright output). Storing them as files keeps the DB small and makes scripts directly editable/runnable outside the CLI. The DB is the index.

### 5. Rich for terminal output
**Choice:** Use `rich.console.Console`, `rich.table.Table`, and `rich.text.Text` for all output.
**Rationale:** Rich provides table formatting, colored output, and Unicode symbols without manual ANSI escape codes. Consistent with the output style requirements (green checkmarks, red crosses, yellow warnings).

### 6. Subprocess-based test execution
**Choice:** Execute each script via `subprocess.run(["python", script_path])` with environment variables injected.
**Rationale:** Scripts are standalone Python files (Playwright codegen output). Running them as subprocesses provides isolation — a script crash doesn't take down the CLI. Environment variables are the natural injection mechanism since Playwright scripts read from `os.environ`.

### 7. Module structure mirrors command hierarchy
**Choice:** `cli/commands/web/feature.py` maps to `qaclan web feature`. Each command file registers its Click group/commands.
**Rationale:** New commands are added by creating a file and registering its group. The file tree is navigable by someone who knows the CLI commands.

## Risks / Trade-offs

- **[Risk] Playwright codegen dependency** — Users must have Playwright installed separately. The CLI can't bundle it in the Nuitka binary. → Mitigation: Clear error message with install command when Playwright is missing.
- **[Risk] No test isolation between suite scripts** — Scripts share a global process environment. If one script leaves state (cookies, localStorage), it may affect the next. → Mitigation: This is acceptable for phase 1. Users can add cleanup to scripts. Suite-level browser context management is a future enhancement.
- **[Risk] Nuitka binary size** — Including `rich` and `click` in a standalone binary may produce a large file. → Mitigation: Acceptable trade-off for distribution simplicity. Can optimize later with `--noinclude-default-mode=nofollow`.
- **[Trade-off] No concurrent script execution** — Scripts run sequentially. Suites with many scripts will be slow. → Acceptable: sequential execution is simpler to reason about and matches the `--stop-on-fail` model.
- **[Trade-off] No migration system for SQLite schema** — Schema is created on first run with `CREATE TABLE IF NOT EXISTS`. Future schema changes will need manual migration. → Acceptable for v1. Can add a version table and migration scripts later.
