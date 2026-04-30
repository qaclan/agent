import json
import os
import shutil
import subprocess
import time
import logging
import traceback
from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
from pathlib import Path

from cli.db import get_conn, generate_id
from cli.config import get_active_project_id, QACLAN_DIR
from cli.runtime import is_frozen_binary, get_default_playwright_browsers_path
from cli.crypto import decrypt
from cli.script_strategies import get_strategy
from cli.script_strategies._shared import substitute_template_vars

logger = logging.getLogger("qaclan.runs")

bp = Blueprint('runs', __name__)

RUNS_DIR = Path(QACLAN_DIR) / "runs"
SCREENSHOTS_DIR = Path(QACLAN_DIR) / "screenshots"
PER_SCRIPT_TIMEOUT_SEC = 300  # 5 minutes per script before kill


def _require_active_project():
    return get_active_project_id()


def _read_artifacts(path: Path):
    """Read the artifacts JSON a script writes on exit. Missing or malformed
    files degrade gracefully to empty lists — a crashed script may not have
    written anything."""
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text())
        return data.get("console_errors", []) or [], data.get("network_failures", []) or []
    except Exception as e:
        logger.warning("Failed to read artifacts at %s: %s", path, e)
        return [], []


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


def _cleanup_run_dir(run_dir):
    """Remove the per-run working directory once data has been persisted to DB.
    Errors are swallowed — a stale run_dir is a disk-space issue, not a
    correctness issue, and the user already has the result they care about."""
    if not run_dir:
        return
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to cleanup run_dir %s: %s", run_dir, e)


@bp.route('/api/runs', methods=['POST'])
def execute_run():
    run_dir = None
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

        items = conn.execute(
            "SELECT si.order_index, sc.id AS script_id, sc.name AS script_name, sc.file_path, "
            "sc.language, sc.start_url_key, sc.start_url_value, sc.var_keys "
            "FROM suite_items si JOIN scripts sc ON si.script_id = sc.id "
            "WHERE si.suite_id = ? ORDER BY si.order_index",
            (suite_id,),
        ).fetchall()
        if not items:
            logger.warning("execute_run: suite %s has no scripts", suite_id)
            return jsonify({"ok": False, "error": "Suite has no scripts"}), 400

        logger.info("execute_run: loaded %d scripts for suite %s (%s)", len(items), suite_id, suite["name"])

        # Pre-flight: every language present in the suite must have a working runtime.
        languages_in_suite = {item["language"] or "python" for item in items}
        for lang in languages_in_suite:
            try:
                get_strategy(lang).validate_runtime()
            except (ValueError, RuntimeError) as e:
                logger.error("execute_run: runtime check failed for language %s: %s", lang, e)
                return jsonify({"ok": False, "error": str(e)}), 400

        # Load env vars for substitution. These are passed to subprocesses via
        # the `env` param only — we never mutate os.environ of the Flask process.
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
                "SELECT key, value, is_secret FROM env_vars WHERE environment_id = ?",
                (env_row["id"],),
            ).fetchall()
            for v in variables:
                val = v["value"]
                if v["is_secret"] and val:
                    val = decrypt(val)
                env_vars_dict[v["key"]] = val
            logger.info("execute_run: loaded %d env vars from environment '%s'", len(env_vars_dict), env_name)

        run_id = generate_id("run")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless) "
            "VALUES (?, ?, ?, ?, 'web', 'RUNNING', ?, ?, ?, ?, ?)",
            (run_id, suite_id, project_id, environment_id, len(items), now, browser_type, resolution, 1 if headless else 0),
        )
        conn.commit()
        logger.info("execute_run: created run %s at %s", run_id, now)

        # Per-run working directory: holds the rendered scripts, the shared
        # storage-state JSON, and per-script artifact files. 0o700 so cookies
        # and decrypted env values aren't world-readable on multi-user hosts.
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        state_file = run_dir / "state.json"  # created on first script's exit

        # Per-language, per-run setup. _test strategies write a single shared
        # playwright.config.js here so each script doesn't rewrite it.
        for lang in languages_in_suite:
            try:
                get_strategy(lang).setup_run_dir(str(run_dir))
            except Exception as e:
                logger.warning("execute_run: setup_run_dir failed for language %s: %s", lang, e)

        total = len(items)
        passed = 0
        failed = 0
        skipped = 0
        stopped = False
        script_results = []
        run_start = time.time()

        # In Nuitka binary builds the bundled Node driver segfaults; set
        # PLAYWRIGHT_BROWSERS_PATH so subprocesses find system-installed browsers.
        default_browsers = get_default_playwright_browsers_path()
        is_frozen = is_frozen_binary()
        logger.info("execute_run: is_frozen=%s", is_frozen)
        pw_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if is_frozen and not pw_browsers_path and os.path.isdir(default_browsers):
            pw_browsers_path = default_browsers
            logger.info("execute_run: using PLAYWRIGHT_BROWSERS_PATH=%s (binary-mode default)", pw_browsers_path)

        for idx, item in enumerate(items):
            srun_id = generate_id("srun")
            script_now = datetime.now(timezone.utc).isoformat()
            language = item["language"] or "python"

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

            logger.info("execute_run: [%d/%d] running '%s' (%s, %s)...",
                        idx + 1, total, item["script_name"], item["script_id"], language)
            script_start = time.time()
            screenshot_path = SCREENSHOTS_DIR / f"{srun_id}.png"
            artifacts_path = run_dir / f"{srun_id}.artifacts.json"

            try:
                strategy = get_strategy(language)
                # File at file_path is the single source of truth for script
                # body. The DB source column is legacy and may be stale or a
                # sentinel ("PULLED", "WEB_CREATED", "CLI_RECORDED").
                script_path = item["file_path"]
                if not script_path or not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script file not found: {script_path}")
                source = Path(script_path).read_text()

                # Resolve {{KEY}} placeholders against the selected env (with
                # recorded start-URL fallback). Values are escaped for the
                # target language so a "-containing value can't break out of
                # the string literal and inject code.
                try:
                    script_var_keys = json.loads(item["var_keys"] or "[]")
                except (TypeError, ValueError) as e:
                    print("execute_run: %s — invalid var_keys: %s -  error: %s", item["script_name"], item["var_keys"], e)
                    script_var_keys = []
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
                rendered_path.write_text(source)
                try:
                    os.chmod(rendered_path, 0o600)
                except OSError:
                    pass

                # Build the subprocess env from scratch — copy the parent env,
                # overlay env_vars_dict (so scripts can read their own secrets
                # via os.environ inside the child), then the QACLAN_* contract
                # vars. Secrets never land in the parent's os.environ.
                child_env = os.environ.copy()
                child_env.update(env_vars_dict)
                child_env["QACLAN_STORAGE_STATE"] = str(state_file)
                child_env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
                child_env["QACLAN_SCREENSHOT_PATH"] = str(screenshot_path)
                child_env["QACLAN_BROWSER"] = browser_type
                child_env["QACLAN_HEADLESS"] = "1" if headless else "0"
                child_env["QACLAN_VIEWPORT"] = resolution or ""
                if pw_browsers_path:
                    child_env["PLAYWRIGHT_BROWSERS_PATH"] = pw_browsers_path

                child_env.update(strategy.extra_env())
                cmd = strategy.build_run_command(str(rendered_path))
                logger.debug("execute_run: spawning %s", cmd)

                proc = subprocess.run(
                    cmd,
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=PER_SCRIPT_TIMEOUT_SEC,
                )

                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                console_errors, network_failures = _read_artifacts(artifacts_path)

                if proc.returncode == 0:
                    status = "PASSED"
                    error_msg = None
                    passed += 1
                    saved_screenshot = None
                    logger.info("execute_run: [%d/%d] %s — PASSED (%dms) console_errors=%d network_failures=%d",
                                idx + 1, total, item["script_name"], duration_ms,
                                len(console_errors), len(network_failures))
                else:
                    status = "FAILED"
                    error_msg = (proc.stderr or "").strip() or f"exit code {proc.returncode}"
                    failed += 1
                    saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
                    logger.error("execute_run: [%d/%d] %s — FAILED (%dms, exit=%d): %s",
                                 idx + 1, total, item["script_name"], duration_ms, proc.returncode,
                                 error_msg[:500])
                    if stop_on_fail:
                        stopped = True
                        logger.info("execute_run: stop-on-fail triggered, remaining scripts will be skipped")

                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, console_errors, network_failures, console_log, network_log, "
                    "screenshot_path, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"], status,
                     duration_ms, error_msg,
                     len(console_errors), len(network_failures),
                     json.dumps(console_errors) if console_errors else None,
                     json.dumps(network_failures) if network_failures else None,
                     saved_screenshot, script_now, finished_at),
                )

                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                })

            except subprocess.TimeoutExpired:
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                error_msg = f"Script timed out after {PER_SCRIPT_TIMEOUT_SEC}s"
                saved_screenshot = str(screenshot_path) if screenshot_path.exists() else None
                logger.error("execute_run: [%d/%d] %s — TIMEOUT (%dms)",
                             idx + 1, total, item["script_name"], duration_ms)
                if stop_on_fail:
                    stopped = True
                console_errors, network_failures = _read_artifacts(artifacts_path)
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
                     saved_screenshot, script_now, finished_at),
                )
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": "FAILED",
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                })

            except Exception as e:
                duration_ms = int((time.time() - script_start) * 1000)
                finished_at = datetime.now(timezone.utc).isoformat()
                failed += 1
                error_msg = traceback.format_exc()
                logger.error("execute_run: [%d/%d] %s — INTERNAL ERROR (%dms): %s",
                             idx + 1, total, item["script_name"], duration_ms, e)
                if stop_on_fail:
                    stopped = True
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"],
                     duration_ms, error_msg, script_now, finished_at),
                )
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": "FAILED",
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                })

        # Ensure the env-vars dict is released promptly so decrypted secrets
        # don't linger in the Flask worker's memory.
        env_vars_dict.clear()

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

        conn.execute(
            "UPDATE suites SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            (finished_at, final_status, suite_id),
        )
        conn.execute(
            "UPDATE suites SET first_run_at = ? WHERE id = ? AND first_run_at IS NULL",
            (finished_at, suite_id),
        )
        conn.commit()

        # Queue run for cloud sync (payload built at drain time from DB)
        logger.debug("execute_run: enqueueing run %s for cloud sync", run_id)
        from cli.sync_queue import enqueue
        enqueue("run", run_id, "upsert")

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
    finally:
        # All console_errors / network_failures / screenshots already in DB
        # or SCREENSHOTS_DIR. Run_dir contents (rendered scripts, state.json,
        # *.artifacts.json, playwright.config.js) are disposable. Drop the
        # directory regardless of success/failure path.
        _cleanup_run_dir(run_dir)
