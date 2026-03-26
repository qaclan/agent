# QAClan CLI

A standalone CLI tool for QA test management and execution. Manage projects, features, scripts, suites, environments, and test runs — all stored locally in SQLite.

Built with Python, Click, and Rich. Supports browser test recording via Playwright codegen.

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# For browser recording support
pip install playwright
playwright install chromium
```

## Quick Start

```bash
# Create a project
python cli.py project create "MyApp"

# Create a feature and record a test
python cli.py web feature create "Login"
python cli.py web record --feature feat_abc123 --name "Verify successful login"

# Set up an environment
python cli.py env create staging
python cli.py env set staging BASE_URL https://staging.example.com
python cli.py env set staging PASSWORD secret123 --secret

# Create a suite, add scripts, and run
python cli.py web suite create "Smoke Suite"
python cli.py web suite add --suite suite_abc123 --script script_abc123
python cli.py web run --suite suite_abc123 --env staging
```

## Commands

### Project

| Command | Description |
|---------|-------------|
| `project create "name"` | Create a project and set it as active |
| `project list` | List all projects |
| `project use <id>` | Switch active project |
| `project show` | Show active project |

### Environment

| Command | Description |
|---------|-------------|
| `env create <name>` | Create an environment |
| `env set <name> KEY value` | Set a variable (`--secret` to mask) |
| `env list [name]` | List environments and variables |
| `env delete <name>` | Delete an environment |

### Web Features

| Command | Description |
|---------|-------------|
| `web feature create "name"` | Create a web feature |
| `web feature list` | List features with script counts |
| `web feature delete <id>` | Delete a feature |

### Web Recording

| Command | Description |
|---------|-------------|
| `web record --feature <id> --name "name"` | Record a browser test via Playwright codegen |
| `web record --feature <id> --name "name" --url <url>` | Record with a start URL |

### Web Scripts

| Command | Description |
|---------|-------------|
| `web script list [--feature <id>]` | List scripts, optionally filtered by feature |
| `web script show <id>` | Print script content |
| `web script import <file> --name "name" --feature <id>` | Import an existing script file |
| `web script delete <id>` | Delete a script |

### Web Suites

| Command | Description |
|---------|-------------|
| `web suite create "name"` | Create a test suite |
| `web suite add --suite <id> --script <id>` | Add a script to a suite |
| `web suite reorder --suite <id> --scripts id1,id2,id3` | Reorder scripts |
| `web suite remove --suite <id> --script <id>` | Remove a script from a suite |
| `web suite show --suite <id>` | Show suite details |
| `web suite list` | List all suites |
| `web suite delete <id>` | Delete a suite |

### Web Execution

| Command | Description |
|---------|-------------|
| `web run --suite <id> --env <name>` | Run a suite with environment variables |
| `web run --suite <id>` | Run without environment |
| `web run --suite <id> --env <name> --stop-on-fail` | Stop on first failure |

### Status & Run History

| Command | Description |
|---------|-------------|
| `status` | Show full project overview by channel |
| `runs [--suite <id>]` | List run history |
| `run show <id>` | Show detailed results for a run |

### API (Coming Soon)

The `api` command group is scaffolded but not yet implemented. All subcommands print a "coming soon" message.

## Data Storage

All data is stored locally at `~/.qaclan/`:

```
~/.qaclan/
├── qaclan.db      ← SQLite database
├── scripts/       ← Recorded/imported script files
└── config.json    ← Active project setting
```

## Build

Compile into a standalone binary using Nuitka:

```bash
pip install nuitka
bash build.sh
# Output: dist/qaclan
```
