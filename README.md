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

QAClan provisions an **isolated runtime** under `~/.qaclan/runtime/` — pinned Playwright + Chromium that lives next to the binary, not in your global `npm` / `pip`. No version clashes with other projects on your machine.

Prerequisites: **Node.js 18+** (with `npm`) and **Python 3.9+** (with `venv`).

**Linux / macOS (one-liner):**

```bash
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

The installer downloads the binary, then runs `qaclan setup --runtime-only` to provision the runtime (Node deps + Python venv + Chromium). Supports Linux (amd64) and macOS (arm64).

**Windows (amd64 / arm64):**

Pick the build that matches your CPU:

- Intel/AMD 64-bit → [`qaclan-windows-amd64.exe`](https://github.com/qaclan/agent/releases/latest/download/qaclan-windows-amd64.exe)
- ARM64 (Surface Pro X, Copilot+ PCs) → [`qaclan-windows-arm64.exe`](https://github.com/qaclan/agent/releases/latest/download/qaclan-windows-arm64.exe)

Or grab the latest from the [releases page](https://github.com/qaclan/agent/releases/latest). After downloading, open **PowerShell** and run:

```powershell
.\qaclan-windows-amd64.exe setup
```

`qaclan setup` (no flags) does the full bootstrap: copies the binary to `%USERPROFILE%\.qaclan\bin\`, adds it to your user PATH, then provisions the runtime. Restart PowerShell after it finishes.

> **SmartScreen note:** Windows may warn that the binary is from an unknown publisher the first time you run it. Click **More info → Run anyway**, or unblock it with `Unblock-File .\qaclan.exe` in PowerShell.

**Direct binary download (any OS):**

Skip the installer, download the binary, then run `qaclan setup` once. The binary self-bootstraps everything (PATH + runtime + Chromium). Re-run safe (idempotent).

**Setup flags:**

| Flag | Use |
|---|---|
| `qaclan setup` | full: move binary, add to PATH, install runtime + Chromium |
| `qaclan setup --runtime-only` | runtime deps only (used by installers) |
| `qaclan setup --path-only` | binary move + PATH only |
| `qaclan setup --no-chromium` | skip Chromium download (CI / pre-staged browsers) |
| `qaclan setup --force` | re-run all steps even if already initialized |
| `qaclan reset-runtime` | wipe `~/.qaclan/runtime/` only (keeps DB, scripts, config) — re-run `setup --runtime-only` to rebuild |
### 3. Log in and launch the web UI

**Linux / macOS:**

```bash
qaclan login --key <your_auth_key> && qaclan serve
```

**Windows (PowerShell):**

```powershell
.\qaclan-windows-amd64.exe login --key <your_auth_key>
.\qaclan-windows-amd64.exe serve
```

(Use `qaclan-windows-arm64.exe` on ARM64 devices.)

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
├── bin/           <- qaclan binary (added to PATH by `qaclan setup`)
├── qaclan.db      <- SQLite database
├── scripts/       <- Recorded/imported script files
├── runs/          <- Run artifacts (screenshots, JSON)
├── runtime/       <- Isolated Playwright runtime (Node deps + venv + Chromium)
│   ├── package.json
│   ├── node_modules/
│   ├── venv/
│   └── browsers/
└── config.json    <- Active project setting
```

Cleanup:
- `qaclan reset-runtime` — wipe just the runtime so `qaclan setup --runtime-only` can rebuild it (keeps DB, scripts, config, binary).
- `qaclan uninstall` — wipe everything (binary, runtime, data).

## Upgrading from older releases

If you previously installed QAClan with global `npm install -g playwright` / `pip install playwright`, run:

```bash
qaclan setup --runtime-only
```

This provisions the new isolated runtime. Old globals are left alone (harmless). See [docs/migration-runtime.md](docs/migration-runtime.md) for full details.

## Learn More

- **Documentation:** [qaclan.com/docs](https://qaclan.com/docs)
- **Cloud & Team Plans:** [qaclan.com](https://qaclan.com)

## License

[Business Source License 1.1](LICENSE)
