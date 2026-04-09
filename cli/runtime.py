import os
import sys
import tempfile


def is_frozen_binary() -> bool:
    """True when running as a Nuitka/PyInstaller compiled binary.

    Nuitka sets ``sys.frozen`` in newer versions, but onefile mode also
    extracts the executable into a temp dir — detect both. Works on
    Linux (``/tmp/onefile_*``), macOS (``$TMPDIR/onefile_*``), and
    Windows (``%TEMP%\\onefile_*``).
    """
    if getattr(sys, "frozen", False):
        return True
    exe = sys.executable
    if not exe:
        return False
    try:
        exe_real = os.path.realpath(exe)
        tmp_real = os.path.realpath(tempfile.gettempdir())
        return exe_real.startswith(tmp_real + os.sep)
    except (OSError, ValueError):
        return False


def is_path_in_temp(path: str) -> bool:
    """True if ``path`` lives under the system temp directory.

    Used to detect Nuitka-extracted bundled drivers (e.g. the Playwright
    Node driver) so we can fall back to a system install instead.
    """
    if not path:
        return False
    try:
        path_real = os.path.realpath(path)
        tmp_real = os.path.realpath(tempfile.gettempdir())
        return path_real.startswith(tmp_real + os.sep)
    except (OSError, ValueError):
        return False


def get_default_playwright_browsers_path() -> str:
    """Return the OS-default ``ms-playwright`` browser cache directory.

    Mirrors what Playwright itself uses when ``PLAYWRIGHT_BROWSERS_PATH``
    is unset, so binary builds can locate browsers installed by a
    side-by-side ``playwright install chromium`` from npm/pip.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return os.path.join(base, "ms-playwright")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/ms-playwright")
    return os.path.expanduser("~/.cache/ms-playwright")
