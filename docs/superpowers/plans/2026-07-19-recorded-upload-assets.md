# Recorded File-Upload Test Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a Playwright script is recorded with a file-upload interaction (`set_input_files`/`setInputFiles`), automatically capture the referenced file into per-script storage and rewrite the recorded call to reference it via a resolvable token, so the upload works when the suite runs — on any machine, any time.

**Architecture:** `post_process_recording()` (already the place raw codegen output gets cleaned up — see the existing `_strip_upload_click` fix) gains a new step that detects `set_input_files`/`setInputFiles` calls with an absolute-path argument, copies the referenced file into `~/.qaclan/uploads/<script_id>/`, and rewrites the call to use a reserved template token (`{{__qaclan_upload_dir__}}/<basename>`). That token is resolved to the real run-time path in `web/routes/runs.py` at script-render time, independent of the existing `{{KEY}}` environment-variable substitution system (so it never needs an environment entry). A configurable per-file size cap (default 20MB) gates what gets copied; oversized/missing files are left as recorded (with a logged warning) rather than silently failing later.

**Tech Stack:** Python (Flask backend, Click CLI), no new dependencies. No automated test framework exists in this repo (per `CLAUDE.md`) — verification steps in this plan use standalone ad hoc scripts run via `python3 -c` / `python3 <scratch file>`, not pytest.

## Global Constraints

- Default size cap: 20MB per file, configurable via `~/.qaclan/config.json` key `upload_size_cap_mb`.
- Storage layout: `~/.qaclan/uploads/<script_id>/<basename>` — one folder per script, no cross-script deduplication.
- Reserved token: `{{__qaclan_upload_dir__}}` — never added to a script's `var_keys`, never resolved through `substitute_template_vars`/the environments system.
- Only the live `qaclan web record` flow (`cli/commands/web/record.py`) wires an `upload_dir` through; the other two `post_process_recording` call sites (`cli/commands/web/script.py`, `web/routes/scripts.py` paste-import) keep calling it without one, so the new step is a no-op for them — no behavior change there.
- No manual "attach file" UI, no fix-up of already-recorded scripts, no cross-script dedup/refcounting — all explicitly out of scope per the spec.
- Spec: `docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md`

---

### Task 1: Config support — size cap + uploads directory

**Files:**
- Modify: `cli/config.py`

**Interfaces:**
- Produces: `UPLOADS_DIR: str` (module-level constant, `~/.qaclan/uploads`), `get_upload_size_cap_mb() -> int`, `set_upload_size_cap_mb(mb: int) -> None`, `DEFAULT_UPLOAD_SIZE_CAP_MB: int = 20`.

- [ ] **Step 1: Write a standalone verification script that shows the gap**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task1.py`:

```python
import os, sys, tempfile, importlib

os.environ["HOME"] = tempfile.mkdtemp()  # isolate from the real ~/.qaclan
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

import cli.config as config
importlib.reload(config)

assert hasattr(config, "UPLOADS_DIR"), "UPLOADS_DIR missing"
assert config.UPLOADS_DIR.endswith(os.path.join(".qaclan", "uploads")), config.UPLOADS_DIR

assert config.get_upload_size_cap_mb() == 20, f"expected default 20, got {config.get_upload_size_cap_mb()}"

config.set_upload_size_cap_mb(5)
assert config.get_upload_size_cap_mb() == 5, f"expected 5 after set, got {config.get_upload_size_cap_mb()}"

config.ensure_dirs()
assert os.path.isdir(config.UPLOADS_DIR), "ensure_dirs() did not create UPLOADS_DIR"

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task1.py`
Expected: `AssertionError: UPLOADS_DIR missing` (attribute doesn't exist yet)

- [ ] **Step 3: Implement**

In `cli/config.py`, change:

```python
QACLAN_DIR = os.path.expanduser("~/.qaclan")
CONFIG_PATH = os.path.join(QACLAN_DIR, "config.json")
SCRIPTS_DIR = os.path.join(QACLAN_DIR, "scripts")


def ensure_dirs():
    os.makedirs(QACLAN_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
```

to:

```python
QACLAN_DIR = os.path.expanduser("~/.qaclan")
CONFIG_PATH = os.path.join(QACLAN_DIR, "config.json")
SCRIPTS_DIR = os.path.join(QACLAN_DIR, "scripts")
UPLOADS_DIR = os.path.join(QACLAN_DIR, "uploads")


def ensure_dirs():
    os.makedirs(QACLAN_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
```

Then, at the end of the file (after `get_editor_mode()`), add:

```python
# Per-file size cap (MB) for files captured from recorded upload
# interactions (set_input_files/setInputFiles). Global, not per-script —
# see docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md.
DEFAULT_UPLOAD_SIZE_CAP_MB = 20


def get_upload_size_cap_mb():
    """Return the configured per-file upload size cap in MB (default 20)."""
    cfg = _read_config()
    val = cfg.get("upload_size_cap_mb", DEFAULT_UPLOAD_SIZE_CAP_MB)
    try:
        return int(val)
    except (TypeError, ValueError):
        return DEFAULT_UPLOAD_SIZE_CAP_MB


def set_upload_size_cap_mb(mb):
    cfg = _read_config()
    cfg["upload_size_cap_mb"] = int(mb)
    _write_config(cfg)
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task1.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/config.py`
Expected: no output (success)

```bash
git add cli/config.py
git commit -m "feat(config): add configurable upload file size cap and uploads dir"
```

---

### Task 2: CLI command to set the upload size cap

**Files:**
- Modify: `qaclan.py`

**Interfaces:**
- Consumes: `cli.config.set_upload_size_cap_mb(mb: int)` from Task 1.
- Produces: `qaclan set-upload-cap <mb>` CLI command.

- [ ] **Step 1: Manually verify the command doesn't exist yet**

Run: `python3 qaclan.py set-upload-cap 10`
Expected: `Error: No such command 'set-upload-cap'.`

- [ ] **Step 2: Implement**

In `qaclan.py`, immediately after the `reset_runtime` command definition (after the line `console.print("[green]✓ Runtime removed.[/green] Run [bold]qaclan setup --runtime-only[/bold] to rebuild.")` and before the `@qaclan.command("_pw-install", hidden=True)` block), add:

```python
@qaclan.command("set-upload-cap")
@click.argument("mb", type=int)
def set_upload_cap(mb):
    """Set the per-file size cap (MB) for files captured from recorded
    upload interactions. Applies globally to every script."""
    from rich.console import Console
    from cli.config import set_upload_size_cap_mb

    console = Console()
    if mb <= 0:
        console.print("[red]Cap must be a positive number of megabytes.[/red]")
        sys.exit(1)
    set_upload_size_cap_mb(mb)
    console.print(f"[green]✓ Upload file size cap set to {mb}MB.[/green]")
```

- [ ] **Step 3: Run it to confirm it works**

Run: `python3 qaclan.py set-upload-cap 15`
Expected: `✓ Upload file size cap set to 15MB.`

Run: `python3 -c "from cli.config import get_upload_size_cap_mb; print(get_upload_size_cap_mb())"`
Expected: `15`

Then restore the default so later tasks' verification scripts (which assert the 20MB default in an isolated `$HOME`) aren't affected by your real `~/.qaclan/config.json`:

Run: `python3 qaclan.py set-upload-cap 20`

- [ ] **Step 4: Commit**

```bash
git add qaclan.py
git commit -m "feat(cli): add 'qaclan set-upload-cap' command"
```

---

### Task 3: Python strategy — detect and capture uploaded files

**Files:**
- Modify: `cli/script_strategies/python_strategy.py`

**Interfaces:**
- Consumes: `cli.config.get_upload_size_cap_mb()` from Task 1.
- Produces: `PythonStrategy._extract_upload_files(actions: str, upload_dir: str | None) -> str`; `PythonStrategy.post_process_recording(raw: str, upload_dir: str = None) -> str` (signature change — adds optional param).

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task3.py`:

```python
import os, sys, tempfile

sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from cli.script_strategies.python_strategy import PythonStrategy

strategy = PythonStrategy()
work = tempfile.mkdtemp()

# A real file that "exists on the recording machine"
src_file = os.path.join(work, "sales_executive_job_description_bangla.pdf")
with open(src_file, "wb") as f:
    f.write(b"%PDF-1.4 fake content")

upload_dir = os.path.join(work, "uploads", "script_test123")

actions = (
    'page.locator("[data-test=\\"button-upload-job-description\\"]").click()\n'
    '_wait_for_network_settle(page)\n'
    f'page.locator("[data-test=\\"button-upload-job-description\\"]").set_input_files("{src_file}")\n'
    'page.locator("[data-test=\\"input-job-experience\\"]").select_option("entry")'
)

result = strategy._extract_upload_files(actions, upload_dir)

expected_dest = os.path.join(upload_dir, "sales_executive_job_description_bangla.pdf")
assert os.path.exists(expected_dest), f"file was not copied to {expected_dest}"
assert '{{__qaclan_upload_dir__}}/sales_executive_job_description_bangla.pdf' in result, result
assert src_file not in result, "original absolute path should have been rewritten out"
# click() line must still be present -- _strip_upload_click runs separately/later
assert '.click()' in result

# upload_dir=None must no-op (used by the two call sites that don't record uploads)
noop = strategy._extract_upload_files(actions, None)
assert noop == actions, "upload_dir=None must be a no-op"

# Oversized file: leave path untouched
import cli.config as config
big_file = os.path.join(work, "big.pdf")
with open(big_file, "wb") as f:
    f.write(b"0" * 1024)  # 1KB
orig_cap = config.get_upload_size_cap_mb
config.get_upload_size_cap_mb = lambda: 0  # 0MB cap -> everything is "oversized"
try:
    big_actions = f'page.locator("x").set_input_files("{big_file}")'
    big_result = strategy._extract_upload_files(big_actions, upload_dir)
    assert big_result == big_actions, "oversized file must be left untouched"
finally:
    config.get_upload_size_cap_mb = orig_cap

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task3.py`
Expected: `AttributeError: 'PythonStrategy' object has no attribute '_extract_upload_files'`

- [ ] **Step 3: Implement**

`cli/script_strategies/python_strategy.py` has a large `_HARNESS_TEMPLATE`
triple-quoted string starting a few lines below its imports — do not add
anything inside that string. Anchor on the exact existing import block
instead. Change:

```python
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli.runtime import is_frozen_binary
from cli import runtime_setup
from cli.script_strategies.base import ScriptStrategy


_BEGIN_MARKER = "# BEGIN ACTIONS"
```

to:

```python
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli.runtime import is_frozen_binary
from cli import runtime_setup
from cli.script_strategies.base import ScriptStrategy

logger = logging.getLogger("qaclan.script_strategies.python")

_SET_INPUT_FILES_RE = re.compile(
    r'\.set_input_files\((\[[^\]]*\]|"[^"]*"|\'[^\']*\')\)'
)
_UPLOAD_QUOTED_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')


_BEGIN_MARKER = "# BEGIN ACTIONS"
```

The `post_process_recording` and `_extract_upload_files` methods below go in
`class PythonStrategy` (line ~273, after the harness template), same as the
existing `_strip_upload_click` method from the earlier click-hang fix — not
near this import block.

Then change the existing:

```python
    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

to:

```python
    def post_process_recording(self, raw: str, upload_dir: str = None) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._extract_upload_files(actions, upload_dir)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

Then add the new method right after `_strip_upload_click` (which already exists from the earlier click-hang fix):

```python
    def _extract_upload_files(self, actions: str, upload_dir: str = None) -> str:
        """Copy any absolute-path file referenced by a recorded
        ``set_input_files()`` call into ``upload_dir`` and rewrite the call to
        reference it via the ``{{__qaclan_upload_dir__}}`` token instead of the
        machine-local path codegen recorded — see
        docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md.

        No-ops if ``upload_dir`` is falsy: only the live `qaclan web record`
        flow supplies one; the paste/import call sites don't."""
        if not upload_dir:
            return actions

        from cli.config import get_upload_size_cap_mb
        cap_bytes = get_upload_size_cap_mb() * 1024 * 1024

        def _replace(m):
            args_text = m.group(1)
            paths = [a or b for a, b in _UPLOAD_QUOTED_STRING_RE.findall(args_text)]
            new_paths = []
            changed = False
            for p in paths:
                if not os.path.isabs(p) or not os.path.exists(p):
                    new_paths.append(p)
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    new_paths.append(p)
                    continue
                if size > cap_bytes:
                    logger.warning(
                        "Upload file %r is %d bytes, over the %dMB cap — not "
                        "captured, recorded path left as-is.",
                        p, size, get_upload_size_cap_mb(),
                    )
                    new_paths.append(p)
                    continue
                basename = os.path.basename(p)
                os.makedirs(upload_dir, exist_ok=True)
                shutil.copyfile(p, os.path.join(upload_dir, basename))
                new_paths.append("{{__qaclan_upload_dir__}}/" + basename)
                changed = True
            if not changed:
                return m.group(0)
            if args_text.startswith("["):
                new_args = "[" + ", ".join(f'"{pp}"' for pp in new_paths) + "]"
            else:
                new_args = f'"{new_paths[0]}"'
            return f".set_input_files({new_args})"

        return _SET_INPUT_FILES_RE.sub(_replace, actions)
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task3.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/python_strategy.py`
Expected: no output (success)

```bash
git add cli/script_strategies/python_strategy.py
git commit -m "feat(record): auto-capture uploaded files during Python script recording"
```

---

### Task 4: JavaScript strategy — detect and capture uploaded files

**Files:**
- Modify: `cli/script_strategies/javascript_strategy.py`
- Modify: `cli/script_strategies/javascript_test_strategy.py`

**Interfaces:**
- Consumes: `cli.config.get_upload_size_cap_mb()` from Task 1.
- Produces: `JavaScriptStrategy._extract_upload_files(actions: str, upload_dir: str | None) -> str`; `JavaScriptStrategy.post_process_recording(raw: str, upload_dir: str = None) -> str`; `JavaScriptTestStrategy.post_process_recording(raw: str, upload_dir: str = None) -> str` (inherits `_extract_upload_files` from `JavaScriptStrategy`; `TypeScriptStrategy`/`TypeScriptTestStrategy` inherit both automatically — no changes needed in those two files).

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task4.py`:

```python
import os, sys, tempfile

sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from cli.script_strategies.javascript_strategy import JavaScriptStrategy
from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy

work = tempfile.mkdtemp()
src_file = os.path.join(work, "report.pdf")
with open(src_file, "wb") as f:
    f.write(b"fake pdf content")

upload_dir = os.path.join(work, "uploads", "script_test456")

actions = (
    'await page.locator("input[type=file]").click();\n'
    f'await page.locator("input[type=file]").setInputFiles("{src_file}");\n'
    'await page.getByRole("button", { name: "Next" }).click();'
)

for cls in (JavaScriptStrategy, JavaScriptTestStrategy):
    strategy = cls()
    result = strategy._extract_upload_files(actions, upload_dir)
    expected_dest = os.path.join(upload_dir, "report.pdf")
    assert os.path.exists(expected_dest), f"[{cls.__name__}] file not copied"
    assert '{{__qaclan_upload_dir__}}/report.pdf' in result, f"[{cls.__name__}] {result}"
    assert src_file not in result
    os.remove(expected_dest)  # reset for next class in the loop

    noop = strategy._extract_upload_files(actions, None)
    assert noop == actions, f"[{cls.__name__}] upload_dir=None must be a no-op"

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task4.py`
Expected: `AttributeError: 'JavaScriptStrategy' object has no attribute '_extract_upload_files'`

- [ ] **Step 3: Implement in `javascript_strategy.py`**

Like the Python file, this one has a large `_HARNESS_TEMPLATE` triple-quoted
string starting a few lines below `logger = ...` — don't add anything
inside it. Anchor on the exact existing block instead. Change:

```python
logger = logging.getLogger("qaclan.script_strategies.javascript")


_BEGIN_MARKER = "// BEGIN ACTIONS"
```

to:

```python
logger = logging.getLogger("qaclan.script_strategies.javascript")

_SET_INPUT_FILES_JS_RE = re.compile(
    r'\.setInputFiles\((\[[^\]]*\]|"[^"]*"|\'[^\']*\')\)'
)
_UPLOAD_QUOTED_STRING_JS_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')


_BEGIN_MARKER = "// BEGIN ACTIONS"
```

The `post_process_recording` and `_extract_upload_files` methods below go in
`class JavaScriptStrategy` (line ~321, after the harness template), same as
the existing `_strip_upload_click` method from the earlier click-hang fix —
not near this import block.

Change:

```python
    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

to:

```python
    def post_process_recording(self, raw: str, upload_dir: str = None) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._extract_upload_files(actions, upload_dir)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

Add the new method after `_strip_upload_click`:

```python
    def _extract_upload_files(self, actions: str, upload_dir: str = None) -> str:
        """Copy any absolute-path file referenced by a recorded
        ``setInputFiles()`` call into ``upload_dir`` and rewrite the call to
        reference it via the ``{{__qaclan_upload_dir__}}`` token — see
        docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md.

        No-ops if ``upload_dir`` is falsy."""
        if not upload_dir:
            return actions

        from cli.config import get_upload_size_cap_mb
        cap_bytes = get_upload_size_cap_mb() * 1024 * 1024

        def _replace(m):
            args_text = m.group(1)
            paths = [a or b for a, b in _UPLOAD_QUOTED_STRING_JS_RE.findall(args_text)]
            new_paths = []
            changed = False
            for p in paths:
                if not os.path.isabs(p) or not os.path.exists(p):
                    new_paths.append(p)
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    new_paths.append(p)
                    continue
                if size > cap_bytes:
                    logger.warning(
                        "Upload file %r is %d bytes, over the %dMB cap — not "
                        "captured, recorded path left as-is.",
                        p, size, get_upload_size_cap_mb(),
                    )
                    new_paths.append(p)
                    continue
                basename = os.path.basename(p)
                os.makedirs(upload_dir, exist_ok=True)
                shutil.copyfile(p, os.path.join(upload_dir, basename))
                new_paths.append("{{__qaclan_upload_dir__}}/" + basename)
                changed = True
            if not changed:
                return m.group(0)
            if args_text.startswith("["):
                new_args = "[" + ", ".join(f'"{pp}"' for pp in new_paths) + "]"
            else:
                new_args = f'"{new_paths[0]}"'
            return f".setInputFiles({new_args})"

        return _SET_INPUT_FILES_JS_RE.sub(_replace, actions)
```

(`logger` and `shutil` already exist at module level in this file.)

- [ ] **Step 4: Implement in `javascript_test_strategy.py`**

Change:

```python
    def post_process_recording(self, raw: str) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

to:

```python
    def post_process_recording(self, raw: str, upload_dir: str = None) -> str:
        actions = self._extract_actions(raw)
        actions = self._patch_goto_wait(actions)
        actions = self._extract_upload_files(actions, upload_dir)
        actions = self._strip_upload_click(actions)
        return self._render_harness(actions)
```

(`_extract_upload_files` is inherited from `JavaScriptStrategy` — no new method needed in this file.)

- [ ] **Step 5: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task4.py`
Expected: `PASS`

- [ ] **Step 6: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/javascript_strategy.py cli/script_strategies/javascript_test_strategy.py`
Expected: no output (success)

```bash
git add cli/script_strategies/javascript_strategy.py cli/script_strategies/javascript_test_strategy.py
git commit -m "feat(record): auto-capture uploaded files during JS/JS-test script recording"
```

---

### Task 5: Wire `upload_dir` through the record flow

**Files:**
- Modify: `cli/commands/web/record.py`
- Modify: `cli/script_strategies/base.py` (signature/docstring parity only)

**Interfaces:**
- Consumes: `cli.config.UPLOADS_DIR` (Task 1), `strategy.post_process_recording(raw, upload_dir=...)` (Tasks 3 & 4).
- Produces: recorded scripts whose `set_input_files`/`setInputFiles` calls reference `{{__qaclan_upload_dir__}}/<basename>` instead of a machine-local path, with the file already copied to `~/.qaclan/uploads/<script_id>/` by the time the DB row is inserted.

- [ ] **Step 1: Update `base.py` for signature parity**

In `cli/script_strategies/base.py`, change:

```python
    def post_process_recording(self, raw: str) -> str:
        """Transform raw codegen output into a self-contained harness script
        that honors the QACLAN_* runtime contract."""
```

to:

```python
    def post_process_recording(self, raw: str, upload_dir: str = None) -> str:
        """Transform raw codegen output into a self-contained harness script
        that honors the QACLAN_* runtime contract.

        ``upload_dir``, if given, is where any file referenced by a recorded
        set_input_files()/setInputFiles() call gets copied — see
        docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md.
        Only the live `qaclan web record` flow supplies one."""
```

- [ ] **Step 2: Reorder `script_id` generation in `record.py` and pass `upload_dir`**

In `cli/commands/web/record.py`, change the import line:

```python
from cli.config import get_active_project, SCRIPTS_DIR
```

to:

```python
from cli.config import get_active_project, SCRIPTS_DIR, UPLOADS_DIR
```

Then change:

```python
        with open(tmp_path, "r", encoding="utf-8") as f:
            raw_script = f.read()

        processed = strategy.post_process_recording(raw_script)

        var_keys_list = []
        start_url_value = url_key_value or url
        if url_key and url_key_value:
            processed = strategy.rewrite_url_template(processed, url_key_value, url_key)
            var_keys_list = [url_key]

        script_id = generate_id("script")
        dest = os.path.join(SCRIPTS_DIR, f"{script_id}{strategy.file_extension}")
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(processed)
```

to:

```python
        with open(tmp_path, "r", encoding="utf-8") as f:
            raw_script = f.read()

        # script_id is generated here (rather than after post-processing, as
        # before) because post_process_recording needs to know where to copy
        # any uploaded test file it detects.
        script_id = generate_id("script")
        upload_dir = os.path.join(UPLOADS_DIR, script_id)
        processed = strategy.post_process_recording(raw_script, upload_dir=upload_dir)

        var_keys_list = []
        start_url_value = url_key_value or url
        if url_key and url_key_value:
            processed = strategy.rewrite_url_template(processed, url_key_value, url_key)
            var_keys_list = [url_key]

        dest = os.path.join(SCRIPTS_DIR, f"{script_id}{strategy.file_extension}")
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(processed)
```

- [ ] **Step 3: Compile check**

Run: `python3 -m py_compile cli/commands/web/record.py cli/script_strategies/base.py`
Expected: no output (success)

- [ ] **Step 4: Manual verification (requires a display — this is the live `qaclan web record` path)**

If you have a GUI environment available: run `python3 qaclan.py web record --feature <existing-feature-id> --name "upload test"`, click a file-upload button in the recorded app, pick a real file, close the browser. Then:

Run: `grep -o '{{__qaclan_upload_dir__}}/[^"]*' ~/.qaclan/scripts/script_*.py` (or `.js`/`.ts` depending on language used) on the newest script file.
Expected: prints the token with the basename of the file you picked, e.g. `{{__qaclan_upload_dir__}}/myfile.pdf`

Run: `ls ~/.qaclan/uploads/<the new script_id>/`
Expected: the picked file is present.

If no GUI is available in this environment, skip this step and note it as unverified — Task 6 and 7's scripted verification still cover the rest of the pipeline.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/web/record.py cli/script_strategies/base.py
git commit -m "feat(record): copy uploaded test files into per-script storage during recording"
```

---

### Task 6: Resolve the upload-dir token at run time

**Files:**
- Modify: `web/routes/runs.py`

**Interfaces:**
- Consumes: `cli.config.UPLOADS_DIR` (Task 1), `strategy.escape_for_literal` (existing).
- Produces: rendered scripts (written to `run_dir`) with `{{__qaclan_upload_dir__}}` replaced by the real absolute path to that script's upload folder.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task6.py`:

```python
import os, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp()
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.config import UPLOADS_DIR
from cli.script_strategies.python_strategy import PythonStrategy

script_id = "script_abc123"
upload_dir = os.path.join(UPLOADS_DIR, script_id)
os.makedirs(upload_dir, exist_ok=True)
with open(os.path.join(upload_dir, "file.pdf"), "wb") as f:
    f.write(b"x")

strategy = PythonStrategy()
source = 'page.locator("x").set_input_files("{{__qaclan_upload_dir__}}/file.pdf")'

# Simulate the substitution runs.py must perform
if "{{__qaclan_upload_dir__}}" in source:
    resolved = source.replace(
        "{{__qaclan_upload_dir__}}",
        strategy.escape_for_literal(upload_dir),
    )
else:
    resolved = source

assert upload_dir in resolved, resolved
assert "{{__qaclan_upload_dir__}}" not in resolved
assert os.path.exists(os.path.join(upload_dir, "file.pdf"))
print("PASS (logic verified standalone -- see Step 4 for the wired-in check)")
```

- [ ] **Step 2: Run it to confirm the substitution logic works standalone**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task6.py`
Expected: `PASS (logic verified standalone -- see Step 4 for the wired-in check)`

(This step doesn't touch `runs.py` yet — it just proves the substitution approach before wiring it into the real request-handling code, which isn't unit-testable in isolation since it lives inside a large Flask route function.)

- [ ] **Step 3: Implement**

In `web/routes/runs.py`, add to the imports near the top:

```python
from cli.config import UPLOADS_DIR
```

Then change:

```python
                    if script_var_keys:
                        source, subs_warnings = substitute_template_vars(
                            source, script_var_keys, env_vars_dict,
                            item["start_url_key"], item["start_url_value"],
                            escape_fn=strategy.escape_for_literal,
                        )
                        for w in subs_warnings:
                            logger.warning("execute_run: %s — %s", item["script_name"], w)

                    # Write the rendered, substituted script into the run directory
                    # so the subprocess executes a known file with no {{KEY}} left.
                    rendered_path = run_dir / f"{srun_id}{strategy.file_extension}"
                    rendered_path.write_text(source, encoding="utf-8")
```

to:

```python
                    if script_var_keys:
                        source, subs_warnings = substitute_template_vars(
                            source, script_var_keys, env_vars_dict,
                            item["start_url_key"], item["start_url_value"],
                            escape_fn=strategy.escape_for_literal,
                        )
                        for w in subs_warnings:
                            logger.warning("execute_run: %s — %s", item["script_name"], w)

                    # Resolve the reserved upload-dir token left by recorded
                    # set_input_files()/setInputFiles() calls. Independent of
                    # the {{KEY}} substitution above -- never needs an
                    # environment entry. See
                    # docs/superpowers/specs/2026-07-19-recorded-upload-assets-design.md.
                    if "{{__qaclan_upload_dir__}}" in source:
                        script_upload_dir = os.path.join(UPLOADS_DIR, item["script_id"])
                        source = source.replace(
                            "{{__qaclan_upload_dir__}}",
                            strategy.escape_for_literal(script_upload_dir),
                        )

                    # Write the rendered, substituted script into the run directory
                    # so the subprocess executes a known file with no {{KEY}} left.
                    rendered_path = run_dir / f"{srun_id}{strategy.file_extension}"
                    rendered_path.write_text(source, encoding="utf-8")
```

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile web/routes/runs.py`
Expected: no output (success)

- [ ] **Step 5: End-to-end manual verification**

Requires a script actually containing the token (produced by Task 5's recording flow, or hand-craft one for this check): create a test script file containing `set_input_files("{{__qaclan_upload_dir__}}/file.pdf")`, insert a matching `scripts` row and a one-item suite pointing at it, put a real `file.pdf` at `~/.qaclan/uploads/<that script_id>/file.pdf`, then run the suite via the web UI or `POST /api/runs/execute`. Confirm in the run's script logs that the upload step no longer errors with "no such file."

- [ ] **Step 6: Commit**

```bash
git add web/routes/runs.py
git commit -m "feat(runs): resolve {{__qaclan_upload_dir__}} token at script render time"
```

---

### Task 7: Clean up upload folder on script deletion

**Files:**
- Modify: `web/routes/scripts.py`

**Interfaces:**
- Consumes: `cli.config.UPLOADS_DIR` (Task 1).
- Produces: `DELETE /api/scripts/<script_id>` also removes `~/.qaclan/uploads/<script_id>/` if present.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task7.py`:

```python
import os, shutil, tempfile

work = tempfile.mkdtemp()
upload_dir = os.path.join(work, "uploads", "script_xyz")
os.makedirs(upload_dir)
with open(os.path.join(upload_dir, "file.pdf"), "wb") as f:
    f.write(b"x")

assert os.path.isdir(upload_dir)

# This is the exact call that must be added to delete_script()
shutil.rmtree(upload_dir, ignore_errors=True)

assert not os.path.exists(upload_dir), "upload_dir should be gone"

# Calling it again (already-deleted case) must not raise
shutil.rmtree(upload_dir, ignore_errors=True)

print("PASS")
```

- [ ] **Step 2: Run it to confirm the deletion call itself is correct**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/c4fc6b5f-036c-402f-b2b6-32381946e5ba/scratchpad/verify_task7.py`
Expected: `PASS`

(Proves the exact `shutil.rmtree` call is safe both when the directory exists and when it doesn't, before wiring it into the route.)

- [ ] **Step 3: Implement**

In `web/routes/scripts.py`, add `shutil` to the top-level imports:

```python
import json
import logging
import os
import re
import shutil
```

Then in `delete_script`, change:

```python
        # Delete file from disk
        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)

        # Delete DB row
        conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
```

to:

```python
        # Delete file from disk
        file_path = row["file_path"]
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)

        # Delete any files captured from recorded upload interactions
        from cli.config import UPLOADS_DIR
        shutil.rmtree(os.path.join(UPLOADS_DIR, script_id), ignore_errors=True)

        # Delete DB row
        conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
```

- [ ] **Step 4: Compile check**

Run: `python3 -m py_compile web/routes/scripts.py`
Expected: no output (success)

- [ ] **Step 5: End-to-end manual verification**

Run: `mkdir -p ~/.qaclan/uploads/script_deletetest && touch ~/.qaclan/uploads/script_deletetest/f.pdf`

Start the server (`python3 qaclan.py serve --port 7823`), insert a throwaway `scripts` row with `id = 'script_deletetest'` (or record a real one and note its id), then:

Run: `curl -X DELETE http://localhost:7823/api/scripts/script_deletetest`
Expected: `{"ok":true}`

Run: `ls ~/.qaclan/uploads/script_deletetest 2>&1`
Expected: `No such file or directory`

- [ ] **Step 6: Commit**

```bash
git add web/routes/scripts.py
git commit -m "fix(scripts): remove a script's upload folder on delete"
```

---

## Post-implementation checklist

- [ ] Re-run `verify_task1.py` through `verify_task7.py` all at once, confirm all print `PASS`.
- [ ] `python3 -m py_compile` every modified file with zero output.
- [ ] Confirm `cli/script_strategies/typescript_strategy.py` and `typescript_test_strategy.py` needed no changes (they inherit `post_process_recording` and `_extract_upload_files` from their JS parents) — `grep -n "post_process_recording\|_extract_upload_files" cli/script_strategies/typescript_strategy.py cli/script_strategies/typescript_test_strategy.py` should return nothing.
