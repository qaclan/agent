## Why

QA teams need a local-first CLI tool to manage the full test lifecycle — projects, features, scripts, suites, environments, and execution — without cloud dependencies. Currently there is no unified tool that handles web test recording (via Playwright codegen), test organization by feature, suite-based execution with environment variable injection, and run history tracking in a single CLI. Building `qaclan` as a standalone binary provides a portable, self-contained QA workflow tool that can later integrate with cloud sync.

## What Changes

- New CLI tool `qaclan` built in Python with Click and Rich
- Channel-based command structure: `qaclan web` for web automation, `qaclan api` (scaffolded, not implemented)
- Shared top-level commands: `project`, `env`, `status`, `runs`
- Web channel commands: `feature`, `record`, `script`, `suite`, `run`
- Local SQLite database at `~/.qaclan/qaclan.db` for all state
- Playwright codegen integration for browser test recording
- Suite-based test execution with environment variable injection
- Run history with per-script results tracking
- Single binary build via Nuitka

## Capabilities

### New Capabilities
- `project-management`: Create, list, switch, and show projects. Active project stored in config.json.
- `environment-management`: Create environments with key-value variables (including secrets). Environment vars injected into test runs.
- `web-features`: Create, list, and delete web features that organize scripts by functional area.
- `web-recording`: Record browser interactions via Playwright codegen and save as named scripts under features.
- `web-scripts`: List, show, import, and delete web test scripts. Scripts stored as Python files.
- `web-suites`: Create suites of ordered scripts. Add, remove, reorder scripts within suites.
- `web-execution`: Execute suites with environment injection, track pass/fail per script, record run history.
- `status-overview`: Show full project state grouped by channel with script counts and warnings.
- `run-history`: View all runs, filter by suite, show detailed per-script results for individual runs.
- `api-channel-scaffold`: Placeholder command group for future API testing — all subcommands print "coming soon".
- `local-storage`: SQLite database schema, config file management, script file storage at ~/.qaclan/.
- `binary-build`: Nuitka build script to produce standalone single-file binary.

### Modified Capabilities
<!-- No existing capabilities to modify — this is a greenfield project. -->

## Impact

- New Python package with Click CLI entrypoint (`cli.py`)
- Dependencies: `click`, `rich`, `playwright`
- Build dependency: `nuitka`
- Creates `~/.qaclan/` directory structure on first run
- No external APIs or services affected — fully local
