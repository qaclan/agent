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

## Getting Started

### 1. Sign up and get your auth key

Create an account at [qaclan.com](https://qaclan.com) and copy your auth key from **Settings > Auth Key**.

### 2. Install the agent

```bash
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

Supports Linux (amd64) and macOS (arm64).

### 3. Launch the web UI

```bash
qaclan serve
```

### 4. Enter your auth key

When the browser opens at `http://localhost:7823`, enter your auth key and start managing your Playwright tests locally.

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
