"""Per-language strategies for Playwright scripts.

All strategies honor the same runtime contract — the harness they emit reads
configuration from these environment variables at execution time:

    QACLAN_STORAGE_STATE   Path to shared state.json (load on start, save on exit)
    QACLAN_ARTIFACTS_PATH  Path where the script writes its artifacts JSON
                           (console_errors + network_failures lists)
    QACLAN_SCREENSHOT_PATH Path where the script writes a screenshot on failure
    QACLAN_BROWSER         "chromium" | "firefox" | "webkit"
    QACLAN_HEADLESS        "1" or "0"
    QACLAN_VIEWPORT        "<W>x<H>" or empty string

The parent (web/routes/runs.py) populates these vars in the subprocess env
before launching each script. Env vars substitute {{KEY}} placeholders via
cli/script_strategies/_shared.py#substitute_template_vars at render time, not
via os.environ — secrets never touch the parent process environment.
"""

from cli.script_strategies.base import ScriptStrategy
from cli.script_strategies.python_strategy import PythonStrategy
from cli.script_strategies.javascript_strategy import JavaScriptStrategy


_STRATEGIES = {
    "python": PythonStrategy(),
    "javascript": JavaScriptStrategy(),
}

SUPPORTED_LANGUAGES = tuple(_STRATEGIES.keys())


def get_strategy(language: str) -> ScriptStrategy:
    strategy = _STRATEGIES.get(language)
    if strategy is None:
        raise ValueError(
            f"Unsupported script language: {language!r}. Supported: {SUPPORTED_LANGUAGES}"
        )
    return strategy


__all__ = ["ScriptStrategy", "get_strategy", "SUPPORTED_LANGUAGES"]
