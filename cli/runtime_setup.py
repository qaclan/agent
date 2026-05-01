"""Isolated per-user runtime under ~/.qaclan/runtime/.

Provisions Node deps (playwright, @playwright/test, tsx) + Python venv with
playwright pkg + Chromium browser. Avoids global npm/pip pollution.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from cli.config import QACLAN_DIR


# package.json shipped as data file under cli/runtime_assets/. Bundled into
# Nuitka binary via build.sh --include-data-dir; resolved via __file__ in dev too.
# Single source of truth — pinned versions live in JSON, scannable by Renovate/Dependabot.
PACKAGE_JSON_TEMPLATE_PATH = Path(__file__).resolve().parent / "runtime_assets" / "package.json"


def _load_package_template() -> dict:
    if not PACKAGE_JSON_TEMPLATE_PATH.exists():
        raise RuntimeError(
            f"Bundled package.json missing at {PACKAGE_JSON_TEMPLATE_PATH}. "
            "Build issue: ensure build.sh passes "
            "--include-data-dir=cli/runtime_assets=cli/runtime_assets to Nuitka."
        )
    return json.loads(PACKAGE_JSON_TEMPLATE_PATH.read_text())


PINNED_PLAYWRIGHT_VERSION = _load_package_template()["dependencies"]["playwright"]

REQUIREMENTS = [f"playwright=={PINNED_PLAYWRIGHT_VERSION}"]


# ---- Paths ----

RUNTIME_DIR = Path(QACLAN_DIR) / "runtime"
BIN_DIR = Path(QACLAN_DIR) / "bin"
NODE_MODULES = RUNTIME_DIR / "node_modules"
VENV_DIR = RUNTIME_DIR / "venv"
BROWSERS_DIR = RUNTIME_DIR / "browsers"
PACKAGE_JSON_PATH = RUNTIME_DIR / "package.json"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def node_bin(name: str) -> Path:
    suffix = ".cmd" if sys.platform == "win32" else ""
    return NODE_MODULES / ".bin" / f"{name}{suffix}"


def runtime_initialized() -> bool:
    return (
        NODE_MODULES.exists()
        and venv_python().exists()
        and PACKAGE_JSON_PATH.exists()
    )


# ---- Pre-flight checks ----

def _which_or_raise(name: str, hint: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name!r} not found on PATH. {hint}")
    return path


def _check_npm() -> str:
    return _which_or_raise(
        "npm",
        "Install Node.js (npm ships with it).",
    )


def _check_python3() -> str:
    """Locate a usable Python 3 interpreter.

    Windows: try `py` launcher first, then `python3`, then `python`. The Microsoft
    Store stub at %LOCALAPPDATA%\\Microsoft\\WindowsApps\\python.exe is a
    zero-byte alias that opens the Store — skip it.
    """
    if sys.platform == "win32":
        candidates = ["py", "python3", "python"]
    else:
        candidates = ["python3", "python"]
    for name in candidates:
        resolved = shutil.which(name)
        if not resolved:
            continue
        if sys.platform == "win32":
            norm = os.path.normcase(os.path.normpath(resolved))
            if os.path.join("microsoft", "windowsapps") in norm:
                continue
        return resolved
    raise RuntimeError(
        "Python 3 not found on PATH. "
        "Install Python >=3.9 (https://www.python.org/downloads/) and ensure "
        "it is on PATH (or `py` launcher available on Windows)."
    )


# ---- Steps ----

def write_package_json() -> bool:
    """Copy bundled package.json template to runtime/. Returns True if changed."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    desired = PACKAGE_JSON_TEMPLATE_PATH.read_text()
    if PACKAGE_JSON_PATH.exists() and PACKAGE_JSON_PATH.read_text() == desired:
        return False
    PACKAGE_JSON_PATH.write_text(desired)
    return True


_PKG_HASH_PATH = RUNTIME_DIR / ".package.sha256"


def _package_hash() -> str:
    """Hash bundled template (sort keys = stable across formatting changes)."""
    import hashlib
    return hashlib.sha256(
        json.dumps(_load_package_template(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def npm_install(force: bool = False) -> bool:
    """Run `npm install` in runtime/. Skip when node_modules matches current package.json hash."""
    current_hash = _package_hash()
    if (
        not force
        and NODE_MODULES.exists()
        and _PKG_HASH_PATH.exists()
        and _PKG_HASH_PATH.read_text().strip() == current_hash
    ):
        return False
    npm = _check_npm()
    subprocess.run(
        [npm, "install", "--no-audit", "--no-fund"],
        cwd=str(RUNTIME_DIR),
        check=True,
    )
    _PKG_HASH_PATH.write_text(current_hash)
    return True


def create_venv(force: bool = False) -> bool:
    if venv_python().exists() and not force:
        return False
    py = _check_python3()
    subprocess.run([py, "-m", "venv", str(VENV_DIR)], check=True)
    return True


def venv_pip_install(force: bool = False) -> bool:
    py = venv_python()
    if not py.exists():
        raise RuntimeError(f"venv Python not found at {py}. Run create_venv first.")
    if not force:
        result = subprocess.run(
            [str(py), "-c", f"import playwright, sys; "
                            f"import importlib.metadata as m; "
                            f"sys.exit(0 if m.version('playwright') == '{PINNED_PLAYWRIGHT_VERSION}' else 1)"],
            capture_output=True,
        )
        if result.returncode == 0:
            return False
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(py), "-m", "pip", "install", *REQUIREMENTS],
        check=True,
    )
    return True


def install_chromium(force: bool = False) -> bool:
    pw = node_bin("playwright")
    if not pw.exists():
        raise RuntimeError(f"playwright CLI not found at {pw}. Run npm_install first.")
    if BROWSERS_DIR.exists() and any(BROWSERS_DIR.glob("chromium-*")) and not force:
        return False
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    subprocess.run([str(pw), "install", "chromium"], env=env, check=True)
    return True


# ---- PATH injection ----

_PATH_MARKER = "# qaclan-managed-path"


def detect_rc_file() -> Path:
    """Pick shell rc file. macOS bash logs in via `.bash_profile` — prefer it
    when it exists; fall back to `.bashrc` for Linux bash users."""
    shell = Path(os.environ.get("SHELL", "")).name
    home = Path.home()
    if shell == "bash":
        bash_profile = home / ".bash_profile"
        if bash_profile.exists() or sys.platform == "darwin":
            return bash_profile
        return home / ".bashrc"
    return {
        "zsh": home / ".zshrc",
        "fish": home / ".config" / "fish" / "config.fish",
    }.get(shell, home / ".profile")


def add_to_path_unix() -> bool:
    """Append PATH export to shell rc. Idempotent via marker comment."""
    rc = detect_rc_file()
    line = f'export PATH="$HOME/.qaclan/bin:$PATH"  {_PATH_MARKER}'
    content = rc.read_text() if rc.exists() else ""
    if _PATH_MARKER in content:
        return False
    rc.parent.mkdir(parents=True, exist_ok=True)
    with rc.open("a") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")
    return True


def add_to_path_windows() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    target = str(BIN_DIR)
    target_norm = os.path.normcase(os.path.normpath(target))
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
    )
    try:
        try:
            current, reg_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, reg_type = "", winreg.REG_EXPAND_SZ
        # Windows PATH is `;`-separated. Split into entries and exact-match
        # each one against target. A substring check on the joined string
        # would falsely match e.g. `C:\foo\.qaclan\bin` against an existing
        # `C:\foo\.qaclan\bin\backup` entry, and we'd never add our path.
        entries = [e for e in (current or "").split(";") if e]
        if any(os.path.normcase(os.path.normpath(e)) == target_norm for e in entries):
            return False
        entries.append(target)
        new = ";".join(entries)
        winreg.SetValueEx(key, "Path", 0, reg_type or winreg.REG_EXPAND_SZ, new)
    finally:
        winreg.CloseKey(key)

    # Broadcast WM_SETTINGCHANGE so new processes see updated PATH.
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x1A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, None,
        )
    except Exception:
        pass
    return True


def move_binary_to_bin_dir() -> Optional[Path]:
    """Copy current binary to ~/.qaclan/bin/. Returns target path if copied."""
    from cli.runtime import is_frozen_binary

    if not is_frozen_binary():
        return None
    src = Path(sys.executable).resolve()
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    name = "qaclan.exe" if sys.platform == "win32" else "qaclan"
    target = BIN_DIR / name
    if src == target:
        return None
    shutil.copy2(src, target)
    if sys.platform != "win32":
        target.chmod(0o755)
    return target


# ---- High-level orchestration ----

def bootstrap_runtime(no_chromium: bool = False) -> None:
    """Run all runtime steps. Idempotent."""
    write_package_json()
    npm_install()
    create_venv()
    venv_pip_install()
    if not no_chromium:
        install_chromium()


# ---- Strategy resolution helpers ----

_DEPRECATION_WARNED = False


def emit_deprecation_warning() -> None:
    """Print global-fallback deprecation warning. Once per process."""
    global _DEPRECATION_WARNED
    if _DEPRECATION_WARNED:
        return
    _DEPRECATION_WARNED = True
    msg = (
        "WARNING: QAClan runtime is not initialized. "
        "Global Playwright fallback is deprecated. "
        "Run: qaclan setup --runtime-only"
    )
    print(msg, file=sys.stderr)


def resolve_venv_python() -> Optional[Path]:
    """Return runtime venv python if present, else None."""
    py = venv_python()
    return py if py.exists() else None


def resolve_node_module(name: str) -> Optional[Path]:
    """Return runtime/node_modules/<name> dir if present, else None."""
    p = NODE_MODULES / name
    return p if p.exists() else None


def resolve_pwtest_cli() -> Optional[Path]:
    """Return runtime @playwright/test cli.js if present, else None."""
    cli = NODE_MODULES / "@playwright" / "test" / "cli.js"
    return cli if cli.exists() else None


def resolve_node_bin(name: str) -> Optional[Path]:
    """Return runtime node_modules/.bin/<name> if present, else None."""
    p = node_bin(name)
    return p if p.exists() else None


def browsers_path_if_present() -> Optional[Path]:
    """Return ~/.qaclan/runtime/browsers if it has chromium installed, else None."""
    if BROWSERS_DIR.exists() and any(BROWSERS_DIR.glob("chromium-*")):
        return BROWSERS_DIR
    return None


def setup_path(no_move: bool = False) -> None:
    """PATH + binary move. Idempotent."""
    if not no_move:
        move_binary_to_bin_dir()
    if sys.platform == "win32":
        add_to_path_windows()
    else:
        add_to_path_unix()
