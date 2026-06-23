# 13 - Step-by-Step Replay

Deep-dive on feature #13 from [feature-ideas.md](../feature-ideas.md). Covers the WebSocket pause protocol, state inspection during pause, and how this relates to the trace viewer (feature #11).

---

## The problem

A test fails at step 12. To understand why:

**Current QAClan approach:**
1. Look at screenshot. Guess.
2. Add `print(await page.content())` to the script.
3. Re-run. Read console log.
4. Repeat until the cause is clear.

This loop takes 5–20 minutes per debugging session.

**PWDEBUG=1 approach (Playwright):**
1. Set env var. Re-run. Playwright Inspector opens.
2. Step through in a separate desktop window.
3. Cannot inspect QAClan `state.json`. Cannot use QAClan UI.
4. Works — but disconnected from QAClan's run history and context.

Step-by-step replay brings Playwright Inspector functionality into the QAClan web UI, integrated with run context and state.json.

## Example

```
User opens script "checkout-flow" detail page.
Clicks "Debug Run" → "Paused at step 1 / 20"

Web UI shows:
  [Step 1 of 20]  goto /cart  ← currently executing
  
  State panel:      state.json = {}  (empty, first script)
  DOM panel:        [live page snapshot]
  Network panel:    [pending requests]
  
  [► Resume] [→ Step] [✕ Abort]

User clicks Step → executes step 1 → pauses at step 2
...
At step 9:
  UI shows: "fill #qty" — DOM panel shows #qty input is not in viewport
  State: { "cart_item_id": "abc123" }
  User sees the issue: page has lazy-loaded content, qty input below fold
  Clicks Abort. Fixes the script to scroll before fill.
```

## Impact

| Dimension | Effect |
|---|---|
| Debug cycle time | 20-minute guess-and-rerun loop → 3-minute step-through. High. |
| State visibility | See state.json mid-run. Crucial for multi-script sessions where shared state causes failures. |
| Onboarding | New users can step through a script to understand what it does, not just read code. |
| Error accuracy | Users identify the exact step that causes side effects instead of guessing from step failure alone. |

Overall: **high impact** for power users who actively debug failing tests. Lower impact for teams that rely on trace viewer (feature #11) post-hoc.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Playwright Inspector** (`PWDEBUG=1`) | Opens desktop GUI with step-through, DOM inspector, locator test. | Separate window. Not integrated with QAClan UI, run history, or state.json. Requires terminal env var. |
| **Cypress Test Runner** | Time-travel debugger: step backward through snapshots of executed test. | Snapshots of completed steps, not live pause. Cannot inspect mid-run state. Cypress-only. |
| **`page.pause()`** | Playwright API to programmatically pause. Opens Inspector on call. | Same limitations as PWDEBUG. No QAClan integration. |

**Our diff:** Pause/resume lives in the QAClan web UI. state.json is visible during pause (critical for shared-state multi-script runs). No separate window. Debug session results appear in run history. Integrates with other QAClan features (environment selector, script editor side by side).

## Architecture — WebSocket pause protocol

The script subprocess and QAClan web server communicate via a WebSocket (or Unix socket).

### Pause mechanism

1. Runner (in [web/routes/runs.py](../../web/routes/runs.py)) injects an environment variable: `QACLAN_DEBUG_SOCKET=<path>`.
2. The script harness template, before each step, connects to the socket and sends a pause event:
   ```json
   {"event": "step_start", "index": 5, "action": "click", "locator": "#submit-btn"}
   ```
3. Harness waits for `{"action": "resume"}` or `{"action": "step"}` or `{"action": "abort"}`.
4. Web UI sends the response to the socket.
5. Harness proceeds or aborts.

### Debug modes

| Mode | Behavior |
|---|---|
| `step` | Pause before every action. User advances manually. |
| `break_on_fail` | Run normally. Pause only when a step fails. Resume or abort. |

### WebSocket vs Unix socket

Unix socket: simpler for local-only communication. No port management. But Windows uses named pipes differently. Use a TCP localhost socket (`127.0.0.1:0` — OS picks a free port) for cross-platform consistency.

## State inspection during pause

During pause, expose three panels in the debug UI:

**1. state.json panel**
```python
# In harness: on pause event, read state.json and include in the pause message
state_path = os.environ.get("QACLAN_STATE_PATH", "")
state_data = json.load(open(state_path)) if os.path.exists(state_path) else {}
pause_event["state"] = state_data
```

**2. DOM snapshot panel**
```python
# In harness: capture page HTML on pause
dom_snapshot = await page.content()
pause_event["dom_b64"] = base64.b64encode(dom_snapshot.encode()).decode()
```

**3. Network panel**
```python
# In harness: accumulate request/response events via page.on("request"/"response")
# Send accumulated list in pause event
pause_event["network"] = network_log
```

Web UI renders these three panels alongside the step control buttons.

## Harness changes per strategy

Each strategy in [cli/script_strategies/](../../cli/script_strategies/) has its own harness template. Debug injection must be added to each.

Python example addition:
```python
import asyncio, json, os, socket

_debug_socket = os.environ.get("QACLAN_DEBUG_SOCKET")

async def _pause(index, action, locator):
    if not _debug_socket:
        return
    host, port = _debug_socket.split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    payload = json.dumps({"event": "step_start", "index": index, "action": action, "locator": locator})
    writer.write(payload.encode() + b"\n")
    response = json.loads(await reader.readline())
    writer.close()
    if response.get("action") == "abort":
        raise KeyboardInterrupt("Debug abort")

# Before each action in harness:
await _pause(5, "click", "#submit-btn")
await page.locator("#submit-btn").click()
```

## Schema changes — none for v1

Debug sessions are transient. Results (if user chooses to save them) are stored as normal script_runs. No new tables needed.

Optional Phase 2: store "debug session replay" as a special run type with pause timestamps recorded.

## Implementation path

### Phase 1 — pause protocol + basic UI

- Add `QACLAN_DEBUG_SOCKET` to runner env when debug mode requested.
- Python harness: add `_pause()` function, inject before each action.
- Web UI: "Debug Run" button on script detail page. Opens debug panel with Step/Resume/Abort controls.
- Runner starts a TCP listener socket, pipes events to UI via SSE or WebSocket.

### Phase 2 — state + DOM panels

- Harness sends state.json and DOM snapshot in pause events.
- UI renders state panel (JSON tree) and DOM panel (HTML preview or simplified element list).

### Phase 3 — network panel + break-on-fail mode

- Harness accumulates network events, sends them in pause payload.
- UI renders network panel (method, URL, status, duration).
- Add "Break on fail" mode toggle: run at full speed, pause only on error.

### Phase 4 — multi-language debug support

- Phase 1 only covers Python harness. Phase 4 adds JS/TS harness debug injection.
- Same TCP socket protocol — server side is language-agnostic.

## Overlap with trace viewer (feature #11)

| Scenario | Best tool |
|---|---|
| Post-hoc: "it failed, I want to see what happened" | Feature #11 Trace Viewer |
| Live: "I want to understand this test step by step" | Feature #13 Step-by-Step Replay |
| Authoring: "write the test interactively" | Feature #2 Visual Element Picker |

The tools are complementary. Trace viewer is passive/retrospective. Replay is active/live. Both are valuable. Replay has a higher implementation cost (socket, harness changes, live UI) but also delivers a more interactive experience.

## Open questions

- **Multiple debug sessions.** Two users debugging two scripts simultaneously. Each needs its own socket. Use a unique port per debug session (OS-assigned). Store `debug_port` in the session context.
- **Timeout during pause.** Script subprocess pauses indefinitely waiting for resume. If user closes the browser tab, the subprocess hangs. Add a timeout: "No response in 5 minutes — aborting debug session."
- **Harness injection timing.** Not every action in the harness is explicitly listed — some are in loops or wrapped calls. The pause must wrap at the right abstraction level. Start with explicit top-level action calls; loops and helpers in Phase 2.

## Next concrete step

Build the TCP socket pause protocol as a standalone Python script (no QAClan wiring) and verify it works: subprocess pauses, web server receives event, sends resume, subprocess continues. Then wire into Python harness template and add the debug UI button.
