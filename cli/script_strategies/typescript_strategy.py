"""TypeScript Playwright script strategy.

Inherits everything from JavaScriptStrategy — same harness template, same
codegen target (Playwright has no --target typescript), same escape rules.
Overrides only the file extension and the run command.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List

from cli.script_strategies.javascript_strategy import JavaScriptStrategy


class TypeScriptStrategy(JavaScriptStrategy):
    language = "typescript"
    codegen_target = "javascript"
    file_extension = ".ts"

    def build_run_command(self, script_path: str) -> List[str]:
        return ["npx", "tsx", script_path]

    def validate_runtime(self) -> None:
        super().validate_runtime()
        result = subprocess.run(
            ["npx", "tsx", "--version"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "'npx tsx' is not available. Install tsx globally: npm install -g tsx\n"
                "Then verify: npx tsx --version"
            )

    def extra_env(self) -> dict:
        npm_env = super().extra_env()
        npx = shutil.which("npx")
        if not npx:
            return npm_env
        return npm_env
