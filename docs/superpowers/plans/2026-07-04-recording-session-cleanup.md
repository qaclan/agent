# Recording Session Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `/api/discover/record/*` from leaking `qaclan_record_*` temp directories (HAR capture + harness script + the multipart-body sidecar) whenever a recording session is abandoned without an explicit `/record/stop` call.

**Architecture:** Add a `created_at` timestamp to each entry in `web/api/routes/discovery.py`'s in-memory `_recording_sessions` dict. A lazy, no-thread-by-default reaper (`_reap_stale_sessions()`) runs at the top of `record_start` and `record_status` — the two endpoints already hit on every discover-record page visit — and pops any session older than a 2-hour TTL out of the dict under `_sessions_lock` (pure dict operations, no I/O, so this scan never adds meaningful latency even with many stale entries). The slow part — killing the recorder process and `shutil.rmtree`-ing its directories — is handed to one throwaway `threading.Thread` per reap call, so the request that happened to trigger the reap returns immediately instead of blocking on a potentially large batch of stale-session cleanup. `record_stop`'s existing terminate+parse+cleanup logic is refactored into two shared helpers (`_terminate_recorder`, `_cleanup_session_dirs`) so both the explicit-stop path and the reaper path use identical teardown code — no duplicated process-killing or rmtree logic to drift out of sync.

**Tech Stack:** Flask (Python 3), Python stdlib only (`threading`, `time`, `shutil`, `os`, `subprocess`) — no new dependencies.

## Global Constraints

- This repo has **no automated test framework** (confirmed in `CLAUDE.md`: "There are no automated tests or linting configured"). Do not add one. Verify each unit with a throwaway script run via `python3 /tmp/<name>.py`, per task, as specified below.
- `_sessions_lock` (a `threading.Lock`, already defined at `web/api/routes/discovery.py:16`) must guard every read/pop of `_recording_sessions` — this is what makes "only one thread ever tears down a given session" a real guarantee instead of a race. Never touch the dict outside the lock.
- The reap's fast path (scan + pop) must stay lock-held and I/O-free. All process termination and filesystem removal must happen only after the lock is released, so the reap never turns into "hold the session lock for the duration of an rmtree."
- TTL default: `2 * 60 * 60` seconds (2 hours) — long enough that a legitimate in-progress recording is never mistaken for abandoned, named `_SESSION_TTL_SECONDS` so it's a single obvious place to tune.
- Preserve `record_stop`'s existing behavior exactly: proc terminated/flushed **before** the HAR file is read (so the capture is complete), directories removed **after** the HAR has been parsed (so cleanup never races the read). The refactor must not reorder this.

---

### Task 1: Extract shared teardown helpers, refactor `record_stop` to use them

**Files:**
- Modify: `web/api/routes/discovery.py:293-362` (`record_stop`)

**Interfaces:**
- Produces: `_terminate_recorder(session: dict) -> None` — stops the recorder browser process referenced by `session["proc"]` if still running (SIGTERM on Unix, stop-file sentinel on Windows, SIGKILL fallback on timeout), safe to call on an already-dead process. Consumed by: Task 2.
- Produces: `_cleanup_session_dirs(session: dict) -> None` — removes `session["capture_dir"]` and `session["harness_dir"]` via `shutil.rmtree`, swallowing all exceptions (mirrors current `record_stop` finally-block behavior). Consumed by: Task 2.

- [ ] **Step 1: Write the failing verification script**

Save to `/tmp/verify_teardown_helpers.py`:

```python
import sys, os, shutil, subprocess, tempfile, time
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from web.api.routes import discovery

# --- _terminate_recorder: kills a real subprocess ---
proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
session = {"proc": proc, "stop_file": ""}
discovery._terminate_recorder(session)
time.sleep(0.2)
assert proc.poll() is not None, "process should be terminated"
print("PASS: _terminate_recorder kills a live process")

# --- _terminate_recorder: no-op on a session with no proc ---
discovery._terminate_recorder({"proc": None, "stop_file": ""})
print("PASS: _terminate_recorder no-ops when proc is None")

# --- _cleanup_session_dirs: removes both dirs, ignores missing ones ---
d1 = tempfile.mkdtemp(prefix="qaclan_record_test_")
d2 = tempfile.mkdtemp(prefix="qaclan_record_test_")
with open(os.path.join(d1, "capture.har"), "w") as f:
    f.write("{}")
session = {"capture_dir": d1, "harness_dir": d2}
discovery._cleanup_session_dirs(session)
assert not os.path.exists(d1), "capture_dir should be removed"
assert not os.path.exists(d2), "harness_dir should be removed"
print("PASS: _cleanup_session_dirs removes both directories")

# --- _cleanup_session_dirs: tolerates an already-missing dir ---
discovery._cleanup_session_dirs({"capture_dir": "/tmp/does-not-exist-qaclan", "harness_dir": None})
print("PASS: _cleanup_session_dirs tolerates missing/None dirs")

print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 /tmp/verify_teardown_helpers.py`
Expected: `AttributeError: module 'web.api.routes.discovery' has no attribute '_terminate_recorder'`

- [ ] **Step 3: Implement the helpers and refactor `record_stop`**

In `web/api/routes/discovery.py`, add these two module-level functions directly above the `@bp.route("/api/discover/record/start", ...)` line (currently line 247):

```python
def _terminate_recorder(session: dict) -> None:
    """Stop the recorder browser process if still running. Safe to call on
    an already-dead proc. Must run before reading its HAR file so the
    capture is fully flushed (ctx.close() in the harness writes the HAR)."""
    import os, subprocess, sys
    proc = session.get("proc")
    stop_file = session.get("stop_file", "")
    if not proc:
        return
    try:
        if sys.platform == "win32" and stop_file:
            try:
                open(stop_file, "w").close()
            except OSError:
                proc.terminate()  # sentinel creation failed — fall back to SIGTERM
        else:
            proc.terminate()
        proc.wait(timeout=8 if sys.platform == "win32" else 5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()  # reap zombie — must follow kill()
    finally:
        if stop_file and os.path.exists(stop_file):
            try:
                os.unlink(stop_file)
            except OSError:
                pass


def _cleanup_session_dirs(session: dict) -> None:
    """Remove a session's capture/harness temp directories, if present."""
    import os, shutil
    for d in (session.get("capture_dir"), session.get("harness_dir")):
        if d and os.path.exists(d):
            try:
                shutil.rmtree(d)
            except Exception:
                pass
```

Then replace the body of `record_stop` (lines 293-362) with:

```python
@bp.route("/api/discover/record/stop", methods=["POST"])
def record_stop():
    """Stop recording session, parse captured HAR, return request list."""
    session = None
    try:
        data = request.get_json(force=True) or {}
        session_id = data.get("session_id", "")
        with _sessions_lock:
            session = _recording_sessions.pop(session_id, None)

        if not session:
            return jsonify({"ok": False, "error": f"Session {session_id} not found"}), 404

        _terminate_recorder(session)

        har_file = session.get("har_file", "")
        requests_list = []
        if har_file and os.path.exists(har_file):
            try:
                with open(har_file) as hf:
                    har_json = json.load(hf)
                from cli.api_discovery.har_parser import parse_har, merge_multipart_postdata
                sidecar_file = har_file + ".multipart.json"
                if os.path.exists(sidecar_file):
                    try:
                        with open(sidecar_file) as sf:
                            merge_multipart_postdata(har_json, json.load(sf))
                    except Exception as e:
                        logger.warning("record_stop: multipart sidecar merge failed: %s", e)
                requests_list = parse_har(har_json)
            except Exception as e:
                logger.warning("record_stop: HAR parse failed (partial capture?): %s", e)

        return jsonify({"ok": True, "requests": requests_list, "count": len(requests_list)})

    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("record_stop")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if session:
            _cleanup_session_dirs(session)
```

Add `import os` to the top-level imports of `discovery.py` (currently only `json, logging, threading, uuid` at lines 2-5) since `_terminate_recorder`/`_cleanup_session_dirs` are module-level and `record_stop` no longer does its own local `import os, shutil, subprocess, sys` — those become unnecessary in `record_stop` itself now that the helpers own their own local imports.

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/verify_teardown_helpers.py`
Expected: `ALL PASS`

- [ ] **Step 5: Manually re-verify `record_stop`'s behavior is unchanged**

Run: `python3 -c "import ast; ast.parse(open('/mnt/ext-drive/qaclan/agent/web/api/routes/discovery.py').read())"` — expect no output (valid syntax). Then read through the new `record_stop` body and confirm the ordering is preserved: pop under lock → terminate proc → read/parse HAR → cleanup dirs in `finally`. This ordering must not change — HAR reads happen while dirs still exist.

- [ ] **Step 6: Commit**

```bash
git add web/api/routes/discovery.py
git commit -m "refactor: extract recorder teardown into shared helpers"
```

---

### Task 2: Add TTL-based reap for abandoned recording sessions

**Files:**
- Modify: `web/api/routes/discovery.py` (module-level constants, `record_start`, `record_status`)

**Interfaces:**
- Consumes: `_terminate_recorder`, `_cleanup_session_dirs` from Task 1.
- Produces: `_SESSION_TTL_SECONDS: int`, `_reap_stale_sessions() -> None`. Not consumed elsewhere in this plan, but this is the fix's actual deliverable.

- [ ] **Step 1: Write the failing verification script**

Save to `/tmp/verify_reaper.py`:

```python
import sys, os, tempfile, time
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from web.api.routes import discovery

# Fresh state for this script's run
discovery._recording_sessions.clear()

def make_session(age_seconds):
    d1 = tempfile.mkdtemp(prefix="qaclan_record_test_")
    d2 = tempfile.mkdtemp(prefix="qaclan_record_test_")
    return {
        "status": "recording",
        "proc": None,
        "stop_file": "",
        "harness_dir": d2,
        "capture_dir": d1,
        "har_file": os.path.join(d1, "capture.har"),
        "created_at": time.time() - age_seconds,
    }

fresh_id = "fresh-session"
stale_id = "stale-session"
fresh = make_session(60)                                   # 1 minute old — must survive
stale = make_session(discovery._SESSION_TTL_SECONDS + 60)   # just past TTL — must be reaped

discovery._recording_sessions[fresh_id] = fresh
discovery._recording_sessions[stale_id] = stale

discovery._reap_stale_sessions()

# Pop is synchronous (fast path) — stale session must be gone from the dict immediately
assert fresh_id in discovery._recording_sessions, "fresh session must not be reaped"
assert stale_id not in discovery._recording_sessions, "stale session must be popped immediately"
print("PASS: stale session popped from dict synchronously, fresh session kept")

# Teardown (rmtree) happens on a spawned thread — poll briefly for it to finish
stale_dirs = (stale["capture_dir"], stale["harness_dir"])
deadline = time.time() + 3
while time.time() < deadline and any(os.path.exists(d) for d in stale_dirs):
    time.sleep(0.05)
assert not any(os.path.exists(d) for d in stale_dirs), "stale session's dirs should be removed"
print("PASS: stale session's directories removed by background teardown")

# Fresh session's dirs must be untouched
assert os.path.exists(fresh["capture_dir"]), "fresh session's capture_dir must survive"
assert os.path.exists(fresh["harness_dir"]), "fresh session's harness_dir must survive"
print("PASS: fresh session's directories untouched")

# Calling reap with nothing stale must be a cheap no-op (no thread spawned, no error)
discovery._reap_stale_sessions()
assert fresh_id in discovery._recording_sessions
print("PASS: reap with nothing stale is a no-op")

# Cleanup
import shutil
shutil.rmtree(fresh["capture_dir"], ignore_errors=True)
shutil.rmtree(fresh["harness_dir"], ignore_errors=True)
discovery._recording_sessions.clear()

print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 /tmp/verify_reaper.py`
Expected: `AttributeError: module 'web.api.routes.discovery' has no attribute '_SESSION_TTL_SECONDS'`

- [ ] **Step 3: Implement the reaper**

In `web/api/routes/discovery.py`, add `import time` to the top-level imports (alongside the existing `json, logging, threading, uuid`). Add this constant right after `_sessions_lock = threading.Lock()` (currently line 16):

```python
_SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours — long enough a legit in-progress recording is never mistaken for abandoned
```

Add this function right after the `_terminate_recorder`/`_cleanup_session_dirs` helpers from Task 1 (still above `record_start`):

```python
def _reap_stale_sessions() -> None:
    """Pop any session older than _SESSION_TTL_SECONDS out of _recording_sessions.
    The scan+pop is synchronous and lock-protected but does no I/O, so it never
    adds meaningful latency to the record_start/record_status call that triggers
    it — even with many stale entries. The slow part (killing the recorder
    process, removing its directories) runs on a throwaway thread so the
    triggering request is never blocked on it. Exists because a client that
    abandons a recording (closed tab, dropped connection) without ever calling
    /record/stop would otherwise leak its capture_dir/harness_dir forever —
    /record/status is deliberately read-only and never tears sessions down."""
    now = time.time()
    stale = []
    with _sessions_lock:
        for session_id in list(_recording_sessions.keys()):
            session = _recording_sessions[session_id]
            if now - session.get("created_at", now) > _SESSION_TTL_SECONDS:
                stale.append(_recording_sessions.pop(session_id))

    if not stale:
        return

    logger.info("_reap_stale_sessions: reaping %d abandoned recording session(s)", len(stale))

    def _teardown_batch():
        for session in stale:
            _terminate_recorder(session)
            _cleanup_session_dirs(session)

    threading.Thread(target=_teardown_batch, daemon=True).start()
```

Then wire it in. In `record_start`, add the call as the very first line inside the `try:` block (before `session_id = str(uuid.uuid4())`, currently line 251):

```python
    try:
        _reap_stale_sessions()
        session_id = str(uuid.uuid4())
```

And add `"created_at": time.time(),` to the session dict built in `record_start` (currently lines 274-281):

```python
        with _sessions_lock:
            _recording_sessions[session_id] = {
                "status": "recording",
                "proc": proc,
                "stop_file": stop_file,
                "harness_dir": harness_dir,
                "capture_dir": capture_dir,
                "har_file": har_file,
                "created_at": time.time(),
            }
```

In `record_status`, add the call as the first line of the function body (before `session_id = request.args.get(...)`, currently line 370):

```python
def record_status():
    """Poll recording session status. Read-only — does not tear down the
    session even once the browser process has exited, since /record/stop
    still needs capture_dir/har_file intact to parse the HAR afterward.
    (Stale/abandoned sessions past the TTL are reaped as a side effect of
    this call, via _reap_stale_sessions — that's a different case from a
    live session's process having exited.)"""
    _reap_stale_sessions()
    session_id = request.args.get("session_id", "")
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/verify_reaper.py`
Expected: `ALL PASS`

- [ ] **Step 5: Confirm the whole module still imports and parses cleanly**

Run: `python3 -c "import web.api.routes.discovery; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add web/api/routes/discovery.py
git commit -m "fix: reap abandoned recording sessions to stop temp-dir leaks"
```

---

### Task 3: Prevent an untracked harness-dir leak in `_spawn_harness`

**Files:**
- Modify: `web/api/services/discovery_service.py` (`_spawn_harness`, non-blocking branch)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this is a robustness fix to an existing private method, no interface change.

**Context:** `_spawn_harness` (non-blocking branch, used by `launch_recorder`) creates a temp dir via `tempfile.mkdtemp(prefix="qaclan_record_")`, writes `record.py` into it, then calls `subprocess.Popen(...)`. If `Popen` itself raises (e.g. the venv python path is bad), the temp dir was already created but is never returned to any caller and never cleaned up — a permanent untracked leak, distinct from the session-level leak Task 2 fixes.

- [ ] **Step 1: Write the failing verification script**

Save to `/tmp/verify_spawn_harness_cleanup.py`:

```python
import sys, os, glob
sys.path.insert(0, "/mnt/ext-drive/qaclan/agent")
from web.api.services.discovery_service import DiscoveryService
from unittest import mock

before = set(glob.glob(os.path.join("/tmp", "qaclan_record_*"))) | \
         set(glob.glob(os.path.join("/var/tmp", "qaclan_record_*")))

svc = DiscoveryService()
with mock.patch("subprocess.Popen", side_effect=OSError("boom")):
    try:
        svc._spawn_harness("http://example.com", "/tmp/fake.har", "print('hi')\n", blocking=False)
        raise AssertionError("expected OSError to propagate")
    except OSError:
        pass

after = set(glob.glob(os.path.join("/tmp", "qaclan_record_*"))) | \
        set(glob.glob(os.path.join("/var/tmp", "qaclan_record_*")))

leaked = after - before
assert not leaked, f"leaked temp dirs after Popen failure: {leaked}"
print("ALL PASS")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 /tmp/verify_spawn_harness_cleanup.py`
Expected: `AssertionError: leaked temp dirs after Popen failure: {...}` (a `qaclan_record_*` dir left behind under `/tmp`)

- [ ] **Step 3: Implement the fix**

In `web/api/services/discovery_service.py`, find the non-blocking branch of `_spawn_harness` (the `else:` branch that currently reads):

```python
        else:
            log_path = os.path.join(d, "record.log")
            with open(log_path, "w") as lf:
                proc = subprocess.Popen(cmd, cwd=d, env=env, stdout=lf, stderr=lf)
            logger.info("record harness launched pid=%d log=%s", proc.pid, log_path)
            return proc, d
```

Replace it with:

```python
        else:
            log_path = os.path.join(d, "record.log")
            try:
                with open(log_path, "w") as lf:
                    proc = subprocess.Popen(cmd, cwd=d, env=env, stdout=lf, stderr=lf)
            except Exception:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
                raise
            logger.info("record harness launched pid=%d log=%s", proc.pid, log_path)
            return proc, d
```

- [ ] **Step 4: Run the verification script again to confirm it passes**

Run: `python3 /tmp/verify_spawn_harness_cleanup.py`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add web/api/services/discovery_service.py
git commit -m "fix: clean up harness temp dir if launching the recorder process fails"
```

---

## Self-Review

**1. Spec coverage:** The design-spec addendum (already added to `docs/superpowers/specs/2026-06-19-api-testing-design.md`, Section 5 / Path 1) makes two claims: (a) multipart CDP-capture sidecar exists — already shipped, documented, not part of this plan's tasks; (b) TTL-based reap with lazy trigger + spawned-thread teardown reclaims abandoned sessions — covered by Task 2, built on Task 1's shared helpers. Task 3 covers the separate untracked-harness-dir gap surfaced during the audit. All three findings from the temp-file audit (session-level leak, harness-dir-on-Popen-failure leak) have a task; the fourth item from the audit (CLI `api_record`'s `TemporaryDirectory()` and the Unix `stop_file`) were already confirmed safe and need no fix.

**2. Placeholder scan:** No TBD/TODO/"handle appropriately" language; every step has complete, runnable code.

**3. Type consistency:** `_terminate_recorder(session: dict)` and `_cleanup_session_dirs(session: dict)` signatures match between their Task 1 definition and Task 2's `_teardown_batch` usage. `_reap_stale_sessions()` takes no arguments and returns `None` consistently wherever referenced. `_SESSION_TTL_SECONDS` is defined once (Task 2, Step 3) and only read (never redefined) elsewhere, including in Task 2's own verification script.
