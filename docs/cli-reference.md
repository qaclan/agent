# CLI Reference

Full command reference for the `qaclan` CLI. For install/setup, see the [README](../README.md) and [install-guide.md](install-guide.md).

Most commands operate on the **active project** (`qaclan project use <name>`), and most (except `login`/`logout`/`version`/`setup`/`serve`/`uninstall`) require you to be logged in (`qaclan login`) — they call an internal auth gate before running.

## Global

| Command | Description |
|---|---|
| `qaclan --help` | List all command groups. `--help` also works on any subcommand. |
| `qaclan --version` | Print version (baked into the binary, or `git describe` in dev mode). |
| `qaclan version` | Same as `--version`, as its own command. |

## Auth

### `qaclan login`

Log in to QAClan cloud with your auth key (from **qaclan.com → Settings → Auth Key**).

```bash
qaclan login                          # interactive prompt for the key
qaclan login --key <auth_key>         # non-interactive (CI/scripts)
qaclan login --key <auth_key> --server <url>   # point at a custom server
```

Validates the key against the server, then stores it (and your display name) in `~/.qaclan/config.json`.

### `qaclan logout`

Removes the stored auth key from `~/.qaclan/config.json`. Local data is untouched.

## Setup & runtime

### `qaclan setup`

Provisions the isolated Playwright runtime under `~/.qaclan/runtime/` (Node deps, Python venv, Chromium) and/or wires the binary onto your `PATH`. Idempotent — safe to re-run; a sha256 sentinel skips `npm install` when the bundled `package.json` hasn't changed.

| Flag | Effect |
|---|---|
| *(no flags)* | Full bootstrap: move binary to `~/.qaclan/bin/`, add to PATH, install runtime deps + Chromium. |
| `--runtime-only` | Runtime deps only (Node + Python + Chromium). Skips PATH/binary move. Used by `install.sh`/`install.ps1`. |
| `--path-only` | Binary move + PATH only. Skips runtime deps. |
| `--no-path` | Skip the PATH step (binary already on PATH). |
| `--no-move` | Don't relocate the binary; only add its current directory to PATH. |
| `--no-chromium` | Skip the Chromium download (faster, useful in CI or when browsers are pre-staged). |
| `--force` | Re-run every step even if already initialized. |

`--path-only` and `--runtime-only` are mutually exclusive.

### `qaclan reset-runtime`

Deletes `~/.qaclan/runtime/` (Node `node_modules/`, Python `venv/`, `browsers/`) so `qaclan setup --runtime-only` can rebuild it from scratch. Does **not** touch the database, scripts, or config. Useful after a corrupted runtime or a Playwright version bump.

```bash
qaclan reset-runtime          # prompts for confirmation
qaclan reset-runtime --yes    # skip the prompt
qaclan setup --runtime-only   # rebuild
```

## Uninstall

### `qaclan uninstall`

Fully removes QAClan from the machine: binary, PATH entries, and all local data. This is the recommended way to uninstall (works identically on Linux/macOS/Windows since it's a single command, unlike the shell scripts below).

```bash
qaclan uninstall          # prompts for confirmation, shows exactly what will be removed
qaclan uninstall --yes    # skip the confirmation prompt
```

What it does, in order:

1. **Removes PATH entries.** Linux/macOS: strips the `qaclan` PATH export line from shell rc files (`.bashrc`, `.zshrc`, etc.). Windows: removes `~/.qaclan/bin` from the user PATH (registry, `HKCU`).
2. **Scrubs shell history** (Linux/macOS only) — removes `qaclan` command entries from `.bash_history` / `.zsh_history` / fish history.
3. **Removes the system-installed binary** — e.g. `/usr/local/bin/qaclan` on Linux/macOS (uses `sudo` if the file isn't writable). On Windows, since the running `.exe` can't delete itself, it renames the binary and schedules deferred deletion via a detached `cmd` process that fires once the terminal closes.
4. **Deletes the entire `~/.qaclan/` data directory** — database (`qaclan.db`), recorded/imported scripts, the isolated runtime (`node_modules`, `venv`, Chromium), config, and auth credentials. On Windows this uses `ignore_errors` since the renamed old binary may still be locked; the deferred `cmd` cleans up any leftovers.

If nothing is installed (no `~/.qaclan/` and no system binary found), it prints a message and exits without doing anything.

> This is irreversible — all local projects, scripts, run history, and environments are deleted. There is no separate "keep data, remove binary" option in this command; use `qaclan reset-runtime` instead if you only want to rebuild the Playwright runtime.

### `uninstall.sh` / `uninstall.ps1` (standalone scripts)

Alternative uninstallers you can run without a working `qaclan` binary (e.g. the binary is already broken), fetched directly from GitHub:

```bash
# Linux/macOS
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/uninstall.sh | sh
```

```powershell
# Windows
irm https://raw.githubusercontent.com/qaclan/agent/master/uninstall.ps1 | iex
```

Both scripts prompt for confirmation, then:
- Remove the binary (`/usr/local/bin/qaclan`, or `%USERPROFILE%\.qaclan\bin\qaclan.exe`).
- Remove the entire `~/.qaclan` (or `%USERPROFILE%\.qaclan`) data directory.
- **`uninstall.ps1` additionally** strips `~/.qaclan/bin` from the Windows user PATH.
- Neither script scrubs shell history or shell rc files — that cleanup is only done by `qaclan uninstall` on Linux/macOS.

## Project

Projects are the top-level container for features, scripts, suites, environments, and API collections.

| Command | Description |
|---|---|
| `qaclan project create <name>` | Create a project and set it as active. |
| `qaclan project list` | List all projects (ID, name, created date). |
| `qaclan project use <project_id>` | Switch the active project. |
| `qaclan project show` | Show the currently active project. |
| `qaclan project delete <project_id>` | Delete a project and all its data (scripts, features, suites, runs, environments — cascades via `ON DELETE CASCADE`). Prompts for confirmation; also deletes script files from disk. |

## Environment

Environments hold key/value variables injected into test runs (e.g. base URLs, credentials per stage).

| Command | Description |
|---|---|
| `qaclan env create <name>` | Create a new environment in the active project. |
| `qaclan env set <env_name> <key> <value>` | Set (or update) a variable. Add `--secret` to mask the value in list output. |
| `qaclan env list [env_name]` | List all environments and their variables, or just one if `env_name` is given. Secret values print as `********`. |
| `qaclan env delete <env_name>` | Delete an environment and all its variables. Prompts for confirmation. |

## Status

### `qaclan status`

Prints a full overview of the active project: every WEB and API feature, its script count, and a warning for features with zero scripts. Ends with a one-line summary (total scripts / features, and how many features have no scripts).

```bash
qaclan status
```

## Runs

### `qaclan runs`

Lists run history for the active project (suite runs, one row each — suite, channel, status, scripts passed/total, start time, duration).

```bash
qaclan runs                     # all runs
qaclan runs --suite <suite_id>  # filter to one suite
```

### `qaclan run show <run_id>`

Shows detailed per-script results for a single run: status, duration, console error count, and for failures a classified plain-language error (category, message, "what to do", plus diagnostic details like the failing selector/timeout/URL when available).

```bash
qaclan run show <run_id>
qaclan run show <run_id> --verbose   # also print the raw traceback
```

Also reachable as `qaclan runs show <run_id>`.

### `qaclan runs report <run_id>`

Generates a self-contained, offline HTML report for a run.

```bash
qaclan runs report <run_id>
qaclan runs report <run_id> --output my-report.html
```

Defaults to writing `qaclan-report-<run_id>.html` in the current directory.

## Cloud sync

### `qaclan pull`

Downloads the team workspace from the cloud and merges it into the local database: projects, features, scripts (files written to `~/.qaclan/scripts/`), API collections/folders/requests/collection vars, environments/env vars, suites, and suite items. Existing local rows (matched by `cloud_id`) are updated in place; new cloud rows are inserted. Prints a per-item log while pulling, then a summary count.

```bash
qaclan pull
```

Requires `qaclan login` first.

### `qaclan push`

Force a full resync: re-enqueues every local entity for the active project (or all projects with `--all`) and drains the sync queue immediately (up to a 60s deadline), rather than waiting for the background queue to catch up on its own.

```bash
qaclan push              # push the active project only
qaclan push --all        # push every local project
```

If there's no active project and `--all` wasn't passed, it falls back to pushing everything. Requires login.

> Day-to-day sync is automatic and best-effort — every create/update/delete command above already enqueues itself in the background sync queue. `push`/`pull` are for explicit, on-demand full resyncs (e.g. onboarding a new machine, or forcing a stuck sync).

## Web testing

All under `qaclan web ...`. Manages Playwright-recorded browser test scripts, organized as feature → script, and suite → ordered scripts.

### `qaclan web feature`

| Command | Description |
|---|---|
| `qaclan web feature create <name>` | Create a web feature in the active project. |
| `qaclan web feature list` | List web features with script counts (⚠ flag for zero-script features). |
| `qaclan web feature delete <feature_id>` | Delete a feature. Warns and confirms if it still has scripts (deletes them too). |

### `qaclan web record`

```bash
qaclan web record --feature <feature_id> --name "name" [--url <start_url>] [--language python|javascript|javascript-test|typescript]
```

Launches Playwright **codegen** against the given start URL (or blank page). Interact with the app in the opened browser, then close it to stop recording — the captured actions are wrapped in a QAClan harness for the chosen language and saved as a new script under the feature.

Codegen driver resolution order: isolated runtime Node bin → isolated runtime venv → system `playwright` CLI on PATH → system Python `playwright` package. Requires `qaclan setup --runtime-only` if none are found. Requires a GUI/display — in Docker, run recording on your host machine instead.

### `qaclan web script`

| Command | Description |
|---|---|
| `qaclan web script list [--feature <feature_id>]` | List web scripts, optionally filtered to one feature. |
| `qaclan web script show <script_id>` | Print a script's file contents. |
| `qaclan web script import <file_path> --name <name> --feature <feature_id> [--language ...]` | Import an existing Playwright codegen script file into a feature. |
| `qaclan web script delete <script_id>` | Delete a script (and its file). Warns and confirms if it's used in any suite. |

### `qaclan web suite`

| Command | Description |
|---|---|
| `qaclan web suite create <name>` | Create a new (empty) web suite. |
| `qaclan web suite add --suite <suite_id> --script <script_id>` | Append a script to the end of a suite. |
| `qaclan web suite remove --suite <suite_id> --script <script_id>` | Remove a script from a suite. |
| `qaclan web suite reorder --suite <suite_id> --scripts <id1,id2,...>` | Set the exact run order of a suite's scripts. |
| `qaclan web suite show --suite <suite_id>` | Show a suite's scripts in order, plus first/last run status. |
| `qaclan web suite list` | List all web suites with script counts and last-run status. |
| `qaclan web suite delete <suite_id>` | Delete a suite (does not delete the underlying scripts). |

### `qaclan web run`

```bash
qaclan web run --suite <id_or_cloud_id_or_name> [--env <env_name>] [--browser chromium|firefox|webkit] \
               [--resolution WxH] [--headless] [--stop-on-fail]
```

Executes every script in a suite, in order, inside one shared browser context (so login/session state persists across scripts via `~/.qaclan/storage_state.json`). For each script:

- Extracts the recorded actions and patches in `wait_for_load_state("networkidle")` after every `goto`/`click`.
- Runs it against a fresh page, capturing console errors/warnings, page errors, and failed network requests.
- On failure, takes a screenshot (saved under `~/.qaclan/screenshots/`) and records a traceback.
- `--stop-on-fail` skips (not fails) all remaining scripts after the first failure.

`--env` loads that environment's variables into the process env for the duration of the run. Results are written to the `suite_runs`/`script_runs` tables (viewable via `qaclan runs` / `qaclan run show`) and the run is queued for cloud sync. Prints a pass/fail summary and the Run ID at the end.

## API testing

All under `qaclan api ...`. Manages HTTP API request collections (independent of the web/browser test scripts above).

| Command | Description |
|---|---|
| `qaclan api list [--collection <name>]` | List all collections, or the requests inside one collection. |
| `qaclan api run <name_or_id>` | Run a single API request by name or ID. |
| `qaclan api run --collection <name> [--env <env_name>]` | Run every request in a collection. |
| `qaclan api export <collection> [--output <dir>]` | Export a collection's requests as Bruno `.bru` files. |
| `qaclan api import <file_or_url> [--format auto\|har\|openapi\|postman\|bruno] [--collection <name>]` | Import requests from a HAR capture, OpenAPI/Swagger spec (file, URL, or YAML/JSON), Postman collection, or Bruno files. Format is auto-detected from the extension/content when `--format auto` (the default). |
| `qaclan api record [--url <start_url>]` | Opens a browser, captures every API call made while you interact with the app (via HAR), then prompts you to save the captured requests into a named collection. |

Pre/post request scripts, assertions, and auth — see [`docs/api-script-reference.md`](api-script-reference.md) and [`docs/api-assertions-reference.md`](api-assertions-reference.md) for the full syntax.

## Web UI

### `qaclan serve`

Starts the local Flask web UI (dashboard for everything above — projects, features, scripts, suites, runs, API collections).

```bash
qaclan serve                          # http://localhost:7823, opens your browser
qaclan serve --port 8000              # custom port
qaclan serve --host 0.0.0.0           # bind all interfaces (e.g. inside Docker)
qaclan serve --no-browser             # don't auto-open a browser tab
```

If you're logged in, this also starts the background sync-queue worker and triggers an immediate sync attempt.
