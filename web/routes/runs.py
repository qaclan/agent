import json
import os
import re
import sys
import shutil
import time
import logging
import traceback
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from pathlib import Path
from cli.db import get_conn, generate_id
from cli.config import get_active_project_id

logger = logging.getLogger("qaclan.runs")

bp = Blueprint('runs', __name__)


def _require_active_project():
    return get_active_project_id()


def _extract_test_actions(script_path):
    """Extract test action lines from a Playwright codegen script."""
    with open(script_path, "r") as f:
        lines = f.readlines()

    actions = []
    capturing = False
    base_indent = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("page = context.new_page()"):
            capturing = True
            continue

        if capturing and stripped.startswith("page.close()"):
            break

        if capturing:
            if not stripped or stripped.startswith("# ---"):
                continue
            if "_qc_state" in stripped or "context.storage_state" in stripped:
                continue
            if base_indent is None:
                base_indent = len(line) - len(line.lstrip())
            current_indent = len(line) - len(line.lstrip())
            relative_indent = max(0, current_indent - base_indent)
            actions.append(" " * relative_indent + stripped)

    return "\n".join(actions)


def _substitute_template_vars(source, var_keys, env_vars, fallback_key, fallback_value):
    """Resolve {{KEY}} placeholders in a script body.

    For each key in var_keys:
      - If present in env_vars, substitute with the env value
      - Else if it matches the script's fallback_key, substitute with fallback_value
        and log a warning
      - Else raise ValueError (caller fails the script)
    """
    warnings = []
    for key in var_keys:
        placeholder = "{{" + key + "}}"
        if key in env_vars:
            value = env_vars[key]
        elif key == fallback_key and fallback_value:
            value = fallback_value
            warnings.append(f"Variable '{key}' not in env, using recorded fallback")
        else:
            raise ValueError(
                f"Script requires variable '{key}' but it's not in the selected environment "
                f"and no fallback is available."
            )
        source = source.replace(placeholder, value)
    return source, warnings


def _patch_actions(actions_src):
    """Apply runtime patches: networkidle waits."""
    actions_src = re.sub(
        r'(page\.goto\([^)]+\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    actions_src = re.sub(
        r'(\.click\(\))',
        r'\1\npage.wait_for_load_state("networkidle")',
        actions_src,
    )
    return actions_src


@bp.route('/api/runs', methods=['GET'])
def list_runs():
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        suite_id = request.args.get("suite_id")

        if suite_id:
            rows = conn.execute(
                "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.status, "
                "sr.started_at, sr.finished_at, sr.total, sr.passed, sr.failed, sr.skipped "
                "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
                "WHERE sr.project_id = ? AND sr.suite_id = ? "
                "ORDER BY sr.started_at DESC",
                (project_id, suite_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.status, "
                "sr.started_at, sr.finished_at, sr.total, sr.passed, sr.failed, sr.skipped "
                "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
                "WHERE sr.project_id = ? "
                "ORDER BY sr.started_at DESC",
                (project_id,),
            ).fetchall()

        runs = [dict(r) for r in rows]
        return jsonify({"ok": True, "runs": runs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/runs/<run_id>', methods=['GET'])
def get_run(run_id):
    try:
        project_id = _require_active_project()
        if not project_id:
            return jsonify({"ok": False, "error": "No active project"}), 400

        conn = get_conn()
        row = conn.execute(
            "SELECT sr.id, sr.suite_id, su.name AS suite_name, sr.environment_id, "
            "sr.channel, sr.status, sr.total, sr.passed, sr.failed, sr.skipped, "
            "sr.started_at, sr.finished_at, sr.browser, sr.resolution, sr.headless "
            "FROM suite_runs sr JOIN suites su ON sr.suite_id = su.id "
            "WHERE sr.id = ? AND sr.project_id = ?",
            (run_id, project_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": f"Run {run_id} not found"}), 404

        run = dict(row)

        # Load script results
        script_rows = conn.execute(
            "SELECT scr.script_id, s.name, scr.status, scr.duration_ms, "
            "scr.console_errors, scr.network_failures, scr.error_message, "
            "scr.console_log, scr.network_log, scr.screenshot_path, "
            "scr.order_index, scr.started_at, scr.finished_at "
            "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
            "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
            (run_id,),
        ).fetchall()
        run["scripts"] = [dict(sr) for sr in script_rows]

        return jsonify({"ok": True, "run": run})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route('/api/runs', methods=['POST'])
def execute_run():
    try:
        project_id = _require_active_project()
        if not project_id:
            logger.warning("execute_run: no active project")
            return jsonify({"ok": False, "error": "No active project"}), 400

        data = request.get_json(force=True)
        suite_id = data.get("suite_id", "").strip()
        env_name = data.get("env_name")
        stop_on_fail = data.get("stop_on_fail", False)
        browser_type = data.get("browser", "chromium")
        resolution = data.get("resolution") or None
        headless = data.get("headless", False)
        logger.info("execute_run: suite_id=%s env_name=%s stop_on_fail=%s browser=%s resolution=%s headless=%s",
                     suite_id, env_name, stop_on_fail, browser_type, resolution, headless)

        if not suite_id:
            return jsonify({"ok": False, "error": "suite_id is required"}), 400

        conn = get_conn()

        # 1. Load suite and validate
        suite = conn.execute(
            "SELECT * FROM suites WHERE id = ? AND project_id = ?",
            (suite_id, project_id),
        ).fetchone()
        if not suite:
            logger.error("execute_run: suite %s not found in project %s", suite_id, project_id)
            return jsonify({"ok": False, "error": f"Suite {suite_id} not found"}), 404
        if suite["channel"] != "web":
            return jsonify({
                "ok": False,
                "error": f"Suite {suite_id} is a {suite['channel'].upper()} suite, not a WEB suite"
            }), 400

        # 2. Load suite items with scripts (ordered)
        items = conn.execute(
            "SELECT si.order_index, sc.id AS script_id, sc.name AS script_name, sc.file_path, "
            "sc.start_url_key, sc.start_url_value, sc.var_keys "
            "FROM suite_items si JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            logger.warning("execute_run: suite %s has no scripts", suite_id)
            return jsonify({"ok": False, "error": "Suite has no scripts"}), 400

        logger.info("execute_run: loaded %d scripts for suite %s (%s)", len(items), suite_id, suite["name"])
        for item in items:
            logger.debug("  script: %s (%s) -> %s", item["script_id"], item["script_name"], item["file_path"])

        # 3. Load env vars if env_name provided
        env_vars_dict = {}
        environment_id = None
        if env_name:
            env_name = env_name.strip()
            env_row = conn.execute(
                "SELECT * FROM environments WHERE project_id = ? AND name = ?",
                (project_id, env_name),
            ).fetchone()
            if not env_row:
                return jsonify({"ok": False, "error": f"Environment \"{env_name}\" not found"}), 404
            environment_id = env_row["id"]
            variables = conn.execute(
                "SELECT key, value FROM env_vars WHERE environment_id = ?",
                (env_row["id"],),
            ).fetchall()
            for v in variables:
                env_vars_dict[v["key"]] = v["value"]
            logger.info("execute_run: loaded %d env vars from environment '%s'", len(env_vars_dict), env_name)

        # Inject env vars into current process
        for k, v in env_vars_dict.items():
            os.environ[k] = v

        # 4. Create suite_run record
        run_id = generate_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', ?, ?, ?, ?, ?)",
            (run_id, suite_id, project_id, environment_id, len(items), now, browser_type, resolution, 1 if headless else 0),
        )
        conn.commit()
        logger.info("execute_run: created run %s at %s", run_id, now)

        total = len(items)
        passed = 0
        failed = 0
        skipped = 0
        stopped = False
        script_results = []
        run_start = time.time()

        # Storage state file for session persistence across runs
        storage_state_path = os.path.join(os.path.expanduser("~/.qaclan"), "storage_state.json")
        logger.debug("execute_run: storage_state_path=%s exists=%s", storage_state_path, os.path.exists(storage_state_path))

        # In Nuitka binary builds, the bundled Node driver segfaults — use system node instead
        default_browsers = os.path.expanduser("~/.cache/ms-playwright")
        is_frozen = getattr(sys, 'frozen', False) or "/tmp/onefile_" in (sys.executable or "")
        logger.info("execute_run: is_frozen=%s sys.executable=%s", is_frozen, sys.executable)

        if is_frozen and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            # Binary mode: force browser path to system location
            if os.path.isdir(default_browsers):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = default_browsers
                logger.info("execute_run: set PLAYWRIGHT_BROWSERS_PATH=%s", default_browsers)
            else:
                logger.warning("execute_run: no browser dir found at %s", default_browsers)

        logger.info("execute_run: PLAYWRIGHT_BROWSERS_PATH=%s", os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "<not set>"))

        if is_frozen:
            node_path = shutil.which("node")
            logger.info("execute_run: binary mode — node_path=%s", node_path)
            if not node_path:
                logger.error("execute_run: Node.js not found in PATH")
                return jsonify({"error": "Node.js is required to run tests in binary mode. Install Node.js and try again."}), 500
            try:
                import playwright._impl._driver as _drv
                _orig_compute = _drv.compute_driver_executable
                def _patched_compute():
                    _node, cli = _orig_compute()
                    logger.debug("execute_run: patched driver — node=%s cli=%s (original node=%s)", node_path, cli, _node)
                    return node_path, cli
                _drv.compute_driver_executable = _patched_compute
                logger.info("execute_run: patched Playwright driver to use system node")
            except Exception as e:
                logger.error("execute_run: failed to patch Playwright driver: %s", e, exc_info=True)

        from playwright.sync_api import sync_playwright, expect as pw_expect
        logger.info("execute_run: starting Playwright...")

        with sync_playwright() as playwright:
            browser_engine = getattr(playwright, browser_type)
            logger.info("execute_run: Playwright started, launching %s (headless=%s)...", browser_type, headless)
            browser_inst = browser_engine.launch(headless=headless)
            logger.info("execute_run: browser launched, creating context...")
            context_opts = {}
            if os.path.exists(storage_state_path):
                context_opts["storage_state"] = storage_state_path
            if resolution:
                w, h = resolution.split("x")
                context_opts["viewport"] = {"width": int(w), "height": int(h)}
            context = browser_inst.new_context(**context_opts)
            logger.info("execute_run: browser context created (storage_state=%s, resolution=%s)",
                        "loaded" if os.path.exists(storage_state_path) else "none", resolution or "default")

            # 6. Loop through scripts
            for idx, item in enumerate(items):
                srun_id = generate_id("srun")
                script_now = datetime.now(timezone.utc).isoformat()

                if stopped:
                    logger.info("execute_run: [%d/%d] %s — SKIPPED (stop-on-fail)", idx + 1, total, item["script_name"])
                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, 'SKIPPED', ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"], script_now, script_now),
                    )
                    skipped += 1
                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": "SKIPPED",
                        "duration_ms": 0,
                        "error_message": None,
                    })
                    continue

                logger.info("execute_run: [%d/%d] running '%s' (%s)...", idx + 1, total, item["script_name"], item["script_id"])
                script_start = time.time()
                console_errors = []
                network_failures = []

                try:
                    # Extract and patch test actions
                    script_path = item["file_path"]
                    if not os.path.exists(script_path):
                        raise FileNotFoundError(f"Script file not found: {script_path}")
                    logger.debug("execute_run: reading script from %s", script_path)

                    actions_src = _extract_test_actions(script_path)
                    if not actions_src.strip():
                        logger.warning("execute_run: extracted empty actions from %s", script_path)
                    else:
                        logger.debug("execute_run: extracted %d chars of actions:\n%s", len(actions_src), actions_src[:500])

                    # Resolve {{KEY}} placeholders against the selected env (with start URL fallback)
                    try:
                        script_var_keys = json.loads(item["var_keys"] or "[]")
                    except (TypeError, ValueError):
                        script_var_keys = []
                    if script_var_keys:
                        actions_src, subs_warnings = _substitute_template_vars(
                            actions_src,
                            script_var_keys,
                            env_vars_dict,
                            item["start_url_key"],
                            item["start_url_value"],
                        )
                        for w in subs_warnings:
                            logger.warning("execute_run: %s — %s", item["script_name"], w)

                    actions_src = _patch_actions(actions_src)
                    logger.debug("execute_run: patched actions (%d chars)", len(actions_src))

                    # Create a new page in the shared context
                    logger.debug("execute_run: creating new page...")
                    page = context.new_page()
                    page.set_default_timeout(30000)

                    # Hook console and network error listeners
                    page.on("console", lambda msg: console_errors.append(
                        {"type": msg.type, "text": msg.text}
                    ) if msg.type in ("error", "warning") else None)
                    page.on("pageerror", lambda err: console_errors.append(
                        {"type": "pageerror", "text": str(err)}
                    ))
                    page.on("requestfailed", lambda req: network_failures.append(
                        {"url": req.url, "method": req.method, "failure": req.failure}
                    ))

                    logger.debug("execute_run: page created, executing actions...")

                    # Execute test actions with page, context, and expect in scope
                    exec(actions_src, {
                        "page": page,
                        "context": context,
                        "expect": pw_expect,
                        "re": re,
                        "os": os,
                    })

                    logger.debug("execute_run: actions executed, waiting 2s for JS persistence...")
                    page.wait_for_timeout(2000)  # Allow JS to persist session to localStorage
                    page.close()

                    duration_ms = int((time.time() - script_start) * 1000)
                    finished_at = datetime.now(timezone.utc).isoformat()

                    status = "PASSED"
                    passed += 1
                    error_msg = None
                    logger.info("execute_run: [%d/%d] %s — PASSED (%dms) console_errors=%d network_failures=%d",
                                idx + 1, total, item["script_name"], duration_ms,
                                len(console_errors), len(network_failures))

                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                        "duration_ms, error_message, console_errors, network_failures, console_log, network_log, "
                        "started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"],
                         status, duration_ms, error_msg,
                         len(console_errors), len(network_failures),
                         json.dumps(console_errors) if console_errors else None,
                         json.dumps(network_failures) if network_failures else None,
                         script_now, finished_at),
                    )

                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": status,
                        "duration_ms": duration_ms,
                        "error_message": error_msg,
                        "console_errors": len(console_errors),
                        "network_failures": len(network_failures),
                        "console_log": json.dumps(console_errors) if console_errors else None,
                        "network_log": json.dumps(network_failures) if network_failures else None,
                    })
                except Exception as e:
                    # Capture screenshot before closing page
                    screenshot_path = None
                    try:
                        screenshots_dir = Path(os.path.expanduser("~/.qaclan/screenshots"))
                        screenshots_dir.mkdir(parents=True, exist_ok=True)
                        screenshot_path = str(screenshots_dir / f"{srun_id}.png")
                        page.screenshot(path=screenshot_path)
                    except Exception:
                        screenshot_path = None

                    try:
                        page.close()
                    except Exception:
                        pass

                    duration_ms = int((time.time() - script_start) * 1000)
                    finished_at = datetime.now(timezone.utc).isoformat()
                    failed += 1
                    error_msg = traceback.format_exc()
                    logger.error("execute_run: [%d/%d] %s — FAILED (%dms): %s", idx + 1, total, item["script_name"], duration_ms, e)
                    logger.debug("execute_run: full traceback:\n%s", error_msg)
                    if stop_on_fail:
                        stopped = True
                        logger.info("execute_run: stop-on-fail triggered, remaining scripts will be skipped")

                    conn.execute(
                        "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                        "duration_ms, error_message, console_errors, network_failures, console_log, network_log, "
                        "screenshot_path, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (srun_id, run_id, item["script_id"], item["order_index"],
                         duration_ms, error_msg,
                         len(console_errors), len(network_failures),
                         json.dumps(console_errors) if console_errors else None,
                         json.dumps(network_failures) if network_failures else None,
                         screenshot_path, script_now, finished_at),
                    )

                    script_results.append({
                        "script_id": item["script_id"],
                        "name": item["script_name"],
                        "status": "FAILED",
                        "duration_ms": duration_ms,
                        "error_message": error_msg,
                        "screenshot_path": screenshot_path,
                        "console_errors": len(console_errors),
                        "network_failures": len(network_failures),
                        "console_log": json.dumps(console_errors) if console_errors else None,
                        "network_log": json.dumps(network_failures) if network_failures else None,
                    })

            # Save storage state for session persistence
            logger.debug("execute_run: saving storage state to %s", storage_state_path)
            context.storage_state(path=storage_state_path)

            # Close shared browser
            logger.info("execute_run: closing browser...")
            context.close()
            browser_inst.close()

        # Clean up injected env vars
        for k in env_vars_dict:
            os.environ.pop(k, None)

        # 8. Finalize suite_run
        final_status = "PASSED" if failed == 0 and skipped == 0 else "FAILED"
        finished_at = datetime.now(timezone.utc).isoformat()
        total_duration_ms = int((time.time() - run_start) * 1000)
        logger.info("execute_run: run %s finished — %s (passed=%d failed=%d skipped=%d duration=%dms)",
                     run_id, final_status, passed, failed, skipped, total_duration_ms)
        conn.execute(
            "UPDATE suite_runs SET status = ?, passed = ?, failed = ?, skipped = ?, finished_at = ? "
            "WHERE id = ?",
            (final_status, passed, failed, skipped, finished_at, run_id),
        )

        # 9. Update suite metadata
        conn.execute(
            "UPDATE suites SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            (finished_at, final_status, suite_id),
        )
        conn.execute(
            "UPDATE suites SET first_run_at = ? WHERE id = ? AND first_run_at IS NULL",
            (finished_at, suite_id),
        )
        conn.commit()

        # Sync run to cloud
        logger.debug("execute_run: syncing run %s to cloud...", run_id)
        from cli.sync import sync_run_to_cloud, _read_screenshot_b64
        sync_run_to_cloud(
            run_id=run_id,
            suite_id=suite_id,
            status=final_status,
            started_at=now,
            completed_at=finished_at,
            duration_ms=total_duration_ms,
            project_id=project_id,
            browser=browser_type,
            resolution=resolution,
            headless=headless,
            script_results=[
                {
                    "script_id": sr["script_id"],
                    "script_name": sr["name"],
                    "status": sr["status"].lower(),
                    "duration_ms": sr.get("duration_ms", 0) or 0,
                    "error_output": sr.get("error_message"),
                    "order_index": idx,
                    "console_errors": sr.get("console_errors", 0),
                    "network_failures": sr.get("network_failures", 0),
                    "console_log": sr.get("console_log"),
                    "network_log": sr.get("network_log"),
                    "screenshot_b64": _read_screenshot_b64(sr.get("screenshot_path")),
                }
                for idx, sr in enumerate(script_results)
            ],
        )

        # 10. Return completed run data
        return jsonify({
            "ok": True,
            "run": {
                "id": run_id,
                "suite_id": suite_id,
                "suite_name": suite["name"],
                "status": final_status,
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "started_at": now,
                "finished_at": finished_at,
                "scripts": script_results,
            },
        })
    except Exception as e:
        logger.error("execute_run: top-level exception: %s", e, exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
