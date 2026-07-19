# Run-Level API Capture: Save, UX, and Filter Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web-automation script runs capture API traffic per script. This plan (1) fixes the capture-time filter so it matches discovery's model instead of a drifted, incomplete blocklist, (2) replaces the per-script "Captured Requests" accordions in the run-results modal with one header-level summary so pass/fail stays the visual focus, (3) makes "save as collection" a single run-scoped action (new or existing collection) instead of one collection per script, and (4) warns before closing the run-results modal with unsaved captures.

**Architecture:** A canonical `(xhr, fetch)` allowlist tuple in `cli/script_strategies/_shared.py` gets JSON-injected into all 4 harness templates (Python, JS, JS-test, TS-test) at render time, replacing each one's independently-hardcoded 5-type blocklist. `cli/api_discovery/captured_request_parser.py` stops faking `_resourceType: "fetch"` on synthetic HAR entries, so discovery's own `_should_skip()`/`_is_static()` heuristics (already correct, untouched) run for real on captured traffic. `web/api/routes/discovery.py`'s `save-requests` endpoint gains an optional `collection_id` to append into an existing collection. `web/static/api/views/request-review-modal.js` (already shared by HAR/Postman/Bruno import) gains an existing-collection picker and script-grouped rendering, both additive and backward compatible. `web/static/app.js`'s `showRunResults()` drops the per-script accordion in favor of one header-level summary + a "Save Captured Requests" action, and `closeModal()` gains a generic pre-close guard hook that the run-results modal uses to confirm before discarding unsaved captures.

**Tech Stack:** Python (Flask backend), vanilla JS frontend, Playwright (Python + `@playwright/test` for JS/TS). No automated test framework exists in this repo (per `CLAUDE.md`) — verification uses standalone scripts (`python3 <script>`), `python3 -m py_compile` / `node --check` syntax checks, and manual browser walkthroughs where JS UI behavior can't be checked any other way.

## Global Constraints

- No automated test suite/linter configured in this repo — every verification step in this plan is either a standalone script, a compile/syntax check, or an explicit manual walkthrough.
- Capture is opt-in: `QACLAN_CAPTURE_REQUESTS=1`, checked once at harness startup. Unaffected by this plan.
- Capture caps unchanged: `_CAPTURE_CAP = 200` requests, `_CAPTURE_BODY_CAP_BYTES = 200_000` bytes per body.
- New canonical filter: `CAPTURE_ALLOWED_RESOURCE_TYPES = ("xhr", "fetch")` in `cli/script_strategies/_shared.py` — allowlist, not blocklist, matching `cli/api_discovery/har_parser.py`'s `_API_RESOURCE_TYPES`.
- No deduplication of captured requests across scripts in a run — every occurrence saved if selected.
- No native `beforeunload` guard anywhere in this repo, and this plan doesn't add one — the close-confirm is the existing in-app `window._confirmDialog()` convention (`web/static/api/api-section.js:98`), scoped to the run-results modal only.
- `captured_requests_count` remains the only DB-persisted signal for a historical/reopened run — this plan does not change that; full request/response bodies still exist only on a fresh `execute_run()` response.
- Spec: `docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md`

---

### Task 1: Canonical capture-allowed resource types

**Files:**
- Modify: `cli/script_strategies/_shared.py`

**Interfaces:**
- Produces: `CAPTURE_ALLOWED_RESOURCE_TYPES: tuple[str, ...]` (module-level constant, `("xhr", "fetch")`).

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task1.py`:

```python
import sys
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES

assert CAPTURE_ALLOWED_RESOURCE_TYPES == ("xhr", "fetch"), CAPTURE_ALLOWED_RESOURCE_TYPES
print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task1.py`
Expected: `ImportError: cannot import name 'CAPTURE_ALLOWED_RESOURCE_TYPES'`

- [ ] **Step 3: Implement**

In `cli/script_strategies/_shared.py`, change:

```python
RESERVED_VAR_TOKENS = {"__qaclan_upload_dir__"}

# Markers emitted by every strategy's harness. Detection is lax on the trailing
```

to:

```python
RESERVED_VAR_TOKENS = {"__qaclan_upload_dir__"}

# Resource types kept during capture-run request recording (opt-in via
# QACLAN_CAPTURE_REQUESTS=1). Matches discovery's live-record filter
# (cli/api_discovery/har_parser.py _API_RESOURCE_TYPES) -- an allowlist, not
# a blocklist, so unknown/future Playwright resource types are excluded by
# default. Single source of truth, JSON-injected into each harness template
# at render time — see
# docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md.
CAPTURE_ALLOWED_RESOURCE_TYPES = ("xhr", "fetch")

# Markers emitted by every strategy's harness. Detection is lax on the trailing
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task1.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/_shared.py`
Expected: no output (success)

```bash
git add cli/script_strategies/_shared.py
git commit -m "feat(capture): add canonical xhr/fetch capture-allowlist constant"
```

---

### Task 2: Python harness — capture filter parity

**Files:**
- Modify: `cli/script_strategies/python_strategy.py`

**Interfaces:**
- Consumes: `cli.script_strategies._shared.CAPTURE_ALLOWED_RESOURCE_TYPES` (Task 1).
- Produces: rendered Python harness whose capture logic keeps only `xhr`/`fetch` requests (previously: blocklist of 5 types).

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task2.py`:

```python
import sys, py_compile, tempfile, os
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.script_strategies.python_strategy import PythonStrategy

strategy = PythonStrategy()
rendered = strategy._render_harness('page.goto("https://example.com")')

assert "{CAPTURE_ALLOWED_TYPES_JSON}" not in rendered, "placeholder not substituted"
assert "_CAPTURE_SKIP_TYPES" not in rendered, "old blocklist name still present"
assert '_CAPTURE_ALLOWED_TYPES = set(["xhr", "fetch"])' in rendered, rendered
assert "if req.resource_type not in _CAPTURE_ALLOWED_TYPES:" in rendered, rendered
assert "if _CAPTURE_ENABLED and req.resource_type in _CAPTURE_ALLOWED_TYPES:" in rendered, rendered

tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
tmp.write(rendered)
tmp.close()
py_compile.compile(tmp.name, doraise=True)
os.unlink(tmp.name)
print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task2.py`
Expected: `AssertionError: ..._CAPTURE_ALLOWED_TYPES = set(["xhr", "fetch"])...` not found (current file still has `_CAPTURE_SKIP_TYPES`)

- [ ] **Step 3: Implement**

In `cli/script_strategies/python_strategy.py`, change the module-level imports:

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
```

to:

```python
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli.runtime import is_frozen_binary
from cli import runtime_setup
from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
from cli.script_strategies.base import ScriptStrategy
```

Then, in `_HARNESS_TEMPLATE`, change:

```python
_CAPTURE_ENABLED = os.environ.get("QACLAN_CAPTURE_REQUESTS") == "1"
_captured_requests = []
_capture_starts = {}
_CAPTURE_CAP = 200
_CAPTURE_BODY_CAP_BYTES = 200_000
_CAPTURE_SKIP_TYPES = {"document", "stylesheet", "image", "font", "script"}
```

to:

```python
_CAPTURE_ENABLED = os.environ.get("QACLAN_CAPTURE_REQUESTS") == "1"
_captured_requests = []
_capture_starts = {}
_CAPTURE_CAP = 200
_CAPTURE_BODY_CAP_BYTES = 200_000
_CAPTURE_ALLOWED_TYPES = set({CAPTURE_ALLOWED_TYPES_JSON})
```

Then change:

```python
def _capture_request(req):
    if not _CAPTURE_ENABLED:
        return
    if req.resource_type in _CAPTURE_SKIP_TYPES:
        return
```

to:

```python
def _capture_request(req):
    if not _CAPTURE_ENABLED:
        return
    if req.resource_type not in _CAPTURE_ALLOWED_TYPES:
        return
```

Then change:

```python
    def _on_request(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight += 1
        if _CAPTURE_ENABLED and req.resource_type not in _CAPTURE_SKIP_TYPES:
            _capture_starts[id(req)] = time.monotonic()
```

to:

```python
    def _on_request(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight += 1
        if _CAPTURE_ENABLED and req.resource_type in _CAPTURE_ALLOWED_TYPES:
            _capture_starts[id(req)] = time.monotonic()
```

Finally, change `_render_harness`:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            # Harness still needs a body — emit a `pass` so the file is valid.
            body = "            pass"
        else:
            body = "\n".join("            " + line if line else "" for line in actions.splitlines())
        body = f"{' ' * 12}{_BEGIN_MARKER}\n{body}\n{' ' * 12}{_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
```

to:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            # Harness still needs a body — emit a `pass` so the file is valid.
            body = "            pass"
        else:
            body = "\n".join("            " + line if line else "" for line in actions.splitlines())
        body = f"{' ' * 12}{_BEGIN_MARKER}\n{body}\n{' ' * 12}{_END_MARKER}"
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task2.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/python_strategy.py`
Expected: no output (success)

```bash
git add cli/script_strategies/python_strategy.py
git commit -m "fix(capture): Python harness keeps xhr/fetch only, matching discovery"
```

---

### Task 3: JavaScript harness — capture filter parity

**Files:**
- Modify: `cli/script_strategies/javascript_strategy.py`

**Interfaces:**
- Consumes: `cli.script_strategies._shared.CAPTURE_ALLOWED_RESOURCE_TYPES` (Task 1).
- Produces: rendered JS harness (`.js` scripts, not `@playwright/test`) whose capture logic keeps only `xhr`/`fetch`.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task3.py`:

```python
import sys, subprocess, tempfile, os, shutil
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.script_strategies.javascript_strategy import JavaScriptStrategy

strategy = JavaScriptStrategy()
rendered = strategy._render_harness('await page.goto("https://example.com");')

assert "{CAPTURE_ALLOWED_TYPES_JSON}" not in rendered, "placeholder not substituted"
assert "_CAPTURE_SKIP_TYPES" not in rendered, "old blocklist name still present"
assert "const _CAPTURE_ALLOWED_TYPES = new Set([\"xhr\", \"fetch\"]);" in rendered, rendered
assert "if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;" in rendered, rendered
assert "if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());" in rendered, rendered

node = shutil.which("node")
if node:
    tmp = tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w")
    tmp.write(rendered)
    tmp.close()
    result = subprocess.run([node, "--check", tmp.name], capture_output=True, text=True)
    os.unlink(tmp.name)
    assert result.returncode == 0, result.stderr
else:
    print("node not found on PATH -- skipping syntax check")

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task3.py`
Expected: `AssertionError: old blocklist name still present`

- [ ] **Step 3: Implement**

In `cli/script_strategies/javascript_strategy.py`, change the module-level imports:

```python
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli import runtime_setup
from cli.script_strategies.base import ScriptStrategy
```

to:

```python
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import List

from cli import runtime_setup
from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
from cli.script_strategies.base import ScriptStrategy
```

Then, in `_HARNESS_TEMPLATE`, change:

```python
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);
```

to:

```python
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_ALLOWED_TYPES = new Set({CAPTURE_ALLOWED_TYPES_JSON});
```

Then change:

```python
async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
```

to:

```python
async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;
```

Then change:

```python
function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

to:

```python
function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

Finally, change `_render_harness`:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
```

to:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task3.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/javascript_strategy.py`
Expected: no output (success)

```bash
git add cli/script_strategies/javascript_strategy.py
git commit -m "fix(capture): JS harness keeps xhr/fetch only, matching discovery"
```

---

### Task 4: JavaScript-test harness — capture filter parity

**Files:**
- Modify: `cli/script_strategies/javascript_test_strategy.py`

**Interfaces:**
- Consumes: `cli.script_strategies._shared.CAPTURE_ALLOWED_RESOURCE_TYPES` (Task 1).
- Produces: rendered `@playwright/test` JS harness (`.spec.js`) whose capture logic keeps only `xhr`/`fetch`.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task4.py`:

```python
import sys, subprocess, tempfile, os, shutil
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy

strategy = JavaScriptTestStrategy()
rendered = strategy._render_harness('await page.goto("https://example.com");')

assert "{CAPTURE_ALLOWED_TYPES_JSON}" not in rendered, "placeholder not substituted"
assert "_CAPTURE_SKIP_TYPES" not in rendered, "old blocklist name still present"
assert "const _CAPTURE_ALLOWED_TYPES = new Set([\"xhr\", \"fetch\"]);" in rendered, rendered
assert "if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;" in rendered, rendered
assert "if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());" in rendered, rendered

node = shutil.which("node")
if node:
    tmp = tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w")
    tmp.write(rendered)
    tmp.close()
    result = subprocess.run([node, "--check", tmp.name], capture_output=True, text=True)
    os.unlink(tmp.name)
    assert result.returncode == 0, result.stderr
else:
    print("node not found on PATH -- skipping syntax check")

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task4.py`
Expected: `AssertionError: old blocklist name still present`

- [ ] **Step 3: Implement**

In `cli/script_strategies/javascript_test_strategy.py`, change the module-level imports:

```python
from cli import runtime_setup
from cli.script_strategies.javascript_strategy import JavaScriptStrategy
```

to:

```python
from cli import runtime_setup
from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
from cli.script_strategies.javascript_strategy import JavaScriptStrategy
```

(`json` is already imported at the top of this file — no change needed there.)

Then, in `_HARNESS_TEMPLATE`, change:

```python
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);
```

to:

```python
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_ALLOWED_TYPES = new Set({CAPTURE_ALLOWED_TYPES_JSON});
```

Then change:

```python
async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
```

to:

```python
async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;
```

Then change:

```python
function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

to:

```python
function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

Finally, change `_render_harness`:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
```

to:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task4.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/javascript_test_strategy.py`
Expected: no output (success)

```bash
git add cli/script_strategies/javascript_test_strategy.py
git commit -m "fix(capture): JS-test harness keeps xhr/fetch only, matching discovery"
```

---

### Task 5: TypeScript-test harness — capture filter parity

**Files:**
- Modify: `cli/script_strategies/typescript_test_strategy.py`

**Interfaces:**
- Consumes: `cli.script_strategies._shared.CAPTURE_ALLOWED_RESOURCE_TYPES` (Task 1).
- Produces: rendered `@playwright/test` TypeScript harness (`.spec.ts`) whose capture logic keeps only `xhr`/`fetch`.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task5.py`:

```python
import sys, subprocess, tempfile, os, shutil
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.script_strategies.typescript_test_strategy import TypeScriptStrategy as _unused  # noqa: sanity import
from cli.script_strategies.typescript_test_strategy import TypeScriptTestStrategy

strategy = TypeScriptTestStrategy()
rendered = strategy._render_harness('await page.goto("https://example.com");')

assert "{CAPTURE_ALLOWED_TYPES_JSON}" not in rendered, "placeholder not substituted"
assert "_CAPTURE_SKIP_TYPES" not in rendered, "old blocklist name still present"
assert "const _CAPTURE_ALLOWED_TYPES = new Set([\"xhr\", \"fetch\"]);" in rendered, rendered
assert "if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;" in rendered, rendered
assert "if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());" in rendered, rendered

node = shutil.which("node")
if node:
    tmp = tempfile.NamedTemporaryFile(suffix=".ts", delete=False, mode="w")
    tmp.write(rendered)
    tmp.close()
    # No tsc available guaranteed in this environment -- node --check only
    # validates JS syntax, so strip TS-only annotations with a crude pass
    # isn't attempted; instead just confirm the file is non-empty and the
    # substitution landed (already asserted above). Full TS typecheck happens
    # naturally the first time a suite actually runs this harness via
    # @playwright/test's esbuild pipeline (Task 5 Step 5 manual check below).
    os.unlink(tmp.name)
else:
    print("node not found on PATH -- skipping placeholder file check")

print("PASS")
```

(Note: unlike Tasks 3/4, this file is TypeScript — `node --check` would reject valid TS syntax like typed parameters, so this script only checks the substitution result, not JS/TS syntax. Step 5 below covers a real compile via `@playwright/test`.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task5.py`
Expected: `AssertionError: old blocklist name still present`

- [ ] **Step 3: Implement**

In `cli/script_strategies/typescript_test_strategy.py`, change:

```python
from __future__ import annotations

from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy
```

to:

```python
from __future__ import annotations

import json

from cli.script_strategies._shared import CAPTURE_ALLOWED_RESOURCE_TYPES
from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy
```

Then, in `_HARNESS_TEMPLATE`, change:

```python
const _captureStarts = new Map<any, number>();
const _capturePending: Promise<void>[] = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);
```

to:

```python
const _captureStarts = new Map<any, number>();
const _capturePending: Promise<void>[] = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_ALLOWED_TYPES = new Set({CAPTURE_ALLOWED_TYPES_JSON});
```

Then change:

```python
async function _captureRequest(req: any): Promise<void> {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
```

to:

```python
async function _captureRequest(req: any): Promise<void> {
  if (!_CAPTURE_ENABLED) return;
  if (!_CAPTURE_ALLOWED_TYPES.has(req.resourceType())) return;
```

Then change:

```python
function _trackNetwork(page: any) {
  page.on('request', (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

to:

```python
function _trackNetwork(page: any) {
  page.on('request', (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && _CAPTURE_ALLOWED_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
```

Finally, change `_render_harness`:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        return _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
```

to:

```python
    def _render_harness(self, actions: str) -> str:
        if not actions.strip():
            body = "    // pass"
        else:
            body = "\n".join("    " + line if line else "" for line in actions.splitlines())
        body = f"    {_BEGIN_MARKER}\n{body}\n    {_END_MARKER}"
        rendered = _HARNESS_TEMPLATE.replace("{ACTIONS}", body)
        return rendered.replace(
            "{CAPTURE_ALLOWED_TYPES_JSON}", json.dumps(list(CAPTURE_ALLOWED_RESOURCE_TYPES))
        )
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task5.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/script_strategies/typescript_test_strategy.py`
Expected: no output (success)

If a project with `@playwright/test` installed is available (`~/.qaclan/runtime/node_modules` after `qaclan setup --runtime-only`), do a real end-to-end sanity run: record or hand-write a trivial `.spec.ts` script, run it with `QACLAN_CAPTURE_REQUESTS=1` against a page that fires at least one real `fetch()` call and one static asset load, and confirm the run's artifacts JSON only contains the `fetch` entry. If no such environment is available in this session, skip this step and note it as unverified beyond the syntax/substitution checks above — Task 6's verification covers the parser-side behavior independently.

```bash
git add cli/script_strategies/typescript_test_strategy.py
git commit -m "fix(capture): TS-test harness keeps xhr/fetch only, matching discovery"
```

---

### Task 6: Parser — real heuristic second pass on captured requests

**Files:**
- Modify: `cli/api_discovery/captured_request_parser.py`

**Interfaces:**
- Consumes: `cli.api_discovery.har_parser.parse_har()` (existing, unchanged).
- Produces: `parse_captured_requests()` (existing signature unchanged) now also filters out static-content-disguised-as-fetch/xhr entries (e.g. `fetch('/static/app.js')`), via discovery's real `_is_static()` heuristics instead of bypassing them.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task6.py`:

```python
import sys
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

from cli.api_discovery.captured_request_parser import parse_captured_requests

api_entry = {
    "method": "GET",
    "url": "https://example.com/api/users",
    "request_headers": {},
    "request_body": None,
    "status_code": 200,
    "response_headers": {"content-type": "application/json"},
    "response_body": '{"ok":true}',
    "duration_ms": 12,
}
static_entry = {
    "method": "GET",
    "url": "https://example.com/static/app.abc123.js",
    "request_headers": {},
    "request_body": None,
    "status_code": 200,
    "response_headers": {"content-type": "application/javascript"},
    "response_body": "console.log(1)",
    "duration_ms": 5,
}

result = parse_captured_requests([api_entry, static_entry])
urls = [r["url"] for r in result]

assert "https://example.com/api/users" in urls, urls
assert "https://example.com/static/app.abc123.js" not in urls, (
    "static-content fetch should have been filtered by _is_static() -- got " + str(urls)
)
print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task6.py`
Expected: `AssertionError: static-content fetch should have been filtered ...` (currently both URLs pass through, since `_resourceType: "fetch"` bypasses the heuristic)

- [ ] **Step 3: Implement**

In `cli/api_discovery/captured_request_parser.py`, change:

```python
    return {
        # Marks this as an XHR/fetch entry so parse_har()'s _should_skip()
        # never filters it out — the harness already filtered at capture time.
        "_resourceType": "fetch",
        "time": captured.get("duration_ms") or 0,
```

to:

```python
    return {
        # No _resourceType key here: the harness already narrowed capture to
        # xhr/fetch (cli.script_strategies._shared
        # CAPTURE_ALLOWED_RESOURCE_TYPES), so parse_har()'s _should_skip()
        # falls through to its real _is_static() heuristic branch for every
        # entry — the same extension/path/content-type check discovery
        # applies to third-party HAR imports, catching e.g.
        # fetch('/static/app.js') that Playwright still labels 'fetch'. See
        # docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md.
        "time": captured.get("duration_ms") or 0,
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task6.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile cli/api_discovery/captured_request_parser.py`
Expected: no output (success)

```bash
git add cli/api_discovery/captured_request_parser.py
git commit -m "fix(capture): reuse discovery's real static-content filter on captured requests"
```

---

### Task 7: Backend — save captured requests into an existing collection

**Files:**
- Modify: `web/api/routes/discovery.py`

**Interfaces:**
- Consumes: `web.api.repositories.collection_repo.CollectionRepo.get(id, project_id)` (existing), `web.api.services.discovery_service._save_requests(project_id, requests, collection_id=None)` (existing, already accepts an existing `collection_id`).
- Produces: `POST /api/discover/save-requests` accepts an optional `collection_id` field; when present, appends into that collection instead of creating a new one via `collection_name`.

- [ ] **Step 1: Write a standalone verification script**

Create `/tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task7.py`:

```python
import os, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp()  # isolate from the real ~/.qaclan
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")

# HOME is set before cli.config/cli.db are imported anywhere in this fresh
# process, so QACLAN_DIR/DB_PATH (computed at import time) already point at
# the isolated tempdir -- no importlib.reload needed.
import cli.db as db
import cli.config as config
db.init_db()

conn = db.get_conn()
conn.execute(
    "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
    ("proj_test1", "Test Project", "2026-07-19T00:00:00Z"),
)
conn.commit()
config.set_active_project_id("proj_test1")

from web.server import create_app
app = create_app()
client = app.test_client()

sample_requests = [{
    "name": "GET /api/users", "method": "GET", "url": "https://example.com/api/users",
    "headers": [], "params": [], "body_type": None, "body": None,
    "auth_type": "none", "auth_config": "{}", "assertions": "[]",
    "request_schema": None, "response_schema": None,
    "response_status": 200, "response_headers": {}, "response_body": None,
    "duration_ms": 10, "include_in_docs": 1,
}]

# 1. No collection_id -> creates a new collection (existing behavior, unchanged)
res1 = client.post("/api/discover/save-requests", json={
    "requests": sample_requests, "collection_name": "Run Capture Test",
})
data1 = res1.get_json()
assert data1["ok"] is True, data1
assert data1["imported"] == 1, data1
col_id = data1["collection_id"]

# 2. With collection_id -> appends into the same collection, no new one created
res2 = client.post("/api/discover/save-requests", json={
    "requests": sample_requests, "collection_id": col_id,
})
data2 = res2.get_json()
assert data2["ok"] is True, data2
assert data2["collection_id"] == col_id, "should reuse the existing collection, not create a new one"

collections = client.get("/api/collections").get_json()["collections"]
matching = [c for c in collections if c["id"] == col_id]
assert len(matching) == 1, "expected exactly one collection with this id"
assert matching[0]["request_count"] == 2, (
    f"expected 2 requests total after both saves, got {matching[0]['request_count']}"
)

# 3. Unknown collection_id -> 404, not a silent new collection
res3 = client.post("/api/discover/save-requests", json={
    "requests": sample_requests, "collection_id": "apicol_does_not_exist",
})
assert res3.status_code == 404, res3.status_code
data3 = res3.get_json()
assert data3["ok"] is False, data3

print("PASS")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task7.py`
Expected: `AssertionError: should reuse the existing collection, not create a new one` (current code always calls `CollectionRepo().create()`, ignoring any `collection_id` in the body since it doesn't read that field at all)

- [ ] **Step 3: Implement**

In `web/api/routes/discovery.py`, change:

```python
@bp.route("/api/discover/save-requests", methods=["POST"])
def save_requests():
    """Save pre-parsed request objects directly (no re-parsing). Body:
    {requests, collection_name, include_in_docs, collection_vars,
    collection_auth}. collection_vars/collection_auth are optional passthrough
    from a Postman/Bruno preview (parse_postman/parse_bruno_collection_settings
    output) so the review-modal save step doesn't lose them."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        requests_list = data.get("requests", [])
        collection_name = data.get("collection_name", "Recorded APIs")
        include_in_docs = int(data.get("include_in_docs", 1))
        collection_vars = data.get("collection_vars")
        collection_auth = data.get("collection_auth")
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        # Stamp include_in_docs on each request
        for r in requests_list:
            r['include_in_docs'] = include_in_docs
        from web.api.services.discovery_service import _save_requests, _apply_collection_extras
        from web.api.repositories.collection_repo import CollectionRepo
        col = CollectionRepo().create(pid, collection_name)
        saved = _save_requests(pid, requests_list, collection_id=col["id"])
```

to:

```python
@bp.route("/api/discover/save-requests", methods=["POST"])
def save_requests():
    """Save pre-parsed request objects directly (no re-parsing). Body:
    {requests, collection_name, collection_id, include_in_docs,
    collection_vars, collection_auth}. collection_id (optional) appends into
    an existing collection instead of creating a new one — see
    docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md (Section
    A). collection_vars/collection_auth are optional passthrough from a
    Postman/Bruno preview (parse_postman/parse_bruno_collection_settings
    output) so the review-modal save step doesn't lose them."""
    try:
        pid = _project_id()
        data = request.get_json(force=True) or {}
        requests_list = data.get("requests", [])
        collection_name = data.get("collection_name", "Recorded APIs")
        collection_id = data.get("collection_id")
        include_in_docs = int(data.get("include_in_docs", 1))
        collection_vars = data.get("collection_vars")
        collection_auth = data.get("collection_auth")
        if not requests_list:
            return jsonify({"ok": False, "error": "No requests provided"}), 400
        # Stamp include_in_docs on each request
        for r in requests_list:
            r['include_in_docs'] = include_in_docs
        from web.api.services.discovery_service import _save_requests, _apply_collection_extras
        from web.api.repositories.collection_repo import CollectionRepo
        if collection_id:
            existing = CollectionRepo().get(collection_id, pid)
            if not existing:
                return jsonify({"ok": False, "error": "Collection not found"}), 404
            col = existing
        else:
            col = CollectionRepo().create(pid, collection_name)
        saved = _save_requests(pid, requests_list, collection_id=col["id"])
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/claude-1000/-mnt-ext-drive-qaclan-agent/ba8759b3-f148-42b3-b775-e59ab03f6eb0/scratchpad/verify_task7.py`
Expected: `PASS`

- [ ] **Step 5: Compile check + commit**

Run: `python3 -m py_compile web/api/routes/discovery.py`
Expected: no output (success)

```bash
git add web/api/routes/discovery.py
git commit -m "feat(discovery): allow save-requests to append into an existing collection"
```

---

### Task 8: Frontend — request-review-modal: group-by-script + existing-collection picker

**Files:**
- Modify: `web/static/api/views/request-review-modal.js`

**Interfaces:**
- Consumes: `GET /api/collections` (existing), `POST /api/discover/save-requests` with optional `collection_id` (Task 7).
- Produces: `showRequestReviewModal(requests, defaultCollectionName, startUrl, extras)` — signature unchanged, but:
  - if any `requests[i]._scriptName` is set, the list renders grouped by that field (script name) instead of flat;
  - a new "or append to existing collection" `<select>` is shown; when a non-blank value is chosen, save passes `collection_id` instead of `collection_name`;
  - `extras.onSaved(data)` (optional callback) is invoked immediately after a successful save, before the modal closes.

- [ ] **Step 1: Manually confirm current behavior has no grouping/picker**

Run: `grep -n "_scriptName\|rev-col-existing\|onSaved" web/static/api/views/request-review-modal.js`
Expected: no output (none of these exist yet)

- [ ] **Step 2: Implement — existing-collection picker + onSaved hook**

In `web/static/api/views/request-review-modal.js`, change the function signature area and the collection-name input block:

```javascript
export function showRequestReviewModal(requests, defaultCollectionName, startUrl, extras) {
  if (!requests?.length) {
    window._alertDialog('No requests found in this file.');
    return;
  }
  const importWarnings = extras?.warnings || [];
  const collectionVars = extras?.collection_vars || null;
  const collectionAuth = extras?.collection_auth || null;
```

to:

```javascript
export function showRequestReviewModal(requests, defaultCollectionName, startUrl, extras) {
  if (!requests?.length) {
    window._alertDialog('No requests found in this file.');
    return;
  }
  const importWarnings = extras?.warnings || [];
  const collectionVars = extras?.collection_vars || null;
  const collectionAuth = extras?.collection_auth || null;
  const onSaved = extras?.onSaved || null;
  let existingCollections = [];
```

Then change:

```javascript
    <div style="margin-bottom:10px;">
      <label class="form-label">Save to collection</label>
      <input id="rev-col-name" type="text" class="input-sm" style="width:100%"
        value="${_esc(defaultCollectionName || 'Imported APIs')}">
    </div>
```

to:

```javascript
    <div style="margin-bottom:10px;">
      <label class="form-label">Save to collection</label>
      <input id="rev-col-name" type="text" class="input-sm" style="width:100%"
        value="${_esc(defaultCollectionName || 'Imported APIs')}">
      <select id="rev-col-existing" class="input-sm" style="width:100%;margin-top:6px;">
        <option value="">— New collection (name above) —</option>
      </select>
    </div>
```

- [ ] **Step 3: Implement — populate the existing-collection picker on open**

Change:

```javascript
  requestAnimationFrame(() => {
    const listEl = document.getElementById('rev-list')
    if (listEl) _renderList(listEl)

    document.getElementById('rev-all')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = true));
    document.getElementById('rev-none')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = false));
    document.getElementById('rev-hide-3p')?.addEventListener('change', e => {
      hidingThirdParty = e.target.checked;
      if (listEl) _renderList(listEl)
    });

    const saveBtn = document.querySelector('[data-btn-idx="1"]');
    document.querySelectorAll('input[name="rev-save-mode"]').forEach(r => {
      r.addEventListener('change', () => {
        const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value;
        if (saveBtn) saveBtn.textContent = mode === 'library' ? 'Next →' : 'Save Selected';
      });
    });
  });
}
```

to:

```javascript
  requestAnimationFrame(async () => {
    const listEl = document.getElementById('rev-list')
    if (listEl) _renderList(listEl)

    document.getElementById('rev-all')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = true));
    document.getElementById('rev-none')?.addEventListener('click', () =>
      document.querySelectorAll('[id^="rev-req-"]').forEach(c => c.checked = false));
    document.getElementById('rev-hide-3p')?.addEventListener('change', e => {
      hidingThirdParty = e.target.checked;
      if (listEl) _renderList(listEl)
    });

    const saveBtn = document.querySelector('[data-btn-idx="1"]');
    document.querySelectorAll('input[name="rev-save-mode"]').forEach(r => {
      r.addEventListener('change', () => {
        const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value;
        if (saveBtn) saveBtn.textContent = mode === 'library' ? 'Next →' : 'Save Selected';
      });
    });

    const existingSel = document.getElementById('rev-col-existing');
    if (existingSel) {
      const res = await window.api('GET', '/collections');
      existingCollections = res?.collections || [];
      for (const c of existingCollections) {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name;
        existingSel.appendChild(opt);
      }
    }
  });
}
```

- [ ] **Step 4: Implement — grouped rendering + pass `collection_id` on save**

Change `_renderList`:

```javascript
  function _renderList(listEl) {
    // Build rows as DOM nodes so we can attach handlers directly
    listEl.innerHTML = '';
    _visible().forEach(r => {
      const wrapper = document.createElement('div');
      wrapper.style.borderBottom = '1px solid var(--border)';
```

to:

```javascript
  function _renderList(listEl) {
    // Build rows as DOM nodes so we can attach handlers directly
    listEl.innerHTML = '';
    let lastGroup = undefined;
    _visible().forEach(r => {
      if (r._scriptName !== undefined && r._scriptName !== lastGroup) {
        lastGroup = r._scriptName;
        const groupHeader = document.createElement('div');
        groupHeader.style.cssText = 'padding:6px 10px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);background:var(--bg-base);border-bottom:1px solid var(--border);';
        groupHeader.textContent = lastGroup || 'Unknown script';
        listEl.appendChild(groupHeader);
      }
      const wrapper = document.createElement('div');
      wrapper.style.borderBottom = '1px solid var(--border)';
```

Then change the Save button's `action`:

```javascript
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value || 'flow';

      if (mode === 'library') {
        const plainRequests = selected.map(({ _idx, ...rest }) => rest);
        const grouped = await window.api('POST', '/discover/group-requests', { requests: plainRequests });
        if (grouped.ok === false) { await window._alertDialog('Grouping failed: ' + grouped.error); return; }
        window.closeModal();
        showVariantComparisonModal(grouped.groups, colName, includeInDocs);
        return;
      }

      const data = await window.api('POST', '/discover/save-requests', {
        requests: selected,
        collection_name: colName,
        include_in_docs: includeInDocs,
        collection_vars: collectionVars,
        collection_auth: collectionAuth,
      });
      window.closeModal();
      if (data.ok) {
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${colName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
```

to:

```javascript
    { label: 'Save Selected', cls: 'btn-primary', action: async () => {
      const colName = document.getElementById('rev-col-name')?.value.trim() || 'Imported APIs';
      const existingColId = document.getElementById('rev-col-existing')?.value || '';
      const selected = indexedRequests.filter(r => document.getElementById(`rev-req-${r._idx}`)?.checked);
      if (!selected.length) { await window._alertDialog('No requests selected.'); return; }
      const includeInDocs = document.getElementById('rev-include-docs')?.checked ? 1 : 0;
      const mode = document.querySelector('input[name="rev-save-mode"]:checked')?.value || 'flow';

      if (mode === 'library') {
        const plainRequests = selected.map(({ _idx, _scriptName, ...rest }) => rest);
        const grouped = await window.api('POST', '/discover/group-requests', { requests: plainRequests });
        if (grouped.ok === false) { await window._alertDialog('Grouping failed: ' + grouped.error); return; }
        window.closeModal();
        showVariantComparisonModal(grouped.groups, colName, includeInDocs);
        return;
      }

      const plainSelected = selected.map(({ _idx, _scriptName, ...rest }) => rest);
      const data = await window.api('POST', '/discover/save-requests', {
        requests: plainSelected,
        collection_name: colName,
        collection_id: existingColId || undefined,
        include_in_docs: includeInDocs,
        collection_vars: collectionVars,
        collection_auth: collectionAuth,
      });
      if (data.ok) onSaved?.(data);
      window.closeModal();
      if (data.ok) {
        const targetName = existingColId
          ? (existingCollections.find(c => c.id === existingColId)?.name || colName)
          : colName;
        window.__qaclanApi?.refresh?.();
        window._toast(`Saved ${data.imported} request${data.imported !== 1 ? 's' : ''} to '${targetName}'.`);
      } else {
        await window._alertDialog('Save failed: ' + data.error);
      }
    }},
```

- [ ] **Step 5: Syntax check**

Run: `node --check web/static/api/views/request-review-modal.js`
Expected: no output (success). (This file uses `import`/`export` — if `node --check` errors on module syntax in this environment, instead run `node --input-type=module --check < web/static/api/views/request-review-modal.js` or skip and rely on Step 6's manual browser check.)

- [ ] **Step 6: Manual verification (requires a browser)**

If a GUI environment is available: start the server (`python3 qaclan.py serve --port 7823`), open the app, trigger any existing HAR/Postman import flow that calls `showRequestReviewModal` (e.g. Discover → import a HAR file). Confirm:
- The modal looks and behaves exactly as before (no `_scriptName` on plain import requests, so no group headers appear; the new "existing collection" dropdown appears but defaults to "— New collection —" and doesn't change existing save behavior when left on that default).
- Picking an existing collection from the new dropdown and saving appends into it instead of creating a new one (cross-check with Task 7's route change).

If no GUI is available in this session, skip this step and note it as unverified — Task 9's manual verification (run-results modal) exercises the grouped-rendering path with real `_scriptName`-tagged data, and Task 7's scripted verification already covers the backend half of this behavior.

- [ ] **Step 7: Commit**

```bash
git add web/static/api/views/request-review-modal.js
git commit -m "feat(discover): request-review-modal supports script grouping and existing-collection save"
```

---

### Task 9: Frontend — run-results modal: header summary, run-scoped save, close-confirm

**Files:**
- Modify: `web/static/app.js`

**Interfaces:**
- Consumes: `showRequestReviewModal(requests, defaultCollectionName, startUrl, extras)` (Task 8, `extras.onSaved` support).
- Produces: `closeModal()` (existing, now checks an optional `window._modalCloseGuard` before closing); `reviewRunCapturedRequests()` (new); `showRunResults(run, suiteName)` (existing, no per-script accordion, one header-level summary instead).

- [ ] **Step 1: Manually confirm current behavior**

Run: `grep -n "_modalCloseGuard\|reviewRunCapturedRequests\|run-capture-summary" web/static/app.js`
Expected: no output (none of these exist yet)

- [ ] **Step 2: Implement — generic close-guard in `closeModal()`**

In `web/static/app.js`, change:

```javascript
function closeModal() {
  // Fire any cleanup hook the current modal registered (e.g. CM6 editor teardown)
  // before we blow away the modal DOM. Runs once, then clears.
  const hook = window._qcModalCleanupHook
  window._qcModalCleanupHook = null
  if (typeof hook === 'function') {
    try { hook() } catch (e) { console.warn('[qaclan] modal cleanup hook failed:', e) }
  }

  document.getElementById('modal-backdrop').classList.add('hidden')
  document.getElementById('modal-root').classList.add('hidden')
  document.getElementById('modal-root').innerHTML = ''
  document.getElementById('modal-backdrop').onclick = null
}
```

to:

```javascript
function closeModal() {
  // Optional async guard the currently-open modal can register (e.g. "you
  // have unsaved captured API requests") — return true to proceed with the
  // close, false/undefined to abort it. Checked before anything else so an
  // aborted close leaves the modal fully intact. See
  // docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md (Section C).
  const guard = window._modalCloseGuard
  if (typeof guard === 'function') {
    guard().then(proceed => {
      if (proceed) {
        window._modalCloseGuard = null
        _doCloseModal()
      }
    })
    return
  }
  _doCloseModal()
}

function _doCloseModal() {
  // Fire any cleanup hook the current modal registered (e.g. CM6 editor teardown)
  // before we blow away the modal DOM. Runs once, then clears.
  const hook = window._qcModalCleanupHook
  window._qcModalCleanupHook = null
  if (typeof hook === 'function') {
    try { hook() } catch (e) { console.warn('[qaclan] modal cleanup hook failed:', e) }
  }

  document.getElementById('modal-backdrop').classList.add('hidden')
  document.getElementById('modal-root').classList.add('hidden')
  document.getElementById('modal-root').innerHTML = ''
  document.getElementById('modal-backdrop').onclick = null
}
```

Then, so a new modal never inherits a stale guard from whatever was open before it, change `showModal`:

```javascript
function showModal(title, bodyHTML, buttons = [], subtitle = '', size = '') {
  const backdrop = document.getElementById('modal-backdrop')
  const root = document.getElementById('modal-root')
```

to:

```javascript
function showModal(title, bodyHTML, buttons = [], subtitle = '', size = '') {
  window._modalCloseGuard = null
  const backdrop = document.getElementById('modal-backdrop')
  const root = document.getElementById('modal-root')
```

- [ ] **Step 3: Implement — remove per-script accordion, add run-level state + functions**

Change:

```javascript
function toggleCapturedRequestSelect(capId, idx, checked) {
  const state = window._capturedReqState && window._capturedReqState[capId]
  if (!state) return
  if (checked) state.selected.add(idx)
  else state.selected.delete(idx)
}

async function saveCapturedRequests(capId, scriptName) {
  const state = window._capturedReqState && window._capturedReqState[capId]
  if (!state || !state.selected.size) { toast('Select at least one request', 'error'); return }
  const selected = state.requests.filter((_, i) => state.selected.has(i))
  const { showRequestReviewModal } = await import('./api/views/request-review-modal.js')
  closeModal()
  showRequestReviewModal(selected, scriptName, selected[0] ? selected[0].url : '')
}
```

to:

```javascript
async function reviewRunCapturedRequests() {
  const requests = window._runCapturedRequests || []
  if (!requests.length) { toast('No captured requests', 'error'); return }
  const { showRequestReviewModal } = await import('./api/views/request-review-modal.js')
  showRequestReviewModal(requests, 'Recorded APIs', requests[0].url, {
    onSaved: () => {
      window._runCapturedRequests = []
      window._modalCloseGuard = null
    },
  })
}
```

- [ ] **Step 4: Implement — aggregate captured requests once per run, add header summary**

Note: the close-confirm guard itself is NOT set here — `showModal()` (Step 2)
resets `window._modalCloseGuard = null` at its own entry, so setting it before
the `showModal(...)` call at the bottom of this function would just have it
wiped out immediately. Step 6 below adds the guard assignment right after
that call instead.

Change:

```javascript
function showRunResults(run, suiteName) {
  const scripts = run.scripts || []
  const skipped = run.skipped || 0
  const statusBadge = run.status === 'PASSED'
    ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
    : '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'
```

to:

```javascript
function showRunResults(run, suiteName) {
  const scripts = run.scripts || []
  const skipped = run.skipped || 0
  const statusBadge = run.status === 'PASSED'
    ? '<span class="badge badge-success"><span class="badge-dot"></span>PASSED</span>'
    : '<span class="badge badge-danger"><span class="badge-dot"></span>FAILED</span>'

  // Aggregate captured requests across the whole run instead of per script
  // (docs/superpowers/specs/2026-07-19-run-api-capture-ux-design.md, Section
  // B) -- one header-level summary, not N per-script accordions.
  const anyFreshCapture = scripts.some(s => Object.prototype.hasOwnProperty.call(s, 'captured_requests'))
  let runCapturedCount = 0
  let capturedSummaryHTML = ''
  window._runCapturedRequests = []
  if (anyFreshCapture) {
    const runCapturedRequests = []
    scripts.forEach(s => {
      if (!s.captured_requests) return
      const parsed = (() => { try { return JSON.parse(s.captured_requests) } catch { return [] } })()
      parsed.forEach(r => runCapturedRequests.push({ ...r, _scriptName: s.name }))
    })
    runCapturedCount = runCapturedRequests.length
    if (runCapturedCount > 0) {
      window._runCapturedRequests = runCapturedRequests
      capturedSummaryHTML = `<div class="run-capture-summary">
        <span>${runCapturedCount} API request${runCapturedCount === 1 ? '' : 's'} captured</span>
        <button class="btn-ghost btn-sm" onclick="reviewRunCapturedRequests()">Save as collection</button>
      </div>`
    }
  } else {
    runCapturedCount = scripts.reduce((sum, s) => sum + (s.captured_requests_count || 0), 0)
    if (runCapturedCount > 0) {
      capturedSummaryHTML = `<div class="run-capture-summary run-capture-summary-historical">
        Captured ${runCapturedCount} request${runCapturedCount === 1 ? '' : 's'} during this run (not saved)
      </div>`
    }
  }
```

- [ ] **Step 5: Implement — insert the summary into the modal body, remove the per-script block**

Change:

```javascript
  const body = `
    <div class="stats-row">
      <div class="stat-card"><div class="stat-value">${run.total || 0}</div><div class="stat-label">Total</div></div>
      <div class="stat-card"><div class="stat-value pass">${run.passed || 0}</div><div class="stat-label">Passed</div></div>
      <div class="stat-card"><div class="stat-value fail">${run.failed || 0}</div><div class="stat-label">Failed</div></div>
      <div class="stat-card"><div class="stat-value">${skipped}</div><div class="stat-label">Skipped</div></div>
    </div>
    ${failureSummary}
    <div class="run-history-scroll">
```

to:

```javascript
  const body = `
    <div class="stats-row">
      <div class="stat-card"><div class="stat-value">${run.total || 0}</div><div class="stat-label">Total</div></div>
      <div class="stat-card"><div class="stat-value pass">${run.passed || 0}</div><div class="stat-label">Passed</div></div>
      <div class="stat-card"><div class="stat-value fail">${run.failed || 0}</div><div class="stat-label">Failed</div></div>
      <div class="stat-card"><div class="stat-value">${skipped}</div><div class="stat-label">Skipped</div></div>
    </div>
    ${capturedSummaryHTML}
    ${failureSummary}
    <div class="run-history-scroll">
```

Then remove the per-script accordion entirely. Change:

```javascript
      // Captured Requests block (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md)
      // s.captured_requests is only ever present on a fresh execute_run() response —
      // get_run() (revisiting a run later) never has it, only the count (Section 0.5).
      let capturedRequestsBlock = ''
      const hasFreshCapture = Object.prototype.hasOwnProperty.call(s, 'captured_requests') && s.captured_requests
      if (hasFreshCapture) {
        const capturedRequests = (() => { try { return JSON.parse(s.captured_requests) } catch { return [] } })()
        if (capturedRequests.length > 0) {
          const capId = 'cap-' + Math.random().toString(36).slice(2, 8)
          window._capturedReqState = window._capturedReqState || {}
          window._capturedReqState[capId] = {
            requests: capturedRequests,
            selected: new Set(capturedRequests.map((_, ri) => ri)),
          }
          const rowsHTML = capturedRequests.map((r, ri) => `
            <div class="cap-req-row">
              <input type="checkbox" class="cap-req-check" checked
                     onchange="toggleCapturedRequestSelect('${capId}', ${ri}, this.checked)">
              <span class="method-badge method-${escHtml(r.method)}">${escHtml(r.method)}</span>
              <span class="cap-req-url" title="${escHtml(r.url)}">${escHtml(r.url)}</span>
              <span class="cap-req-status">${r.response_status != null ? r.response_status : '—'}</span>
              <span class="cap-req-duration">${r.duration_ms != null ? r.duration_ms + 'ms' : '—'}</span>
            </div>`).join('')
          capturedRequestsBlock = `<div class="script-result-diagnostics">
            <div class="script-result-error-toggle" onclick="document.getElementById('${capId}').classList.toggle('collapsed')">
              <span class="script-result-error-label" style="color: var(--accent)">Captured Requests (${capturedRequests.length})</span>
              <span class="script-result-error-chevron">&#9662;</span>
            </div>
            <div id="${capId}" class="script-result-error-body collapsed">
              <div class="cap-req-list">${rowsHTML}</div>
              <div class="cap-req-actions">
                <button class="btn-ghost btn-sm" onclick="saveCapturedRequests('${capId}', ${escHtml(JSON.stringify(s.name))})">Save Selected</button>
              </div>
            </div>
          </div>`
        }
      } else if ((s.captured_requests_count || 0) > 0) {
        // Historical view (e.g. run reopened from run history): the array
        // was never persisted, so there's nothing to pick from — just say so.
        capturedRequestsBlock = `<div class="script-result-diagnostics">
          <div class="cap-req-historical">Captured ${s.captured_requests_count} request${s.captured_requests_count === 1 ? '' : 's'} during this run (not saved)</div>
        </div>`
      }

      // Error block. Prefer the structured error_detail (classified, plain
```

to:

```javascript
      // Error block. Prefer the structured error_detail (classified, plain
```

Then remove its render slot. Change:

```javascript
        ${errorBlock}
        ${diagnosticsBlock}
        ${capturedRequestsBlock}
      </div>`
```

to:

```javascript
        ${errorBlock}
        ${diagnosticsBlock}
      </div>`
```

- [ ] **Step 6: Implement — set the close-confirm guard after `showModal(...)` runs**

`showModal()` (Step 2) unconditionally resets `window._modalCloseGuard = null`
the moment it's called, so the guard must be assigned AFTER that call
returns, not before — otherwise it's wiped out immediately. Change the very
end of `showRunResults`:

```javascript
  const reportBtn = run.id
    ? [{ label: 'Download report', cls: 'btn-ghost', keepOpen: true, action: () => {
        downloadReport(run.id)
      } }]
    : []
  showModal('Execution History', body, [
    ...reportBtn,
    { label: 'Close', cls: 'btn-ghost', action: () => { closeModal(); renderSuitesPage() } }
  ], suiteName + ' · ' + statusBadge, 'report')
}
```

to:

```javascript
  const reportBtn = run.id
    ? [{ label: 'Download report', cls: 'btn-ghost', keepOpen: true, action: () => {
        downloadReport(run.id)
      } }]
    : []
  showModal('Execution History', body, [
    ...reportBtn,
    { label: 'Close', cls: 'btn-ghost', action: () => { closeModal(); renderSuitesPage() } }
  ], suiteName + ' · ' + statusBadge, 'report')

  // Assigned after showModal() (which resets any prior guard to null) so it
  // isn't immediately wiped out. Harmless no-op when there's nothing unsaved
  // -- always set, not just when captures are present.
  window._modalCloseGuard = async () => {
    if (!window._runCapturedRequests || !window._runCapturedRequests.length) return true
    return !!(await window._confirmDialog(
      'Unsaved captured API requests',
      `You have ${window._runCapturedRequests.length} unsaved captured API request${window._runCapturedRequests.length === 1 ? '' : 's'}. Close anyway?`,
      'Close anyway', 'btn btn-sm btn-danger',
    ))
  }
}
```

- [ ] **Step 7: Syntax check**

Run: `node --check web/static/app.js`
Expected: no output (success)

- [ ] **Step 8: Manual verification (requires a browser)**

Start the server: `python3 qaclan.py serve --port 7823`. In the UI:

1. Create or open a suite with at least 2 web-automation scripts that hit real endpoints (at least one `fetch`/XHR call each, ideally against pages that also load static assets/images so Task 6's filtering is visible in practice).
2. Run the suite with "Capture API Requests" checked. Confirm the run-results modal shows one header line (e.g. "N API requests captured · Save as collection") near the stats row, and no per-script "Captured Requests" accordions anywhere in the script cards.
3. Click "Save as collection". Confirm the review panel shows requests grouped under each script's name (group headers), all checked by default. Save with a new collection name; confirm exactly one collection is created containing every selected request from both scripts (no dedup — same-endpoint hits from both scripts both appear if applicable).
4. Run the suite again with capture on; this time in the review panel pick an existing collection (the one just created) from the new dropdown and save; confirm the request count on that collection increases instead of a second collection being created.
5. Run the suite again with capture on; this time close the run-results modal (via the X, the backdrop, or the footer "Close" button) without clicking "Save as collection" first. Confirm a confirm dialog appears ("Unsaved captured API requests... Close anyway?") and the modal stays open until you answer; confirm "Close anyway" then does close it.
6. Run the suite again with capture on, click "Save as collection", save successfully, then close the modal. Confirm no confirm dialog appears (state was cleared on save).
7. Reopen an older run from the Runs page (`viewRunModal`) that has `captured_requests_count > 0` from before this change (or any run recorded with capture on). Confirm the header shows the static "Captured N requests during this run (not saved)" text, with no button and no close-confirm (matches existing historical-view behavior).

If no GUI is available in this session, skip this step and note it as unverified beyond the syntax check above.

- [ ] **Step 9: Commit**

```bash
git add web/static/app.js
git commit -m "feat(runs): run-level captured-request summary, save, and close-confirm"
```

---

## Post-implementation checklist

- [ ] Re-run `verify_task1.py` through `verify_task7.py` all at once, confirm all print `PASS`.
- [ ] `python3 -m py_compile` every modified Python file with zero output:
  `python3 -m py_compile cli/script_strategies/_shared.py cli/script_strategies/python_strategy.py cli/script_strategies/javascript_strategy.py cli/script_strategies/javascript_test_strategy.py cli/script_strategies/typescript_test_strategy.py cli/api_discovery/captured_request_parser.py web/api/routes/discovery.py`
- [ ] `node --check` both modified JS files with zero output:
  `node --check web/static/app.js` and (module syntax permitting) `web/static/api/views/request-review-modal.js`.
- [ ] Confirm `grep -rn "saveCapturedRequests\|toggleCapturedRequestSelect\|_capturedReqState" web/` returns nothing (dead code fully removed, not just unreferenced).
- [ ] Confirm `grep -rn "_CAPTURE_SKIP_TYPES" cli/script_strategies/` returns nothing across all 4 harness files.
- [ ] If a GUI environment was unavailable during implementation, re-run Task 5 Step 5, Task 8 Step 6, and Task 9 Step 7 manually before considering this plan fully verified end-to-end.
