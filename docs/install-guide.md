# Install QAClan Agent

QAClan Agent is a self-contained binary. Install in two steps: **download** the binary, then run **`qaclan setup`** once to provision the runtime.

---

## 1. Download

### Windows (PowerShell)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
irm https://raw.githubusercontent.com/qaclan/agent/master/install.ps1 | iex
```

`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force` lets the installer script run **for this PowerShell session only**. Windows blocks unsigned remote scripts by default; `Bypass` lifts that block, `-Scope Process` limits it to the current window (no permanent system change), and `-Force` skips the confirmation prompt. When the window closes, the policy reverts.

`irm ... | iex` downloads `install.ps1` and runs it. It places the binary at `~/.qaclan/bin/qaclan.exe`, adds that folder to your user PATH, then runs `qaclan setup --runtime-only`.

### Linux / macOS

```sh
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

Installs the binary to `/usr/local/bin/qaclan` and runs `qaclan setup --runtime-only`.

> **Direct binary download** — if you grab the binary manually from the [Releases page](https://github.com/qaclan/agent/releases) instead of using the installer, skip the runtime flag and run the full `qaclan setup` (see below).

---

## 2. Set up — `qaclan setup`

`qaclan setup` is one idempotent command that bootstraps everything: PATH, binary placement, isolated Node + Python runtime, and the Chromium browser. Re-running it is safe — completed steps are skipped.

### What `qaclan setup` does (no flags = full install, all OS)

| Step | Action |
|---|---|
| 1. PATH / binary move | Copies the binary to the standard location, adds it to PATH |
| 2. Runtime dir | Creates `~/.qaclan/runtime/` |
| 3. `package.json` | Copies pinned `package.json` (bundled in the binary) into the runtime |
| 4. `npm install` | Installs Node deps (`playwright`, `@playwright/test`, `tsx`) inside the runtime |
| 5. venv | Creates a Python venv at `runtime/venv/` |
| 6. Playwright (pip) | Installs the pinned `playwright` pip package into the venv |
| 7. Chromium | Installs Chromium into `runtime/browsers/` |

Everything lands under `~/.qaclan/runtime/` — no `npm install -g`, no global pip, no PEP 668 / `externally-managed` errors. Existing global installs are left untouched.

### Per-OS behavior

| | Windows | Linux | macOS |
|---|---|---|---|
| Binary destination | `~/.qaclan/bin/qaclan.exe` | `~/.qaclan/bin/qaclan` | `~/.qaclan/bin/qaclan` |
| PATH persistence | `HKCU\Environment` registry (user scope only — never HKLM) | `export` line appended to shell rc | `export` line appended to shell rc |
| Shell rc file | n/a | `~/.bashrc` (bash), `~/.zshrc` (zsh), `~/.config/fish/config.fish` (fish), `~/.profile` (fallback) | same — detected from `$SHELL` |
| Apply PATH | Restart terminal | `source ~/.bashrc` or open new terminal | `source ~/.zshrc` or open new terminal |
| venv python | `runtime\venv\Scripts\python.exe` | `runtime/venv/bin/python` | `runtime/venv/bin/python` |

The runtime contents (Node deps, venv, Chromium) are identical across OS — only PATH mechanism and path separators differ.

### Flags

| Flag | Action |
|---|---|
| *(none)* | Full: move binary + PATH + runtime + Chromium |
| `--path-only` | Binary move + PATH only, skip runtime deps |
| `--runtime-only` | Runtime deps only, skip PATH/binary move (used by `install.sh` / `install.ps1`) |
| `--no-path` | Skip PATH step (binary already on PATH) |
| `--no-move` | Add current binary location to PATH, don't relocate it |
| `--no-chromium` | Skip Chromium install (faster, for CI / pre-staged browsers) |
| `--force` | Re-run every step even if already initialized (bypass skips) |

`--path-only` and `--runtime-only` cannot be combined.

> The installer scripts already handle binary placement + PATH, so they call `qaclan setup --runtime-only` to avoid duplicating that work. A **direct binary download** has nothing placed yet — run the bare `qaclan setup`.

### Verify

Confirm the install worked:

```sh
qaclan version
```

Prints the installed version:

```
qaclan 0.1.12
```

---

## 3. Reset — `qaclan reset-runtime`

Use when the runtime is corrupt, or after a Playwright version bump where you want a clean rebuild.

```sh
qaclan reset-runtime          # asks for confirmation
qaclan reset-runtime --yes    # skip the prompt
```

It deletes `~/.qaclan/runtime/` only — Node deps, venv, Chromium, `package.json`, hash sentinel. It does **not** touch your database, scripts, config, or the binary.

Rebuild afterward:

```sh
qaclan setup --runtime-only
```

---

## 4. Final layout (all OS)

```
~/.qaclan/
├── bin/qaclan(.exe)            # binary (added to PATH)
├── qaclan.db                   # SQLite database
├── config.json                 # auth_key, active_project
├── scripts/                    # your test scripts
├── runs/                        # run artifacts
└── runtime/                     # isolated dependencies (qaclan setup)
    ├── package.json             # pinned: playwright, @playwright/test, tsx
    ├── package-lock.json
    ├── node_modules/
    ├── venv/                    # Python venv
    │   ├── bin/python           # Scripts/python.exe on Windows
    │   └── lib/.../site-packages/playwright
    └── browsers/                # PLAYWRIGHT_BROWSERS_PATH target
        └── chromium-*/
```

`reset-runtime` wipes only the `runtime/` folder. Everything else under `~/.qaclan/` survives.
