"""Strategy interface for per-language Playwright script handling.

Each ScriptStrategy owns:
- The codegen target flag used at recording time
- The post-processing that wraps the codegen output into a runnable harness
- URL templating (rewriting absolute URLs to {{KEY}} placeholders)
- The subprocess argv used to execute the script at run time
- A runtime validation pre-flight

The harness emitted by post_process_recording must read configuration from
the QACLAN_* env vars documented in cli/script_strategies/__init__.py so every
language speaks the same runtime contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple


class ScriptStrategy(ABC):
    language: str = ""
    codegen_target: str = ""
    file_extension: str = ""
    expect_timeout: int = 7000

    @abstractmethod
    def post_process_recording(self, raw: str) -> str:
        """Transform raw codegen output into a self-contained harness script
        that honors the QACLAN_* runtime contract."""

    def starter_template(self) -> str:
        """Return the empty harness scaffolding for this language.

        Used to seed the script editor for new manual scripts so they share
        the same structure as recorded scripts. Defaults to rendering the
        harness with no actions; strategies can override if needed.
        """
        return self._render_harness("")

    @abstractmethod
    def _render_harness(self, actions: str) -> str:
        """Wrap ``actions`` in the language-specific harness template."""

    @abstractmethod
    def rewrite_url_template(self, content: str, base_value: str, key_name: str) -> str:
        """Replace occurrences of ``base_value`` inside page.goto(...) URLs with
        a ``{{KEY}}`` placeholder. Returns the script with placeholders injected."""

    @abstractmethod
    def build_run_command(self, script_path: str) -> List[str]:
        """Return the subprocess argv used to execute ``script_path``."""

    @abstractmethod
    def validate_runtime(self) -> None:
        """Raise RuntimeError with a user-facing message if the interpreter or
        required dependencies are not installed."""

    def extract_actions_freeform(self, raw: str) -> Tuple[str, list]:
        """Best-effort extraction of action body from a user-supplied script
        that is neither a QAClan harness nor raw codegen output.

        Subclasses override to apply language-specific heuristics. Returns
        ``(actions, warnings)`` where ``warnings`` is a list of
        ``cli.script_strategies._shared.ImportWarning`` instances. The
        default implementation returns the raw text unchanged with a single
        warning so the user is forced to review.
        """
        from cli.script_strategies._shared import ImportWarning
        return raw, [ImportWarning(
            severity="error",
            code="extraction_failed",
            message="Could not auto-extract action body. Review and rewrite manually.",
        )]

    def extra_env(self) -> dict:
        """Return extra environment variables to inject into the script subprocess.
        Override in language strategies that need runtime-specific env (e.g. NODE_PATH)."""
        return {}

    def setup_run_dir(self, run_dir: str) -> None:
        """Per-suite-run, per-language setup. Called once after run_dir is
        created, before any script in that language runs. Override to drop
        shared files (e.g. playwright.config.js) that all scripts in the run
        will share."""
        return None

    def escape_for_literal(self, value: str) -> str:
        """Escape ``value`` so it can be safely spliced into a string literal
        of the target language. Default implementation handles Python/JSON-like
        backslash+quote escaping; override for languages with different rules."""
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
