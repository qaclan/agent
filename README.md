<p align="center">
  <img src="logo.png" alt="QAClan" width="500">
</p>

<p align="center">
  <em>Your Playwright tests. Organized locally. Analyzed intelligently.</em>
</p>

<p align="center">
  Local-first Playwright test management agent with cloud-powered regression intelligence.
</p>

---

## Install

### Binary (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

Supports Linux (amd64) and macOS (arm64).

### From source (Python)

```bash
git clone https://github.com/qaclan/agent.git
cd agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Run with:

```bash
python qaclan.py [command]
```

## Quick Start

```bash
qaclan login              # Authenticate with your API key
qaclan serve              # Launch the web UI at http://localhost:7823
```

## Features

- **Record tests** via Playwright codegen — no manual scripting needed
- **Organize** scripts into projects, features, and suites
- **Deterministic execution** — AI analyzes results, never touches test steps
- **Web UI** dashboard at `localhost:7823` for managing everything visually
- **Cloud sync** — best-effort sync to QAClan cloud for team insights
- **Environment management** — inject variables into test runs
- **Offline-capable** — everything works locally, cloud is optional

## Data Storage

All data is stored locally at `~/.qaclan/`:

```
~/.qaclan/
├── qaclan.db      <- SQLite database
├── scripts/       <- Recorded/imported script files
└── config.json    <- Active project setting
```

## Learn More

Visit [qaclan.com](https://qaclan.com) for cloud features and team plans.

## License

[Business Source License 1.1](LICENSE)
