# Binary Dependencies Installation Plan

Status: **planning** — not yet implemented.
Owner: TBD.
Target: replace global `npm install -g` and global pip installs with isolated per-user runtime under `~/.qaclan/runtime/`.

---

## 1. Goal

Make `qaclan` a self-contained, self-bootstrapping CLI:

- No `npm install -g` of Playwright / `@playwright/test` / `tsx`.
- No global `pip install playwright`.
- Binary alone is enough — running `qaclan setup` provisions everything (PATH, Node deps, Python venv, Chromium browser).
- Existing global installs left untouched (no automatic uninstall).

---

## 2. Current State (problems)

| Layer | Where today | Problem |
|---|---|---|
| Python `playwright` pkg | global pip (system or user site-packages) | pollutes user env, version clash with other projects, PEP 668 ("externally-managed") on macOS / modern Linux |
| Node `playwright`, `@playwright/test`, `tsx` | global npm (`npm install -g`) | clashes with other Playwright versions on machine, requires npm global bin on PATH, version drift if user upgrades Playwright in another project |
| Chromium browser | `~/.cache/ms-playwright/` (default) | shared across all Playwright installs on the machine — usually fine, but tied to whichever Playwright runs first |
| PATH for binary | manual / installer-only | direct binary downloaders must edit PATH themselves |

Pinned `playwright@1.58.0` global is a land-mine: any other project that bumps Playwright will break qaclan.

---

## 3. Design — Isolated Runtime

### 3.1 Final layout

```
~/.qaclan/
├── bin/qaclan(.exe)                 # binary (added to PATH)
├── qaclan.db                        # SQLite (existing)
├── config.json                      # auth_key, active_project (existing)
├── scripts/                         # user scripts (existing)
├── runs/                            # run artifacts (existing)
└── runtime/                         # NEW — isolated dependencies
    ├── package.json                 # pinned: playwright@1.58.0, @playwright/test@1.58.0, tsx
    ├── package-lock.json
    ├── node_modules/
    ├── venv/                        # python venv
    │   ├── bin/python               # (Scripts/python.exe on Windows)
    │   └── lib/.../site-packages/playwright
    └── browsers/                    # PLAYWRIGHT_BROWSERS_PATH target
        └── chromium-*/
```

### 3.2 Why local, not global

Modern standard for production CLI tools:

- Cypress, Playwright Test, Vite, Storybook → project-local `node_modules`.
- `gh`, `terraform`, `kubectl` → ship all deps inside binary.
- Global only acceptable for dev tools the user explicitly *wants* global.

Per-user runtime gives:
- Pinned versions safe from external bumps.
- `qaclan` upgrade ≡ `runtime/` upgrade, no system-wide impact.
- No PEP 668 / `npm prefix` / global-bin-PATH issues.

---

## 4. `qaclan setup` — Self-Bootstrap Command

Single subcommand that handles **PATH + runtime deps + Chromium**. Idempotent — re-run safe.

### 4.1 Default flow

**Windows:**
```
$ qaclan setup
>>> Binary at: C:\Users\foo\Downloads\qaclan-windows-amd64.exe
>>> Move to standard location? [y/n/yes/no] (default: yes): y
>>> Copied to: C:\Users\foo\.qaclan\bin\qaclan.exe
>>> Add C:\Users\foo\.qaclan\bin to user PATH? [y/n/yes/no] (default: yes): y
>>> PATH updated (HKCU\Environment). Restart terminal to apply.
>>> Initializing runtime (Node + Python deps)...
>>> Setup complete.
```

**Linux:**
```
$ qaclan setup
>>> Binary at: /home/foo/Downloads/qaclan-linux-amd64
>>> Move to standard location? [y/n/yes/no] (default: yes): y
>>> Copied to: /home/foo/.qaclan/bin/qaclan
>>> Add /home/foo/.qaclan/bin to PATH via ~/.bashrc? [y/n/yes/no] (default: yes): y
>>> Appended PATH export to ~/.bashrc. Run: source ~/.bashrc  (or open new terminal).
>>> Initializing runtime (Node + Python deps)...
>>> Setup complete.
```

**macOS:**
```
$ qaclan setup
>>> Binary at: /Users/foo/Downloads/qaclan-macos-arm64
>>> Move to standard location? [y/n/yes/no] (default: yes): y
>>> Copied to: /Users/foo/.qaclan/bin/qaclan
>>> Add /Users/foo/.qaclan/bin to PATH via ~/.zshrc? [y/n/yes/no] (default: yes): y
>>> Appended PATH export to ~/.zshrc. Run: source ~/.zshrc  (or open new terminal).
>>> Initializing runtime (Node + Python deps)...
>>> Setup complete.
```

Shell rc file detected from `$SHELL` (`zsh` → `~/.zshrc`, `bash` → `~/.bashrc`, `fish` → `~/.config/fish/config.fish`, fallback → `~/.profile`).

### 4.2 Flags

| Flag | Action |
|---|---|
| (none) | full: move binary + PATH + runtime + Chromium |
| `--path-only` | binary move + PATH only, skip deps |
| `--runtime-only` | deps only, skip PATH (used by `install.sh` / `install.ps1`) |
| `--no-path` | skip PATH step (binary already on PATH) |
| `--no-move` | add current binary location to PATH, don't relocate |
| `--no-chromium` | skip `playwright install chromium` (faster, for CI / pre-staged browsers) |
| `--offline` | future — skip npm/pip, expect pre-staged `runtime/` dir (air-gapped) |

### 4.3 Steps performed (in order)

1. **PATH / binary move** (unless `--runtime-only` or `--no-path`).
2. **Create `~/.qaclan/runtime/`**.
3. **Write `package.json`** from hardcoded dict embedded in binary.
4. **Run `npm install`** inside `runtime/`.
5. **Create venv**: `python3 -m venv runtime/venv`.
6. **Install Playwright pip pkg into venv**: `runtime/venv/bin/pip install playwright==<pinned>`.
7. **Install Chromium**: `PLAYWRIGHT_BROWSERS_PATH=~/.qaclan/runtime/browsers runtime/node_modules/.bin/playwright install chromium` (unless `--no-chromium`).

Each step idempotent — detects already-done state and skips.

---

## 5. PATH Injection Mechanism

### 5.1 Linux / macOS

Detect shell, append PATH line to rc file:

```python
binary = Path(sys.executable if is_nuitka_compiled() else sys.argv[0]).resolve()
target_dir = Path.home() / ".qaclan" / "bin"
target = target_dir / "qaclan"

if binary != target:
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, target)
    target.chmod(0o755)

shell_name = Path(os.environ.get("SHELL", "")).name
rc_file = {
    "zsh":  Path.home() / ".zshrc",
    "bash": Path.home() / ".bashrc",
    "fish": Path.home() / ".config/fish/config.fish",
}.get(shell_name, Path.home() / ".profile")

line = 'export PATH="$HOME/.qaclan/bin:$PATH"  # qaclan'
content = rc_file.read_text() if rc_file.exists() else ""
if "qaclan" not in content:
    rc_file.parent.mkdir(parents=True, exist_ok=True)
    rc_file.write_text(content + "\n" + line + "\n")
```

### 5.2 Windows

Persist user PATH via registry (HKCU\Environment), broadcast `WM_SETTINGCHANGE`:

```python
import winreg
target_dir = Path.home() / ".qaclan" / "bin"

key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
try:
    current, _ = winreg.QueryValueEx(key, "Path")
except FileNotFoundError:
    current = ""
if str(target_dir) not in current:
    new = f"{current};{target_dir}" if current else str(target_dir)
    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new)
```

User-scope only (HKCU). Never write HKLM, even if running as admin.

---

## 6. Hardcoded `package.json`

`package.json` content lives as a Python dict inside the binary, written to disk at runtime by `qaclan setup`:

```python
PACKAGE_JSON = {
    "name": "qaclan-runtime",
    "version": "1.0.0",
    "private": True,
    "dependencies": {
        "playwright": "1.58.0",
        "@playwright/test": "1.58.0",
        "tsx": "^4.0.0"
    }
}
```

### Why hardcode

| Approach | Direct-download user (no installer)? |
|---|---|
| **Hardcode (recommended)** | works — string lives in `.exe` |
| Nuitka `--include-data-file=package.json` | also works, extra build step, file extracted at runtime |
| Ship `package.json` next to binary | breaks — user only downloads `.exe`, no sidecar |
| Fetch from GitHub at runtime | breaks offline use, version skew if repo updated |

Same approach for any other config files (e.g. `requirements.txt` for venv → embedded as Python list).

---

## 7. Strategy Code Changes

`cli/script_strategies/python_strategy.py` and `javascript_test_strategy.py`:

- `validate_runtime()` checks `~/.qaclan/runtime/` populated, not global.
- Subprocess argv use **absolute paths**:
  - Python: `~/.qaclan/runtime/venv/bin/python <script>` (`venv\Scripts\python.exe` on Windows).
  - JS: `node` with `NODE_PATH=~/.qaclan/runtime/node_modules`, or invoke `runtime/node_modules/.bin/tsx <script>` directly.
- Set `PLAYWRIGHT_BROWSERS_PATH=~/.qaclan/runtime/browsers` so Playwright finds the locally-installed Chromium.

### Lazy auto-trigger

If `~/.qaclan/runtime/node_modules` missing when a script run is invoked:

```
>>> Runtime not initialized. Run setup now? [y/n/yes/no] (default: yes):
```

User never needs to read README — first run auto-bootstraps.

---

## 8. Cross-Platform Notes

| Item | Linux/macOS | Windows |
|---|---|---|
| venv python | `runtime/venv/bin/python` | `runtime\venv\Scripts\python.exe` |
| node bin | `runtime/node_modules/.bin/playwright` | `runtime\node_modules\.bin\playwright.cmd` |
| browser path env | `PLAYWRIGHT_BROWSERS_PATH` | same |
| system libs (Linux) | `playwright install --with-deps chromium` still needs sudo for apt libs | N/A — runtime libs ship with OS |
| PATH persist | shell rc file | HKCU\Environment registry |

---

## 9. Installer Changes

### `install.sh` / `install.ps1`

1. Download qaclan binary → `~/.qaclan/bin/`.
2. Add `~/.qaclan/bin/` to PATH (already done by installer today).
3. Verify Node.js + Python3 present on system. Prompt-install if missing (existing behavior).
4. **Remove** `npm install -g playwright @playwright/test tsx`.
5. **Remove** `playwright install chromium` from installer.
6. **Call `qaclan setup --runtime-only`** at end — hands off to binary for runtime bootstrap.

Direct-download users: skip installer, just run `qaclan setup` after putting binary anywhere.

---

## 10. Trigger Paths Matrix

| User path | Setup trigger |
|---|---|
| `install.sh` / `install.ps1` | installer auto-runs `qaclan setup --runtime-only` |
| Direct binary download | `qaclan setup` manual; OR lazy auto-trigger on first `qaclan run` / record |
| Docker | `Dockerfile` runs `RUN qaclan setup --no-path` at image build |
| Air-gapped | `qaclan setup --offline` (future), user pre-stages `runtime/` |

---

## 11. Migration

Existing users have global Playwright. **Plan leaves global setup untouched.**

- Old global `playwright` / `@playwright/test` / `tsx` stay.
- qaclan stops *using* them — strategy code switches to absolute paths under `~/.qaclan/runtime/`.
- Global pkgs become dormant — harmless, just wasted disk.
- Doc note: user *may* `npm uninstall -g playwright @playwright/test tsx` and `pip uninstall playwright` later if they want a clean system. Optional, not required.
- No automatic uninstall. No touch of system pip / npm globals.

Same for Python: prior `pip install playwright` global stays; qaclan uses its own venv.

---

## 12. Tradeoffs

| Pro | Con |
|---|---|
| no global pollution | first-run slower (Node deps + Chromium ~150MB) |
| pinned versions safe | disk: ~500MB under `~/.qaclan/runtime/` |
| upgrade qaclan ≡ upgrade deps | needs `qaclan setup` after install (auto-handled) |
| no PEP 668 / npm prefix issues | strategy code must use absolute paths, not `which playwright` |
| binary self-installing (PATH + deps) | shell rc file mutation on Linux/macOS — user must restart terminal |

---

## 13. Edge Cases

| Case | Behavior |
|---|---|
| Binary already in `~/.qaclan/bin/` | skip move |
| Binary already on PATH at different location | offer to move, or accept current location |
| Windows PS as admin | still write HKCU, never HKLM |
| `~/.zshrc` missing | create it |
| Idempotent re-run | detect existing PATH entry / runtime dir, skip |
| Symlink vs copy on Linux | copy (single-file binary, copy safe; symlink breaks if original deleted) |
| Node missing at setup time | prompt install (existing installer logic, reused inside binary) |
| Python3 missing | prompt install with package-manager hint (`apt`/`brew`/`winget`) |
| `npm install` fails (network) | leave partial state, exit non-zero, user re-runs `qaclan setup` |
| Runtime missing at script run (Phase 2) | fall back to global Playwright, print deprecation warning: `QAClan runtime is not initialized. Global Playwright fallback is deprecated. Run: qaclan setup --runtime-only` |
| Chromium download fails | runtime still usable for non-browser features; warn and exit 0 |

---

## 14. Implementation Phases

1. **Phase 1 — Add `qaclan setup`** (PATH + runtime + Chromium), no strategy code changes yet. Manual opt-in via flag/env.
2. **Phase 2 — Switch strategies** to use `~/.qaclan/runtime/` paths. Fall back to global if runtime missing (transition period). On fallback, emit deprecation warning:

   ```
   WARNING: QAClan runtime is not initialized. Global Playwright fallback is deprecated.
   Run: qaclan setup --runtime-only
   ```
3. **Phase 3 — Lazy auto-trigger** on script run if runtime missing.
4. **Phase 4 — Update installers** to call `qaclan setup --runtime-only`, remove global npm/pip steps.
5. **Phase 5 — Remove global fallback** in strategies (require runtime). Concrete cleanup:
   - `python_strategy._resolve_python_executable()` → return `runtime_setup.venv_python()` only. Drop `is_frozen_binary` branch, `py`/`python3`/`python` PATH search, Windows Store stub detection.
   - `javascript_strategy.validate_runtime()` → check runtime/node_modules/playwright only. Drop `_global_node_path_env()` fallback. Delete `_global_node_path_env()` method.
   - `javascript_strategy.extra_env()` → return `{"NODE_PATH": str(NODE_MODULES)}` unconditionally.
   - `javascript_test_strategy._resolve_pwtest_cli()` → return `runtime_setup.resolve_pwtest_cli()` or raise. Drop `npm root -g` block.
   - `typescript_strategy.build_run_command()` → runtime tsx only. Drop `npx tsx` fallback. `validate_runtime()` → drop fallback branch.
   - `runtime_setup.py` → delete `emit_deprecation_warning()` + `_DEPRECATION_WARNED`.
   - `web/routes/runs.py` → drop `default_browsers` / frozen-binary branch. `PLAYWRIGHT_BROWSERS_PATH` always = `runtime_setup.BROWSERS_DIR`. Drop `cli.runtime.get_default_playwright_browsers_path` import.
   - Update [Phase 2 deprecation block](#14-implementation-phases) wording: fallback removed.
   - Update [Edge Cases table](#13-edge-cases) row "Runtime missing at script run" → hard error, not fallback.

   Net: ~150 LOC deleted. Single resolution path. Failure mode = clear `qaclan setup --runtime-only` hint instead of silent global usage.

   Risk: any user who skipped `qaclan setup` post-upgrade breaks immediately. Mitigation: ship Phase 5 in major-version bump, give Phase 2-4 a few releases of soak time.

6. **Phase 6 — Docs**: README rewrite, migration note for existing users (see `docs/migration-runtime.md`).

---

## 15. Open Questions (resolved)

1. **Bundle `package.json` template in binary or hardcode?** → Hardcode as Python dict, write at runtime. Simpler, no Nuitka data flag, works for direct-download users.
2. **Pin Node version?** → No. Require ≥18 at runtime check, accept whatever system Node user has.
3. **Pin Python version?** → Require ≥3.9 (venv module stable, f-string support).
4. **Auto-run setup after installer, or manual?** → Auto. Add `--no-setup` opt-out flag for air-gapped envs.
