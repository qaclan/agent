"""TypeScript Playwright script strategy.

Inherits everything from JavaScriptStrategy — same harness template, same
codegen target (Playwright has no --target typescript), same escape rules.
Overrides only the file extension and the run command.
"""

from __future__ import annotations

import subprocess
from typing import List

from cli import runtime_setup
from cli.script_strategies.javascript_strategy import JavaScriptStrategy


class TypeScriptStrategy(JavaScriptStrategy):
    language = "typescript"
    codegen_target = "javascript"
    file_extension = ".ts"

    def build_run_command(self, script_path: str) -> List[str]:
        # Prefer runtime tsx binary.
        rt_tsx = runtime_setup.resolve_node_bin("tsx")
        if rt_tsx is not None:
            return [str(rt_tsx), script_path]
        runtime_setup.emit_deprecation_warning()
        return ["npx", "tsx", script_path]

    def validate_runtime(self) -> None:
        super().validate_runtime()
        rt_tsx = runtime_setup.resolve_node_bin("tsx")
        if rt_tsx is not None:
            result = subprocess.run(
                [str(rt_tsx), "--version"], capture_output=True, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Runtime tsx at {rt_tsx} is broken. "
                    "Re-run: qaclan setup --runtime-only --force"
                )
            return
        # Fallback: global npx tsx.
        result = subprocess.run(
            ["npx", "tsx", "--version"], capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "'tsx' is not available. Run: qaclan setup --runtime-only "
                "(or install globally: npm install -g tsx)"
            )

    def extra_env(self) -> dict:
        return super().extra_env()
