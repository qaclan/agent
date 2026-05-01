# Migration: Global Playwright → Isolated Runtime

QAClan now provisions Playwright in an isolated runtime under `~/.qaclan/runtime/` instead of using globally-installed `playwright` / `@playwright/test` / `tsx`. This page tells existing users what to do.

## TL;DR

```bash
qaclan setup --runtime-only
```

That's it. Re-run safe.

## Why

Pinned global `playwright@1.58.0` was a land-mine: any other project on your machine that bumped Playwright would silently break QAClan. The isolated runtime fixes this — QAClan owns its own copy at `~/.qaclan/runtime/`, immune to system-wide changes.

## What changes for you

### Before

QAClan resolved Playwright via:
- `npm root -g` → global `node_modules/playwright`
- system `python3` → site-packages `playwright`
- shared `~/.cache/ms-playwright/` browsers

### After

QAClan resolves Playwright via:
- `~/.qaclan/runtime/node_modules/playwright`
- `~/.qaclan/runtime/venv/bin/python` (with playwright pip pkg installed)
- `~/.qaclan/runtime/browsers/` (`PLAYWRIGHT_BROWSERS_PATH` set automatically)

## Steps

### 1. Upgrade the binary

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/qaclan/agent/master/install.sh | sh
```

```powershell
# Windows
.\qaclan-windows-amd64.exe setup --force
```

### 2. Provision the runtime

```bash
qaclan setup --runtime-only
```

First run takes a few minutes — downloads ~150MB (Node deps + Chromium). Subsequent runs are idempotent (skip already-installed steps).

Disk cost: ~500MB under `~/.qaclan/runtime/`.

### 3. Verify

```bash
ls ~/.qaclan/runtime/
# expected: package.json  node_modules/  venv/  browsers/

qaclan serve
# Run a script — should work without warnings.
```

### Stuck? Reset and retry

If the runtime ends up half-installed or corrupted (e.g. `npm install` got killed mid-way, venv broken after a system Python upgrade), wipe just the runtime and rebuild:

```bash
qaclan reset-runtime          # removes ~/.qaclan/runtime/ only
qaclan setup --runtime-only   # rebuild from scratch
```

DB, scripts, config, and the binary are kept.

## Transition fallback (current releases)

If the runtime is missing, QAClan **falls back to globally-installed Playwright** with a one-time deprecation warning to stderr:

```
WARNING: QAClan runtime is not initialized. Global Playwright fallback is deprecated.
Run: qaclan setup --runtime-only
```

This fallback exists for one-off compatibility during the transition. **It will be removed in a future major release** — at which point QAClan will hard-fail without the runtime. Run `qaclan setup --runtime-only` now to avoid disruption later.

## Cleaning up old globals (optional)

Old global installs are left alone — they're harmless, just wasted disk. If you want a clean system:

```bash
# npm globals
npm uninstall -g playwright @playwright/test tsx

# pip global
pip uninstall playwright
# or, if installed with --break-system-packages:
pip uninstall --break-system-packages playwright

# shared browser cache (only if no other Playwright project uses it)
rm -rf ~/.cache/ms-playwright    # Linux
rm -rf ~/Library/Caches/ms-playwright    # macOS
# Windows: %USERPROFILE%\AppData\Local\ms-playwright
```

None of this is required. QAClan ignores them either way.

## CI / Docker

```dockerfile
RUN qaclan setup --no-path
```

`--no-path` skips PATH mutation (binary already on PATH inside the image, no shell rc to write).

For air-gapped builds, pre-stage `~/.qaclan/runtime/` from a network-connected machine and copy it into the image. Future `--offline` flag will formalize this.

## FAQ

**Q: My CI was running `npm install -g playwright@1.58.0` before invoking qaclan. Do I still need that?**
A: No. Replace with `qaclan setup --runtime-only` after the binary install step. Drop the global npm install entirely.

**Q: What about `playwright install --with-deps` for Linux system libs?**
A: Still needed — system shared libraries (libnss3, libgbm1, etc.) can't ship inside the runtime venv. The shipped `install.sh` runs `apt-get install` for these libs on Linux. On other distros, install Chromium runtime libs manually if browsers fail to launch.

**Q: Can I pin a different Playwright version per-project?**
A: Not yet. The runtime ships one pinned version (1.58.0). Per-project Playwright versions are out of scope for v1.

**Q: Does this break recording (`qaclan record`)?**
A: No. Recording uses the same runtime resolution.
