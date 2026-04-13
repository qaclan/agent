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

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

Supports Linux (amd64) and macOS (arm64).

**Windows (amd64 / arm64):**

QAClan ships a standalone `.exe` — no Python required. Pick the build that matches your CPU:

- Intel/AMD 64-bit → [`qaclan-windows-amd64.exe`](https://github.com/qaclan/agent/releases/latest/download/qaclan-windows-amd64.exe)
- ARM64 (Surface Pro X, Copilot+ PCs) → [`qaclan-windows-arm64.exe`](https://github.com/qaclan/agent/releases/latest/download/qaclan-windows-arm64.exe)

Or grab the latest from the [releases page](https://github.com/qaclan/agent/releases/latest).

**Install Playwright:**

The Windows binary uses your system-installed Playwright instead of bundling it. Install Node.js from [nodejs.org](https://nodejs.org/) (LTS), then in PowerShell:

```powershell
npm install -g playwright@1.58.0
playwright install chromium
```

### 3. Log in and launch the web UI

```bash
qaclan login --key <your_auth_key> && qaclan serve
```

The browser opens at `http://localhost:7823` — start managing your Playwright tests locally.

## Features

- **Record tests** via Playwright codegen — no manual scripting needed
- **Organize** scripts into projects, features, and suites
- **Deterministic execution** — AI analyzes results, never touches test steps
- **Web UI** dashboard at `localhost:7823` for managing everything visually
- **Cloud sync** — best-effort sync to QAClan cloud for team insights
- **Environment management** — inject variables into test runs
- **Offline-capable** — everything works locally, cloud is optional

## Data Storage

All data is stored locally in your home directory:

- Linux / macOS: `~/.qaclan/`
- Windows: `%USERPROFILE%\.qaclan\` (e.g. `C:\Users\<you>\.qaclan\`)

```
.qaclan/
├── qaclan.db      <- SQLite database
├── scripts/       <- Recorded/imported script files
└── config.json    <- Active project setting
```

## Learn More

- **Documentation:** [qaclan.com/docs](https://qaclan.com/docs)
- **Cloud & Team Plans:** [qaclan.com](https://qaclan.com)

## License

[Business Source License 1.1](LICENSE)
